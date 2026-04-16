"""CLI backend — launches Claude Code headlessly.

Supports OAuth (via `claude` CLI auth) or ANTHROPIC_API_KEY.
"""

import json
import os
import subprocess
import sys
import tempfile

from valid.agent import MAX_TURNS, build_prompt


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_VALID_MCP_SERVER = os.path.join(_REPO_ROOT, "valid-mcp", "dist", "index.js")


def _mcp_config() -> dict:
    return {
        "mcpServers": {
            "validation": {
                "command": sys.executable,
                "args": ["-m", "valid.tools_server"],
                "cwd": _REPO_ROOT,
            },
            "valid": {
                "command": "node",
                "args": [_VALID_MCP_SERVER],
            },
        }
    }


async def validate_cli(
    task: str,
    implementation_summary: str,
    diff: str,
) -> dict:
    prompt = build_prompt(task, implementation_summary, diff)
    mcp_conf = _mcp_config()

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, prefix="valid-mcp-"
    ) as f:
        json.dump(mcp_conf, f)
        mcp_config_path = f.name

    allowed = ",".join([
        "mcp__validation__discover_daemons",
        "mcp__validation__exec",
        "mcp__validation__list_tools",
        "mcp__validation__call_tool",
        "mcp__validation__session_log",
        "mcp__validation__session_screenshots",
        "mcp__valid__valid_create",
        "mcp__valid__valid_add_screenshot",
        "mcp__valid__valid_add_text",
        "mcp__valid__valid_render",
    ])

    cmd = [
        "claude",
        "-p", "Begin validation.",
        "--system-prompt", prompt,
        "--mcp-config", mcp_config_path,
        "--allowedTools", allowed,
        "--max-turns", str(MAX_TURNS),
        "--output-format", "stream-json",
        "--verbose",
    ]

    proc = None
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
        )

        result_text = ""
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            etype = event.get("type")
            if etype == "assistant":
                msg = event.get("message", {})
                for block in msg.get("content", []):
                    if block.get("type") == "text":
                        print(block["text"])
                    elif block.get("type") == "tool_use":
                        name = block.get("name", "?")
                        print(f"  → {name}()")
            elif etype == "result":
                result_text = event.get("result", "")

        proc.wait(timeout=30)

        if proc.returncode != 0:
            stderr = proc.stderr.read()
            if stderr:
                print(f"Claude Code stderr: {stderr[:500]}")
            return {"status": "unknown", "reason": stderr, "report_path": None}

        try:
            return json.loads(result_text)
        except (json.JSONDecodeError, TypeError):
            # Agent sometimes wraps JSON in prose — extract it.
            start = result_text.find("{")
            end = result_text.rfind("}")
            if start != -1 and end > start:
                try:
                    return json.loads(result_text[start : end + 1])
                except (json.JSONDecodeError, TypeError):
                    pass
            return {"status": "unknown", "reason": str(result_text), "report_path": None}

    except FileNotFoundError:
        raise RuntimeError(
            "claude CLI not found. Install Claude Code: https://docs.anthropic.com/en/docs/claude-code"
        )
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill()
        os.unlink(mcp_config_path)
