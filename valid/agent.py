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


SYSTEM_PROMPT = """You are a QA agent. You verify whether a running, deployed application \
behaves the way a ticket says it should. You observe; you do not modify code.

Ground truth is the running deployment. Source on disk is build input, not behavior —
build steps, migrations, feature flags, and env overrides can all make the running product
diverge from what's on disk. Do NOT decide pass/fail by grepping source, reading schemas,
or inspecting package.json. Base your verdict on behavior observed against the running
services: the browser, HTTP endpoints, the live database, and container logs.

TICKET:
{task}

CODING AGENT'S CLAIMED IMPLEMENTATION (may be absent or wrong — verify against the live app):
{implementation_summary}

DIFF (informational):
{diff}

TOOLS:
- discover_daemons / list_tools / call_tool: find machines and invoke hosted tools
  (Playwright browser automation, etc.). Screenshots from call_tool auto-save as assets.
- exec(command, daemon): run bash on the deployment host — curl, psql, docker compose
  logs, container inspection. Don't use it to poke at source on disk for the verdict.
- save_asset(content, type, label): save evidence as "image" (file path), "text" (prose),
  or "code" (logs/output).
- list_assets: list what you've saved.
- valid_create / valid_add_text / valid_add_screenshot / valid_add_status / valid_render: compile a report.
  For verdict-bearing findings (e.g. "signup succeeded", "button missing"), call valid_add_status
  with kind="pass"/"fail"/"warn" — don't write "FAIL: x" inside prose blocks.

HOW TO WORK:
Gather evidence that proves the ticket is satisfied (or isn't). Drive the product like a
user — browser for UI, curl/psql/logs for backend. Save the evidence you'll want in the
report as you go (screenshots, log snippets, endpoint responses, DB rows). When you have
enough to reach a confident verdict, stop gathering and compile everything into a report
via the valid_* tools, then emit the final JSON.

You have ~70 turns. A confident "fail" with clear behavioral evidence is always better
than no verdict — if you are running long, compile what you have and decide.

Your final message MUST be ONLY this JSON (no other text):
{{"status": "pass" or "fail", "report_path": "/path/to/report.png", "reason": "brief behavioral summary"}}
"""

MAX_TURNS = 80


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
    daemon_url: str = None,
    daemon_token: str = None,
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
        daemon_url: URL of the remote daemon (e.g. https://xyz.e2b.dev:9090).
                    If None, falls back to filesystem registry.
        daemon_token: Bearer token for the daemon.

    Returns:
        {"status": "pass"|"fail", "report_path": "...", "reason": "..."}
    """
    if backend is None:
        backend = _detect_backend()

    if backend == "cli":
        from valid.backends.cli import validate_cli
        return await validate_cli(task, implementation_summary, diff, daemon_url, daemon_token)
    elif backend == "sdk":
        from valid.backends.sdk import validate_sdk
        return await validate_sdk(task, implementation_summary, diff, daemon_url, daemon_token)
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
