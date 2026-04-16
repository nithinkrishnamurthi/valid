"""E2B deploy — spins up a sandbox from a custom Docker-enabled template,
uploads the app, runs docker compose, and starts the exec daemon.

Requires (in ../../.env):
    E2B_API_KEY=...              # from https://e2b.dev/dashboard
    E2B_TEMPLATE_ID=...          # from `e2b template build` in this dir

See README.md in this directory for first-time setup.
"""

import io
import json
import os
import subprocess
import sys
import tarfile
import time
import uuid

from dotenv import load_dotenv
from e2b_code_interpreter import Sandbox

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from valid import registry


load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))


HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.join(HERE, "..", "..")
DAEMON_SRC = os.path.join(REPO_ROOT, "daemon")
DAEMON_PORT = 9090
POLL_INTERVAL = 3
HEALTH_TIMEOUT = 120
DOCKER_READY_TIMEOUT = 60


def _require_env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(
            f"Missing {name}. Set it in ../../.env — see e2e/e2b/README.md"
        )
    return v


def _build_daemon_linux_amd64() -> str:
    """Cross-compile the Go daemon for linux/amd64. Returns binary path."""
    out_path = os.path.join(DAEMON_SRC, "daemon.linux-amd64")
    env = {**os.environ, "GOOS": "linux", "GOARCH": "amd64", "CGO_ENABLED": "0"}
    subprocess.run(
        ["go", "build", "-o", out_path, "."],
        cwd=DAEMON_SRC,
        env=env,
        check=True,
    )
    return out_path


def _tarball(src_dir: str, arcname: str) -> bytes:
    """Pack a directory into a tar.gz bytes blob (arcname = top-level dir inside)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        tf.add(src_dir, arcname=arcname)
    return buf.getvalue()


def _wait_for_docker(sbx: Sandbox, timeout: int = DOCKER_READY_TIMEOUT) -> None:
    """Block until `docker info` succeeds inside the sandbox."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = sbx.commands.run("docker info", timeout=5)
        if r.exit_code == 0:
            return
        time.sleep(2)
    raise TimeoutError("dockerd not ready inside sandbox after %ds" % timeout)


def _all_healthy(sbx: Sandbox, compose_file: str) -> bool:
    """Parse `docker compose ps --format json` and check all services are healthy."""
    r = sbx.commands.run(
        f"cd /app && docker compose -f {compose_file} ps --format json",
        timeout=10,
    )
    if r.exit_code != 0:
        return False
    for line in r.stdout.strip().splitlines():
        try:
            svc = json.loads(line)
        except json.JSONDecodeError:
            return False
        if svc.get("Health", "") in ("unhealthy", "starting"):
            return False
    return True


def deploy(
    compose_dir: str,
    compose_file: str = "docker-compose.yml",
) -> dict:
    """
    1. Build daemon for linux/amd64
    2. Create an E2B sandbox from the custom template
    3. Wait for dockerd to be ready
    4. Upload the compose_dir as a tarball, extract to /app
    5. docker compose up
    6. Upload & start the daemon
    7. Register with the daemon registry
    """
    _require_env("E2B_API_KEY")
    template_id = _require_env("E2B_TEMPLATE_ID")

    print(f"Cross-compiling daemon for linux/amd64...")
    daemon_bin = _build_daemon_linux_amd64()

    print(f"Creating E2B sandbox from template {template_id}...")
    sbx = Sandbox(template=template_id)
    token = f"eph_{uuid.uuid4().hex[:16]}"

    try:
        print("Waiting for dockerd to be ready...")
        _wait_for_docker(sbx)

        print("Uploading app...")
        tarball = _tarball(compose_dir, arcname="app")
        sbx.files.write("/tmp/app.tar.gz", tarball)
        sbx.commands.run("mkdir -p /app && tar -xzf /tmp/app.tar.gz -C /tmp && cp -r /tmp/app/. /app/", timeout=30)

        print("Running docker compose up...")
        r = sbx.commands.run(
            f"cd /app && docker compose -f {compose_file} up -d --build",
            timeout=300,
        )
        if r.exit_code != 0:
            raise RuntimeError(f"docker compose up failed:\n{r.stdout}\n{r.stderr}")

        print("Waiting for services to be healthy...")
        deadline = time.time() + HEALTH_TIMEOUT
        while time.time() < deadline:
            if _all_healthy(sbx, compose_file):
                break
            time.sleep(POLL_INTERVAL)
        else:
            logs = sbx.commands.run(
                f"cd /app && docker compose -f {compose_file} logs --tail=50",
                timeout=10,
            )
            raise TimeoutError(
                f"Services not healthy after {HEALTH_TIMEOUT}s.\n{logs.stdout}\n{logs.stderr}"
            )

        print("Uploading daemon binary...")
        with open(daemon_bin, "rb") as f:
            sbx.files.write("/usr/local/bin/daemon", f.read())
        sbx.commands.run("chmod +x /usr/local/bin/daemon")

        print("Starting daemon...")
        sbx.commands.run(
            f"DAEMON_TOKEN={token} nohup /usr/local/bin/daemon --port {DAEMON_PORT} > /tmp/daemon.log 2>&1 &",
            timeout=5,
        )
        time.sleep(2)
        r = sbx.commands.run(f"curl -s http://localhost:{DAEMON_PORT}/health", timeout=5)
        if r.exit_code != 0 or "ok" not in r.stdout:
            daemon_log = sbx.commands.run("cat /tmp/daemon.log", timeout=5)
            raise RuntimeError(f"Daemon failed to start: {daemon_log.stdout}")

        daemon_url = f"https://{sbx.get_host(DAEMON_PORT)}"
        daemon_name = f"e2b-{sbx.sandbox_id}"
        registry.register(daemon_name, daemon_url, token)

        return {
            "sandbox": sbx,
            "daemon_name": daemon_name,
            "daemon_url": daemon_url,
            "token": token,
            "compose_dir": compose_dir,
            "compose_file": compose_file,
        }
    except Exception:
        sbx.kill()
        raise


def redeploy(bundle: dict) -> None:
    """Re-upload app (with coding agent's changes) and restart services."""
    sbx: Sandbox = bundle["sandbox"]
    compose_dir = bundle["compose_dir"]
    compose_file = bundle["compose_file"]

    print("Re-uploading app with changes...")
    tarball = _tarball(compose_dir, arcname="app")
    sbx.files.write("/tmp/app.tar.gz", tarball)
    sbx.commands.run("rm -rf /app/* && tar -xzf /tmp/app.tar.gz -C /tmp && cp -r /tmp/app/. /app/", timeout=30)

    print("Restarting services...")
    sbx.commands.run(f"cd /app && docker compose -f {compose_file} down", timeout=60)
    r = sbx.commands.run(
        f"cd /app && docker compose -f {compose_file} up -d --build",
        timeout=300,
    )
    if r.exit_code != 0:
        raise RuntimeError(f"docker compose up failed on redeploy:\n{r.stdout}\n{r.stderr}")

    deadline = time.time() + HEALTH_TIMEOUT
    while time.time() < deadline:
        if _all_healthy(sbx, compose_file):
            return
        time.sleep(POLL_INTERVAL)

    raise TimeoutError(f"Services not healthy after {HEALTH_TIMEOUT}s on redeploy")


def teardown(bundle: dict) -> None:
    """Unregister the daemon and kill the sandbox."""
    sbx: Sandbox = bundle["sandbox"]
    registry.unregister(bundle["daemon_name"])
    sbx.kill()
