# Local development and manual acceptance

Impostr runs on this PC, loopback only. Native PDFs and the composer are implemented;
local extraction, OCR/text preview and the extractor container are removed.
Bubblewrap still confines the planning worker. OpenCode has no exact version/hash lock.

The owner chose manual acceptance after implementation. Browser/full-app and actual
Azure acceptance are **not passed**. Actual synthetic backup/restore transport and
app-role ownership succeeded; the automated full constraint comparison remains
unresolved. No more testing or comparison refinements were done for this handoff.

History is preserved in `local-development-history.md`. Product rules are in PROJECT.md;
delivery and caveats are in BACKLOG.md.

## Before starting

- Docker with Compose runs the app and PostgreSQL; no host PostgreSQL install.
  Host Python, Bubblewrap and the fixed-path OpenCode executable are needed for chat.
  The launcher checks availability, other runtime pins and actual compatibility.
- Real credentials and commands below are **human only**. Never give provider auth,
  owner files or real dumps to an agent. No provider key belongs in the DB, browser,
  worker or dotenv. Automatic host OpenCode authentication reuse is not implemented.
- For an existing installation, keep its actual Compose project name and env file.
  A different project name creates a separate stack/volume, not an upgrade.
  Never use `down -v` on your data stack as a restart or upgrade command.

The following local names are examples, not credentials or deployment requirements.

## New local setup

From `/home/kemal/projects/impostr`, create a private configuration directory once:

```sh
mkdir -m 700 "$HOME/impostr-private"
(umask 077; cp -n .env.example "$HOME/impostr-private/local.env")
```

Do not overwrite existing configuration. Edit the file yourself, setting unique random
hexadecimal `POSTGRES_PASSWORD` and `DB_PASSWORD` values. Keep it mode0600.
`IMPOSTR_RATE_LIMIT_KEY` may be separate; blank uses `DB_PASSWORD`.
For default loopback use, keep `APP_PORT=8080` and `IMPOSTR_PUBLIC_ORIGIN` blank.

Set these non-secret variables in terminals used to manage this stack:

```sh
ENV_FILE="$HOME/impostr-private/local.env"
STACK=impostr-local
```

Build, initialize the DB and apply forward migrations:

```sh
docker compose --env-file "$ENV_FILE" -p "$STACK" build db api frontdoor
docker compose --env-file "$ENV_FILE" -p "$STACK" up -d --wait db
docker compose --env-file "$ENV_FILE" -p "$STACK" run --rm --no-deps api alembic upgrade head
```

For a **new** DB, create the first administrator from a plain interactive terminal.
Replace `YOUR_ADMIN_USERNAME`; its password is prompted, never passed as an argument:

```sh
docker compose --env-file "$ENV_FILE" -p "$STACK" run --rm --no-deps -it api python -m app.bootstrap_admin bootstrap --username YOUR_ADMIN_USERNAME
docker compose --env-file "$ENV_FILE" -p "$STACK" up -d --wait api frontdoor
```

Open `http://127.0.0.1:8080` and sign in. Administrators manage accounts; no public signup.
For an existing administrator, use the same interactive command with `recover` instead
of `bootstrap`. Do not bootstrap a second first-admin on a restored DB.

For an existing stack, build and migrate using its existing env/project, then recreate
API/frontdoor. Migration0013 removes extraction fields but keeps originals/history;
do not edit old migrations or wipe the DB to upgrade.

## Enable planning chat

The ordinary base stack starts without chat. In a **human's plain terminal**:

```sh
/usr/bin/python3 -I -B scripts/imp005_connection.py connect
```

Enter the actual provider API type, host, route, version and deployment requested by
the prompts. Do not guess Azure settings. Its API-key prompt is no-echo; the key stays
in the foreground host transport and is cleared on exit. Both planning text and selected
original PDFs may go to that provider. Actual Azure acceptance remains your later test.

After it reports the channel ready, use another terminal with `ENV_FILE` and `STACK` set:

```sh
export IMPOSTR_CHAT_CHANNEL_DIR=/tmp/impostr-chat-1000/channel
docker compose --env-file "$ENV_FILE" -p "$STACK" -f compose.yaml -f compose.chat.yaml up -d --no-deps --force-recreate api
```

Only the channel is mounted—not private scratch, settings or the key. Keep the foreground
connection running. Ctrl-C stops it and clears owned runtime state. To disable chat again:

