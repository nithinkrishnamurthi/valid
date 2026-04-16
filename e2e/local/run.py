"""
Local closed-loop e2e: coding agent implements a ticket, docker compose
deploy, validation agent verifies, coding agent fixes if needed.

Usage:
    cd e2e/local
    uv run run.py --example dashboard
    uv run run.py --example kanban
    uv run run.py --example todo --max-attempts 3
"""

import argparse
import os
import sys

import anyio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from deploy import deploy, redeploy, teardown
from valid.loop import run_loop

HERE = os.path.dirname(os.path.abspath(__file__))
E2B_DIR = os.path.join(HERE, "..", "e2b")


async def main(example: str, backend: str = None, max_attempts: int = 5):
    example_dir = os.path.join(E2B_DIR, example)
    if not os.path.isdir(example_dir):
        avail = [
            d for d in os.listdir(E2B_DIR)
            if os.path.isdir(os.path.join(E2B_DIR, d))
            and os.path.exists(os.path.join(E2B_DIR, d, "ticket.md"))
        ]
        print(f"Example '{example}' not found. Available: {', '.join(sorted(avail))}")
        sys.exit(1)

    await run_loop(
        app_dir=os.path.join(example_dir, "app"),
        ticket_path=os.path.join(example_dir, "ticket.md"),
        deploy_fn=lambda: deploy(example_dir),
        redeploy_fn=redeploy,
        teardown_fn=teardown,
        backend=backend,
        max_attempts=max_attempts,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--example", default="dashboard", help="Example to run (dashboard, kanban, todo)")
    parser.add_argument("--backend", choices=["cli", "sdk"], default=None)
    parser.add_argument("--max-attempts", type=int, default=5)
    args = parser.parse_args()
    anyio.run(main, args.example, args.backend, args.max_attempts)
