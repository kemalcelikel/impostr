# Local development setup

These instructions describe the IMP-001 bootstrap only. Run commands from the
repository root. Docker Compose is the supported install and start path; there is
no supported direct Vite development-server command. The current application is a
local bootstrap, not a multi-user or shared-server release.

## Prerequisites and pinned runtimes

- Docker Engine with Compose v2 (`docker compose`); observed verification host:
  Docker 29.8.0 and Compose 5.5.1.
- The host Python 3 executable is used only to generate the local `.env` file.
  Observed host version was Python 3.10.12.
- `curl` is optional and is used only for the command-line health check below;
  the same local endpoint can be opened in a browser.
- Application containers use Python 3.12.11, Node 22.17.0 with npm 10.9.2,
  PostgreSQL 17.6, and nginx 1.29.0. API dependencies are hash-pinned in
  `api/requirements.lock` and `api/requirements-dev.lock`; web dependencies are
  pinned by `web/package-lock.json` and `web/.npmrc` enforces the Node/npm engine
  versions. No host Node or Python application install is required.

## Create local credentials and start

1. Create a private local environment file from the canonical example. The
   following command creates `.env` with two separate random 256-bit hex passwords,
   sets mode `0600`, and refuses to overwrite an existing file:

   ```sh
   python3 -c 'from pathlib import Path; import os, secrets; os.umask(0o077); p=Path(".env"); t=Path(".env.example").read_text(); assert not p.exists(), ".env already exists; refusing to overwrite"; t=t.replace("POSTGRES_PASSWORD=\n", "POSTGRES_PASSWORD="+secrets.token_hex(32)+"\n").replace("DB_PASSWORD=\n", "DB_PASSWORD="+secrets.token_hex(32)+"\n"); p.write_text(t); p.chmod(0o600)'
   ```

   Keep `.env` local and do not copy these development credentials to another
   environment. If `.env` already exists, preserve it and handle it securely;
   do not rerun the generation command over it. The example's bind address and
   port default to `127.0.0.1:8080`; do not change the bind address to expose this
   incomplete bootstrap to a network.

2. Build the pinned service images, apply migrations, then start the stack. Use
   the same explicit Compose project name for every command in this guide; choose
   a different unique local name if another stack would otherwise share it.

   ```sh
   docker compose -p impostr-verify1 config --quiet
   docker compose -p impostr-verify1 build db api frontdoor
   docker compose -p impostr-verify1 run --rm api alembic upgrade head
   docker compose -p impostr-verify1 run --rm api alembic current
   docker compose -p impostr-verify1 up -d
   docker compose -p impostr-verify1 ps
   ```

   The migration command starts and waits for the database dependency. Apply
   migrations before starting/updating the API and front door. The current
   migration revision is `20260925_0001`; it records an empty schema baseline and
   does not create application-domain tables. The API and front door wait for
   their dependencies' health checks.

3. Open <http://127.0.0.1:8080> on the same machine. The only host-published
   service is the front door. Verify the API/database health endpoint with:

   ```sh
   curl --fail --silent --show-error http://127.0.0.1:8080/api/health
   ```

   No TLS or domain is configured. No user accounts or test logins exist yet;
   there is no account-creation or authentication workflow at this stage.

## Tests and checks

Compose loads `.env` while parsing the project, so create it before running these
commands. The `checks` profile builds the development/check images; API tests use
SQLite fixtures and do not require a running PostgreSQL service. These are the
coordinator-verified combined gates:

```sh
docker compose -p impostr-verify1 --profile checks run --build --rm api-check sh -c 'python -m pytest -p no:cacheprovider && ruff check . && ruff format --check . && mypy app'
docker compose -p impostr-verify1 --profile checks run --build --rm web-check sh -c 'npm run test && npm run lint && npm run format:check && npm run typecheck && npm run build'
```

The coordinator verified Compose configuration, image builds, a fresh migration
and current revision (`20260925_0001`), stack start/status/restart, and health
behavior. Health returned 200 normally, 503 with the database stopped, and 200
after database recovery; `/api/agents` returned 404. The only published service
was `127.0.0.1:8080`; all listed commands exited 0. Both combined app gates above
passed with four tests each and all checks at exit 0; the toolkit suite passed six
tests. Browser checks at 1440, 1024, 768, and 375 px found no horizontal overflow
and confirmed keyboard focus. The first API gate found that Ruff's default cache
path was read-only; the Compose `api-check` environment was corrected to set
`RUFF_CACHE_DIR=/tmp/ruff` and `MYPY_CACHE_DIR=/tmp/mypy`; the full rerun passed.

The local `.env` generation helper was tested by the developer from an initially
absent file; no `.env` was committed. The optional `curl` health probe was run by
the coordinator. `npm audit --audit-level=moderate` (from `web/`) found zero
moderate-or-higher issues. Host `pip-audit` is not installed and no final
independent Python dependency audit was run; no release security gate has been
established.

## Restart, updates, and troubleshooting

- Restart the existing services without rebuilding: `docker compose -p
  impostr-verify1 restart`.
- After changing image inputs, rebuild with `docker compose -p impostr-verify1
  build`. If migrations changed, apply `docker compose -p impostr-verify1 run --rm
  api alembic upgrade head` before re-creating the API/front-door containers with
  `docker compose -p impostr-verify1 up -d`.
- Inspect state and logs with `docker compose -p impostr-verify1 ps` and
  `docker compose -p impostr-verify1 logs --tail=100 db api frontdoor`.
- If a service is unhealthy, inspect its logs and `.env` variable names/values
  locally; never paste passwords into an issue or log. Compose requires both
  `POSTGRES_PASSWORD` and `DB_PASSWORD` to be non-empty.
- Stop the stack with `docker compose -p impostr-verify1 down`. The named
  `postgres-data` volume persists by default. Do not use `down -v` for a stack
  containing data you need: it permanently removes that project's database
  volume. Use volume deletion only for an explicitly disposable, isolated test
  stack. Backups, restore, and migration recovery procedures are not yet
  established, so do not treat this bootstrap as durable storage.

## Release boundary

Compose binds the front door to loopback by default and does not publish the
database or API ports. This is not a shared-server deployment recipe: the current
bootstrap has no application accounts, authentication, domain tables, TLS/domain
configuration, backup/restore guidance, release security gates, or verified
production isolation. Do not expose it by changing `APP_BIND_ADDRESS`, a firewall,
or a proxy. Those capabilities and their operational controls require separate
implementation and verification before shared-server use.
