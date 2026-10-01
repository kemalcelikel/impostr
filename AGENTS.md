# Repository agent rules: Impostr

## Current interactive chat-safety repair (2026-10-01)

The owner asked why the runner stopped, then selected **Fix chat safety first**.
Latest runner sessions delivered IMP-014 and IMP-010; at `d74ee13` the root parser
finds zero eligible items. The runner is stopped, not crashed. Interactive tech-lead
now owns the bounded IMP-002 repair; do not run a concurrent batch or automatically
restart it. Senior-developer implements; independent review covers the substantial
isolation/relay boundary. The new budget is three focused substantive attempts,
preserving earlier history; capability inspection does not consume an attempt.

Authorized scope is an operator-only, non-serving synthetic prototype of the
fail-closed bwrap worker and trusted model-only relay, using existing model access.
No product gateway/UI, host fallback, tooling installation, credential disclosure
to agents/workers, external service exposure, network provisioning, task push or PR.
Preserve existing logs/browser artifacts. Selective verified local task/bookkeeping
commits follow the existing work-branch limits. IMP-002 stays blocked until its
actual acceptance is proved; prototype success alone does not unblock chat tasks.

First inspect actual runtime identity/dependencies and available aggregate resource
controls without private host auth/config or live application access. Stop on missing
essential capability. Before live model use, independently review the implemented
boundary and pass synthetic containment/relay checks. Only the reviewed operator-run
relay may resolve existing credentials privately; agents must not inspect, copy or
receive them. Record proved commands and missing operator capabilities, not invented
provider settings. Current BACKLOG.md records the detailed checkpoint; this section
supersedes historical runner-only handoffs for this assignment only.

**Later owner decision:** For this personal, non-serving prototype, defer aggregate
memory/CPU/process/scratch quota checks. Owner accepts possible host resource
exhaustion and disruption; do not require cgroup inspection/provisioning to proceed.
This supersedes the resource-control prerequisite above, not denied-path rules or
filesystem/credential/socket/network isolation. Retain practical time/output/relay
bounds where available, without claiming aggregate containment. No broader release
or attachment safety requirement is waived. Runner remains stopped until an actual
executable handoff exists; this decision alone does not complete or requeue IMP-002.

**Verified prototype checkpoint:** The four IMP-002 operator script/test files passed
independent synthetic-only review and coordinator checks (9 unit tests and all four
launcher modes). Three substantive attempts are consumed; no further implementation
within this budget. Existing worker launch/stub relay is real, but live model transport
and full session/proposal acceptance are absent. Keep IMP-002 blocked and runner stopped;
next work requires renewed bounded authorization. Verified non-serving commands:
`/usr/bin/python3 -B -m unittest discover -s scripts -p 'test_imp002_*.py'` and
`/usr/bin/python3 -I -B scripts/imp002_prototype.py synthetic` (also `probes`,
`outage`, `timeout`). Runtime pins require UID/GID 1000:1000, bwrap 0.6.1,
OpenCode 1.18.34 and measured executable/library digests; mismatch fails closed.
No live mode or credential input exists; do not replace synthetic settings with secrets.

**Owner-requested continuation:** After that checkpoint, owner directed “get back to
me when i can run the runner.” This authorizes continued bounded repair/preparation
from `ae1fab8`/`2d31591`, not restarting the runner or claiming prototype acceptance
as chat acceptance. New budget: three focused substantive attempts, keeping the
previous 3/3 history. Delegate the smallest real transport/session continuation;
preserve non-serving scope, synthetic-data limits, resource-quota deferral and all
credential/denied-path/Git restrictions. Before any live model operation, independently
review the new credential-bearing relay and pass synthetic checks. Agents still must
not inspect private provider configuration/auth; only a reviewed operator-run resolver
may use existing credentials privately. If essential endpoint/auth facts cannot be
established safely, prepare the exact operator step and stop there. No tooling install,
network provisioning, task push/PR, unsafe fallback or automatic runner launch.

**Continuation operator checkpoint:** New transport/streaming changes passed
22 coordinator unit tests and five synthetic launcher modes, with independent
approval after an endpoint-binding repair. Continuation budget used: 2/3; previous
3/3 preserved. No resolver or live model operation has run. Essential next step
requires the human operator's plain terminal, not agent tools:
`/usr/bin/python3 -I -B scripts/imp002_prototype.py operator-inspect`.
It returns only a nonsecret fingerprint or generic failure. On success the operator
may run `operator-live --contract-sha256 <returned-fingerprint>` on the same script.
Share sanitized outcomes only; failure/drift stops. Do not directly inspect private
files or execute the operator-only resolver as coordinator/subagent. Full session
resume/questions/permissions/proposals remain absent; no runner-ready handoff yet.

