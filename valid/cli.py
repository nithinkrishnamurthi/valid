"""CLI entry point for valid.

Usage:
    valid run  --task ticket.md --diff "$(git diff main)"   # validate a diff
    valid loop --task ticket.md                              # code + validate loop
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


def _load_config(config_path: str = None) -> dict:
    """Load valid.yml from the given path or current directory."""
    if config_path:
        import yaml
        with open(config_path) as f:
            return yaml.safe_load(f) or {}
    for name in ("valid.yml", "valid.yaml"):
        path = os.path.join(os.getcwd(), name)
        if os.path.exists(path):
            import yaml
            with open(path) as f:
                return yaml.safe_load(f) or {}
    return {}


def _require_config(config_path: str = None) -> dict:
    config = _load_config(config_path)
    if not config:
        click.echo("Error: valid.yml not found. Use --config or run from a directory with valid.yml.", err=True)
        sys.exit(1)
    if not config.get("provider"):
        click.echo("Error: 'provider' is required in valid.yml.", err=True)
        sys.exit(1)
    return config


def _make_provider(config: dict, token: str = None, e2b_api_key: str = None):
    """Instantiate the deploy provider from config."""
    import uuid

    provider = config["provider"]
    compose_dir = os.getcwd()
    compose_file = config.get("compose", "docker-compose.yml")

    if token is None:
        token = f"eph_{uuid.uuid4().hex[:16]}"

    if provider == "e2b":
        e2b_api_key = e2b_api_key or config.get("e2b_api_key")
        if not e2b_api_key:
            click.echo("Error: --e2b-api-key or E2B_API_KEY env var required for e2b provider.", err=True)
            sys.exit(1)
        from valid.providers.e2b import E2BProvider
        return E2BProvider(
            api_key=e2b_api_key,
            token=token,
            compose_dir=compose_dir,
            compose_file=compose_file,
        )
    elif provider == "local":
        from valid.providers.local import LocalProvider
        return LocalProvider(compose_dir=compose_dir, compose_file=compose_file)
    else:
        click.echo(f"Error: unknown provider '{provider}' in valid.yml.", err=True)
        sys.exit(1)


@click.group()
@click.version_option(__version__)
def main():
    """Closed-loop agent validation system."""
    _load_dotenv()


@main.command()
@click.option("--config", "config_path", default=None, type=click.Path(exists=True), help="Path to valid.yml.")
@click.option("--task", required=True, type=click.Path(exists=True), help="Path to task/ticket file.")
@click.option("--diff", required=True, help="Git diff of changes to validate.")
@click.option("--token", default=None, help="Shared secret for daemon auth. Auto-generated if omitted.")
@click.option("--e2b-api-key", envvar="E2B_API_KEY", default=None, help="E2B API key.")
@click.option("--backend", type=click.Choice(["cli", "sdk"]), default=None, help="Validation agent backend.")
def run(config_path, task, diff, token, e2b_api_key, backend):
    """Validate an existing diff. Deploy, run validation agent, teardown."""
    from valid.agent import validate

    config = _require_config(config_path)
    prov = _make_provider(config, token, e2b_api_key)

    with open(task) as f:
        task_text = f.read()

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


@main.command()
@click.option("--config", "config_path", default=None, type=click.Path(exists=True), help="Path to valid.yml.")
@click.option("--task", required=True, type=click.Path(exists=True), help="Path to task/ticket file.")
@click.option("--token", default=None, help="Shared secret for daemon auth. Auto-generated if omitted.")
@click.option("--e2b-api-key", envvar="E2B_API_KEY", default=None, help="E2B API key.")
@click.option("--backend", type=click.Choice(["cli", "sdk"]), default=None, help="Validation agent backend.")
@click.option("--max-attempts", default=5, help="Max coding+validation attempts.")
@click.option("--app-dir", default=None, type=click.Path(exists=True, file_okay=False),
              help="Directory the coding agent modifies. Defaults to cwd.")
def loop(config_path, task, token, e2b_api_key, backend, max_attempts, app_dir):
    """Run a coding agent, then validate. Loop until pass or max attempts.

    A headless Claude agent implements the task, deploys the result,
    the validation agent checks it, and if it fails the coding agent
    tries again.
    """
    from valid.loop import run_loop

    config = _require_config(config_path)
    prov = _make_provider(config, token, e2b_api_key)

    compose_dir = os.getcwd()
    if app_dir is None:
        app_dir = compose_dir

    def deploy_fn():
        daemon_url, daemon_token = prov.deploy()
        return {"daemon_url": daemon_url, "daemon_token": daemon_token}

    def redeploy_fn(bundle):
        prov.redeploy(compose_dir)

    def teardown_fn(bundle):
        prov.teardown()

    async def _run():
        return await run_loop(
            app_dir=app_dir,
            ticket_path=task,
            deploy_fn=deploy_fn,
            redeploy_fn=redeploy_fn,
            teardown_fn=teardown_fn,
            backend=backend,
            max_attempts=max_attempts,
        )

    verdict = anyio.run(_run)
    click.echo(json.dumps(verdict, indent=2))
    sys.exit(0 if verdict.get("status") == "pass" else 1)
