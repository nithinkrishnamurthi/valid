"""Daemon binary management.

For the alpha, we cross-compile from source if the daemon/ directory exists
(development mode). In the future, we'll download pre-built binaries from
GitHub Releases.
"""

import os
import subprocess


def ensure_daemon_binary() -> str:
    """Return path to a linux/amd64 daemon binary, building if needed."""
    # Development mode: build from source
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    daemon_src = os.path.join(repo_root, "daemon")

    if os.path.isdir(daemon_src) and os.path.exists(os.path.join(daemon_src, "go.mod")):
        return _build_from_source(daemon_src)

    # Check cache
    cache_dir = os.path.expanduser("~/.valid/bin")
    cached = os.path.join(cache_dir, "daemon.linux-amd64")
    if os.path.exists(cached):
        return cached

    raise RuntimeError(
        "Daemon binary not found. Either clone the valid repo (for development) "
        "or ensure ~/.valid/bin/daemon.linux-amd64 exists."
    )


def _build_from_source(daemon_src: str) -> str:
    out_path = os.path.join(daemon_src, "daemon.linux-amd64")
    env = {**os.environ, "GOOS": "linux", "GOARCH": "amd64", "CGO_ENABLED": "0"}
    subprocess.run(
        ["go", "build", "-o", out_path, "."],
        cwd=daemon_src,
        env=env,
        check=True,
    )
    return out_path
