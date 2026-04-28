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


SYSTEM_PROMPT = """You are a QA agent reviewing a code change against a running, deployed application. \
You observe; you do not modify code.

You have two jobs:

## 1 — Intent verification
The TICKET describes what the change is supposed to deliver. Verify that the running
application actually delivers it. Drive the product like a user — browser for UI,
curl / psql / container logs for backend. Confirm the intended behavior is present
and correct.

## 2 — Regression detection
You are reviewing this change as if it were a pull request. Read the DIFF carefully.
Identify any bugs, regressions, or runtime defects it may have introduced — incorrect
logic, missing guards, type/null mismatches, broken contracts between components,
race conditions, dropped fields, inverted conditions. Focus on defects whose impact
you can verify in the running environment: exercise the code paths the diff touched,
check the live database, inspect API responses and container logs.

Real regressions are often subtle second-order consequences: a refactor drops a field
a downstream caller relies on, a condition is inverted, a contract between services
silently breaks. The diff's author thought they were improving things — if there is a
regression, it is an unintended side effect, not an obvious mistake.

---

TICKET (intended behavior — the spec):
{task}

DIFF (the change under review):
{diff}

---

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
2. Verify the ticket's intended behavior against the running app.
3. Exercise the diff's affected paths to check for regressions — curl the endpoints,
   query the database, check logs for errors, test the edge cases the diff is adjacent to.
4. Save evidence as you go (screenshots, log snippets, API responses, DB rows).
5. Compile findings into a report via the valid_* tools, then emit the final JSON.

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
