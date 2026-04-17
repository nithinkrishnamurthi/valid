"""SDK backend — uses Claude Agent SDK directly.

Reuses the same stdio tools server (valid.tools_server) that the CLI backend
uses, so tool definitions live in exactly one place.
"""

import json
import os
import sys

from valid.agent import MAX_TURNS, build_prompt


def _valid_mcp_server_path() -> str:
    """Locate the bundled valid-mcp server JS file."""
    bundled = os.path.join(os.path.dirname(__file__), "..", "data", "valid-mcp.js")
    if os.path.exists(bundled):
        return os.path.abspath(bundled)
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(repo_root, "valid-mcp", "dist", "index.js")


async def validate_sdk(
    task: str,
    implementation_summary: str,
    diff: str,
    daemon_url: str = None,
    daemon_token: str = None,
) -> dict:
    from claude_agent_sdk import (
        ClaudeSDKClient,
        ClaudeAgentOptions,
        AssistantMessage,
        ResultMessage,
        TextBlock,
    )

    prompt = build_prompt(task, implementation_summary, diff)

    tools_args = ["-m", "valid.tools_server"]
    if daemon_url:
        tools_args += ["--daemon-url", daemon_url]
    if daemon_token:
        tools_args += ["--daemon-token", daemon_token]

    options = ClaudeAgentOptions(
        allowed_tools=[
            "mcp__validation__discover_daemons",
            "mcp__validation__exec",
            "mcp__validation__list_tools",
            "mcp__validation__call_tool",
            "mcp__validation__save_asset",
            "mcp__validation__list_assets",
            "mcp__valid__valid_create",
            "mcp__valid__valid_add_screenshot",
            "mcp__valid__valid_add_text",
            "mcp__valid__valid_render",
        ],
        mcp_servers={
            "validation": {
                "command": sys.executable,
                "args": tools_args,
            },
            "valid": {"command": "node", "args": [_valid_mcp_server_path()]},
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
