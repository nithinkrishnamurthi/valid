"""
Local closed-loop e2e: coding agent implements a ticket, docker compose
deploy, validation agent verifies, coding agent fixes if needed.

Usage:
    cd e2e/local
    uv run run.py --example dashboard
    uv run run.py --example kanban --backend cli
    uv run run.py --example dashboard --max-attempts 3
"""

import argparse
import os
import sys

import anyio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from deploy import deploy, redeploy, teardown
from valid.loop import run_loop

HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLES_DIR = os.path.join(HERE, "..", "examples")


async def main(example: str, backend: str = None, max_attempts: int = 5):
    example_dir = os.path.join(EXAMPLES_DIR, example)
    if not os.path.isdir(example_dir):
        avail = [d for d in os.listdir(EXAMPLES_DIR) if os.path.isdir(os.path.join(EXAMPLES_DIR, d))]
        print(f"Example '{example}' not found. Available: {', '.join(sorted(avail))}")
        sys.exit(1)

    app_dir = os.path.join(example_dir, "app")
    ticket_path = os.path.join(example_dir, "ticket.md")

    await run_loop(
        app_dir=app_dir,
        ticket_path=ticket_path,
        deploy_fn=lambda: deploy(example_dir),
        redeploy_fn=redeploy,
        teardown_fn=teardown,
        backend=backend,
        max_attempts=max_attempts,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--example", default="dashboard", help="Example to run (dashboard, kanban)")
    parser.add_argument("--backend", choices=["cli", "sdk"], default=None)
    parser.add_argument("--max-attempts", type=int, default=5)
    args = parser.parse_args()
    anyio.run(main, args.example, args.backend, args.max_attempts)
