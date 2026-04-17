"""E2B provider — deploys to an E2B sandbox with Docker Compose.

Handles template auto-management, daemon binary upload, and MCP gateway setup.
"""

import io
import json
import os
import tarfile
import time
import uuid

import requests

from valid.providers._daemon import ensure_daemon_binary
from valid.providers._template import ensure_template


DAEMON_PORT = 9090
POLL_INTERVAL = 3
HEALTH_TIMEOUT = 120
DOCKER_READY_TIMEOUT = 60
MCP_CONFIG_PATH = "/home/user/mcp-config.json"

MCP_CONFIG = {
    "mcpServers": {
        "playwright": {
            "command": "npx",
            "args": ["-y", "@playwright/mcp", "--headless"],
        }
    }
}


def _tarball(src_dir: str, arcname: str) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        tf.add(src_dir, arcname=arcname)
    return buf.getvalue()


def _upload_app(sbx, compose_dir: str) -> None:
    stage_tar = "/home/user/_upload.tar.gz"
    stage_dir = "/home/user/_upload"

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


def _wait_for_docker(sbx, timeout: int = DOCKER_READY_TIMEOUT) -> None:
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


def _all_healthy(sbx, compose_file: str) -> bool:
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


class E2BProvider:
    def __init__(
        self,
        api_key: str,
        token: str,
        compose_dir: str,
        compose_file: str = "docker-compose.yml",
    ):
        self.api_key = api_key
        self.token = token
        self.compose_dir = compose_dir
        self.compose_file = compose_file
        self._sbx = None

    def deploy(self) -> tuple[str, str]:
        """Deploy to E2B. Returns (daemon_url, token)."""
        from e2b_code_interpreter import Sandbox

        os.environ["E2B_API_KEY"] = self.api_key

        print("Cross-compiling daemon for linux/amd64...")
        daemon_bin = ensure_daemon_binary()

        template_id = ensure_template(self.api_key)

        print(f"Creating E2B sandbox from template {template_id}...")
        sbx = Sandbox.create(template=template_id, timeout=900)
        self._sbx = sbx

        try:
            print("Waiting for dockerd...")
            _wait_for_docker(sbx)

            print("Uploading app...")
            _upload_app(sbx, self.compose_dir)

            print("Running docker compose up...")
            r = sbx.commands.run(
                f"cd /home/user/app && sudo docker compose -f {self.compose_file} up -d --build",
                timeout=300,
            )
            if r.exit_code != 0:
                raise RuntimeError(f"docker compose up failed:\n{r.stdout}\n{r.stderr}")

            print("Waiting for services to be healthy...")
            deadline = time.time() + HEALTH_TIMEOUT
            while time.time() < deadline:
                if _all_healthy(sbx, self.compose_file):
                    break
                time.sleep(POLL_INTERVAL)
            else:
                logs = sbx.commands.run(
                    f"cd /home/user/app && sudo docker compose -f {self.compose_file} logs --tail=50",
                    timeout=10,
                )
                raise TimeoutError(
                    f"Services not healthy after {HEALTH_TIMEOUT}s.\n{logs.stdout}\n{logs.stderr}"
                )

            print("Uploading daemon binary...")
            with open(daemon_bin, "rb") as f:
                sbx.files.write("/tmp/daemon", f.read())
            sbx.commands.run("sudo install -m 0755 /tmp/daemon /usr/local/bin/daemon", timeout=5)

            print("Uploading MCP config...")
            sbx.files.write(MCP_CONFIG_PATH, json.dumps(MCP_CONFIG).encode())

            print("Starting daemon...")
            sbx.commands.run(
                f"sudo -b env DAEMON_TOKEN={self.token} /usr/local/bin/daemon "
                f"--port {DAEMON_PORT} --mcp-config {MCP_CONFIG_PATH} "
                f"> /tmp/daemon.log 2>&1",
                timeout=5,
            )

            print("Waiting for daemon to be ready...")
            daemon_deadline = time.time() + 30
            daemon_up = False
            while time.time() < daemon_deadline:
                try:
                    r = sbx.commands.run(
                        f"curl -s http://localhost:{DAEMON_PORT}/health", timeout=5,
                    )
                    if r.exit_code == 0 and "ok" in r.stdout:
                        daemon_up = True
                        break
                except Exception:
                    pass
                time.sleep(2)
            if not daemon_up:
                daemon_log = sbx.commands.run("cat /tmp/daemon.log", timeout=5)
                raise RuntimeError(
                    f"Daemon failed to start after 30s.\n"
                    f"Daemon log:\n{daemon_log.stdout}\n{daemon_log.stderr}"
                )

            daemon_url = f"https://{sbx.get_host(DAEMON_PORT)}"

            # Log available MCP tools
            try:
                r = requests.get(
                    f"{daemon_url}/tools",
                    headers={"Authorization": f"Bearer {self.token}"},
                    timeout=10,
                )
                tools = r.json().get("tools", [])
                print(f"Daemon MCP tools ({len(tools)}):")
                for t in tools:
                    print(f"  - {t['name']}: {t.get('description', '')[:80]}")
            except Exception as e:
                print(f"Warning: could not list daemon tools: {e}")

            return daemon_url, self.token

        except Exception:
            sbx.kill()
            self._sbx = None
            raise

    def teardown(self) -> None:
        if self._sbx is not None:
            self._sbx.kill()
            self._sbx = None
