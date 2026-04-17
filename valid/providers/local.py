"""Local provider — runs docker compose on the host machine.

No remote daemon needed. The validation agent executes commands locally.
"""

import json
import subprocess
import time


POLL_INTERVAL = 3
HEALTH_TIMEOUT = 90


def _all_healthy(compose_dir: str, compose_file: str) -> bool:
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
        if svc.get("Health", "") in ("unhealthy", "starting"):
            return False
    return True


class LocalProvider:
    def __init__(self, compose_dir: str, compose_file: str = "docker-compose.yml"):
        self.compose_dir = compose_dir
        self.compose_file = compose_file

    def deploy(self) -> tuple[str | None, str | None]:
        """Start services locally. Returns (None, None) — no remote daemon."""
        up = subprocess.run(
            ["docker", "compose", "-f", self.compose_file, "up", "-d", "--build"],
            cwd=self.compose_dir,
            capture_output=True,
            text=True,
        )
        if up.returncode != 0:
            raise RuntimeError(
                f"docker compose up failed:\n{up.stdout}\n{up.stderr}"
            )

        deadline = time.time() + HEALTH_TIMEOUT
        while time.time() < deadline:
            if _all_healthy(self.compose_dir, self.compose_file):
                break
            time.sleep(POLL_INTERVAL)
        else:
            logs = subprocess.run(
                ["docker", "compose", "-f", self.compose_file, "logs", "--tail=50"],
                cwd=self.compose_dir,
                capture_output=True,
                text=True,
            )
            raise TimeoutError(
                f"Services not healthy after {HEALTH_TIMEOUT}s.\n{logs.stdout}\n{logs.stderr}"
            )

        return None, None

    def redeploy(self, compose_dir: str) -> None:
        """Restart services after code changes."""
        subprocess.run(
            ["docker", "compose", "-f", self.compose_file, "down"],
            cwd=compose_dir,
            capture_output=True,
        )
        up = subprocess.run(
            ["docker", "compose", "-f", self.compose_file, "up", "-d", "--build"],
            cwd=compose_dir,
            capture_output=True,
            text=True,
        )
        if up.returncode != 0:
            raise RuntimeError(
                f"docker compose up failed on redeploy:\n{up.stdout}\n{up.stderr}"
            )

        deadline = time.time() + HEALTH_TIMEOUT
        while time.time() < deadline:
            if _all_healthy(compose_dir, self.compose_file):
                return
            time.sleep(POLL_INTERVAL)
        raise TimeoutError(f"Services not healthy after {HEALTH_TIMEOUT}s on redeploy")

    def teardown(self) -> None:
        subprocess.run(
            ["docker", "compose", "-f", self.compose_file, "down"],
            cwd=self.compose_dir,
            capture_output=True,
        )
