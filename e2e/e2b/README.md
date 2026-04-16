# E2B closed-loop example

This runs the same closed-loop demo as `e2e/local`, but the FastAPI +
Postgres stack is deployed to an [E2B](https://e2b.dev) sandbox (a
Firecracker microVM) instead of your local Docker. The validation agent
connects to the sandbox via a Go daemon and runs commands remotely.

## One-time setup

### 1. Install the E2B CLI and authenticate

```bash
npm install -g @e2b/cli
e2b auth login
```

### 2. Build the E2B template

The sandbox needs Docker + compose preinstalled. Build a custom template
from `e2b.Dockerfile` in this directory:

```bash
cd e2e/e2b
e2b template build
```

When the build finishes, the CLI prints something like:

```
✔ Building template finished.
Template ID:   abcd1234efgh5678
Template name: valid-docker-compose
```

### 3. Set up `.env` at the repo root

Create (or edit) `.env` in the repo root with:

```ini
E2B_API_KEY=e2b_xxxxxxxxxxxxxxxxxxxxxxxxxxxx
E2B_TEMPLATE_ID=abcd1234efgh5678
```

- **`E2B_API_KEY`** — copy from https://e2b.dev/dashboard
- **`E2B_TEMPLATE_ID`** — the ID printed by `e2b template build` in step 2

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
- **`dockerd not ready inside sandbox after 60s`** — the `start_cmd` in
  `e2b.toml` needs to launch dockerd at boot. If you hand-edited the
  template or skipped rebuilding after a change, run `e2b template build`
  again.
- **`docker compose up failed`** — check the printed logs. The most common
  cause is your `app/Dockerfile` failing to build. Test it locally first:
  `cd ../local && docker compose up --build`.
- **Cross-compile fails** — make sure `go` is on your PATH. The daemon is
  pure-Go with no cgo, so `GOOS=linux GOARCH=amd64 go build` just works.
