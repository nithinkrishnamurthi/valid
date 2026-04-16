"""
Local e2e example — deploys a FastAPI todo app via docker compose,
starts the daemon locally, runs the validation agent.

Usage:
    cd e2e/local
    python run.py              # auto-detect backend
    python run.py --backend cli   # force Claude Code CLI
    python run.py --backend sdk   # force Agent SDK
"""

import argparse
import os
import sys
import anyio

# Add project root to path for orchestrator import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from deploy import deploy, redeploy, teardown
from orchestrator import validate


TASK = """\
Add a PATCH endpoint `PATCH /api/todos/:id/toggle` that flips the `done` status
of a todo item. If the todo is currently `done: false`, it should become `done: true`,
and vice versa. Return the updated todo object. Return 404 if not found.\
"""

IMPLEMENTATION_SUMMARY = """\
- Added PATCH /api/todos/{todo_id}/toggle endpoint to main.py
- Uses UPDATE todos SET done = NOT done WHERE id = %s RETURNING id, title, done
- Returns 404 if no row found
"""

DIFF = """\
(placeholder — in a real flow the coding agent would provide the actual diff)
"""


async def main(backend: str = None):
    compose_dir = os.path.dirname(os.path.abspath(__file__))

    print("=== Deploying locally ===")
    bundle = deploy(compose_dir)
    print("Services up.")

    try:
        print("\n=== Running validation agent ===")
        verdict = await validate(
            task=TASK,
            implementation_summary=IMPLEMENTATION_SUMMARY,
            diff=DIFF,
            backend=backend,
        )

        print(f"\n{'=' * 60}")
        print(f"Status: {verdict.get('status', 'unknown')}")
        print(f"Report: {verdict.get('report_path', 'none')}")
        if verdict.get("reason"):
            print(f"Reason: {verdict['reason']}")
    finally:
        print("\n=== Tearing down ===")
        teardown(bundle)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=["cli", "sdk"], default=None)
    args = parser.parse_args()
    anyio.run(main, args.backend)
