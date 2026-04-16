"""
E2B closed-loop e2e: coding agent implements a ticket, deploys to an
E2B sandbox with docker compose, validation agent verifies, coding
agent fixes if needed.

First-time setup: see README.md in this directory.

Usage:
    cd e2e/e2b
    uv run run.py
    uv run run.py --backend cli
    uv run run.py --max-attempts 3
"""

import argparse
import os
import sys

import anyio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from deploy import deploy, redeploy, teardown
from valid.loop import run_loop

HERE = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(HERE, "app")
TICKET_PATH = os.path.join(HERE, "ticket.md")


async def main(backend: str = None, max_attempts: int = 5):
    await run_loop(
        app_dir=APP_DIR,
        ticket_path=TICKET_PATH,
        deploy_fn=lambda: deploy(HERE),
        redeploy_fn=redeploy,
        teardown_fn=teardown,
        backend=backend,
        max_attempts=max_attempts,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=["cli", "sdk"], default=None)
    parser.add_argument("--max-attempts", type=int, default=5)
    args = parser.parse_args()
    anyio.run(main, args.backend, args.max_attempts)
