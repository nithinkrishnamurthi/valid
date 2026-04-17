# /validate

Run validation against a local deployment to verify your changes work correctly in a live environment.

## Instructions

1. Look at the current git diff (`git diff main` or `git diff HEAD`) to understand what was changed.
2. Write a `ticket.md` file in the project directory describing what the changes are supposed to accomplish. Keep it concise — one paragraph is fine.
3. Run validation:

```bash
valid run --task ticket.md --diff "$(git diff main)"
```

4. Read the JSON verdict from stdout. If it fails, report the reason to the user.
5. Clean up the ticket.md file after.

## Prerequisites

- A `valid.yml` must exist in the project directory (or a parent). It defines the deploy config:

```yaml
compose: docker-compose.yml
provider: local
```

- Docker must be running locally.

## Notes

- Exit code 0 = pass, 1 = fail
- The validation agent deploys the app via docker compose, checks health/logs/endpoints, and optionally does visual regression testing via browser automation
- If no `valid.yml` exists, tell the user they need one and explain the format