## Sources and current state

**Latest template consumer repair:** Owner directed fixing consumers of the replacement
examples, authorizing existing IMP-022 integration after its prior deferral. Nested
trio discovery/build/profile validation and fixture archive compatibility now passed
focused checks, ordinary runtime/development builds, exact image mapping and independent
review; consult current BACKLOG.md for delivery. Earlier root-template/build blockers
are historical, not instructions to restore roots/use browser-harness exceptions.
IMP-014 still requires a new exact committed-base profile/preflight/rendered review.

**Latest verified recovery:** After the stopped runner, owner requested repair.
IMP-020 persistence was verified/committed in `d556043` (outcome `24fbd39`); #11
consumed. IMP-021's #12 checkbox-evidence repair passed independent combined review,
focused API/static and fresh owned PostgreSQL tests; consult its current BACKLOG.md
outcome for delivery. #13 was not needed. Older readiness/unused-budget and dirty-code
summaries below are historical; the owner committed that partial material in `e2412b1`,
which was not acceptance. Local bounded test-harness templates do not fix ordinary
worktree builds. Runner is stopped; interactive coordinator owns this repair and
must hand back coordination before any later owner-started runner.
**Continuation handoff:** Approval code `2e7a0e9` and outcome `72e37e9` are committed;
IMP-014 is now the sole eligible item. For the next owner-started root batch,
`overnight` resumes sole coordination without a concurrent interactive implementation.
Start IMP-014 with actual committed-base/profile reconciliation and fresh candidate
proof/rendered checks; previous fingerprints and API-only harnesses are not its gates.

**Current task authority and runner handoff:** Use the current `BACKLOG.md` for
scope/readiness/dependencies and the latest checkpoint; `docs/backlog-history.md`
preserves earlier specifications/attempts, not competing active task states. The
owner requested runner preparation after rejecting reviewer temporary-folder access
as a gate. Initial IMP-020 exact API-source mapping and in-repo preparation review
passed; its actual tests/acceptance remain execution work. IMP-009 is superseded,
IMP-020 ready, IMP-021 ready but waiting for committed IMP-020; consumer gates now
reference IMP-021. These latest entries supersede older draft/blocked summaries below.

For the next owner-started root batch, `overnight` takes sole coordination from
interactive tech-lead, delegates approval recovery to senior-developer and obtains
separate independent in-repo review. Preserve shared #11–13 and all partial code;
no default budget renewal. Coordinator owns actual tested-source mapping, refreshed
inputs and sanitized results. No snapshot-folder review, denied-content transport,
root-template restoration or new-template adoption. Pin missing Compose/DB inputs
as part of execution; API-only preparation is not a passing build/migration check.
Single-branch local delivery and candidate/secret/cleanup limits remain. Preparation
does not start a runner, authorize task pushes, or waive any acceptance requirement.

- `PROJECT.md` is the product, data, security and UI contract; `BACKLOG.md` holds
  future slices and readiness. `PROJECT.md` distinguishes the target first release
  from the currently implemented slice; local operation instructions are in
   `docs/local-development.md`. The owner selected the simplified
   `overnight-agent/{PROJECT,AGENTS,BACKLOG}.md.example` files as the canonical
   inputs for future projects and deleted the root examples. Application packaging,
   discovery and approval profiles still expect the legacy inputs; IMP-022 must
   integrate the new bundle. Preserve existing immutable starter provenance.
   Root `scripts/backlog.py` defines the application's compatible
  backlog parser/eligibility behavior; `.env.example` is for this checkout's local
  Compose setup.
- `overnight-agent/agents/` contains the distribution agent definitions. The
  current OpenCode CLI can list the installed `tech-lead`, `architect`,
  `ui-designer`, `developer`, `senior-developer`, `reviewer`, `docs` and `overnight`.
  `overnight` is runner-only; web planning uses `tech-lead`.
