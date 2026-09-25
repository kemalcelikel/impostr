# Repository agent rules: Impostr

## Sources and current state

- `PROJECT.md` is the product, data, security and UI contract; `BACKLOG.md` holds
  future slices and readiness. `PROJECT.md` contains pre-bootstrap status statements
  that are now stale; current local operation instructions are in
  `docs/local-development.md`. Root `PROJECT.md.example`, `AGENTS.md.example`, and
  `BACKLOG.md.example` are canonical _inputs_ for Impostr-created projects, not
  Impostr's live instructions. Root `scripts/backlog.py` defines the compatible
  backlog parser/eligibility behavior; `.env.example` is for this checkout's local
  Compose setup.
- `overnight-agent/agents/` contains the distribution agent definitions. The
  current OpenCode CLI can list the installed `tech-lead`, `architect`,
  `ui-designer`, `developer`, `senior-developer`, `reviewer`, `docs` and `overnight`.
  `overnight` is runner-only; web planning uses `tech-lead`.
- This checkout now contains the IMP-001 application bootstrap: Compose services,
  a FastAPI health endpoint, a static web front door, PostgreSQL, and an initial
  Alembic baseline. It is not yet the planned user-facing application: there is no
  sign-in, test account, domain schema, project workflow, or shared-server release.
  Do not substitute toolkit runner tests or the current health checks for those
  missing application acceptance tests. The supported local setup and exact
  verified commands are in `docs/local-development.md`.
- The published planning baseline was `v1` at `1731c81`; the IMP-001 batch started
  from `86a97a4` on `feature/impostr-v1`. This work branch is not itself a published
  release. Confirm the current published baseline and workflow before future work
  or publication. The owner approved replacing the selected sprint flow with the
  single-branch batch contract below; do not run under the new contract until it
  has been published.

## Start of work and delegation

Read the assignment and relevant project contract; inspect `git status --short`
and recent history before changing files. Preserve existing/untracked work and
record the baseline. `tech-lead` and owner decide future backlog scope/readiness;
`architect` resolves new trust/contract boundaries, `ui-designer` sets material UI
direction and reviews rendered screens, developer implements, and reviewer
independently reviews significant behavior, especially identity, multi-project
authorization, agent isolation, revisions and export. Docs follows a stable feature
batch. Subagents do not independently change task status or commit. No agent
installs/updates skills or tooling to make missing capabilities appear present.

Generated items are `[-]` until owner approval of their readiness. Do not claim
or reset another run's `[~]`, or requeue `[!]` without owner approval. The root
runner is **not yet authorized to implement this unpublished backlog**: publish the
approved batch contract and readiness markers, then create the work branch from
the aligned published baseline. Do not run it just because it exists here. For
future user-created projects, exporting files does not initialize a repo or make
its runner safe to launch. Avoid two writers in the same checkout or the same
project's planning files.

## Verified commands and capability gaps

Commands below are observed on this checkout; run from repository root unless
otherwise stated. Application commands, runtime pins, and local-only operating
limits are maintained in `docs/local-development.md`.

| Purpose                                                                                     | Command                                                                      | Observed status / limitation                                                                                          |
| ------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| Toolkit runner regression                                                                   | `python3 -m unittest discover -s scripts -p 'test_*.py'`                     | Verified: six passing tests with fake OpenCode, not Impostr app tests.                                                |
| Backlog parser smoke                                                                        | `python3 scripts/backlog.py list-all BACKLOG.md.example`                     | Verified against starter backlog; use `BACKLOG.md` for the live plan after drafting.                                  |
| Inspect agent availability                                                                  | `opencode agent list`                                                        | Verified CLI responds and includes relevant agents; not a live web integration test.                                  |
| Toolchain inspection                                                                        | `python3 --version`; `node --version`; `npm --version`; `opencode --version` | Host observed Python 3.10.12, Node v24.12.0, npm 11.6.2, OpenCode 1.18.32. App containers pin Python 3.12.11, Node 22.17.0/npm 10.9.2, PostgreSQL 17.6, and nginx 1.29.0. |
| Docker/Compose baseline | `docker info --format '{{.ServerVersion}}'`; `docker compose version` | Verified Docker server 29.8.0 and Compose v5.5.1. Docker socket access is host-root-equivalent; web planning agents must not receive it. |
| GitHub PR tooling (read-only) | `gh --version`; `gh repo view --json nameWithOwner -q .nameWithOwner`; `gh pr list --state open --json number,headRefName,baseRefName --limit 20` | Verified GitHub CLI 2.101.0 is authenticated and can read `kemalcelikel/impostr`; PR creation and new branch push have not been exercised. Do not log tokens. |
| IMP-001 install/start/migrations/tests/lint/format/typecheck/build/container checks          | Exact verified commands below; expanded setup in `docs/local-development.md` | Coordinator verification passed: API 4 tests/checks, web 4 tests/checks, container/health/recovery checks, and six toolkit tests. No test accounts or end-to-end product workflow tests exist. |
| Dependency/security checks                                                                    | From `web/`: `npm audit --audit-level=moderate` | Coordinator verified 0 moderate-or-higher npm findings. Host `pip-audit` is not installed; no final independent Python dependency audit was run. No release security gate/policy is configured. |

