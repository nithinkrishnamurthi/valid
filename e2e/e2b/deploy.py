"""Deploy function — spins up an E2B sandbox, deploys code, starts the daemon."""

import os
import sys
import uuid
import time
from e2b_code_interpreter import Sandbox

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import registry


DAEMON_PORT = 9090
POLL_INTERVAL = 5
HEALTH_TIMEOUT = 120


def deploy(
    repo_url: str,
    branch: str,
    compose_file: str = "docker-compose.yml",
    daemon_binary_path: str = "daemon/daemon",
) -> dict:
    """
    1. Create an E2B sandbox
    2. Clone the repo and checkout the branch
    3. Run docker compose up -d
    4. Wait for services to be healthy
    5. Generate a random token
    6. Upload and start the daemon
    7. Return the connection bundle
    """
    sbx = Sandbox()
    token = f"eph_{uuid.uuid4().hex[:16]}"

    # Clone repo
    sbx.commands.run(f"git clone --branch {branch} --single-branch {repo_url} /app", timeout=60)

    # Docker compose up
    sbx.commands.run(f"cd /app && docker compose -f {compose_file} up -d", timeout=120)

    # Wait for healthy
    deadline = time.time() + HEALTH_TIMEOUT
    while time.time() < deadline:
        result = sbx.commands.run(f"cd /app && docker compose -f {compose_file} ps --format json", timeout=10)
        if result.exit_code == 0 and "unhealthy" not in result.stdout and "starting" not in result.stdout:
            break
        time.sleep(POLL_INTERVAL)
    else:
        logs = sbx.commands.run(f"cd /app && docker compose -f {compose_file} logs --tail=50", timeout=10)
        raise TimeoutError(f"Services not healthy after {HEALTH_TIMEOUT}s.\n{logs.stdout}\n{logs.stderr}")

    # Upload daemon binary
    with open(daemon_binary_path, "rb") as f:
        sbx.files.write("/usr/local/bin/daemon", f.read())
    sbx.commands.run("chmod +x /usr/local/bin/daemon")

    # Start daemon in background
    sbx.commands.run(
        f"DAEMON_TOKEN={token} nohup /usr/local/bin/daemon --port {DAEMON_PORT} > /tmp/daemon.log 2>&1 &",
        timeout=5,
    )

    # Wait for daemon to be ready
    time.sleep(2)
    result = sbx.commands.run(f"curl -s http://localhost:{DAEMON_PORT}/health", timeout=5)
    if result.exit_code != 0 or "ok" not in result.stdout:
        raise RuntimeError(f"Daemon failed to start: {result.stderr}")

    daemon_url = f"https://{sbx.get_host(DAEMON_PORT)}"
    registry.register(f"e2b-{sbx.sandbox_id}", daemon_url, token)

    return {
        "sandbox": sbx,
        "environment_id": sbx.sandbox_id,
        "daemon_url": daemon_url,
        "token": token,
        "repo": repo_url,
        "branch": branch,
        "compose_file": compose_file,
    }


def redeploy(bundle: dict) -> None:
    """
    Inside the existing sandbox:
    1. git pull to get fix commits
    2. docker compose down + up
    3. Wait for healthy
    """
    sbx: Sandbox = bundle["sandbox"]
    compose_file = bundle["compose_file"]

    sbx.commands.run("cd /app && git pull", timeout=30)
    sbx.commands.run(f"cd /app && docker compose -f {compose_file} down", timeout=30)
    sbx.commands.run(f"cd /app && docker compose -f {compose_file} up -d", timeout=120)

    deadline = time.time() + HEALTH_TIMEOUT
    while time.time() < deadline:
        result = sbx.commands.run(f"cd /app && docker compose -f {compose_file} ps --format json", timeout=10)
        if result.exit_code == 0 and "unhealthy" not in result.stdout and "starting" not in result.stdout:
            return
        time.sleep(POLL_INTERVAL)

    raise TimeoutError(f"Services not healthy after {HEALTH_TIMEOUT}s on redeploy")


def teardown(bundle: dict) -> None:
    """Kill the E2B sandbox and unregister from registry."""
    sbx: Sandbox = bundle["sandbox"]
    registry.unregister(f"e2b-{sbx.sandbox_id}")
    sbx.kill()
