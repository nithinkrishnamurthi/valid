"""
Validation orchestrator — runs a read-only validation agent against a
deployed environment, returns verdict + report.

Supports two backends:
  - "cli": launches Claude Code headlessly (supports OAuth token or API key)
  - "sdk": uses the Claude Agent SDK (requires ANTHROPIC_API_KEY)

Daemons are discovered via the filesystem registry (see registry.py).
Deploy scripts register daemons after startup; the validation agent
discovers them automatically. If no daemons are registered, the agent
validates locally using its own machine.

Deploy is pluggable: see e2e/local/ and e2e/e2b/ for examples.
"""

import os
import json
import subprocess
import tempfile

VALID_SERVER_PATH = os.path.join(os.path.dirname(__file__), "dist", "index.js")
VALIDATION_TOOLS_SERVER = os.path.join(os.path.dirname(__file__), "validation_tools_server.py")

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


def _build_prompt(task: str, implementation_summary: str, diff: str) -> str:
    return SYSTEM_PROMPT.format(
        task=task,
        implementation_summary=implementation_summary,
        diff=diff,
    )


def _mcp_config() -> dict:
    """MCP server config used by both backends."""
    import sys
    return {
        "mcpServers": {
            "validation": {
                "command": sys.executable,
                "args": [VALIDATION_TOOLS_SERVER],
            },
            "valid": {
                "command": "node",
                "args": [VALID_SERVER_PATH],
            },
        }
    }


# ---------------------------------------------------------------------------
# CLI backend — launches Claude Code headlessly
# ---------------------------------------------------------------------------

async def _validate_cli(
    task: str,
    implementation_summary: str,
    diff: str,
) -> dict:
    prompt = _build_prompt(task, implementation_summary, diff)
    mcp_conf = _mcp_config()

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, prefix="valid-mcp-"
    ) as f:
        json.dump(mcp_conf, f)
        mcp_config_path = f.name

    allowed = ",".join([
        "mcp__validation__discover_daemons",
        "mcp__validation__exec",
        "mcp__valid__valid_create",
        "mcp__valid__valid_add_screenshot",
        "mcp__valid__valid_add_text",
        "mcp__valid__valid_render",
    ])

    # Write system prompt to file to avoid CLI arg length limits
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, prefix="valid-prompt-"
    ) as pf:
        pf.write(prompt)
        prompt_path = pf.name

    cmd = [
        "claude",
        "-p", "Begin validation.",
        "--system-prompt", prompt,
        "--mcp-config", mcp_config_path,
        "--allowedTools", allowed,
        "--max-turns", str(MAX_TURNS),
        "--output-format", "json",
    ]

    try:
        print(f"Running: claude -p ... --mcp-config {mcp_config_path}")
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
            stdin=subprocess.DEVNULL,
        )

        if proc.stderr:
            print(f"Claude Code stderr: {proc.stderr[:500]}")

        if proc.returncode != 0:
            return {"status": "unknown", "reason": proc.stderr, "report_path": None}

        if not proc.stdout.strip():
            return {"status": "unknown", "reason": "Claude Code returned empty output", "report_path": None}

        result = json.loads(proc.stdout)
        result_text = result.get("result", "")

        print(f"Claude Code result: {result_text[:500]}")

        # The agent's final message should be JSON
        try:
            return json.loads(result_text)
        except (json.JSONDecodeError, TypeError):
            return {"status": "unknown", "reason": str(result_text), "report_path": None}

    except subprocess.TimeoutExpired:
        return {"status": "unknown", "reason": "Claude Code timed out after 600s", "report_path": None}
    except FileNotFoundError:
        raise RuntimeError(
            "claude CLI not found. Install Claude Code: https://docs.anthropic.com/en/docs/claude-code"
        )
    finally:
        os.unlink(mcp_config_path)
        os.unlink(prompt_path)


# ---------------------------------------------------------------------------
# SDK backend — uses Claude Agent SDK directly
# ---------------------------------------------------------------------------

async def _validate_sdk(
    task: str,
    implementation_summary: str,
    diff: str,
) -> dict:
    import asyncio
    import registry
    import requests
    from claude_agent_sdk import (
        tool,
        create_sdk_mcp_server,
        ClaudeSDKClient,
        ClaudeAgentOptions,
        AssistantMessage,
        ResultMessage,
        TextBlock,
    )

    # Define tools inline for the SDK (can't share the MCP server module)
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

    custom_server = create_sdk_mcp_server(
        "validation-tools", tools=[discover_daemons_tool, exec_tool]
    )

    prompt = _build_prompt(task, implementation_summary, diff)

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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def validate(
    task: str,
    implementation_summary: str,
    diff: str,
    backend: str = None,
) -> dict:
    """
    Run the validation agent against an already-deployed environment.

    Args:
        task: What was supposed to be implemented.
        implementation_summary: Structured list of what the coding agent did.
        diff: Git diff of changes.
        backend: "cli" for Claude Code, "sdk" for Agent SDK.
                 If None, auto-selects: "cli" if `claude` is on PATH,
                 falls back to "sdk" if ANTHROPIC_API_KEY is set.

    Returns:
        {"status": "pass"|"fail", "report_path": "...", "reason": "..."}
    """
    if backend is None:
        backend = _detect_backend()

    if backend == "cli":
        return await _validate_cli(task, implementation_summary, diff)
    elif backend == "sdk":
        return await _validate_sdk(task, implementation_summary, diff)
    else:
        raise ValueError(f"Unknown backend: {backend!r}. Use 'cli' or 'sdk'.")


def _detect_backend() -> str:
    """Auto-detect which backend to use."""
    # Prefer CLI if claude is available
    try:
        subprocess.run(
            ["claude", "--version"],
            capture_output=True,
            timeout=5,
        )
        return "cli"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    if os.environ.get("ANTHROPIC_API_KEY"):
        return "sdk"

    raise RuntimeError(
        "No backend available. Either install Claude Code (for OAuth/CLI) "
        "or set ANTHROPIC_API_KEY (for Agent SDK)."
    )
