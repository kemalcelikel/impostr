# Local development setup

These instructions cover the IMP-001 bootstrap and the IMP-003 identity/account
administration and private project-metadata slice. Run commands from the repository
root. Docker Compose is the supported install and start path; there is no supported
direct Vite development-server command. The application is local-only, not a
shared-server release.

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
   do not rerun the generation command over it. The database password variables
   `POSTGRES_PASSWORD` and `DB_PASSWORD` must be non-empty. The front door is
   published on `127.0.0.1:${APP_PORT:-8080}`; do not expose it to a network.

   Compose reads `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `DB_USER`,
   `DB_PASSWORD`, `IMPOSTR_RATE_LIMIT_KEY`, `IMPOSTR_PUBLIC_ORIGIN`, and
   `APP_PORT`. The example uses database `impostr`, database owner
   `impostr_owner`, and application role `impostr_app`. Leave
   `IMPOSTR_PUBLIC_ORIGIN` unset for this local setup; the API derives
   `http://127.0.0.1:<APP_PORT>`. A blank `IMPOSTR_RATE_LIMIT_KEY` uses
   `DB_PASSWORD` as the key for pseudonymized rate-limit buckets; a separately
   configured key must contain at least 32 bytes. `APP_BIND_ADDRESS` is not a
   current setting.

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
   migration revision is `20260925_0002`; it adds account/session, audit,
   rate-limit, bootstrap-state, and project-metadata tables. This is metadata only:
   it does not implement project creation or store planning documents. The API and
   front door wait for their dependencies' health checks.

3. Bootstrap the first administrator once, after migrations and stack startup.
   Replace `adminname` with a chosen username accepted by the account rules. The
   command prompts twice for the password in the terminal; do not put passwords in
   command arguments or copy them into Git.

   ```sh
   docker compose -p impostr-verify1 run --rm -it api \
     python -m app.bootstrap_admin bootstrap --username adminname
   ```

   Bootstrap succeeds only once, when migrations are applied and the users table
   is empty. Usernames are normalized to lowercase, must start with an ASCII letter
   or digit, and contain 3–127 ASCII letters, digits, or `.`, `_`, `@`, `+`, `-`.
   Passwords must contain at least 12 characters.

4. Open <http://127.0.0.1:8080> on the same machine (the default `APP_PORT` is
   `8080`; use the configured port if you changed it). The only host-published
   service is the front door. Sign in with the credentials you chose. Verify the
   API/database health endpoint with:

   ```sh
   curl --fail --silent --show-error http://127.0.0.1:8080/api/health
   ```

   This health command uses the default port; replace `8080` if `APP_PORT` was
   changed.

   Health checks database reachability only; it does not verify sign-in or a
   project workflow. Local sign-in uses an operator-provisioned account; there is
   no public registration.

## Tests and checks

Compose loads `.env` while parsing the project, so create it before running these
commands. The `checks` profile builds the development/check images; API tests use
SQLite fixtures and do not require a running PostgreSQL service. These are the
coordinator-verified combined gates:

```sh
docker compose -p impostr-verify1 --profile checks run --build --rm api-check sh -c 'python -m pytest -p no:cacheprovider && ruff check . && ruff format --check . && mypy app'
docker compose -p impostr-verify1 --profile checks run --build --rm web-check sh -c 'npm run test && npm run lint && npm run format:check && npm run typecheck && npm run build'
```

The 3 PostgreSQL-specific integration tests are skipped in the default API gate and
were run separately against an isolated validation database. Do not run those
integration tests against a database containing local project data.

The coordinator verified Compose configuration, image builds, a fresh migration
and current revision (`20260925_0002`), stack start/status/restart, and health
behavior. Health returned 200 normally, 503 with the database stopped, and 200
after database recovery; `/api/agents` returned 404. The only published service
was `127.0.0.1:8080`; all listed commands exited 0. The API gate passed 32 tests,
skipped 3 PostgreSQL-only tests, and passed Ruff, format, and mypy. Separate
PostgreSQL migration and 3 integration tests passed. The web gate passed 6 tests
plus lint, format, typecheck, and build; the toolkit suite passed 6 tests. Browser
checks at 1440, 1024, 768, and 375 px found no horizontal overflow and confirmed
keyboard focus.

The local `.env` generation helper was tested by the developer from an initially
absent file; no `.env` was committed. The optional `curl` health probe was run by
the coordinator. An earlier `npm audit --audit-level=moderate` check (from `web/`)
found zero moderate-or-higher issues; the latest attempt was blocked by `EAI_AGAIN`
resolving the npm registry. Host `pip-audit` is not installed and no final
independent Python dependency audit was run; no release security gate has been
established.

## Accounts and operator recovery

- The initial administrator is created only through the offline bootstrap command
  above. There is no public or network endpoint to bootstrap or recover an admin.
- Administrators provision accounts in the authenticated UI. There is no
  self-registration. Admins can reset another account's password or deactivate
  it; deactivation and password resets revoke that account's active sessions.
  Users can change their own password; that revokes other sessions while keeping
  the current session active. Credential administration is recorded in the audit
  table.
- To recover an existing administrator, use the same Compose project/database and
  substitute the real administrator username. The command prompts for and
  confirms a new password, re-enables the account, and revokes its active sessions:

  ```sh
  docker compose -p impostr-verify1 run --rm -it api \
    python -m app.bootstrap_admin recover --username adminname
  ```

- Browser sessions last 12 hours. The session cookie is HttpOnly and SameSite
  Strict; unsafe API requests require a matching CSRF token and exact configured
  Origin. The API uses Argon2id password hashes and database-backed rate limits.
  These controls do not make the local-only deployment suitable for external
  exposure.

- A signed-in member can read only project metadata belonging to their account;
  administrators can read all project metadata, with admin reads audited. Project
  creation is not implemented, so a fresh local database can have no projects.
  This slice does not contain planning documents or project workflow data.

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
- If database health reports 503 during an outage, inspect the database logs,
  start the database, then wait for the API/front door health checks:

  ```sh
  docker compose -p impostr-verify1 logs --tail=100 db
  docker compose -p impostr-verify1 start db
  docker compose -p impostr-verify1 up -d
  curl --fail --silent --show-error http://127.0.0.1:8080/api/health
  ```

- Stop the stack with `docker compose -p impostr-verify1 down`. The named
  `postgres-data` volume persists by default. Do not use `down -v` for a stack
  containing data you need: it permanently removes that project's database
  volume. Use volume deletion only for an explicitly disposable, isolated test
  stack. Backups and restore procedures are not established. Migration `0002`
  creates identity, session, audit, rate-limit, and project-metadata data; do not
  use a downgrade as routine recovery because it drops these tables. No migration
  recovery procedure or durable-storage guarantee is established.

## Release boundary

Compose binds the front door to loopback by default and does not publish the
database or API ports. The application has account authentication and
administrator-managed accounts, but does not yet provide project creation,
planning documents, chat, approvals, exports, or an agent gateway. It has no TLS
or domain setup, trusted external reverse-proxy/client-IP contract, backup/restore
runbook, complete release security gate, or verified agent isolation. Do not
expose it by changing the published binding, firewall, or proxy configuration.
The agent-runtime gate remains blocked: installed OpenCode agents and a bare
`bwrap` namespace smoke test do not demonstrate a brokered, secret-safe isolated
integration. Do not infer shared-server readiness from local checks.
