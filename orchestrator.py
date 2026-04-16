"""
Validation orchestrator — runs a read-only validation agent against a
deployed environment, returns verdict + report.

Daemons are discovered via the filesystem registry (see registry.py).
Deploy scripts register daemons after startup; the validation agent
discovers them automatically. If no daemons are registered, the agent
validates locally using its own machine.

Deploy is pluggable: see e2e/local/ and e2e/e2b/ for examples.
"""

import os
import json
import asyncio
import anyio
import requests

import registry
from claude_agent_sdk import (
    tool,
    create_sdk_mcp_server,
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
    TextBlock,
)


VALID_SERVER_PATH = os.path.join(os.path.dirname(__file__), "dist", "index.js")

MAX_TURNS = 50

SYSTEM_PROMPT = """You are a validation agent. Your job is to verify that a code change \
works correctly in a live deployment.

You can ONLY observe and report. You cannot modify code.

You have access to:
- discover_daemons: list available remote machines you can execute commands on
- exec: run a bash command (locally, or on a remote daemon by name)
- valid_create, valid_add_text, valid_add_screenshot, valid_render: build a visual QA report

TASK THAT WAS IMPLEMENTED:
{task}

IMPLEMENTATION SUMMARY:
{implementation_summary}

THE DIFF:
{diff}

INSTRUCTIONS:
1. Call discover_daemons to see what machines are available.
   - If daemons are listed, use exec with the daemon name to run commands remotely.
   - If no daemons are available, use exec to run commands on your local machine.
2. Check what services are running (e.g. docker compose ps)
3. Check for errors in logs (e.g. docker compose logs --tail=50)
4. Based on the diff and implementation summary, test the changed functionality:
   - Curl endpoints
   - Query the database
   - Check service health
5. Build a validation report using the valid tools:
   - valid_create with a title describing what was validated
   - Use valid_add_text with format="prose" to narrate what you did and what you observed.
     Prose supports **bold**, *italic*, lists, and other markdown formatting.
   - Use valid_add_text with format="code" for log excerpts and command output
   - valid_render to produce the final PNG
6. Your report should tell a clear story: what you tested, what you observed, what worked,
   what didn't. Be specific — include endpoint URLs, status codes, relevant log lines.

Your final message MUST be valid JSON in this format:
{{"status": "pass" or "fail", "report_path": "/path/to/report.png", "reason": "brief summary"}}
"""


def _make_tools():
    """Create discover_daemons + exec tools for the validation agent."""

    @tool(
        "discover_daemons",
        "List available remote machines. Each entry has a name you can pass "
        "to the exec tool. Returns an empty list if no remote machines are "
        "registered — in that case, exec runs locally.",
        {},
    )
    async def discover_daemons_tool(args):
        daemons = registry.discover()
        if not daemons:
            text = "No remote daemons available. Use exec without a daemon to run commands locally."
        else:
            entries = [{"name": d["name"], "url": d["url"]} for d in daemons]
            text = json.dumps(entries, indent=2)
        return {"content": [{"type": "text", "text": text}]}

    @tool(
        "exec",
        "Execute a bash command. If 'daemon' is provided, runs on that remote "
        "machine (must match a name from discover_daemons). If omitted, runs "
        "locally on this machine.",
        {"command": str, "daemon": str},
    )
    async def exec_tool(args):
        command = args["command"]
        daemon_name = args.get("daemon")

        if daemon_name:
            # Remote execution via daemon — look up from registry
            daemon_map = {d["name"]: d for d in registry.discover()}
            if daemon_name not in daemon_map:
                return {
                    "content": [{"type": "text", "text": f"Unknown daemon '{daemon_name}'. Call discover_daemons to see available machines."}],
                    "isError": True,
                }
            d = daemon_map[daemon_name]
            try:
                resp = requests.post(
                    f"{d['url']}/exec",
                    json={"command": command},
                    headers={"Authorization": f"Bearer {d['token']}"},
                    timeout=35,
                )
                result = resp.json()
            except Exception as e:
                return {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True}

            output = ""
            if result.get("stdout"):
                output += f"STDOUT:\n{result['stdout']}\n"
            if result.get("stderr"):
                output += f"STDERR:\n{result['stderr']}\n"
            output += f"EXIT CODE: {result.get('exit_code', -1)}"
        else:
            # Local execution
            try:
                proc = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            except asyncio.TimeoutError:
                return {"content": [{"type": "text", "text": "Command timed out after 30s"}], "isError": True}
            except Exception as e:
                return {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True}

            output = ""
            if stdout:
                output += f"STDOUT:\n{stdout.decode()}\n"
            if stderr:
                output += f"STDERR:\n{stderr.decode()}\n"
            output += f"EXIT CODE: {proc.returncode}"

        return {"content": [{"type": "text", "text": output}]}

    return [discover_daemons_tool, exec_tool]


async def validate(
    task: str,
    implementation_summary: str,
    diff: str,
) -> dict:
    """
    Run the validation agent against an already-deployed environment.

    The caller is responsible for deploying, redeploying, and tearing down.
    This function only runs the validation agent and returns the verdict.

    Daemons are discovered automatically from the registry. Deploy scripts
    should call registry.register() before invoking validate().

    Args:
        task: What was supposed to be implemented.
        implementation_summary: Structured list of what the coding agent did.
        diff: Git diff of changes.

    Returns:
        {"status": "pass"|"fail", "report_path": "...", "reason": "..."}
    """
    custom_tools = _make_tools()
    custom_server = create_sdk_mcp_server("validation-tools", tools=custom_tools)

    prompt = SYSTEM_PROMPT.format(
        task=task,
        implementation_summary=implementation_summary,
        diff=diff,
    )

    options = ClaudeAgentOptions(
        allowed_tools=[],
        mcp_servers={
            "validation": custom_server,
            "valid": {"command": "node", "args": [VALID_SERVER_PATH]},
        },
        system_prompt=prompt,
        max_turns=MAX_TURNS,
    )

    result_text = ""
    async with ClaudeSDKClient(options=options) as client:
        await client.query("Begin validation.")
        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(block.text)
            if isinstance(message, ResultMessage):
                result_text = message.result

    try:
        return json.loads(result_text)
    except json.JSONDecodeError:
        return {"status": "unknown", "reason": result_text, "report_path": None}