### IMP-001 verified local commands

Run from the repository root with a local `.env` created from `.env.example`;
never copy its generated secrets elsewhere. Compose reads `POSTGRES_DB`,
`POSTGRES_USER`, `POSTGRES_PASSWORD`, `DB_USER`, `DB_PASSWORD`,
`APP_BIND_ADDRESS`, and `APP_PORT`. The password values are required; the example
defaults to database `impostr`, owner `impostr_owner`, app role `impostr_app`, and
loopback `127.0.0.1:8080`. The app dependency/runtime locks are
`api/requirements.lock`, `api/requirements-dev.lock`, and
`web/package-lock.json` (`web/.npmrc` enforces Node/npm versions).

The coordinator verified this isolated local sequence with project name
`impostr-verify1`:

```sh
docker compose -p impostr-verify1 config --quiet
docker compose -p impostr-verify1 build db api frontdoor
docker compose -p impostr-verify1 run --rm api alembic upgrade head
docker compose -p impostr-verify1 run --rm api alembic current
docker compose -p impostr-verify1 up -d
docker compose -p impostr-verify1 ps
curl --fail --silent --show-error http://127.0.0.1:8080/api/health
docker compose -p impostr-verify1 restart
docker compose -p impostr-verify1 run --rm api alembic current
```

The current migration revision is `20260925_0001`. All commands in the setup and
recovery sequences exited 0.
The only published host port was loopback `127.0.0.1:8080`; health returned 200.
Coordinator recovery checks also confirmed database stop returned health 503,
database start restored health 200, and `/api/agents` returned 404:

```sh
docker compose -p impostr-verify1 stop db
curl --silent --output /dev/null --write-out 'DB outage HTTP %{http_code}\n' http://127.0.0.1:8080/api/health
docker compose -p impostr-verify1 start db
docker compose -p impostr-verify1 up -d
curl --fail --silent --show-error http://127.0.0.1:8080/api/health
curl --silent --output /dev/null --write-out 'Unknown endpoint HTTP %{http_code}\n' http://127.0.0.1:8080/api/agents
docker compose -p impostr-verify1 down
```

The supported tests and checks are:

```sh
docker compose -p impostr-verify1 --profile checks run --build --rm api-check sh -c 'python -m pytest -p no:cacheprovider && ruff check . && ruff format --check . && mypy app'
docker compose -p impostr-verify1 --profile checks run --build --rm web-check sh -c 'npm run test && npm run lint && npm run format:check && npm run typecheck && npm run build'
python3 -m unittest discover -s scripts -p 'test_*.py'
```

Both app gates passed with four tests each and all listed checks at exit 0; the
toolkit suite passed six tests. Browser checks at 1440, 1024, 768, and 375 px found
no horizontal overflow and confirmed keyboard focus. The first API gate exposed a
Ruff cache write failure in the read-only check image; Compose now sets
`RUFF_CACHE_DIR=/tmp/ruff` and `MYPY_CACHE_DIR=/tmp/mypy`, and the rerun passed.
See `docs/local-development.md` for local secret setup, health/recovery details,
and operating limits.

