"""
Standalone MCP server exposing daemon tools + session assets.

Used by both the Agent SDK backend and Claude Code CLI backend via stdio:
    python -m valid.tools_server --daemon-url URL --daemon-token TOKEN
"""

import argparse
import json
import asyncio
import base64
import os
import tempfile
import time

import requests
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("validation-tools")

# ── Daemon connection ───────────────────────────────────────────────
# Set via CLI args or configure(). Falls back to filesystem registry.

_DAEMON_URL: str | None = None
_DAEMON_TOKEN: str | None = None


def configure(daemon_url: str | None = None, daemon_token: str | None = None):
    global _DAEMON_URL, _DAEMON_TOKEN
    _DAEMON_URL = daemon_url
    _DAEMON_TOKEN = daemon_token


def _discover() -> list[dict]:
    """Return available daemons — explicit config first, then registry fallback."""
    if _DAEMON_URL:
        return [{"name": "daemon", "url": _DAEMON_URL, "token": _DAEMON_TOKEN or ""}]
    try:
        from valid import registry
        return registry.discover()
    except Exception:
        return []

# ── Session ──────────────────────────────────────────────────────────
# Assets are the things the agent wants to keep for the report:
# screenshots, log snippets, command output, etc. Each has a type
# ("image", "text", "code"), content, and an optional label.

_SESSION_DIR = tempfile.mkdtemp(prefix="valid-session-")
_assets: list[dict] = []
_asset_seq = 0
_screenshot_seq = 0


def _next_asset_id() -> str:
    global _asset_seq
    _asset_seq += 1
    return f"asset_{_asset_seq:03d}"


def _add_asset(type: str, content: str, label: str = "") -> dict:
    asset = {
        "id": _next_asset_id(),
        "type": type,
        "label": label,
        "content": content,
        "ts": time.time(),
    }
    _assets.append(asset)
    return asset


def _save_screenshot_file(data: bytes, ext: str = ".png") -> str:
    global _screenshot_seq
    _screenshot_seq += 1
    path = os.path.join(_SESSION_DIR, f"screenshot_{_screenshot_seq:03d}{ext}")
    with open(path, "wb") as f:
        f.write(data)
    return path


# ── Daemon tools ─────────────────────────────────────────────────────

@mcp.tool()
async def discover_daemons() -> str:
    """List available remote machines. Each entry has a name you can pass
    to the exec tool. Returns an empty list if no remote machines are
    registered — in that case, exec runs locally."""
    daemons = _discover()
    if not daemons:
        return "No remote daemons available. Use exec without a daemon to run commands locally."
    entries = [{"name": d["name"], "url": d["url"]} for d in daemons]
    return json.dumps(entries, indent=2)


@mcp.tool()
async def exec(command: str, daemon: str = "") -> str:
    """Execute a bash command. If 'daemon' is provided, runs on that remote
    machine (must match a name from discover_daemons). If omitted, runs
    locally on this machine."""

    if daemon:
        daemon_map = {d["name"]: d for d in _discover()}
        if daemon not in daemon_map:
            return f"Error: Unknown daemon '{daemon}'. Call discover_daemons to see available machines."
        d = daemon_map[daemon]
        try:
            resp = requests.post(
                f"{d['url']}/exec",
                json={"command": command},
                headers={"Authorization": f"Bearer {d['token']}"},
                timeout=35,
            )
            result = resp.json()
        except Exception as e:
            return f"Error: {e}"

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
            return "Error: Command timed out after 30s"
        except Exception as e:
            return f"Error: {e}"

        output = ""
        if stdout:
            output += f"STDOUT:\n{stdout.decode()}\n"
        if stderr:
            output += f"STDERR:\n{stderr.decode()}\n"
        output += f"EXIT CODE: {proc.returncode}"

    return output


@mcp.tool()
async def list_tools(daemon: str) -> str:
    """List tools available on a remote daemon (e.g. browser automation).
    Returns tool names and schemas. Use call_tool to invoke them."""
    daemon_map = {d["name"]: d for d in _discover()}
    if daemon not in daemon_map:
        return f"Error: Unknown daemon '{daemon}'. Call discover_daemons to see available machines."
    d = daemon_map[daemon]
    try:
        resp = requests.get(
            f"{d['url']}/tools",
            headers={"Authorization": f"Bearer {d['token']}"},
            timeout=10,
        )
        return resp.text
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
async def call_tool(daemon: str, name: str, arguments: str = "{}") -> str:
    """Call a tool on a remote daemon. Use list_tools first to see what's
    available. Arguments is a JSON string matching the tool's input schema.
    Screenshots are auto-saved as image assets."""
    daemon_map = {d["name"]: d for d in _discover()}
    if daemon not in daemon_map:
        return f"Error: Unknown daemon '{daemon}'. Call discover_daemons to see available machines."
    d = daemon_map[daemon]
    try:
        args = json.loads(arguments)
    except json.JSONDecodeError as e:
        return f"Error: Invalid JSON arguments: {e}"
    try:
        resp = requests.post(
            f"{d['url']}/tools/call",
            json={"name": name, "arguments": args},
            headers={"Authorization": f"Bearer {d['token']}"},
            timeout=120,
        )
        result = resp.json()
    except Exception as e:
        return f"Error: {e}"

    if isinstance(result, dict) and "error" in result:
        return f"Error: {result['error']}"

    if isinstance(result, dict) and "content" in result:
        parts = []
        for item in result["content"]:
            if item.get("type") == "text":
                parts.append(item["text"])
            elif item.get("type") == "image":
                data = base64.b64decode(item.get("data", ""))
                ext = ".png" if "png" in item.get("mimeType", "") else ".jpg"
                path = _save_screenshot_file(data, ext)
                asset = _add_asset("image", path, label=name)
                parts.append(f"[screenshot saved as {asset['id']}: {path}]")
            else:
                parts.append(json.dumps(item))
        return "\n".join(parts)

    return json.dumps(result, indent=2)


# ── Asset tools ──────────────────────────────────────────────────────

@mcp.tool()
async def save_asset(content: str, type: str = "text", label: str = "") -> str:
    """Save an asset to the session for use in the validation report.

    type:
      "image" — content is a file path to an image on disk
      "text"  — prose / narrative content
      "code"  — log output, command output, code snippets

    Returns the asset ID. Use list_assets to see all saved assets."""
    asset = _add_asset(type, content, label)
    return json.dumps({"id": asset["id"], "type": type, "label": label})


@mcp.tool()
async def list_assets() -> str:
    """List all assets saved during this session. Image assets show their
    file path; text/code assets show a preview. Use these when building
    the validation report with valid_add_screenshot and valid_add_text."""
    if not _assets:
        return "No assets saved yet."
    summary = []
    for a in _assets:
        entry = {"id": a["id"], "type": a["type"], "label": a["label"]}
        if a["type"] == "image":
            entry["path"] = a["content"]
        else:
            entry["preview"] = a["content"][:200] + ("..." if len(a["content"]) > 200 else "")
        summary.append(entry)
    return json.dumps(summary, indent=2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--daemon-url", default=None)
    parser.add_argument("--daemon-token", default=None)
    args = parser.parse_args()
    configure(args.daemon_url, args.daemon_token)
    mcp.run(transport="stdio")
