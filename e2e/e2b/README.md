# E2B closed-loop example

This runs the same closed-loop demo as `e2e/local`, but the FastAPI +
Postgres stack is deployed to an [E2B](https://e2b.dev) sandbox (a
Firecracker microVM) instead of your local Docker. The validation agent
connects to the sandbox via a Go daemon and runs commands remotely.

## One-time setup

### 1. Get your E2B API key

Copy it from https://e2b.dev/dashboard and add to `.env` at the repo root:

```ini
E2B_API_KEY=e2b_xxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### 2. Build the E2B template

The sandbox needs Docker + compose preinstalled. Build the template from
`e2b.Dockerfile` using the Python SDK:

```bash
cd e2e/e2b
uv run template.py
```

When the build finishes it prints something like:

```
✓ Build complete.
  template_id:   abcd1234efgh5678
  template_name: valid-docker-compose

Add this line to ../../.env:
    E2B_TEMPLATE_ID=abcd1234efgh5678
```

### 3. Add the template ID to `.env`

Append the line it printed to the repo-root `.env`:

```ini
E2B_API_KEY=e2b_xxxxxxxxxxxxxxxxxxxxxxxxxxxx
E2B_TEMPLATE_ID=abcd1234efgh5678
```

### 4. Make sure Go is installed

`deploy.py` cross-compiles the daemon (`daemon/main.go`) for linux/amd64
every time you deploy. You just need a working `go` on your PATH:

```bash
go version   # any 1.21+
```

## Run the demo

```bash
cd e2e/e2b
uv run run.py
```

This will:

1. Cross-compile the Go daemon for `linux/amd64`
2. Spawn an E2B sandbox from your custom template
3. Wait for `dockerd` inside the sandbox to be ready
4. Upload `app/`, `docker-compose.yml`, `migrations/` as a tarball
5. Run the coding agent locally against `app/` to implement `ticket.md`
6. Run `docker compose up -d --build` inside the sandbox
7. Start the daemon, register it with the validator
8. Run the validation agent (locally), which drives commands remotely
   against the sandbox
9. Retry with feedback if validation fails (up to `--max-attempts`)
10. Kill the sandbox and restore `app/` to its original state

## Troubleshooting

- **`Missing E2B_TEMPLATE_ID`** — finish step 2+3 above.
- **`dockerd not ready inside sandbox after 60s`** — the `set_start_cmd`
  in `template.py` launches dockerd at boot. If you changed the Dockerfile
  or that command, re-run `uv run template.py` and update
  `E2B_TEMPLATE_ID` in `.env` with the new ID.
- **`docker compose up failed`** — check the printed logs. The most common
  cause is your `app/Dockerfile` failing to build. Test it locally first:
  `cd ../local && docker compose up --build`.
- **Cross-compile fails** — make sure `go` is on your PATH. The daemon is
  pure-Go with no cgo, so `GOOS=linux GOARCH=amd64 go build` just works.
