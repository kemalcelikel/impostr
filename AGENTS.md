# Repository agent guide: Impostr

## Read first

- Product/domain rules: PROJECT.md. Scope, dependencies, budgets and outcomes: BACKLOG.md.
- Setup and operator instructions: docs/local-development.md. Old decisions/checkpoints:
  docs/agent-history.md and existing history documents; these are not active assignments.
- Keep this guide short. Product behavior belongs in PROJECT.md; task evidence belongs
  in BACKLOG.md, not another repeated handoff or mandatory verification checklist.

## Current work

Native backend is delivered in `a966d77`, composer/fixture cleanup in `34dbcb0`,
extractor retirement in `d05233f`, and private backup/fresh-target restore in `756a3c8`.
Owner explicitly stopped tests, verification and comparator refinements and will
manually accept the application. Preserve residual work/history; do not restart the runner.

The implementation queue through IMP-011 is complete under owner-deferred acceptance.
Automated full restore-constraint comparison remains unresolved—not passed. Do not
start another check/review loop, activate deferred/live scope or discard attempt history.
Setup/backup/restore: docs/local-development.md; BACKLOG.md owns caveats and outcomes.
Keep Bubblewrap; no Podman/sbx migration.
OpenCode has no exact version or executable-hash admission lock; retain fixed-path safe
availability, observational digest, other runtime pins and actual compatibility checks.
Original PDFs use native OpenCode/Azure input, not local parsing/OCR/text preview.
Real-provider acceptance is owner-deferred, not passed or an immediate execution gate.

## Keep execution simple

- Reuse existing code, upstream SDK behavior and fixtures. Choose the smallest adequate
  change; no new parser, diagnostic framework, service or compatibility layer for a small bug.
- Check the changed behavior and realistic failures. Reuse unchanged valid evidence;
  no coverage targets, exhaustive matrices or mandatory whole-suite runs per edit.
- Owner defers remaining browser/full-app walkthroughs to manual testing after
  implementation. Do not launch more browser suites, create test-placement/permission
  work, or block delivery solely on that deferred evidence. Never label it passed.
- Final owner instruction also stops additional restore verification/comparator work.
  Package the existing implementation; report its unresolved comparison honestly.
- Review substantial/security/data-sensitive changes independently; re-review only the
  affected repair. Concrete important defects block, optional polish/coverage does not.
- Ordinary formatting, focused tests and a distinct in-scope repair need no extra owner
  approval. A fix request authorizes local recovery commits with a finite new allocation;
  preserve used attempts. Stop for exhausted scope, missing essential capability or an
  action outside these limits—not for another paperwork or review-only pass.
- Use one coordinator per checkout. On owner runner launch, `overnight` takes coordination
  and delegates implementation; interactive execution ends. Continue dependency-eligible
  approved work after verified local commits, through IMP-011, unless an actual blocker
  stops it. Do not reopen deferred items or run the later live test to drain the queue.

## Verified commands

Run from the repository root. These are tools, not mandatory gates for every task.
Application setup, Compose/check commands and the human-only connection are documented
in docs/local-development.md; agents must not use its real-credential/operator modes.

| Purpose | Command | Scope |
|---|---|---|
| Backlog syntax/status | `python3 -B scripts/backlog.py list-all BACKLOG.md` | Root parser is the app compatibility oracle. |
| Queue eligibility | `python3 -B scripts/backlog.py count-eligible BACKLOG.md` | Dependencies must be locally committed `[x]`. |
| Focused native helper tests | `/usr/bin/python3 -B -m unittest discover -s scripts -p 'test_imp025_*.py'` | Changed PDF helper behavior; not a real-provider test. |
| Native candidate preflight | `/usr/bin/python3 -I -B scripts/imp025_verify.py --preflight` | Coordinator; anchored to verified native delivery. New task profiles follow actual committed inputs; full modes need fresh fingerprint/review. |
| Whitespace | `git diff --check` | Use focused paths if unrelated work is dirty. |
| Owner runner launch | `RUNNER_USE_SBX=0 ./run-tonight.sh` | Owner only, from this checkout on feature/impostr-v1. |

The root helper takes one dependency-eligible item per session and rechecks after it.
Its timeout/exit0 alone does not prove delivery. Use the root helper/parser, not the
nested toolkit's sprint defaults. No generally available automatic browser test login.

## Code and environment conventions

- API: api/ (Python/FastAPI/SQLAlchemy/Alembic); UI: web/ (Vite/React/TypeScript/Tailwind).
  Pin dependencies in existing manifests/locks; do not hand-edit generated lockfiles.
  Use forward migrations; preserve originals, approvals, revisions and template provenance.
- Starter inputs are overnight-agent/{PROJECT,AGENTS,BACKLOG}.md.example. Never restore
  deleted root examples or rewrite immutable starters to repair current behavior.
  /workspaces is a disposable API mirror, not an agent workspace or authority.
- Same-PC loopback only. Use owned synthetic DB/accounts/files for verification, never
  owner's files, reusable logins, private live data, provider auth/config or host env values.
  Only reviewed human-run connection code may obtain real credentials. No installs,
  network provisioning, deployment, host auth copies or unsafe host execution fallback.
- Preserve UID/GID, namespaces, read-only runtime/discovery masks, bounded files/transport,
  project/session authorization, credential separation and deletion fencing. Personal
  text-chat aggregate quota work stays cancelled; do not revive it as a prerequisite.
- Docker is coordinator-only, never exposed to product workers or implementation agents.
  Stop on an essential tool denial; no alternate path/transport/tool to bypass it.
- Candidate execution uses reviewed exact input bytes, fresh fingerprint and owned cleanup.
  UI review uses normal generated Member sign-in; keep the exact approved synthetic
  /tmp/opencode/impostr-review-handoff UID/GID1000 mode0775 exception, accepting group
  observation/tampering only there. Other path/owner/no-symlink/credential checks remain.
  Shared Playwright is not OS-confined; never use its incidental host/Docker access.
  Do not grant developer access to privileged handoff data or transmit denied contents.

## Git and task state

Use the existing **single-branch batch**, not sprint mode: feature/impostr-v1 based on
published origin/v1. Inspect status, assigned diff and recent history; preserve dirty
work. Flags follow Git subcommands, e.g. `git diff --no-ext-diff --no-textconv` and
`git log --no-ext-diff --no-textconv --oneline -10`. No developer Git writes/branch commands.

Coordinator may make verified local task/recovery commits, staging only intended files
or hunks. `[x]` means verified and committed here, not merged. Subagents do not commit or
change task state. `[ ]` approved ready; `[~]` claimed; `[!]` blocked; `[-]` draft/deferred.
Do not reset another run's claim or requeue an unrelated blocker. Approved bounded
unfinished work may checkpoint `[~]` for the root helper to resume within remaining limits;
repeated failure without a new hypothesis, missing capability or exhaustion stays `[!]`.

No current push/PR permission. No merge, force push, history rewrite, skipped hooks,
discarding user work or Git initialization for exported projects. Do not commit .env,
dumps, provider settings, logins/cookies, private artifacts, runner logs or progress.md.
Keep progress.md as a compact checkpoint and DONE.md as the existing brief batch summary.
Finish with what changed, what was checked and what remains—usually five bullets or fewer.
