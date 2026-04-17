"""CLI entry point for valid.

Reads valid.yml from the current directory for project config, then:
    valid run --provider e2b --diff "$(git diff main)"
"""

import json
import os
import sys

import anyio
import click

from valid import __version__


def _load_dotenv() -> None:
    """Load .env from the current directory if it exists."""
    env_path = os.path.join(os.getcwd(), ".env")
    if not os.path.isfile(env_path):
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(env_path)
    except ImportError:
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


def _load_config() -> dict:
    """Load valid.yml from the current directory."""
    for name in ("valid.yml", "valid.yaml"):
        path = os.path.join(os.getcwd(), name)
        if os.path.exists(path):
            import yaml  # lazy — only needed if config exists
            with open(path) as f:
                return yaml.safe_load(f) or {}
    return {}


@click.group()
@click.version_option(__version__)
def main():
    """Closed-loop agent validation system."""
    _load_dotenv()


@main.command()
@click.option("--task", required=True, type=click.Path(exists=True), help="Path to task/ticket file.")
@click.option("--diff", required=True, help="Git diff of changes to validate.")
@click.option("--token", default=None, help="Shared secret for daemon auth. Auto-generated if omitted.")
@click.option("--e2b-api-key", envvar="E2B_API_KEY", default=None, help="E2B API key.")
@click.option("--backend", type=click.Choice(["cli", "sdk"]), default=None, help="Validation agent backend.")
def run(task, diff, token, e2b_api_key, backend):
    """Deploy, validate, and teardown in one shot.

    Reads valid.yml from the current directory for build/deploy config:

    \b
        compose: docker-compose.yml
        provider: e2b
    """
    import uuid
    from valid.agent import validate

    config = _load_config()
    if not config:
        click.echo("Error: valid.yml not found in current directory.", err=True)
        sys.exit(1)

    provider = config.get("provider")
    compose_file = config.get("compose", "docker-compose.yml")

    if not provider:
        click.echo("Error: 'provider' is required in valid.yml.", err=True)
        sys.exit(1)

    with open(task) as f:
        task_text = f.read()

    compose_dir = os.getcwd()

    if token is None:
        token = f"eph_{uuid.uuid4().hex[:16]}"

    if provider == "e2b":
        e2b_api_key = e2b_api_key or config.get("e2b_api_key")
        if not e2b_api_key:
            click.echo("Error: --e2b-api-key or E2B_API_KEY env var required for e2b provider.", err=True)
            sys.exit(1)
        from valid.providers.e2b import E2BProvider
        prov = E2BProvider(
            api_key=e2b_api_key,
            token=token,
            compose_dir=compose_dir,
            compose_file=compose_file,
        )
    elif provider == "local":
        from valid.providers.local import LocalProvider
        prov = LocalProvider(compose_dir=compose_dir, compose_file=compose_file)
    else:
        click.echo(f"Error: unknown provider '{provider}' in valid.yml.", err=True)
        sys.exit(1)

    async def _run():
        daemon_url, daemon_token = prov.deploy()
        try:
            verdict = await validate(
                task=task_text,
                implementation_summary="(see diff)",
                diff=diff,
                backend=backend,
                daemon_url=daemon_url,
                daemon_token=daemon_token,
            )
        finally:
            prov.teardown()
        return verdict

    verdict = anyio.run(_run)
    click.echo(json.dumps(verdict, indent=2))
    sys.exit(0 if verdict.get("status") == "pass" else 1)
