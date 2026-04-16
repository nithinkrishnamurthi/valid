"""
Validation orchestrator — deploys code, runs a read-only validation agent,
returns verdict + report.

The validation agent can only observe and report. It CANNOT modify code.
If validation fails, the calling agent (coding agent) reads the report,
fixes code, commits, and calls validate() again.
"""

import os
import sys
import json
import anyio
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

from deploy import deploy, redeploy, teardown


VALID_SERVER_PATH = os.path.join(os.path.dirname(__file__), "dist", "index.js")

MAX_TURNS = 50

SYSTEM_PROMPT = """You are a validation agent. Your job is to verify that a code change \
works correctly in a live deployment.

You can ONLY observe and report. You cannot modify code.

You have access to:
- remote_exec: run any bash command on the deployment machine (docker compose environment)
- valid_create, valid_add_text, valid_add_screenshot, valid_render: build a visual QA report

TASK THAT WAS IMPLEMENTED:
{task}

IMPLEMENTATION SUMMARY:
{implementation_summary}

THE DIFF:
{diff}

INSTRUCTIONS:
1. Check what services are running: remote_exec("docker compose ps")
2. Check for errors in logs: remote_exec("docker compose logs --tail=50")
3. Based on the diff and implementation summary, test the changed functionality:
   - Curl endpoints
   - Query the database
   - Check service health
4. Build a validation report using the valid tools:
   - valid_create with a title describing what was validated
   - Use valid_add_text with format="prose" to narrate what you did and what you observed.
     Prose supports **bold**, *italic*, lists, and other markdown formatting.
   - Use valid_add_text with format="code" for log excerpts and command output
   - valid_render to produce the final PNG
5. Your report should tell a clear story: what you tested, what you observed, what worked,
   what didn't. Be specific — include endpoint URLs, status codes, relevant log lines.

Your final message MUST be valid JSON in this format:
{{"status": "pass" or "fail", "report_path": "/path/to/report.png", "reason": "brief summary"}}
"""


def _make_tools(bundle: dict):
    """Create the remote_exec tool for the validation agent."""

    daemon_url = bundle["daemon_url"]
    token = bundle["token"]

    @tool(
        "remote_exec",
        "Execute a bash command on the remote deployment environment. "
        "Use this to inspect running services, check logs, query databases, "
        "curl endpoints, or run any diagnostic command.",
        {"command": str},
    )
    async def remote_exec_tool(args):
        command = args["command"]
        try:
            resp = requests.post(
                f"{daemon_url}/exec",
                json={"command": command},
                headers={"Authorization": f"Bearer {token}"},
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
        return {"content": [{"type": "text", "text": output}]}

    return [remote_exec_tool]


async def validate(
    task: str,
    repo_url: str,
    branch: str,
    implementation_summary: str,
    diff: str,
    compose_file: str = "docker-compose.yml",
    daemon_binary_path: str = None,
    bundle: dict = None,
) -> dict:
    """
    Deploy the code (or reuse an existing deployment), run the validation
    agent, return the verdict.

    Args:
        task: What was supposed to be implemented.
        repo_url: Git repo URL.
        branch: Branch to deploy.
        implementation_summary: Structured list of what the coding agent did.
        diff: Git diff of changes.
        compose_file: Docker compose file path.
        daemon_binary_path: Path to the daemon binary.
        bundle: Existing deployment bundle. If provided, redeploys instead
                of creating a new sandbox. Caller manages teardown.

    Returns:
        {"status": "pass"|"fail", "report_path": "...", "reason": "...",
         "bundle": <deployment bundle for reuse>}
    """
    if daemon_binary_path is None:
        daemon_binary_path = os.path.join(os.path.dirname(__file__), "daemon", "daemon")

    owns_bundle = bundle is None

    if bundle is None:
        print("Deploying...")
        bundle = deploy(repo_url, branch, compose_file, daemon_binary_path)
        print(f"Deployed to {bundle['daemon_url']}")
    else:
        print("Redeploying...")
        redeploy(bundle)
        print("Redeployed.")

    try:
        custom_tools = _make_tools(bundle)
        custom_server = create_sdk_mcp_server("validation-tools", tools=custom_tools)

        prompt = SYSTEM_PROMPT.format(
            task=task,
            implementation_summary=implementation_summary,
            diff=diff,
        )

        # Validation agent is read-only: no file tools, no bash
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
            verdict = json.loads(result_text)
        except json.JSONDecodeError:
            verdict = {"status": "unknown", "reason": result_text, "report_path": None}

        verdict["bundle"] = bundle
        return verdict

    except Exception:
        if owns_bundle:
            teardown(bundle)
        raise


async def main():
    """CLI entrypoint for testing."""
    if len(sys.argv) < 4:
        print("Usage: python orchestrator.py <repo_url> <branch> <task_description>")
        print("  Set IMPLEMENTATION_SUMMARY env var for the handoff artifact.")
        sys.exit(1)

    repo_url = sys.argv[1]
    branch = sys.argv[2]
    task = sys.argv[3]
    impl_summary = os.environ.get("IMPLEMENTATION_SUMMARY", "No summary provided.")

    diff = ""
    try:
        import subprocess
        result = subprocess.run(
            ["git", "diff", f"main...{branch}"],
            capture_output=True, text=True, timeout=30,
        )
        diff = result.stdout or "(no diff available)"
    except Exception:
        diff = "(could not generate diff)"

    verdict = await validate(
        task=task,
        repo_url=repo_url,
        branch=branch,
        implementation_summary=impl_summary,
        diff=diff,
    )

    bundle = verdict.pop("bundle", None)

    print(f"\n{'=' * 60}")
    print(f"Status: {verdict.get('status', 'unknown')}")
    print(f"Report: {verdict.get('report_path', 'none')}")
    if verdict.get("reason"):
        print(f"Reason: {verdict['reason']}")

    if bundle:
        teardown(bundle)


if __name__ == "__main__":
    anyio.run(main)
