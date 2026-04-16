"""
Standalone MCP server exposing discover_daemons + exec tools.

Used by both the Agent SDK backend and Claude Code CLI backend via stdio:
    python -m valid.tools_server
"""

import json
import asyncio
import base64
import os
import tempfile

import requests
from mcp.server.fastmcp import FastMCP

from valid import registry

mcp = FastMCP("validation-tools")


@mcp.tool()
async def discover_daemons() -> str:
    """List available remote machines. Each entry has a name you can pass
    to the exec tool. Returns an empty list if no remote machines are
    registered — in that case, exec runs locally."""
    daemons = registry.discover()
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
        daemon_map = {d["name"]: d for d in registry.discover()}
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
    daemon_map = {d["name"]: d for d in registry.discover()}
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
    available. Arguments is a JSON string matching the tool's input schema."""
    daemon_map = {d["name"]: d for d in registry.discover()}
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

    # Format MCP content array into readable output.
    # Images get saved to temp files so the agent can reference them.
    if isinstance(result, dict) and "content" in result:
        parts = []
        for item in result["content"]:
            if item.get("type") == "text":
                parts.append(item["text"])
            elif item.get("type") == "image":
                data = base64.b64decode(item.get("data", ""))
                ext = ".png" if "png" in item.get("mimeType", "") else ".jpg"
                fd, path = tempfile.mkstemp(suffix=ext, prefix="valid_")
                os.write(fd, data)
                os.close(fd)
                parts.append(f"[screenshot saved: {path}]")
            else:
                parts.append(json.dumps(item))
        return "\n".join(parts)

    return json.dumps(result, indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
