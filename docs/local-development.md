# Local development setup

These instructions cover the IMP-001 bootstrap, IMP-003 identity/account
administration, and the IMP-004 project and Markdown-draft implementation present
in this worktree. Run commands from the repository root. Docker Compose is the
supported install and start path; there is no supported direct Vite development-
server command. This is local-only, work-branch software, not a shared-server
release. Consult `BACKLOG.md` for the IMP-004 delivery outcome on this branch;
neither a candidate preview nor a worktree alone constitutes a release.

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
   migrations before starting/updating the API and front door. The earlier
   IMP-001/003 baseline check reached `20260925_0002`. This worktree adds
   `20260925_0003` for project-name keys and document/revision/conflict-proposal
   tables; the API seeds three root-template drafts on project creation and startup.
   `20260925_0004` bounds normalized project-name keys to 64-character digests.
   The candidate fixture separately
   checked a fresh database at head `20260925_0004`; this does not establish that
   every existing local database has been migrated. The API and front door wait
   for their dependencies' health checks.

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

The current IMP-004 API gate skips 9 PostgreSQL-specific integration tests; all
9 passed separately against a fresh isolated validation database migrated to
`20260925_0004`. The earlier IMP-001/003 baseline had only 3 such tests. Do not
run integration tests against a database containing local project data.

In the earlier IMP-001/003 baseline validation, the coordinator verified Compose
configuration, image builds, a fresh migration at `20260925_0002`, stack
start/status/restart, and health behavior. Health returned 200 normally, 503 with
the database stopped, and 200 after database recovery; `/api/agents` returned
404. The only published service was `127.0.0.1:8080`; all listed commands exited
0. That baseline API gate passed 32 tests, skipped 3 PostgreSQL-only tests, and
passed Ruff, format, and mypy; separate PostgreSQL migration and 3 integration
tests passed. The baseline web gate passed 6 tests plus lint, format, typecheck,
and build. Browser checks at 1440, 1024, 768, and 375 px found no horizontal
overflow and confirmed keyboard focus. These IMP-001/003 results are not final
IMP-004 gates. The latest toolkit run passed 98 tests with one gated live-Docker
test skipped; the separately exercised live recovery test is described below.

## Disposable authenticated browser review (operator-only)

This is a maintainer/operator check for the approved local checkout, not a general
product setup, CI service, or unattended global fixture. It requires Docker with a
working local Unix socket and the owner-approved handoff directory
`/tmp/opencode/impostr-review-handoff` already available to the operator and
permitted file tools. The directory must be owned by the current user and mode
`0700`; the fixture creates handoff files as mode `0600`. If tool permissions for
this channel change, first prove a harmless marker can be written and read through
the permitted tools. If that proof is denied, stop before launching or creating
credentials; do not move the file or use another tool to bypass the denial.

From the repository root, start the fixture with the approved 30-minute lifetime:

```sh
python3 scripts/local_browser_fixture.py launch --handoff-dir /tmp/opencode/impostr-review-handoff --lifetime-minutes 30
```

On success, the launcher prints the run's temporary loopback browser origin and
the private handoff-file location. Use the permitted `Read` tool to read
`member-login.json`; enter that generated, short-lived synthetic Member login in
the application's normal sign-in form in the shared Playwright page. Keep that
same authenticated page open for `ui-designer`'s rendered review. The generated
Member usernames are compact, validator-compatible synthetic identifiers, not
real-person accounts. The fixture creates a fresh disposable app/database and
does not use a test-only sign-in bypass. Do not copy login values, session data,
or the temporary origin into Git, issues, or public logs; keep browser/tool logs
private and untracked. Never use owner-created or other real-user logins, or
owner/admin/database/provider/host credentials or sessions.

After the review, stop the fixture and read its sanitized cleanup record through
the permitted `Read` tool:

```sh
python3 scripts/local_browser_fixture.py stop
```

Read `/tmp/opencode/impostr-review-handoff/cleanup-status.json`. Verified cleanup
has a stopped phase, the generated login removed, owned Compose resources and
images removed, private fixture state removed, and recovery either not needed or
completed. The cleanup record contains status values only, not credentials. A
zero exit from `stop` with that verified status indicates normal completion; a
nonzero exit means setup or review failed, even when cleanup succeeded. Two fresh
runs of this fixture completed normal browser sign-in and rendered review;
`ui-designer` returned PASS. Its checks included Member denial of an admin-only
request (HTTP 403), expired/revoked session denial (HTTP 401), and post-handoff
account/session and owned-resource cleanup.

If launch fails, it exits nonzero and reports that setup failed or no safe browser
handoff was produced; do not continue to the browser. Read the sanitized cleanup
status rather than relying on process exit or raw logs. `stop` may also exit
nonzero when setup/review failed even if owned cleanup was verified; that does not
mean the review passed. If owned teardown is still unverified after the supervisor
has stopped, retry its ownership-checked recovery:

```sh
python3 scripts/local_browser_fixture.py recover
```