- This checkout has verified local commits through IMP-007, including private
  projects, versioned drafts, human pair approval and backlog task editing, on
  `feature/impostr-v1`. `/workspaces` is a disposable API mirror, not the
  authority or an agent workspace. IMP-009 approval/download API/migration/tests
  and IMP-014 human backlog rail/UI/tests are **uncommitted partial work** in
  this checkout; neither has final acceptance. Chat, final three-file approval,
  approved downloads, and the first release are not delivered. Consult the
  outcomes in `BACKLOG.md`; project data, candidate-review steps and local
  operating limits are in `docs/local-development.md`.
- The owner revised the first **target** to one owner on this PC, reachable from
  another LAN device only through a later verified private HTTPS route, with
  bounded PNG/JPEG, text/Markdown, selectable-text PDF and text-only DOCX chat
  attachments. This is planned behavior, **not** current implementation. No
  origin, certificate, proxy procedure, upload limits, converter or image/model
  transport has been verified. IMP-016/017/018 and later multi-user IMP-019 are
  drafts; do not claim or implement them until their prerequisites and owner
  readiness decisions exist. Existing login/project authorization remains.
- IMP-004, IMP-013 and IMP-007 were eventually verified and committed after
  bounded recoveries; their failed attempts remain historical evidence in
  `BACKLOG.md` and `.opencode/progress.md`, not current blockers. IMP-015's
  disposable authenticated browser fixture was verified locally, but its shared
  browser tool server is not OS-confined. The committed-HEAD fixture cannot review
  dirty IMP-014 UI, and earlier IMP-004/013/007 candidate fingerprints cannot be
  reused. The owner reports updating the effective installed `overnight` agent;
  its private configuration text is not independently readable in this session.
  A fresh process must use the current project contract and fail closed if its
  effective permissions prevent the approved local handoff. Preserve all dirty
  IMP-009/014 code and prior review evidence; passing intermediate tests are not
  final acceptance. Neither human-only item delivers chat or shared-server
  readiness.
- IMP-002 remains blocked: OpenCode 1.18.32 and the installed agents are present,
  with the host CLI now observed at 1.18.33, but no brokered, secret-safe isolated
  agent integration has been demonstrated. The owner chose a first personal
  release on this PC with `bwrap`-first per-project workers and a trusted host
  model relay; bounded synthetic live model/media tests are approved. Existing
  host OpenCode auth stays outside the worker/repo/browser. No relay, live
  session transport, actual worker isolation or denial proof exists yet.
  A bare `bwrap` 0.6.1 namespace smoke test exiting 0 is not proof of a usable boundary;
  live sessions, protocol events/questions, permission handling, and denial cases
  have not been verified. Do not claim an agent gateway or shared-server readiness.
- The published planning baseline is `origin/v1` at `86a97a4`; the batch began
  from that commit on `feature/impostr-v1`. Local commits through IMP-007 exist on
  that work branch; it is not itself a published release. Confirm current Git and
  runner state before further work. The owner-approved single-branch contract
  below has been published and is in use; preserve existing changes and do not
  replace this checkout with a clean checkout.

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
or reset another run's `[~]`, or requeue `[!]` without owner approval. Preserve
the uncommitted IMP-009/014 work and earlier outcome evidence. Do not requeue
IMP-002 or claim tasks dependent on IMP-002 while isolation remains blocked.
IMP-009 remains blocked after ten cumulative substantive attempts; IMP-014 is
ready but waiting on verified approval implementation as an execution-only
dependency. The owner approved IMP-020/021 and shared attempts #11–13, but their
exact-source snapshot prerequisite was denied; both remain drafts, not executable.
The template deletion now also breaks fresh API builds. Do not bypass denied
snapshot access or infer effective installed permissions from distribution files.
Do not run merely because tasks are marked ready.
After the owner's restart/requested retry, senior's exact-directory marker proof
passed, but independent reviewer Read of that same marker was denied. No snapshot
or #11 logic attempt occurred; BACKLOG.md holds the latest checkpoint. The owner
declined new IMP-022 execution in favor of existing approval work first.
The owner then rejected that access detour. Reviewer snapshot-directory access is
no longer a gate: independent review uses permitted in-repo code/test reads, while
coordinator owns actual baseline/overlay/source-byte mapping and sanitized check
results. Do not transport denied file contents or bypass the denied marker. Keep
historical templates inside the committed-baseline snapshot only; no restoration
or new-template adoption is implied. Current-worktree build/release is still broken.
For future user-created projects, exporting files does not initialize a repo or
make its runner safe to launch. Avoid two writers in the same checkout or the
same project's planning files.

