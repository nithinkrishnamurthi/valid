"""
Standalone MCP server exposing daemon tools + session log.

Used by both the Agent SDK backend and Claude Code CLI backend via stdio:
    python -m valid.tools_server
"""

import json
import asyncio
import base64
import os
import tempfile
import time

import requests
from mcp.server.fastmcp import FastMCP

from valid import registry

mcp = FastMCP("validation-tools")

# ── Session log ──────────────────────────────────────────────────────
# Append-only JSONL log of every tool call, its result, and any images.
# Screenshots are saved into the session directory with sequential names.

_SESSION_DIR = tempfile.mkdtemp(prefix="valid-session-")
_SESSION_LOG_PATH = os.path.join(_SESSION_DIR, "session.jsonl")
_session_seq = 0
_session_screenshot_seq = 0


def _log(tool: str, args: dict, result: str, images: list[str] | None = None):
    """Append an entry to the session log."""
    global _session_seq
    _session_seq += 1
    entry = {
        "seq": _session_seq,
        "ts": time.time(),
        "tool": tool,
        "args": args,
        "result": result[:2000],
        "images": images or [],
    }
    with open(_SESSION_LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _save_screenshot(data: bytes, ext: str = ".png") -> str:
    """Save screenshot bytes into the session directory, return path."""
    global _session_screenshot_seq
    _session_screenshot_seq += 1
    name = f"screenshot_{_session_screenshot_seq:03d}{ext}"
    path = os.path.join(_SESSION_DIR, name)
    with open(path, "wb") as f:
        f.write(data)
    return path


# ── Tools ────────────────────────────────────────────────────────────

@mcp.tool()
async def discover_daemons() -> str:
    """List available remote machines. Each entry has a name you can pass
    to the exec tool. Returns an empty list if no remote machines are
    registered — in that case, exec runs locally."""
    daemons = registry.discover()
    if not daemons:
        result = "No remote daemons available. Use exec without a daemon to run commands locally."
    else:
        entries = [{"name": d["name"], "url": d["url"]} for d in daemons]
        result = json.dumps(entries, indent=2)
    _log("discover_daemons", {}, result)
    return result


@mcp.tool()
async def exec(command: str, daemon: str = "") -> str:
    """Execute a bash command. If 'daemon' is provided, runs on that remote
    machine (must match a name from discover_daemons). If omitted, runs
    locally on this machine."""

    if daemon:
        daemon_map = {d["name"]: d for d in registry.discover()}
        if daemon not in daemon_map:
            output = f"Error: Unknown daemon '{daemon}'. Call discover_daemons to see available machines."
            _log("exec", {"command": command, "daemon": daemon}, output)
            return output
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
            output = f"Error: {e}"
            _log("exec", {"command": command, "daemon": daemon}, output)
            return output

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
            output = "Error: Command timed out after 30s"
            _log("exec", {"command": command}, output)
            return output
        except Exception as e:
            output = f"Error: {e}"
            _log("exec", {"command": command}, output)
            return output

        output = ""
        if stdout:
            output += f"STDOUT:\n{stdout.decode()}\n"
        if stderr:
            output += f"STDERR:\n{stderr.decode()}\n"
        output += f"EXIT CODE: {proc.returncode}"

    _log("exec", {"command": command, "daemon": daemon or "(local)"}, output)
    return output


@mcp.tool()
async def list_tools(daemon: str) -> str:
    """List tools available on a remote daemon (e.g. browser automation).
    Returns tool names and schemas. Use call_tool to invoke them."""
    daemon_map = {d["name"]: d for d in registry.discover()}
    if daemon not in daemon_map:
        result = f"Error: Unknown daemon '{daemon}'. Call discover_daemons to see available machines."
        _log("list_tools", {"daemon": daemon}, result)
        return result
    d = daemon_map[daemon]
    try:
        resp = requests.get(
            f"{d['url']}/tools",
            headers={"Authorization": f"Bearer {d['token']}"},
            timeout=10,
        )
        result = resp.text
    except Exception as e:
        result = f"Error: {e}"
    _log("list_tools", {"daemon": daemon}, result)
    return result


@mcp.tool()
async def call_tool(daemon: str, name: str, arguments: str = "{}") -> str:
    """Call a tool on a remote daemon. Use list_tools first to see what's
    available. Arguments is a JSON string matching the tool's input schema."""
    daemon_map = {d["name"]: d for d in registry.discover()}
    if daemon not in daemon_map:
        result = f"Error: Unknown daemon '{daemon}'. Call discover_daemons to see available machines."
        _log("call_tool", {"daemon": daemon, "name": name}, result)
        return result
    d = daemon_map[daemon]
    try:
        args = json.loads(arguments)
    except json.JSONDecodeError as e:
        result = f"Error: Invalid JSON arguments: {e}"
        _log("call_tool", {"daemon": daemon, "name": name}, result)
        return result
    try:
        resp = requests.post(
            f"{d['url']}/tools/call",
            json={"name": name, "arguments": args},
            headers={"Authorization": f"Bearer {d['token']}"},
            timeout=120,
        )
        result = resp.json()
    except Exception as e:
        output = f"Error: {e}"
        _log("call_tool", {"daemon": daemon, "name": name, "arguments": args}, output)
        return output

    if isinstance(result, dict) and "error" in result:
        output = f"Error: {result['error']}"
        _log("call_tool", {"daemon": daemon, "name": name, "arguments": args}, output)
        return output

    # Format MCP content array. Images saved into session directory.
    images = []
    if isinstance(result, dict) and "content" in result:
        parts = []
        for item in result["content"]:
            if item.get("type") == "text":
                parts.append(item["text"])
            elif item.get("type") == "image":
                data = base64.b64decode(item.get("data", ""))
                ext = ".png" if "png" in item.get("mimeType", "") else ".jpg"
                path = _save_screenshot(data, ext)
                images.append(path)
                parts.append(f"[screenshot saved: {path}]")
            else:
                parts.append(json.dumps(item))
        output = "\n".join(parts)
    else:
        output = json.dumps(result, indent=2)

    _log("call_tool", {"daemon": daemon, "name": name, "arguments": args}, output, images)
    return output


# ── Session log tools ────────────────────────────────────────────────

@mcp.tool()
async def session_log() -> str:
    """Return the full session log — a chronological record of every tool
    call, its result, and paths to any screenshots. Use this to review
    what you've done before building the report."""
    if not os.path.exists(_SESSION_LOG_PATH):
        return "Session log is empty."
    with open(_SESSION_LOG_PATH) as f:
        return f.read()


@mcp.tool()
async def session_screenshots() -> str:
    """Return paths to all screenshots taken during this session, in order.
    Use these paths with valid_add_screenshot when building the report."""
    shots = sorted(
        f for f in os.listdir(_SESSION_DIR) if f.endswith((".png", ".jpg"))
    )
    if not shots:
        return "No screenshots taken yet."
    paths = [os.path.join(_SESSION_DIR, f) for f in shots]
    return json.dumps(paths, indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
