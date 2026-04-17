# /validate

Run validation against a local deployment. Use this after implementing a ticket to verify your changes work correctly in a live environment.

## Prerequisites

- A `valid.yml` file in the project directory (or specify with `--config`)
- Docker running locally
- The `valid` CLI installed (`pip install valid` or `uv pip install valid`)

## Usage

### Validate a diff you've already written

```bash
valid run --task <ticket_file> --diff "$(git diff main)"
```

### Full coding + validation loop

```bash
valid loop --task <ticket_file> --max-attempts 5
```

### With a config file in a different directory

```bash
valid run --config path/to/valid.yml --task ticket.md --diff "$(git diff main)"
```

## What happens

1. Reads `valid.yml` for deploy config (compose file, provider)
2. Loads `.env` from cwd for secrets (e.g. `E2B_API_KEY`)
3. Deploys the app (docker compose up locally, or to an E2B sandbox)
4. Runs a validation agent that inspects the deployment:
   - Checks service health, logs, API endpoints
   - Uses browser automation if available (Playwright via daemon)
   - Takes screenshots for visual regression
5. Returns a JSON verdict: `{"status": "pass"|"fail", "reason": "..."}`
6. Tears down the deployment

## valid.yml format

```yaml
compose: docker-compose.yml
provider: local    # or "e2b" for remote sandboxes
```

## Example: validate after coding

After you finish implementing a ticket:

```bash
# From the directory containing valid.yml and docker-compose.yml
valid run --task ticket.md --diff "$(git diff main)"
```

The exit code is 0 for pass, 1 for fail. The JSON verdict is printed to stdout.
