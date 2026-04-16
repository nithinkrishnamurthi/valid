"""Local deploy — runs docker compose on the host machine.

No daemon needed: the validation agent runs on the same machine
and executes commands locally via the exec tool.
"""

import json
import os
import subprocess
import time


POLL_INTERVAL = 3
HEALTH_TIMEOUT = 90


def _all_healthy(compose_dir: str, compose_file: str) -> bool:
    """Check if all services with health checks are healthy."""
    result = subprocess.run(
        ["docker", "compose", "-f", compose_file, "ps", "--format", "json"],
        cwd=compose_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False
    for line in result.stdout.strip().splitlines():
        try:
            svc = json.loads(line)
        except json.JSONDecodeError:
            return False
        health = svc.get("Health", "")
        if health in ("unhealthy", "starting"):
            return False
    return True


def deploy(
    compose_dir: str,
    compose_file: str = "docker-compose.yml",
) -> dict:
    """
    1. docker compose up -d
    2. Wait for services to be healthy
    3. Return bundle
    """
    up = subprocess.run(
        ["docker", "compose", "-f", compose_file, "up", "-d", "--build"],
        cwd=compose_dir,
        capture_output=True,
        text=True,
    )
    if up.returncode != 0:
        print(up.stdout)
        print(up.stderr)
        up.check_returncode()

    deadline = time.time() + HEALTH_TIMEOUT
    while time.time() < deadline:
        if _all_healthy(compose_dir, compose_file):
            break
        time.sleep(POLL_INTERVAL)
    else:
        logs = subprocess.run(
            ["docker", "compose", "-f", compose_file, "logs", "--tail=50"],
            cwd=compose_dir,
            capture_output=True,
            text=True,
        )
        raise TimeoutError(
            f"Services not healthy after {HEALTH_TIMEOUT}s.\n{logs.stdout}\n{logs.stderr}"
        )

    return {
        "compose_dir": compose_dir,
        "compose_file": compose_file,
    }


def redeploy(bundle: dict) -> None:
    """Restart services (after code changes)."""
    compose_dir = bundle["compose_dir"]
    compose_file = bundle["compose_file"]

    subprocess.run(
        ["docker", "compose", "-f", compose_file, "down"],
        cwd=compose_dir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["docker", "compose", "-f", compose_file, "up", "-d", "--build"],
        cwd=compose_dir,
        check=True,
        capture_output=True,
    )

    deadline = time.time() + HEALTH_TIMEOUT
    while time.time() < deadline:
        if _all_healthy(compose_dir, compose_file):
            return
        time.sleep(POLL_INTERVAL)

    raise TimeoutError(f"Services not healthy after {HEALTH_TIMEOUT}s on redeploy")


def teardown(bundle: dict) -> None:
    """Stop docker compose."""
    compose_dir = bundle.get("compose_dir")
    compose_file = bundle.get("compose_file", "docker-compose.yml")
    if compose_dir:
        subprocess.run(
            ["docker", "compose", "-f", compose_file, "down"],
            cwd=compose_dir,
            capture_output=True,
        )
