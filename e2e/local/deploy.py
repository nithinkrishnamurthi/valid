"""Local deploy — runs docker compose and daemon on the host machine."""

import os
import sys
import subprocess
import time
import uuid
import signal
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import registry


DAEMON_PORT = 9090
POLL_INTERVAL = 3
HEALTH_TIMEOUT = 90


def deploy(
    compose_dir: str,
    compose_file: str = "docker-compose.yml",
    daemon_binary: str = None,
) -> dict:
    """
    1. docker compose up -d
    2. Wait for services to be healthy
    3. Start the daemon locally
    4. Return connection bundle
    """
    if daemon_binary is None:
        # Default: built daemon binary at repo root
        daemon_binary = os.path.join(
            os.path.dirname(__file__), "..", "..", "daemon", "daemon"
        )
    daemon_binary = os.path.abspath(daemon_binary)

    if not os.path.isfile(daemon_binary):
        raise FileNotFoundError(
            f"Daemon binary not found at {daemon_binary}. "
            f"Build it with: cd daemon && go build -o daemon ."
        )

    token = f"eph_{uuid.uuid4().hex[:16]}"

    # Start services
    subprocess.run(
        ["docker", "compose", "-f", compose_file, "up", "-d", "--build"],
        cwd=compose_dir,
        check=True,
        capture_output=True,
    )

    # Wait for healthy
    deadline = time.time() + HEALTH_TIMEOUT
    while time.time() < deadline:
        result = subprocess.run(
            ["docker", "compose", "-f", compose_file, "ps", "--format", "json"],
            cwd=compose_dir,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and "unhealthy" not in result.stdout and "starting" not in result.stdout:
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

    # Start daemon
    env = os.environ.copy()
    env["DAEMON_TOKEN"] = token
    daemon_proc = subprocess.Popen(
        [daemon_binary, "--port", str(DAEMON_PORT)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for daemon to be ready
    time.sleep(1)
    for _ in range(10):
        try:
            resp = requests.get(f"http://localhost:{DAEMON_PORT}/health", timeout=2)
            if resp.status_code == 200:
                break
        except requests.ConnectionError:
            time.sleep(0.5)
    else:
        daemon_proc.kill()
        raise RuntimeError("Daemon failed to start")

    daemon_url = f"http://localhost:{DAEMON_PORT}"
    registry.register("local", daemon_url, token)

    return {
        "daemon_url": daemon_url,
        "token": token,
        "compose_dir": compose_dir,
        "compose_file": compose_file,
        "daemon_proc": daemon_proc,
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
        result = subprocess.run(
            ["docker", "compose", "-f", compose_file, "ps", "--format", "json"],
            cwd=compose_dir,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and "unhealthy" not in result.stdout and "starting" not in result.stdout:
            return
        time.sleep(POLL_INTERVAL)

    raise TimeoutError(f"Services not healthy after {HEALTH_TIMEOUT}s on redeploy")


def teardown(bundle: dict) -> None:
    """Stop daemon, docker compose, and unregister from registry."""
    registry.unregister("local")

    daemon_proc = bundle.get("daemon_proc")
    if daemon_proc:
        daemon_proc.send_signal(signal.SIGTERM)
        try:
            daemon_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            daemon_proc.kill()

    compose_dir = bundle.get("compose_dir")
    compose_file = bundle.get("compose_file", "docker-compose.yml")
    if compose_dir:
        subprocess.run(
            ["docker", "compose", "-f", compose_file, "down"],
            cwd=compose_dir,
            capture_output=True,
        )
