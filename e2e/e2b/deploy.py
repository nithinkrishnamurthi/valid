"""E2B deploy — spins up a sandbox from a custom Docker-enabled template,
uploads the app, runs sudo docker compose, and starts the exec daemon.

Requires (in e2e/e2b/.env):
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


load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))


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
            f"Missing {name}. Set it in e2e/e2b/.env — see e2e/e2b/README.md"
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


def _upload_app(sbx: Sandbox, compose_dir: str) -> None:
    """Tar up compose_dir and write it into /home/user/app inside the sandbox.

    Uses paths under /home/user (owned by the `user` account) and sudo-cleans
    any leftover files so a fresh upload always overwrites cleanly. The app
    dir itself (/home/user/app) isn't removed — it's a user-owned WORKDIR
    set up at template build time — we just clear its contents.
    """
    stage_tar = "/home/user/_upload.tar.gz"
    stage_dir = "/home/user/_upload"

    # Clean any leftovers from a previous deploy; use sudo in case something
    # along the way (e.g. a docker mount) chowned files to root.
    sbx.commands.run(
        f"sudo rm -rf {stage_tar} {stage_dir} && "
        "sudo rm -rf /home/user/app/* /home/user/app/.[!.]*",
        timeout=10,
    )

    sbx.files.write(stage_tar, _tarball(compose_dir, arcname="app"))

    sbx.commands.run(
        f"mkdir -p {stage_dir} && tar -xzf {stage_tar} -C {stage_dir} && "
        f"cp -r {stage_dir}/app/. /home/user/app/ && "
        f"rm -rf {stage_tar} {stage_dir}",
        timeout=30,
    )


def _wait_for_docker(sbx: Sandbox, timeout: int = DOCKER_READY_TIMEOUT) -> None:
    """Block until `sudo docker info` succeeds inside the sandbox.

    get.docker.com installs dockerd as a systemd service that auto-starts
    at sandbox boot, but the first `docker info` after boot can hang for
    a while waiting on dockerd to finish initializing. We catch HTTP-stream
    timeouts from slow commands and keep polling.
    """
    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        try:
            r = sbx.commands.run("sudo docker info", timeout=10)
            if r.exit_code == 0:
                return
            last_err = r.stderr
        except Exception as e:
            last_err = repr(e)
        time.sleep(3)
    raise TimeoutError(
        f"dockerd not ready inside sandbox after {timeout}s. Last error:\n{last_err}"
    )


def _all_healthy(sbx: Sandbox, compose_file: str) -> bool:
    """Parse `sudo docker compose ps --format json` and check all services are healthy."""
    r = sbx.commands.run(
        f"cd /home/user/app && sudo docker compose -f {compose_file} ps --format json",
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
    4. Upload the compose_dir as a tarball, extract to /home/user/app
    5. sudo docker compose up
    6. Upload & start the daemon
    7. Register with the daemon registry
    """
    _require_env("E2B_API_KEY")
    template_id = _require_env("E2B_TEMPLATE_ID")

    print(f"Cross-compiling daemon for linux/amd64...")
    daemon_bin = _build_daemon_linux_amd64()

    print(f"Creating E2B sandbox from template {template_id}...")
    # Default sandbox timeout is 5 min — bump for docker compose + tests.
    sbx = Sandbox.create(template=template_id, timeout=900)
    token = f"eph_{uuid.uuid4().hex[:16]}"

    try:
        print("Waiting for dockerd to be ready...")
        _wait_for_docker(sbx)

        print("Uploading app...")
        _upload_app(sbx, compose_dir)

        print("Running docker compose up...")
        r = sbx.commands.run(
            f"cd /home/user/app && sudo docker compose -f {compose_file} up -d --build",
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
                f"cd /home/user/app && sudo docker compose -f {compose_file} logs --tail=50",
                timeout=10,
            )
            raise TimeoutError(
                f"Services not healthy after {HEALTH_TIMEOUT}s.\n{logs.stdout}\n{logs.stderr}"
            )

        print("Uploading daemon binary...")
        # Write to /tmp (writable by `user`), then sudo-install to /usr/local/bin.
        with open(daemon_bin, "rb") as f:
            sbx.files.write("/tmp/daemon", f.read())
        sbx.commands.run("sudo install -m 0755 /tmp/daemon /usr/local/bin/daemon", timeout=5)

        print("Starting daemon...")
        # Run as root so the validation agent's `exec` calls can talk to
        # the docker socket without also needing sudo.
        sbx.commands.run(
            f"sudo -b env DAEMON_TOKEN={token} /usr/local/bin/daemon --port {DAEMON_PORT} "
            f"> /tmp/daemon.log 2>&1",
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
    _upload_app(sbx, compose_dir)

    print("Restarting services...")
    sbx.commands.run(f"cd /home/user/app && sudo docker compose -f {compose_file} down", timeout=60)
    r = sbx.commands.run(
        f"cd /home/user/app && sudo docker compose -f {compose_file} up -d --build",
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