## Verified commands and capability gaps

Commands below are observed on this checkout; run from repository root unless
otherwise stated. Application commands, runtime pins, and local-only operating
limits are maintained in `docs/local-development.md`.

| Purpose                                                                                     | Command                                                                      | Observed status / limitation                                                                                          |
| ------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| Toolkit and local browser fixture tests | `python3 -m unittest discover -s scripts -p 'test_*.py'` | Latest run on this dirty checkout: 128 passed, 1 gated live-Docker test skipped. This is not final IMP-009/014 acceptance; local browser evidence is in `docs/local-development.md`. |
| Backlog parser smoke | `python3 scripts/backlog.py list-all BACKLOG.md` | Live plan parses; root parser remains the app oracle, not the expanded nested toolkit parser. |
| Inspect agent availability                                                                  | `opencode agent list`                                                        | Verified CLI responds and includes relevant agents; not a live web integration test.                                  |
| Toolchain inspection                                                                        | `python3 --version`; `node --version`; `npm --version`; `opencode --version` | Host observed Python 3.10.12, Node v24.12.0, npm 11.6.2, and OpenCode 1.18.33 (latest check; earlier probe 1.18.32). App containers pin Python 3.12.11, Node 22.17.0/npm 10.9.2, PostgreSQL 17.6, and nginx 1.29.0. |
| Docker/Compose baseline | `docker info --format '{{.ServerVersion}}'`; `docker compose version` | Verified Docker server 29.8.0 and Compose v5.5.1. Docker socket access is host-root-equivalent; web planning agents must not receive it. |
| GitHub PR tooling (read-only) | `gh --version`; `gh repo view --json nameWithOwner -q .nameWithOwner`; `gh pr list --state open --json number,headRefName,baseRefName --limit 20` | An earlier read worked, but the latest `gh pr list` returned HTTP 401; recheck authorization before eventual delivery. PR creation and branch push have not been exercised. Do not log tokens. |
| IMP-001/003 local install, migrations, app gates, and recovery checks | Exact verified commands below; expanded setup in `docs/local-development.md` | API gate: 32 passed, 3 PostgreSQL-only skipped, plus Ruff/format/mypy exit 0. Separate PostgreSQL migration and 3 integration tests exited 0. Web: 6 tests plus lint/format/typecheck/build exit 0. Toolkit: 6 tests. No full project-planning end-to-end workflow exists. |
| IMP-002 agent runtime integration | No verified integration command | Blocked: no brokered, secret-safe isolation or live session/protocol/question/permission/denial evidence. Do not infer capability from `opencode agent list` or a bare namespace smoke test. |
| Candidate-app and media/private-LAN acceptance | `python3 scripts/local_browser_fixture.py candidate-preflight`, then a `launch --candidate-fingerprint <fingerprint>` only for the exact preflight snapshot | The dirty IMP-004 candidate fixture has separate opt-in preflight/launch modes; rerun preflight and rendered review whenever candidate inputs change. This is local synthetic review, not product-agent isolation. No brokered image/DOCX/PDF handoff or private HTTPS phone-access procedure has been established. Do not invent a URL, certificate, provider config or media limits. |
| Dependency/security checks | From `web/`: `npm audit --audit-level=moderate` | An earlier check found 0 moderate-or-higher npm findings; the latest attempt was blocked by `EAI_AGAIN` resolving the npm registry. Host `pip-audit` is not installed; no final independent Python dependency audit was run. No release security gate/policy is configured. |

### Historical IMP-001/003 verified local commands

These commands/results record the verified baseline, not fresh evidence for this
dirty checkout. Expanded setup is in `docs/local-development.md`. Root-template
deletion currently prevents fresh API image builds; do not report historical
checks as a passing check of the selected new bundle.

Run from the repository root with a local `.env` created from `.env.example`;
never copy its generated secrets elsewhere. Compose reads `POSTGRES_DB`,
`POSTGRES_USER`, `POSTGRES_PASSWORD`, `DB_USER`, `DB_PASSWORD`,
`IMPOSTR_RATE_LIMIT_KEY`, `IMPOSTR_PUBLIC_ORIGIN`, and `APP_PORT`. The database
password values are required; the example defaults to database `impostr`, owner
`impostr_owner`, app role `impostr_app`, and loopback `127.0.0.1:8080`.
`IMPOSTR_PUBLIC_ORIGIN` defaults to the loopback HTTP origin derived from
`APP_PORT`; leave it unset for this local setup. A blank
`IMPOSTR_RATE_LIMIT_KEY` falls back to `DB_PASSWORD`; a separately configured key
must contain at least 32 bytes. `APP_BIND_ADDRESS` is not a current setting. The
app dependency/runtime locks are
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
docker compose -p impostr-verify1 run --rm -it api \
  python -m app.bootstrap_admin bootstrap --username adminname