Recovery succeeds only when the fixture's registered resources and private state
can be verified as removed. If a supervisor or guardian is still active, use
`stop` first. If Docker is unavailable or the local engine is recovering, retain
the private recovery state and retry after the engine is available. If the status
is `manual-required`, ownership cannot be verified: do not run broad Docker
cleanup or delete the private recovery state; request operator-assisted recovery.
The launcher also refuses to replace an existing login or prior run with
unverified cleanup. The requested lifetime is bounded (5–240 minutes) and the
fixture performs automatic teardown at its limit.

By default, the fixture archives committed `HEAD` for the app snapshot, not dirty
working-tree changes. Uncommitted IMP-004 code is therefore excluded from the
default mode. An opt-in, fingerprint-pinned candidate mode is described below; it
does not change the default. The normal browser page is served only on loopback,
but the shared Playwright tool server is **not OS-confined** and may have access to
Docker, host secrets, or another stack. This is an accepted residual host risk for
this local synthetic review, not a security control; do not claim a proven denial,
intentionally use those capabilities, or extend this exception to product-agent
isolation or shared-server readiness.

### Reviewing the dirty IMP-004 candidate

This operator-only path is separate from the committed-`HEAD` fixture mode. It is
for reviewing the specific IMP-004 worktree candidate based on `2d71c1b`; it is not
a general dirty-tree preview or a product/deployment command. The preflight needs
Docker with the local Docker socket. Candidate launch additionally requires the
already-approved handoff directory `/tmp/opencode/impostr-review-handoff` to be
owned by the operator with mode `0700` and available through the permitted file
tools. If the channel's permissions may have changed, prove a harmless write/read
marker first. If that fails, stop before creating credentials; do not choose
another path or tool.

First run the candidate infrastructure preflight from the repository root:

```sh
python3 scripts/local_browser_fixture.py candidate-preflight
```

It accepts only the fixture's explicit reviewed runtime-input and test-only
allowlists over the pinned base commit. It rejects unrelated or missing changes,
symlinks, traversal, oversized inputs (512 KiB per file and 2 MiB total), and
recognized literal secrets. The tests are accepted as test-only input, not copied
into runtime images. The fixture fingerprints the base commit, path/status/mode,
and input content digests; the fingerprint does not disclose file contents. The
preflight builds and migrates a fresh isolated Compose stack to `20260925_0004`,
checks project creation, template provenance for all three drafts, cross-member
denial and cleanup. It does **not** perform browser rendering or publish a login.
Copy the exact lowercase 64-character `CANDIDATE_FINGERPRINT` it prints. Do not
reuse any fingerprint from an earlier run or from this document.

Only if preflight passes and none of its candidate inputs have changed, launch the
rendered-review fixture with that exact fingerprint (replace the placeholder):

```sh
python3 scripts/local_browser_fixture.py launch \
  --handoff-dir /tmp/opencode/impostr-review-handoff \
  --lifetime-minutes 30 \
  --candidate-fingerprint <CANDIDATE_FINGERPRINT_FROM_THIS_PREFLIGHT>
```

The launch refuses an invalid or stale fingerprint, rechecks the snapshot, and
uses a new uniquely named local Compose project and loopback-only front door. Read
only the generated `member-login.json` through the permitted tool, use it for
normal Member sign-in, and keep that authenticated page open for the rendered
review. The fingerprint printed at launch must match the preflight fingerprint.
Candidate preflight alone is infrastructure evidence, not rendered-review signoff.
Any candidate input change requires a fresh preflight and rendered review of that
same new fingerprint.

After review, stop the supervisor and inspect only the sanitized cleanup status:

```sh
python3 scripts/local_browser_fixture.py stop \
  --handoff-dir /tmp/opencode/impostr-review-handoff
```

Read `/tmp/opencode/impostr-review-handoff/cleanup-status.json` through the
permitted tool. Confirm the phase is stopped, the generated login/accounts are
removed or disabled, owned Compose resources and run-built images are removed,
private fixture state is removed, and recovery is either `not-needed` or
`completed`. A failed review remains a failure even if owned cleanup succeeded.
If cleanup is not verified, follow the ownership-checked `recover` procedure above;
do not run broad Docker cleanup or delete recovery state manually. The fixture
removes only resources it registered to its unique project and does not prune the
shared Docker cache.

The candidate fixture necessarily uses the local Docker daemon and contains an
unconfined shared browser-tool-server residual risk. Use only its generated
synthetic account and project. Do not infer Docker/host-secret denial, product
agent isolation, or shared-server readiness. The candidate preview and browser
review do not make the dirty implementation committed or establish production
acceptance.

The separately gated live SIGKILL recovery test is run from the repository root
with Docker available and an appropriate container image already cached. It does
not pull an image; if none is cached, the test skips. The test starts two isolated
throwaway Compose projects, simulates an abrupt supervisor-child `SIGKILL`, and
checks recovery removes only the fixture-owned resources while preserving the
other test project:

```sh
IMPOSTR_FIXTURE_LIVE_RECOVERY=1 PYTHONPATH=scripts python3 -m unittest test_local_browser_fixture.RecoveryOwnershipTests.test_live_abrupt_failure_recovery_preserves_an_unrelated_compose_project
```

