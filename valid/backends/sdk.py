"""SDK backend — uses Claude Agent SDK directly.

Reuses the same stdio tools server (valid.tools_server) that the CLI backend
uses, so tool definitions live in exactly one place.
"""

import json
import os
import sys

from valid.orchestrator import MAX_TURNS, build_prompt


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_VALID_MCP_SERVER = os.path.join(_REPO_ROOT, "valid-mcp", "dist", "index.js")


async def validate_sdk(
    task: str,
    implementation_summary: str,
    diff: str,
) -> dict:
    from claude_agent_sdk import (
        ClaudeSDKClient,
        ClaudeAgentOptions,
        AssistantMessage,
        ResultMessage,
        TextBlock,
    )

    prompt = build_prompt(task, implementation_summary, diff)

    options = ClaudeAgentOptions(
        allowed_tools=[
            "mcp__validation__discover_daemons",
            "mcp__validation__exec",
            "mcp__valid__valid_create",
            "mcp__valid__valid_add_screenshot",
            "mcp__valid__valid_add_text",
            "mcp__valid__valid_render",
        ],
        mcp_servers={
            "validation": {
                "command": sys.executable,
                "args": ["-m", "valid.tools_server"],
                "cwd": _REPO_ROOT,
            },
            "valid": {"command": "node", "args": [_VALID_MCP_SERVER]},
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
