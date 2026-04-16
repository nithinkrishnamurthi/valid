"""Build the E2B sandbox template from e2b.Dockerfile.

Run this once (per E2B account) before using run.py:

    cd e2e/e2b
    uv run template.py

It prints the template ID to put in ../../.env as E2B_TEMPLATE_ID.
"""

import os
import sys

from dotenv import load_dotenv
from e2b import Template


HERE = os.path.dirname(os.path.abspath(__file__))
DOCKERFILE = os.path.join(HERE, "e2b.Dockerfile")
TEMPLATE_NAME = "valid-docker-compose"


def main():
    load_dotenv(os.path.join(HERE, "..", "..", ".env"))

    if not os.environ.get("E2B_API_KEY"):
        print("Missing E2B_API_KEY. Set it in ../../.env — see README.md", file=sys.stderr)
        sys.exit(1)

    # Print build logs as they stream.
    def on_log(entry):
        msg = getattr(entry, "message", str(entry))
        print(f"  {msg}")

    # No set_start_cmd: the get.docker.com install script sets up dockerd
    # as a systemd service that auto-starts at sandbox boot. deploy.py polls
    # for readiness and can fall back to `sudo service docker start` if
    # dockerd isn't up yet.
    #
    # Strip comments so e2b's Dockerfile parser doesn't print
    # "Unsupported instruction: COMMENT" for every `#` line.
    with open(DOCKERFILE) as f:
        dockerfile_content = "\n".join(
            line for line in f.read().splitlines() if not line.lstrip().startswith("#")
        )
    template = Template().from_dockerfile(dockerfile_content)

    print(f"Building template '{TEMPLATE_NAME}' (2 CPU, 2 GB RAM)...")
    info = Template.build(
        template,
        TEMPLATE_NAME,
        cpu_count=2,
        memory_mb=2048,
        on_build_logs=on_log,
    )

    print()
    print(f"✓ Build complete.")
    print(f"  template_id:   {info.template_id}")
    print(f"  template_name: {info.name}")
    print()
    print("Add this line to ../../.env:")
    print(f"    E2B_TEMPLATE_ID={info.template_id}")


if __name__ == "__main__":
    main()
