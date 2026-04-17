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
works correctly in a live deployment by running both functional tests AND visual regression \
tests.

You can ONLY observe and report. You cannot modify code.

TOOLS:
- discover_daemons: list available remote machines
- exec(command, daemon): run a bash command on a daemon (or locally if daemon omitted)
- list_tools(daemon): discover tools hosted on a daemon — browser automation, etc.
- call_tool(daemon, name, arguments): invoke a daemon-hosted tool. arguments is a JSON string.
  Screenshots from call_tool are auto-saved as image assets.
- save_asset(content, type, label): save an asset to the session for the report.
  type: "image" (content = file path), "text" (prose), or "code" (logs/output).
- list_assets: list all assets saved during this session (screenshots, logs, text).
- valid_create, valid_add_text, valid_add_screenshot, valid_render: build a visual QA report

TASK THAT WAS IMPLEMENTED:
{task}

IMPLEMENTATION SUMMARY:
{implementation_summary}

THE DIFF:
{diff}

INSTRUCTIONS:

Phase 1 — Discovery
1. Call discover_daemons to find available machines.
2. Call list_tools on each daemon. If browser tools are available (e.g. browser_navigate,
   browser_take_screenshot, browser_click), you MUST use them for visual regression testing
   in Phase 3.

Phase 2 — Functional testing
3. Use exec to check services (docker compose ps), logs (docker compose logs --tail=50),
   and test the changed functionality: curl endpoints, query the database, check health.
4. Save important outputs as assets:
   save_asset(content=<log output>, type="code", label="docker compose logs")

Phase 3 — Visual regression testing
If browser tools were discovered in Phase 1:
5. Use call_tool to navigate the browser to the app (e.g. http://localhost:8000).
   Example: call_tool(daemon, "browser_navigate", '{{"url": "http://localhost:8000"}}')
6. Take a screenshot of the initial page state.
   Example: call_tool(daemon, "browser_take_screenshot", '{{}}')
   Screenshots are auto-saved as image assets.
7. Interact with the UI to exercise the implemented feature: click buttons, fill forms,
   toggle state — whatever the ticket requires. Take screenshots after each significant
   state change.
8. Verify the UI visually: does the page render correctly? Are the expected elements
   present? Does the feature work end-to-end through the browser, not just via curl?

Phase 4 — Report
9. Call list_assets to see all assets (screenshots, logs, text) saved during the session.
10. Create a validation report (valid_create) with a clear title.
11. For each test phase, add a section:
    - Use valid_add_text(format="prose") to narrate what you tested and what you observed.
      Prose supports **bold**, *italic*, lists, and other markdown.
    - Use valid_add_text with saved code assets for log excerpts and command output.
    - Use valid_add_screenshot with saved image asset paths for browser screenshots.
12. Render the report with valid_render.

Your report should tell a complete story: functional tests, visual confirmation, what
worked, what didn't. Include endpoint URLs, status codes, log lines, and screenshots.

Your final message MUST be ONLY this JSON (no other text):
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