docker compose -p impostr-verify1 restart
docker compose -p impostr-verify1 run --rm api alembic current
```

The bootstrap command prompts twice for the new administrator password without
putting it in command arguments. Use a real, chosen username in place of
`adminname`; it must satisfy the account username rules. Bootstrap succeeds only
once on an empty users table after migrations. For an existing administrator,
offline recovery uses:

```sh
docker compose -p impostr-verify1 run --rm -it api \
  python -m app.bootstrap_admin recover --username adminname
```

It re-enables that admin, changes its password, and revokes its active sessions.
Neither operation has a public or network recovery endpoint. That baseline's migration
revision was `20260925_0002`; committed application head is now `20260929_0005`,
with uncommitted `20260930_0006` pending acceptance. These historical checks exited 0.
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

That baseline API check passed 32 tests, skipped 3 PostgreSQL-only integration tests,
and passed Ruff, format, and mypy checks. The separate PostgreSQL migration and
integration gate passed 3 tests; the web gate passed 6 tests plus lint, format,
typecheck, and build; the toolkit suite passed 6 tests. Browser checks at 1440,
1024, 768, and 375 px found no horizontal overflow and confirmed keyboard focus.
See `docs/local-development.md` for local secret setup, account bootstrap/recovery,
health and database recovery, and operating limits.

Do not commit `.env`, database dumps, private transcripts, provider config or
`.opencode/progress.md`/runner logs. The checked-in `.env.example` contains empty
local-development secret fields, not usable credentials. Current Compose publishes
only the front door on loopback. The application now has cookie-backed sign-in and
offline account bootstrap/recovery, but has no TLS or domain setup, trusted external
proxy contract, backup/restore runbook, agent broker/isolation, or shared-server
deployment. Use the local-only setup instructions and do not infer production or
release readiness from passing container checks. The installed
`ui-ux-pro-max` and `ui-styling` skills are optional design aids; the `ui-designer`
may use them without reinstalling them. Browser tools are available, but no
generally available product/CI browser-test command or checked-in/reusable test
credentials have been established.
The owner has created disposable local application accounts for interactive
testing, but their passwords are not an unattended reviewer credential channel.
The IMP-015 operator fixture and authenticated context handoff to `ui-designer`
are now verified for this owner's local synthetic review only. Two fresh runs
completed normal sign-in and rendered review; `ui-designer` returned PASS. The
fixture verified Member denial of an admin-only request (403), expired/revoked
session denial (401), and post-handoff account/session and owned-resource cleanup.
The live SIGKILL recovery-test command and prerequisites are in
`docs/local-development.md`. These results alone did not verify IMP-004; its later
verified delivery is recorded in BACKLOG.md.

The scripts `scripts/local_browser_fixture.py` and
`scripts/test_local_browser_fixture.py` are present in this working tree. Their
operator-only commands are documented in `docs/local-development.md`; this is
not a generally available product setup or unattended global service. Launch
archives committed `HEAD` for the application, not dirty worktree changes; the
separate opt-in candidate mode requires a pinned fingerprint. An earlier toolkit
run passed 98 tests with one gated live-Docker test skipped. Preserve unrelated
planning edits and do not mix them into an isolated IMP-015 delivery.

The older failed IMP-015 attempts remain history: an earlier migration archive
was unreadable under its umask, one private log read and a later marker write
were denied, and browser/review/cleanup gates had not yet been completed then.
The fixture-only migration permission repair passed a fresh probe at
`20260925_0002` with `users` present. The committed and working-tree username
patterns accept `_`; the previous statement that `_` was rejected was incorrect.
Never use the owner's test accounts, reusable logins, production data, or
admin/DB/provider/host credentials or sessions. Do not commit member logins,
cookies, screenshots containing login material, or logs. Under the owner's
approved local-only handoff, only a generated short-lived Member login and
sanitized cleanup status may be shared; never include privileged credentials,
raw Compose settings, database URLs, private host data, or unredacted logs.

The approved handoff directory is local to this checkout's operator setup. If
its tool permissions change, first prove a harmless marker can be written and
read through the permitted tools before any credential setup. If that proof is
denied, stop; do not move the file or use another tool to bypass the denial.
The existing shared Playwright tool server is **not OS-confined** and may access
Docker, host secrets, or another stack. Do not intentionally use those
capabilities or claim a proven denial. This residual host risk is not a security
control and does not extend to product-agent isolation or shared-server release.
Use only generated synthetic Member logins in the disposable browser, through
normal sign-in; do not use a test-only auth bypass or expose the app externally.
The earlier temporary broad `overnight` edit permission was a one-attempt
IMP-015 exception, not isolation. For the current **one local root-runner batch**,
the owner again selected installed `overnight` `edit: allow` and explicitly
accepts that the root helper may continue to dependency-eligible IMP-013 and
other human-only slices after IMP-004 passes. This does not relax code review,
tests, project authorization, secrets or task-specific `[x]` gates. Do not give
the developer subagent privileged handoff access, widen the existing private
external-directory allowance or stage unrelated dirty work. The coordinator
must own synthetic candidate sign-in and rendered design review. Broad edit is
not product-agent isolation. The owner should restore restrictive coordinator
edit rules **after the whole batch ends and before a separate later run**;
do not claim that restoration has already occurred or block an otherwise
fully verified code task solely to manufacture another verification-only run.

## Implementation and review boundaries

- Follow `PROJECT.md` for ownership, revision/approval invariants, agent runtime
  isolation and export behavior. A browser check or client-side state restriction
  never replaces server authorization; test cross-user/project/session access and
  stale-version behavior. Keep privileged model/DB/network configuration outside
  agent workspaces and Git.
- Protect immutable template provenance and root runner/parser compatibility; if changing their
  semantics, separately scope regression tests and migration/compatibility work.
  Keep user-created project workspaces away from other projects and this repo's
  live planning files. Do not hand-edit generated lockfiles or compiled assets.
- For IMP-004, the IMP-015 fixture normally archives **committed HEAD**. Its
  separate candidate mode is opt-in and fingerprint-pinned to a reviewed runtime
  allowlist over the fixture's pinned base; the candidate preflight is
  infrastructure evidence only. Recompute the fingerprint for the exact current
  inputs, require normal synthetic Member login in the coordinator's browser and
  owned cleanup, and repeat preflight/rendered review if any candidate input
  changes. Do not reuse an earlier fingerprint as current evidence. The developer
  subagent's private-login read was denied during the prior attempt; do not grant
  it privileged channel access or use another transport to bypass that denial.
  The coordinator must own the approved private handoff and design-review flow.
  For later media work, never treat an uploaded file or filename as evidence that
  the model saw pixels or extracted text; project/session authorization and
  bounded, private processing are required before model handoff.
- Pin actual dependencies and commit manifests/lockfiles during bootstrap. Use
  Alembic migrations for schema changes with upgrade/recovery evidence. For
  security findings, report reproducible impact and blocked checks; only the
  owner may explicitly accept residual risk. Do not disable checks to pass CI.
- Inspect the assigned baseline-to-result diff. Start with focused checks for
  changed behavior and realistic regressions. Listed command bundles are tools,
  not gates for every task. Broaden for concrete integration risk, release
  acceptance, or essential task checks below. Update existing docs when useful
  instructions/contracts change, not as a mandatory pass on every task.

### Simplified testing and review policy (owner requested 2026-09-30)

This replaces generic full-suite, repeated full-review, documentation-pass and
exhaustive-matrix demands in older process/task text. Historical outcomes, failed
attempts and actual acceptance remain intact; no task is requeued here.

- Verify main changed behavior and meaningful failure paths. Reuse unchanged valid
  evidence and existing fixtures; no coverage target or exhaustive matrix. Prose
  and formatting corrections do not require app suites or another code review.
- Review selectively: substantial changes, approval interpretation, identity/project
  authorization, isolation, migrations/data integrity and export need independent
  review. Small routine changes do not. Inspect the full assigned change once;
  re-review affected repairs, not a restarted audit after each mechanical edit.
  Concrete important acceptance failures, regressions or serious security/data
  defects block; optional coverage, speculative semantics and polish are notes.
- IMP-020 needs exact standalone-source proof, migration/preservation/constraint
  checks on fresh owned PostgreSQL, relevant existing API behavior and static
  checks for changed Python. IMP-021 needs actual invalid/valid approval HTTP
  regressions, status/audit/download invariants, authorization/stale revisions
  and PostgreSQL approval/save concurrency. Toolkit suites apply when helper or
  fixture behavior changes, not automatically to a schema/API-only slice. Broaden
  for shared-code risk or actual failures; never waive a reproduced approval bypass.
- IMP-014 still needs a reviewed exact-input candidate profile, pinned preflight,
  normal generated Member sign-in, authenticated rendered interaction/design
  spot-checks, authorization denials and owned cleanup. Focus web checks on editing,
  readiness, conflicts and navigation. Changed preview inputs invalidate snapshot
  evidence; no generic full API rerun for UI-only changes.
- Product release checks in PROJECT.md and IMP-011/012, synthetic-data limits,
  credential handling, denied-path rules and explicit recovery budgets remain.
  Missing essential capability blocks affected work; unavailable optional checks
  or unrelated findings are reported, not silently passed or added to scope.

## Git, workflow and reporting

### Toolkit compatibility notes (2026-09-30 inspection)

- This project's single-branch rules override distribution sprint defaults. Root
  and nested runner/parser files are deliberately not synchronized wholesale.
  Run the root helper from this repository root: its direct invocation currently
  does not pass the project directory to OpenCode. It also logs exit-124 timeouts
  without counting them as session failures; do not treat its exit 0 alone as
  proof of task acceptance. These code fixes are not implemented by this planning update.
- Distribution tech-lead Git wording assumes a declared sprint even though the
  skill is optional. Its recovery-budget default must not replenish this project's
  explicit cumulative limits. Distribution review wording should mean focused
  re-review of distinct in-budget repairs, not one hard pass that waives defects
  or prevents valid remaining attempts. Project rules above resolve these conflicts
  here; the attempted toolkit prose edit was tool-denied and left unapplied.
- Distribution README names `gpt-6-sol` whereas agent/config routing uses
  `gpt-6.1-sol`; its claim that the runner does not fetch describes initial
  preflight only, not post-session sprint return. Nested sprint reconciliation
  carries terminal outcomes by ID even when task scope changed: do not certify a
  revised/reopened task from an old completion; reconcile before a sprint launch.
- Distribution MCP uses enabled `npx -y @playwright/mcp@latest`, which may fetch/
  install a changing package at startup. No pinned provisioned version was proved
  here. Tool availability, broad edit and temporary-directory allowances are not
  authorization or OS isolation. No installed private config was inspected or
  changed. Restart OpenCode after owner-applied agent/config updates; current
  processes keep their already-loaded configuration.

Owner-approved workflow: **single-branch batch,
not sprint mode**. The published `origin/v1` is the starting baseline. The owner
creates `feature/impostr-v1` from the fetched, aligned `origin/v1` after the plan
and readiness markers are published, and runs the root `run-tonight.sh` from that
work branch, not from `v1`. The local `run-tonight.sh` now claims one
dependency-eligible task per session and continues while eligible work
remains; timeouts, failed checks and dependency blocks may stop it early.

Keep implementation, migrations, tests, and backlog outcomes on **the same work
branch**. After each item passes its actual checks and independent review where
required, verified local commits may record it. `[x]` means locally verified and
committed in that branch, not PR-submitted or merged. There are no per-task PRs
or pushes. Do not start a dependent item until its prerequisite's `[x]` code is
already in the same branch. Leave genuinely blocked or budget-exhausted items
`[!]` with blocker, attempt and partial-work evidence; use the owner-approved
continuation policy below only when its conditions hold. Do not skip tests or
claim unavailable services passed to drain the queue. A later run resumes the
same branch and reviews earlier outcomes. Do not reset another run's active
claim or requeue a blocker without the owner's decision.

### Owner-approved bounded unattended recovery contract (2026-09-30)

For an owner-approved same-ID recovery with a stated finite additional attempt
budget, a reviewer finding with a concrete, in-scope fix is not itself an owner
decision. The coordinator should preserve the dirty work and cumulative attempt
count, try a distinct fix with negative regression tests, and obtain independent
re-review. If work remains incomplete but a specific next action, available
capabilities and budget remain, the coordinator may leave its assigned item
`[~]` with a concise `.opencode/progress.md` checkpoint; the root runner resets
it to `[ ]` for a bounded next session. This is not permission to reopen a
pre-existing `[!]`, extend the budget, relax a failed check or skip a required
rendered review. A repeated finding without a new hypothesis, exhausted budget,
missing capability, changed scope or security exception remains `[!]`. The root
runner's three-no-outcome-session stop still applies.

The local synthetic UI-review path for IMP-014 requires a separately reviewed,
exact-input and fingerprint-pinned candidate profile over the actual committed
base after IMP-009. The owner approved the inventory in BACKLOG.md; building and
proving the new profile is IMP-014's first implementation/acceptance gate, not
evidence already obtained. Reconcile the full dirty diff before preview and keep
existing size/path/secret limits, normal generated Member login, authorization
denials and owned cleanup. This does not confer general permission to preview
arbitrary dirty code, reuse older fingerprints, widen the private handoff, or
expose services outside loopback. An absent/rejected profile is a capability
blocker, not a waiver; never mark `[x]` without actual authenticated rendering.
This contract does not authorize requeueing IMP-002 or any chat-dependent item.

### Owner-approved interactive IMP-009 recovery (2026-09-30)

The owner selected direct **Repair here** after the latest runner stop. For this
bounded assignment, tech-lead is the sole interactive execution coordinator:
delegate repair to senior-developer, obtain separate independent reviewer
approval, coordinate final gates and affected docs, and deliver verified local
task and bookkeeping commits on existing `feature/impostr-v1`. Do not require
overnight as an intermediary or run it concurrently. BACKLOG.md records acceptance,
file boundaries and at most two additional substantive attempts (#9–10 cumulative);
retain IMP-009 `[!]` until verified delivery. Preserve all existing unrelated dirty
planning, IMP-014 UI, runner changes and private logs; stage only reviewed task
material and approved recovery planning/outcome hunks. No push, PR, merge,
deployment, real-data access, tooling installation or automatic runner restart.
This narrow handover leaves ordinary dependency, candidate-review, database,
permission and batch preflight gates unchanged. Unfinished IMP-002 is not requeued.

**Current checkpoint:** That #9–10 budget is exhausted. Independent review and
actual synthetic HTTP evidence still show checkbox metadata supplying absent
required task evidence. The original remains `[!]`; preserve the repair and
historical authorization above, but do not treat it as permission for #11.
BACKLOG.md now proposes IMP-020 inert persistence followed by IMP-021 integrated
enforcement. Both remain `[-]` until the owner approves scope/budget and execution
prerequisites are established. The proposed split does not reset attempts, remove
approval checks, activate incomplete routes or relax IMP-014 candidate safety.
No application edits, snapshot setup or new local delivery are authorized by the
draft split alone.

**Subsequent owner authorization (2026-09-30):** Owner approved **Yes, finish it**
for IMP-020 then IMP-021 with up to three additional substantive attempts total
(#11–13 cumulative), at most one persistence/test-hardening attempt and two
enforcement attempts. Tech-lead remains the sole interactive recovery coordinator;
senior-developer implements, separate reviewer inspects actual full assigned
material and regression evidence. Review targets demonstrable agreed-contract
defects, not speculative semantics, additional polish or redesign; no reproduced
approval bypass or failed gate is waived. Bounded non-serving source-snapshot
setup under `/tmp/opencode/`, disposable local database checks and selective local
task/bookkeeping commits are authorized. Establish exact-source prerequisites
before queue promotion/supersession; IMP-021 implementation waits for committed
IMP-020. Preserve the existing checkout/pending code and all attempt evidence.
No unrelated implementation, push, PR, merge, deployment, real-data access, tooling
installation, new browser profile, weakened preflight or automatic runner restart.

After all in-scope feature items are verified on that branch, finalization checks
the whole branch. `overnight` may push only the checked
`feature/impostr-v1` head to `origin` and open/reuse **one** review-ready GitHub
PR with explicit source `feature/impostr-v1` and destination `development`, using
existing `gh` authentication. Verify the published head and PR contents/URL. If
push or PR submission fails, preserve local commits and mark final delivery
blocked; never substitute another transport. Humans perform every merge. No
agent pushes `v1`, `development`, `master` or `main`, force-pushes, or merges;
no agent initializes Git for an Impostr-created project on export.

The original planning-only transition was published on `v1`; no further direct
planning or code pushes to `v1` are authorized by this batch policy. Future
recovery decisions remain on the existing work branch until final delivery.

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
