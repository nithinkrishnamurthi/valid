"""E2B template auto-management.

Builds the sandbox template on first run, caches the template ID
in ~/.valid/templates.json keyed by version.
"""

import json
import os

from valid import __version__


CACHE_PATH = os.path.expanduser("~/.valid/templates.json")
TEMPLATE_NAME_PREFIX = "valid-v"


def _load_cache() -> dict:
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH) as f:
            return json.load(f)
    return {}


def _save_cache(cache: dict) -> None:
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, "w") as f:
        json.dump(cache, f, indent=2)


def _dockerfile_content() -> str:
    """Load the bundled Dockerfile."""
    bundled = os.path.join(os.path.dirname(__file__), "..", "data", "e2b.Dockerfile")
    if os.path.exists(bundled):
        with open(bundled) as f:
            content = f.read()
    else:
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        with open(os.path.join(repo_root, "e2e", "e2b", "e2b.Dockerfile")) as f:
            content = f.read()
    # Strip comments — E2B's parser complains about them
    return "\n".join(
        line for line in content.splitlines() if not line.lstrip().startswith("#")
    )


def ensure_template(api_key: str, cpu_count: int = 2, memory_mb: int = 2048) -> str:
    """Return a template ID, building one if it doesn't exist for this version."""
    from e2b import Template

    template_name = f"{TEMPLATE_NAME_PREFIX}{__version__}"

    # Check local cache
    cache = _load_cache()
    if template_name in cache:
        return cache[template_name]

    print(f"Building E2B template '{template_name}' ({cpu_count} CPU, {memory_mb} MB RAM)...")
    print("This is a one-time operation and takes a few minutes.")

    def on_log(entry):
        msg = getattr(entry, "message", str(entry))
        print(f"  {msg}")

    dockerfile = _dockerfile_content()
    template = Template().from_dockerfile(dockerfile)
    info = Template.build(
        template,
        template_name,
        cpu_count=cpu_count,
        memory_mb=memory_mb,
        on_build_logs=on_log,
    )

    print(f"Template built: {info.template_id}")

    cache[template_name] = info.template_id
    _save_cache(cache)
    return info.template_id