The default toolkit command remains `python3 -m unittest discover -s scripts -p 'test_*.py'`;
it skips this live test unless `IMPOSTR_FIXTURE_LIVE_RECOVERY=1` is set.

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

- A signed-in member can list, create, and read projects owned by their account;
  administrators can read all project metadata and documents, with admin reads
  audited. Project names are trimmed and NFC-normalized, 1–120 characters, cannot
  contain path separators/control/format characters, and are unique per owner after
  NFKC normalization, trimming and case-folding. Names never become filesystem
  paths. A new project receives an opaque ID, creator and UTC creation time, plus
  draft `PROJECT.md`, `AGENTS.md`, and `BACKLOG.md` revisions seeded from the root
  `.example` templates. The initial revision records template source and SHA-256
  provenance. On API startup, missing template drafts are also backfilled for
  existing metadata-only projects. This does not create a Git repository or launch
  the toolkit.

## Project drafts, history, and local data recovery

PostgreSQL is authoritative for project metadata, each document's current-head
number, immutable document revisions, and stale-write conflict proposals. A
revision records UTF-8 Markdown content, a SHA-256 content digest, UTC timestamp,
origin (`template` or `human`), author where applicable, and template source/digest
for template revisions. Each of the three document kinds allows at most 128 KiB
of UTF-8 content. Project and document reads/writes are restricted to the owner;
administrators may access all projects and their reads/writes are audited. A
foreign or missing project is reported as not found.

Saving a draft requires the revision number the editor read. A current expected
revision creates the next immutable `human` revision. A stale expected revision
does not overwrite the saved head: the API returns HTTP 409 with the latest
revision and records the submitted text, expected/observed revision numbers,
author, timestamp and digest as an immutable conflict proposal. Review and
reapplication are explicit; there is no automatic merge. Revision history is
ordered by revision number. Conflict-proposal pagination uses a stable cursor so
concurrent proposals do not shift already paged rows; a new history request can
show later proposals.

The API also mirrors current document heads as files named `PROJECT.md`,
`AGENTS.md`, and `BACKLOG.md` under an opaque project-ID directory in
`IMPOSTR_WORKSPACE_ROOT` (Compose currently mounts `/workspaces` as a bounded
256 MiB `tmpfs`, mode `0700`, with `noexec`, `nosuid`, and `nodev`). Workspace
directories use mode `0700` and document files mode `0600`, owned by the API user.
They are a disposable cache, not an agent workspace, approval surface, or source
of truth.
Authorized document reads rebuild the mirror from the current PostgreSQL heads.
Mirror write failures do not replace or roll back PostgreSQL data; the cache is
discarded and a later authorized read rebuilds it. The bounded cache can evict old
entries, so do not back it up or edit it as durable data.

The named `postgres-data` volume persists across ordinary `docker compose down`;
`down -v` removes it. Keep database backups outside the repository, protected
from other local users, and treat dumps as sensitive project/account data; do not
commit them. A copy of the workspace mirror
does not recover project ownership/history, and a database dump does not reproduce
uncommitted application code. Match the application/migration version when
restoring.

**Backup/restore status:** No backup/restore procedure or restore drill is
verified. The safe approach to test is a PostgreSQL-native archive (for example,
`pg_dump` in custom format) stored with owner-only permissions outside the repo,
restored with PostgreSQL tooling (for example, `pg_restore`) into a new, uniquely
named Compose project with a fresh volume. Do not use the live project volume as a
restore target or publish the test stack on the same front-door port. Verify
migration head `20260925_0004`, project ownership, all three current drafts,
revision/proposal history, and normal authorization against synthetic data; then
remove only that test project's resources and verify the original stack/data
remain untouched. These tool choices and steps are guidance, not verified
commands. Record the recovery drill as unverified until actually exercised. Do not
use Alembic downgrade or `docker compose down -v` on the source stack as recovery.

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
  stack. Migration `0003` adds project document/revision/proposal tables and the
  owner-scoped name key; `0004` bounds that key. These migrations have no verified
  backup/restore recovery procedure. Do not use a downgrade as routine recovery;
  in particular, downgrading `0003` drops project document histories and conflict
  proposals. The database volume is persistent local storage, not a tested backup
  or durability guarantee.

## Release boundary

Compose binds the front door to loopback by default and does not publish the
database or API ports. This worktree includes account authentication,
administrator-managed accounts, project creation, and private draft/revision
history. It does not yet provide chat, approvals, exports, or an agent gateway.
It has no TLS or domain setup, trusted external reverse-proxy/client-IP contract,
verified backup/restore runbook, complete release security gate, or verified agent
isolation. Do not expose it by changing the published binding, firewall, or proxy
configuration.
The agent-runtime gate remains blocked: installed OpenCode agents and a bare
`bwrap` namespace smoke test do not demonstrate a brokered, secret-safe isolated
integration. Do not infer shared-server readiness from local checks.
