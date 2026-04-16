"""
Full closed-loop e2e: coding agent implements a ticket, deploy,
validation agent verifies, coding agent fixes if needed.

Usage:
    cd e2e/local
    uv run run.py
    uv run run.py --backend cli
    uv run run.py --max-attempts 3
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

import anyio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from deploy import deploy, redeploy, teardown
from orchestrator import validate

HERE = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(HERE, "app")
TICKET_PATH = os.path.join(HERE, "ticket.md")

MAX_ATTEMPTS = 5

CODING_SYSTEM_PROMPT = """\
You are a coding agent. You will be given a ticket describing a feature to implement.
You must modify the application code to implement the feature.

The application is a FastAPI todo app at {app_dir}.
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


def _read_ticket() -> str:
    with open(TICKET_PATH) as f:
        return f.read()


def _save_original() -> str:
    """Snapshot app/ before the coding agent touches it."""
    backup = tempfile.mkdtemp(prefix="valid-backup-")
    shutil.copytree(APP_DIR, os.path.join(backup, "app"))
    return backup


def _get_diff(backup_dir: str) -> str:
    """Diff original app/ vs current app/."""
    result = subprocess.run(
        ["diff", "-ruN", os.path.join(backup_dir, "app"), APP_DIR],
        capture_output=True,
        text=True,
    )
    return result.stdout or "(no diff)"


def _restore_original(backup_dir: str) -> None:
    """Restore app/ from backup (for clean teardown)."""
    shutil.rmtree(APP_DIR)
    shutil.copytree(os.path.join(backup_dir, "app"), APP_DIR)


def _run_coding_agent(prompt: str) -> dict:
    """Run the coding agent via claude CLI. Returns parsed JSON response."""
    system = CODING_SYSTEM_PROMPT.format(app_dir=APP_DIR)

    cmd = [
        "claude",
        "-p", prompt,
        "--system-prompt", system,
        "--allowedTools", "Edit,Write,Read,Bash,Glob,Grep",
        "--output-format", "stream-json",
        "--max-turns", "30",
    ]

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=True,
        cwd=APP_DIR,
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


async def main(backend: str = None, max_attempts: int = MAX_ATTEMPTS):
    ticket = _read_ticket()
    backup_dir = _save_original()

    print("=" * 60)
    print("TICKET:")
    print(ticket)
    print("=" * 60)

    bundle = None
    try:
        for attempt in range(1, max_attempts + 1):
            print(f"\n{'=' * 60}")
            print(f"ATTEMPT {attempt}/{max_attempts}")
            print("=" * 60)

            # --- Coding agent ---
            if attempt == 1:
                print("\n--- Coding agent: implementing ticket ---")
                coding_result = _run_coding_agent(
                    f"Implement this ticket:\n\n{ticket}"
                )
            else:
                print("\n--- Coding agent: fixing based on validation feedback ---")
                coding_result = _run_coding_agent(
                    CODING_FIX_PROMPT.format(reason=verdict.get("reason", "unknown"))
                )

            summary = coding_result.get("summary", "No summary provided.")
            diff = _get_diff(backup_dir)

            print(f"\nImplementation summary: {summary}")
            print(f"Diff length: {len(diff)} chars")

            # --- Deploy ---
            if bundle is None:
                print("\n--- Deploying ---")
                bundle = deploy(HERE)
                print("Services up.")
            else:
                print("\n--- Redeploying ---")
                redeploy(bundle)
                print("Services restarted.")

            # --- Validate ---
            print("\n--- Validation agent ---")
            verdict = await validate(
                task=ticket,
                implementation_summary=summary,
                diff=diff,
                backend=backend,
            )

            status = verdict.get("status", "unknown")
            print(f"\nVerdict: {status}")
            if verdict.get("report_path"):
                print(f"Report: {verdict['report_path']}")
            if verdict.get("reason"):
                print(f"Reason: {verdict['reason']}")

            if status == "pass":
                print("\n✓ Validation passed!")
                break
        else:
            print(f"\n✗ Failed after {max_attempts} attempts.")

    finally:
        if bundle:
            print("\n--- Tearing down ---")
            teardown(bundle)
        # Restore original files so the example is rerunnable
        _restore_original(backup_dir)
        shutil.rmtree(backup_dir)
        print("App files restored to original state.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=["cli", "sdk"], default=None)
    parser.add_argument("--max-attempts", type=int, default=MAX_ATTEMPTS)
    args = parser.parse_args()
    anyio.run(main, args.backend, args.max_attempts)
