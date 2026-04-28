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


SYSTEM_PROMPT = """You are reviewing this code change as if it were a pull request submitted \
for your review. You have a running, deployed application available — use it.

Read the diff carefully. Identify any bugs, regressions, or runtime defects it may have
introduced. Focus on actual defects (incorrect logic, missing guards, type/null mismatches,
broken contracts, race conditions, security issues), not style nits.

Unlike a static reviewer, you can exercise the affected code paths against the live
environment: hit the endpoints, query the database, inspect container logs, drive the
browser. Use this to confirm or rule out each potential defect with behavioral evidence
rather than inference from source alone.

DIFF:
{diff}

TICKET (context for what the change intended to deliver — do not treat as the verdict criterion):
{task}

TOOLS:
- discover_daemons / list_tools / call_tool: find machines and invoke hosted tools
  (Playwright browser automation, etc.). Screenshots from call_tool auto-save as assets.
- bash(command, daemon): run a shell command on the deployment host — curl, psql, docker
  compose logs, container inspection.
- read(path, daemon): read a file on the deployment host.
- write(path, content, daemon): write a file on the deployment host.
- grep(pattern, path, daemon): search for a pattern in files on the deployment host.
- glob(pattern, daemon): list files matching a pattern on the deployment host.
- save_asset(content, type, label): save evidence as "image" (file path), "text" (prose),
  or "code" (logs/output).
- list_assets: list what you've saved.
- valid_create / valid_add_text / valid_add_screenshot / valid_add_status / valid_render: compile a report.
  For verdict-bearing findings call valid_add_status with kind="pass"/"fail"/"warn".

HOW TO WORK:
1. Read the diff and identify the code paths it touches.
2. Exercise those paths in the running app — curl endpoints, query the DB, check logs,
   drive the browser through the affected flows.
3. Save evidence as you go (API responses, log snippets, screenshots, DB rows).
4. Compile findings into a report via the valid_* tools, then emit the final JSON.

You have ~70 turns. A confident "fail" with clear behavioral evidence beats no verdict —
if you are running long, compile what you have and decide.

Emit the verdict as ONLY this JSON (no other text):
{{"status": "pass" or "fail", "report_path": "/path/to/report.png", "reason": "one mechanical sentence naming the behavioral evidence"}}
"""

MAX_TURNS = 80


def build_prompt(task: str, diff: str) -> str:
    return SYSTEM_PROMPT.format(task=task, diff=diff)


async def validate(
    task: str,
    diff: str,
    backend: str = None,
    daemon_url: str = None,
    daemon_token: str = None,
) -> dict:
    """
    Run the validation agent against an already-deployed environment.

    Args:
        task: Ticket describing what the change should deliver.
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
        return await validate_cli(task, diff, daemon_url, daemon_token)
    elif backend == "sdk":
        from valid.backends.sdk import validate_sdk
        return await validate_sdk(task, diff, daemon_url, daemon_token)
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
