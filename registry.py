"""
Daemon registry — filesystem-based coordination between deploy and validate.

Deploy scripts call register() after starting a daemon.
Teardown calls unregister() to remove it.
The validation agent calls discover() to find available machines.

Each daemon is a JSON file in .valid/daemons/:
    .valid/daemons/e2b-sandbox.json
    .valid/daemons/local.json

This works cross-process on the same machine. For cross-machine
coordination, swap the filesystem backend for S3 or an HTTP endpoint.
"""

import os
import json
import glob as _glob


DEFAULT_REGISTRY_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), ".valid", "daemons"
)


def _registry_dir(registry_dir: str = None) -> str:
    d = registry_dir or os.environ.get("VALID_REGISTRY_DIR") or DEFAULT_REGISTRY_DIR
    os.makedirs(d, exist_ok=True)
    return d


def register(name: str, url: str, token: str, registry_dir: str = None) -> str:
    """
    Register a daemon. Returns the path to the registration file.
    """
    d = _registry_dir(registry_dir)
    path = os.path.join(d, f"{name}.json")
    with open(path, "w") as f:
        json.dump({"name": name, "url": url, "token": token}, f)
    return path


def unregister(name: str, registry_dir: str = None) -> None:
    """Remove a daemon registration."""
    d = _registry_dir(registry_dir)
    path = os.path.join(d, f"{name}.json")
    if os.path.exists(path):
        os.remove(path)


def discover(registry_dir: str = None) -> list[dict]:
    """
    Return all registered daemons.
    Each entry: {"name": str, "url": str, "token": str}
    """
    d = _registry_dir(registry_dir)
    daemons = []
    for path in sorted(_glob.glob(os.path.join(d, "*.json"))):
        try:
            with open(path) as f:
                daemons.append(json.load(f))
        except (json.JSONDecodeError, OSError):
            continue
    return daemons


def clear(registry_dir: str = None) -> None:
    """Remove all daemon registrations."""
    d = _registry_dir(registry_dir)
    for path in _glob.glob(os.path.join(d, "*.json")):
        os.remove(path)
