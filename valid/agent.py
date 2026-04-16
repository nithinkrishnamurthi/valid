"""
Validation agent — runs a read-only validation agent against a
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
import subprocess


SYSTEM_PROMPT = """You are a validation agent. Your job is to verify that a code change \
works correctly in a live deployment.

You can ONLY observe and report. You cannot modify code.

You have access to:
- discover_daemons: list available remote machines you can execute commands on
- exec: run a bash command (locally, or on a remote daemon by name)
- list_tools: discover additional tools hosted on a remote daemon
- call_tool: call a daemon-hosted tool by name and arguments (JSON string)
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
2. Call list_tools on each daemon to discover what additional tools are available
   (e.g. browser automation). Use call_tool to invoke them.
3. Check what services are running (e.g. docker compose ps)
4. Check for errors in logs (e.g. docker compose logs --tail=50)
5. Based on the diff and implementation summary, test the changed functionality:
   - Curl endpoints
   - Query the database
   - Check service health
   - If browser tools are available, use them for visual verification.
     Screenshots from call_tool are saved to local temp files — use with valid_add_screenshot.
6. Build a validation report using the valid tools:
   - valid_create with a title describing what was validated
   - Use valid_add_text with format="prose" to narrate what you did and what you observed.
     Prose supports **bold**, *italic*, lists, and other markdown formatting.
   - Use valid_add_text with format="code" for log excerpts and command output
   - valid_render to produce the final PNG
7. Your report should tell a clear story: what you tested, what you observed, what worked,
   what didn't. Be specific — include endpoint URLs, status codes, relevant log lines.

Your final message MUST be valid JSON in this format:
{{"status": "pass" or "fail", "report_path": "/path/to/report.png", "reason": "brief summary"}}
"""

MAX_TURNS = 50


def build_prompt(task: str, implementation_summary: str, diff: str) -> str:
    return SYSTEM_PROMPT.format(
        task=task,
        implementation_summary=implementation_summary,
        diff=diff,
    )


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
        from valid.backends.cli import validate_cli
        return await validate_cli(task, implementation_summary, diff)
    elif backend == "sdk":
        from valid.backends.sdk import validate_sdk
        return await validate_sdk(task, implementation_summary, diff)
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
