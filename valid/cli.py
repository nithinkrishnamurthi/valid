"""CLI entry point for valid.

Usage:
    valid run --provider e2b --token SECRET --task ticket.md --diff "$(git diff main)"
    valid run --provider local --task ticket.md --diff "$(git diff main)"
"""

import json
import os
import sys

import anyio
import click

from valid import __version__


@click.group()
@click.version_option(__version__)
def main():
    """Closed-loop agent validation system."""
    pass


@main.command()
@click.option(
    "--provider",
    type=click.Choice(["e2b", "local"]),
    required=True,
    help="Deploy provider.",
)
@click.option(
    "--token",
    default=None,
    help="Shared secret for daemon auth. Auto-generated if omitted.",
)
@click.option(
    "--task",
    required=True,
    type=click.Path(exists=True),
    help="Path to task/ticket markdown file.",
)
@click.option(
    "--diff",
    required=True,
    help="Git diff of changes to validate.",
)
@click.option(
    "--e2b-api-key",
    envvar="E2B_API_KEY",
    default=None,
    help="E2B API key (required for e2b provider). Also reads E2B_API_KEY env var.",
)
@click.option(
    "--backend",
    type=click.Choice(["cli", "sdk"]),
    default=None,
    help="Validation agent backend. Auto-detected if omitted.",
)
@click.option(
    "--compose-file",
    default="docker-compose.yml",
    help="Docker Compose file name.",
)
def run(provider, token, task, diff, e2b_api_key, backend, compose_file):
    """Deploy, validate, and teardown in one shot."""
    import uuid
    from valid.agent import validate

    with open(task) as f:
        task_text = f.read()

    compose_dir = os.getcwd()

    if token is None:
        token = f"eph_{uuid.uuid4().hex[:16]}"

    if provider == "e2b":
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