Do not commit `.env`, database dumps, private transcripts, provider config or
`.opencode/progress.md`/runner logs. The checked-in `.env.example` contains empty
local-development secret fields, not usable credentials. Current Compose publishes
only the front door on loopback; it provides no TLS, domain, account bootstrap, or
shared-server deployment. Use the local-only setup instructions and do not infer
production or release readiness from a passing container check. The installed
`ui-ux-pro-max` and `ui-styling` skills are optional design aids; the `ui-designer`
may use them without reinstalling them. Browser tools are available, but no
application browser-test command or test login has been established.

## Implementation and review boundaries

- Follow `PROJECT.md` for ownership, revision/approval invariants, agent runtime
  isolation and export behavior. A browser check or client-side state restriction
  never replaces server authorization; test cross-user/project/session access and
  stale-version behavior. Keep privileged model/DB/network configuration outside
  agent workspaces and Git.
- Protect root templates and runner/parser compatibility; if changing their
  semantics, separately scope regression tests and migration/compatibility work.
  Keep user-created project workspaces away from other projects and this repo's
  live planning files. Do not hand-edit generated lockfiles or compiled assets.
- Pin actual dependencies and commit manifests/lockfiles during bootstrap. Use
  Alembic migrations for schema changes with upgrade/recovery evidence. For
  security findings, report reproducible impact and blocked checks; only the
  owner may explicitly accept residual risk. Do not disable checks to pass CI.
- Review the entire baseline-to-result change, run relevant focused tests plus
  established gates, then obtain independent review for security/data-contract
  changes and rendered design review for material UI changes. Update operational
  docs once the feature batch stabilizes. A task is complete only after its own
  acceptance and actual verification pass; report unavailable services honestly.

## Git, workflow and reporting

Owner-approved workflow, pending publication: **single-branch batch,
not sprint mode**. The published `origin/v1` is the starting baseline. The owner
creates `feature/impostr-v1` from the fetched, aligned `origin/v1` after the plan
and readiness markers are published, and runs the root `run-tonight.sh` from that
work branch, not from `v1`. In non-sprint mode the runner can claim up to three
currently dependency-eligible tasks per session and continue while eligible work
remains; timeouts, failed checks and dependency blocks may stop it early.

Keep implementation, migrations, tests, and backlog outcomes on **the same work
branch**. After each item passes its actual checks and independent review where
required, verified local commits may record it. `[x]` means locally verified and
committed in that branch, not PR-submitted or merged. There are no per-task PRs
or pushes. Do not start a dependent item until its prerequisite's `[x]` code is
already in the same branch. Leave failed or unverified items `[!]` with blocker,
attempt and partial-work evidence; continue only independent eligible items. Do
not skip tests or claim unavailable services passed to drain the queue. A later
run resumes the same branch and reviews earlier outcomes. Do not reset another
run's active claim or requeue a blocker without the owner's decision.

After all in-scope feature items are verified on that branch, finalization checks
the whole branch. `overnight` may push only the checked
`feature/impostr-v1` head to `origin` and open/reuse **one** review-ready GitHub
PR with explicit source `feature/impostr-v1` and destination `development`, using
existing `gh` authentication. Verify the published head and PR contents/URL. If
push or PR submission fails, preserve local commits and mark final delivery
blocked; never substitute another transport. Humans perform every merge. No
agent pushes `v1`, `development`, `master` or `main`, force-pushes, or merges;
no agent initializes Git for an Impostr-created project on export.

The tech-lead may publish this **approved planning-only transition** on the
existing aligned `v1` under the *previously selected* sprint skill before the
work branch starts. This exception does not extend to code or runner outcomes.
After publication, the explicit single-branch policy above governs delivery.

The coordinator owns delivery outcomes: `[ ]` owner-approved ready, `[~]` claimed,
`[x]` verified/committed in the work branch, `[!]` blocked with
checkpoint, and `[-]` draft/deferred. `[-]` and `[ ]` are the first-release web
editor's only writable task markers. The root helper considers dependency-
eligible only a ready item whose declared prerequisites are `[x]`; a submitted PR
is not proof of integrated code. Preserve stable task IDs, previous attempts,
branch/PR references and other checkout changes when replanning.

For runner attempts, `.opencode/progress.md` is the compact recovery record and
`DONE.md` is the existing runner's batch summary; neither is an app transcript.
Finish with one concise report of changed paths, verification and blockers. No
application URL, CI job, credential name or deployment command is implied here.
