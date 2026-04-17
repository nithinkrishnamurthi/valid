"""
Closed-loop driver: coding agent implements a ticket, deploys, validation
agent verifies, coding agent fixes if needed. Loops until pass or max attempts.

Deploy is pluggable — callers pass in deploy / redeploy / teardown callables.
This lets the same driver work for local docker compose, an E2B sandbox,
or any other deploy target.
"""

import json
import os
import shutil
import subprocess
import tempfile
from typing import Awaitable, Callable

from valid.agent import validate


CODING_SYSTEM_PROMPT = """\
You are a coding agent. You will be given a ticket describing a feature to implement.
You must modify the application code to implement the feature.

The application is at {app_dir}.
Only modify files inside that directory.

After making changes, your final message MUST be a JSON object:
{{"summary": "bullet list of what you did", "files_changed": ["list of modified files"]}}
"""

CODING_FIX_PROMPT = """\
The validation agent tested your implementation and it FAILED.

Validation report:
{reason}

Fix the code and try again. Your final message MUST be a JSON object:
{{"summary": "bullet list of what you changed", "files_changed": ["list of modified files"]}}
"""


def _save_original(app_dir: str) -> str:
    """Snapshot app/ before the coding agent touches it."""
    backup = tempfile.mkdtemp(prefix="valid-backup-")
    shutil.copytree(app_dir, os.path.join(backup, "app"))
    return backup


def _get_diff(backup_dir: str, app_dir: str) -> str:
    result = subprocess.run(
        ["diff", "-ruN", os.path.join(backup_dir, "app"), app_dir],
        capture_output=True,
        text=True,
    )
    return result.stdout or "(no diff)"


def _restore_original(backup_dir: str, app_dir: str) -> None:
    shutil.rmtree(app_dir)
    shutil.copytree(os.path.join(backup_dir, "app"), app_dir)


def _run_coding_agent(prompt: str, app_dir: str) -> dict:
    """Run the coding agent via claude CLI. Returns parsed JSON response."""
    system = CODING_SYSTEM_PROMPT.format(app_dir=app_dir)

    cmd = [
        "claude",
        "-p", prompt,
        "--system-prompt", system,
        "--allowedTools", "Edit,Write,Read,Bash,Glob,Grep",
        "--output-format", "stream-json",
        "--verbose",
        "--max-turns", "30",
    ]

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=True,
        cwd=app_dir,
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
                    print(f"  → {block.get('name', '?')}()")
        elif etype == "result":
            result_text = event.get("result", "")

    proc.wait(timeout=30)

    try:
        return json.loads(result_text)
    except (json.JSONDecodeError, TypeError):
        return {"summary": result_text, "files_changed": []}


async def run_loop(
    app_dir: str,
    ticket_path: str,
    deploy_fn: Callable[[], dict],
    redeploy_fn: Callable[[dict], None],
    teardown_fn: Callable[[dict], None],
    backend: str = None,
    max_attempts: int = 5,
) -> dict:
    """
    Run the full closed-loop: coding agent → deploy → validate → fix → repeat.

    deploy_fn should return a dict with optional "daemon_url" and "daemon_token"
    keys. These are passed to the validation agent automatically.
    """
    with open(ticket_path) as f:
        ticket = f.read()

    backup_dir = _save_original(app_dir)

    print("=" * 60)
    print("TICKET:")
    print(ticket)
    print("=" * 60)

    bundle = None
    verdict = {"status": "unknown"}
    try:
        for attempt in range(1, max_attempts + 1):
            print(f"\n{'=' * 60}")
            print(f"ATTEMPT {attempt}/{max_attempts}")
            print("=" * 60)

            if attempt == 1:
                print("\n--- Coding agent: implementing ticket ---")
                coding_result = _run_coding_agent(
                    f"Implement this ticket:\n\n{ticket}", app_dir
                )
            else:
                print("\n--- Coding agent: fixing based on validation feedback ---")
                coding_result = _run_coding_agent(
                    CODING_FIX_PROMPT.format(reason=verdict.get("reason", "unknown")),
                    app_dir,
                )

            summary = coding_result.get("summary", "No summary provided.")
            diff = _get_diff(backup_dir, app_dir)

            print(f"\nImplementation summary: {summary}")
            print(f"Diff length: {len(diff)} chars")

            if bundle is None:
                print("\n--- Deploying ---")
                bundle = deploy_fn()
                print("Services up.")
            else:
                print("\n--- Redeploying ---")
                redeploy_fn(bundle)
                print("Services restarted.")

            # Pull daemon params from bundle if available
            _url = bundle.get("daemon_url") if isinstance(bundle, dict) else None
            _token = bundle.get("daemon_token") if isinstance(bundle, dict) else None

            print("\n--- Validation agent ---")
            verdict = await validate(
                task=ticket,
                implementation_summary=summary,
                diff=diff,
                backend=backend,
                daemon_url=_url,
                daemon_token=_token,
            )

            status = verdict.get("status", "unknown")
            print(f"\nVerdict: {status}")
            if verdict.get("report_path"):
                print(f"Report: {verdict['report_path']}")
            if verdict.get("reason"):
                print(f"Reason: {verdict['reason']}")

            if status == "pass":
                print("\n✓ Validation passed!")
                return verdict
        else:
            print(f"\n✗ Failed after {max_attempts} attempts.")
            return verdict

    finally:
        if bundle is not None:
            print("\n--- Tearing down ---")
            teardown_fn(bundle)
        _restore_original(backup_dir, app_dir)
        shutil.rmtree(backup_dir)
        print("App files restored to original state.")
