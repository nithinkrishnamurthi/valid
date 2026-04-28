"""CLI backend — launches Claude Code headlessly.

Supports OAuth (via `claude` CLI auth) or ANTHROPIC_API_KEY.
"""

import json
import os
import subprocess
import sys
import tempfile

from valid.agent import MAX_TURNS, build_prompt


def _valid_mcp_server_path() -> str:
    """Locate the bundled valid-mcp server JS file."""
    bundled = os.path.join(os.path.dirname(__file__), "..", "data", "valid-mcp.js")
    if os.path.exists(bundled):
        return os.path.abspath(bundled)
    # Fallback for development: use repo-local valid-mcp/dist/index.js
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(repo_root, "valid-mcp", "dist", "index.js")


def _mcp_config(daemon_url: str = None, daemon_token: str = None) -> dict:
    tools_args = ["-m", "valid.tools_server"]
    if daemon_url:
        tools_args += ["--daemon-url", daemon_url]
    if daemon_token:
        tools_args += ["--daemon-token", daemon_token]

    return {
        "mcpServers": {
            "validation": {
                "command": sys.executable,
                "args": tools_args,
            },
            "valid": {
                "command": "node",
                "args": [_valid_mcp_server_path()],
            },
        }
    }


async def validate_cli(
    task: str,
    diff: str,
    daemon_url: str = None,
    daemon_token: str = None,
) -> dict:
    prompt = build_prompt(task, diff)
    mcp_conf = _mcp_config(daemon_url, daemon_token)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, prefix="valid-mcp-"
    ) as f:
        json.dump(mcp_conf, f)
        mcp_config_path = f.name

    allowed = ",".join([
        "mcp__validation__discover_daemons",
        "mcp__validation__bash",
        "mcp__validation__read",
        "mcp__validation__write",
        "mcp__validation__grep",
        "mcp__validation__glob",
        "mcp__validation__list_tools",
        "mcp__validation__call_tool",
        "mcp__validation__save_asset",
        "mcp__validation__list_assets",
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