```sh
docker compose --env-file "$ENV_FILE" -p "$STACK" -f compose.yaml up -d --no-deps --force-recreate api
```

Do not adopt/delete unknown stale connection locks or fall back to host execution.
No extractor setting, image, socket or overlay is needed for PDFs.

## Use and shutdown

Upload/select a PDF in a conversation and send a question. Removing a selection is not
deleting its stored file. Each file and the aggregate originals in a request must be
under50,000,000 bytes; retained history counts. Page images increase provider cost/context.
Deletion fences future sends but cannot retract prior provider input or quotations.

For shutdown, Ctrl-C the human connection, then:

```sh
docker compose --env-file "$ENV_FILE" -p "$STACK" stop api frontdoor
```

Keep DB running for backup. Full non-destructive shutdown uses `down` without `-v`.
The `/workspaces` API mirror is disposable; recreate API after restoration. Broker
scratch, channels and native processes are not backup data.

## Private backup

Human only. Stop API/frontdoor, any other non-DB services in this project, and the
foreground connection first. Keep DB running. Choose a **new** archive filename:

```sh
/usr/bin/python3 -I -B scripts/local_data.py backup --project "$STACK" --env-file "$ENV_FILE" --output "$HOME/impostr-private/impostr-backup.dump"
```

The existing parent must be operator-owned0700; env/input archives must be regular0600
single-link files. Ancestors must not be writable by another identity. Unsafe paths or
symlinks are refused, not repaired; use a genuinely private location.

The helper uses container `pg_dump`, publishes only completed private archives, and
doesn't overwrite outputs. It captures originals, users/password hashes/sessions,
projects, drafts, revisions, approvals, conversations, receipts and deletion tombstones.
Provider keys/native process state are not stored. Treat archives as private data.
64GiB/1800s are engineering bounds, not product quotas.

## Restore to a fresh target

Only restore your own trusted archive: PostgreSQL restoration executes SQL. Keep the
source app/connection stopped. Use a **different** new project and private target env
with new DB passwords—not a live or populated DB:

```sh
TARGET_ENV="$HOME/impostr-private/restore.env"
RESTORE_STACK=impostr-restore
```

Prepare `restore.env` yourself from `.env.example`, mode0600. Build only target DB, then:

```sh
docker compose --env-file "$TARGET_ENV" -p "$RESTORE_STACK" build db
/usr/bin/python3 -I -B scripts/local_data.py restore --project "$RESTORE_STACK" --env-file "$TARGET_ENV" --input "$HOME/impostr-private/impostr-backup.dump"
```

The helper starts only that DB, checks freshness/no other DB clients, and restores
transactionally as the initialized app role. It refuses populated targets and never
uses `--clean`, destroys volumes, starts apps or builds/pulls images itself.
A failure is not readiness; private PostgreSQL diagnostics are suppressed.

After successful restore, build the target API/frontdoor, migrate and recreate the cache:

```sh
docker compose --env-file "$TARGET_ENV" -p "$RESTORE_STACK" build api frontdoor
docker compose --env-file "$TARGET_ENV" -p "$RESTORE_STACK" run --rm --no-deps api alembic upgrade head
docker compose --env-file "$TARGET_ENV" -p "$RESTORE_STACK" up -d --force-recreate --wait api frontdoor
```

Use restored accounts or interactive administrator recovery; start a new human connection
only afterward. Do not run source and target against the same broker: restored project/
conversation IDs are duplicated. Older archives can resurrect deleted PDFs/accounts or
earlier session-revocation state. Later deletion does not remove those archives.

Actual synthetic transport and app-role ownership succeeded. The automated full schema/
constraint comparison remains unresolved; do not call manual restore acceptance passed.

## Your manual acceptance

- Try login, projects, PDF upload/select/send, tab/reconnect and desktop/narrow/keyboard
  behavior; check that failures keep unsent input.
- Exercise questions/permissions, proposals/conflicts, human approvals and exact downloads.
  Agents cannot approve documents or activate tasks themselves.
- Check private access and deletion; manually accept the actual Azure connection and PDF
  understanding. Already-sent provider content cannot be retracted.
- Start with disposable data for backup/restore. Check restored originals, approvals,
  drafts and access; the automated comparison caveat is not a claimed pass.

No installation, real-provider connection, ordinary app start, deployment or publication
was performed automatically for this final handoff.
