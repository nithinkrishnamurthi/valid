"""
Standalone MCP server exposing discover_daemons + exec tools.

Used by both the Agent SDK backend and Claude Code CLI backend via stdio:
    python -m valid.tools_server
"""

import json
import asyncio

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


if __name__ == "__main__":
    mcp.run(transport="stdio")
