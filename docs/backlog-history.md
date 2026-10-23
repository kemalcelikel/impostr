# Backlog history — preserved 2026-09-30

This is the full backlog as it stood before simplification, including uncommitted
owner decisions, failed attempts, approvals, fingerprints and delivery evidence.
It is a historical reference, **not an executable queue**. Current task states,
acceptance and next steps are in [BACKLOG.md](../BACKLOG.md); current operating
limits are in [AGENTS.md](../AGENTS.md). Superseded instructions below do not
override those files. Preserve this record rather than updating its old statuses.

Original BACKLOG.md SHA-256:
`af5c3563daafcabe14565bc9a1512243755a69be942e40343888e60cb891993a`.

# Impostr v1 — owner-approved single-branch batch

- Base branch: origin/v1
- Sprint branch: v1
- Work branch: feature/impostr-v1 (existing; preserve uncommitted IMP-009/014 work)
- Final PR: feature/impostr-v1 → development (human merge)
- Version control: GitHub

Canonical scope/contracts: `PROJECT.md`; execution/check policy: `AGENTS.md`.
The owner approved the original 12 slices, the IMP-013/014 human-only extractions,
IMP-015's local review prerequisite, and one final human merge. The new
personal-release media/LAN/hardening slices below remain `[-]` drafts until
their prerequisites and operator inputs are reviewed and approved. The
single-branch workflow and its original `[ ]` markers were published;
dependency eligibility and real checks still gate work. The `Sprint branch`
field retains the declared planning-publication target from the previous
workflow; the new runner uses the work branch and does not select sprint mode.
Permanent IDs and `## [state] ID — Title` headings follow the root helper's format.
`[-]` draft/deferred; `[ ]` owner-approved ready;
`[~]` runner claimed; `[x]` verified delivered under project policy; `[!]`
blocked/incomplete with recovery decision. A first-release Impostr user can only
toggle a project task between draft and ready, not invent runner outcomes.

Dependency lines are comma-separated IDs; the helper selects dependency-eligible
`[ ]` tasks in file order only when prerequisites are `[x]` on the same work
branch. The non-sprint runner can continue independently eligible tasks after a
blocker; it stops when nothing eligible remains and never skips a prerequisite.
These IDs are for building **Impostr**, not pre-filled tasks for the projects it
will create.
App commands below are not invented: where no command exists, verification names
the evidence to establish during implementation. Prior runner assignments and outcomes
are retained below; this workflow adoption starts no runner or new assignment.
Queueing every item does not guarantee overnight completion: actual checks,
isolation and operator inputs remain gates at the relevant item.

## Current testing/review policy

The simplified policy in AGENTS.md replaces generic full-suite, repeated whole-diff
review, mandatory documentation-pass and exhaustive-matrix process demands below.
Historical attempt text/results are preserved, not current instructions to rerun
every suite. Start with changed behavior and realistic risks, broaden for concrete
integration risk, and independently review substantial/higher-risk changes only.
Product/data/security acceptance, exact-source and candidate proof, authorized
synthetic data, cleanup, explicit attempt budgets and release gates remain required.
IMP-020/021 and IMP-014 have focused current check guidance in AGENTS.md; no status,
attempt count, dependency or readiness is changed by adoption. Dependencies still
resolve under the root parser, not the expanded distribution parser.

---

## [x] IMP-001 — Bootstrap app and database baseline

Type: feature
**Depends on:** None
**Scope:** Impostr frontend/API skeleton, PostgreSQL Docker service, Nginx routing,
Alembic migration baseline and reproducible development checks; do not add project
or OpenCode behavior yet.
**Required capabilities:** Operator-provisioned Docker/Compose on a development
host (verified in this checkout); pinned Python/Node dependencies.

### Done looks like
- A Vite/React/Tailwind client reaches a Python/FastAPI health endpoint through
  the planned origin; PostgreSQL starts with a migration baseline and no database
  port or privileged agent endpoint exposed to the browser.
- Exact install, start, migration, test, lint, format, typecheck, build and container
  commands, runtime versions and configuration-example names are verified and
  recorded in AGENTS.md; secrets are not committed.

### Verification
- On the provisioned host, exercise service start, migration on an empty database,
  API/client smoke, restart and the recorded checks; record failures honestly.

**Documentation impact:** AGENTS.md environment/command table and operator setup.
**Open decisions:** Actual host paths, TLS/domain and secret provisioning belong to
the operator; no deployment address or credentials may be guessed.
**Verified commit:** `af0c9e7` on `feature/impostr-v1` (local only); bootstrap and
recovery checks passed. No shared-server release or Python dependency audit claimed.

---

## [!] IMP-002 — Prove safe OpenCode web-session integration

Type: feature
**Depends on:** IMP-001
**Scope:** Bounded integration experiment/contract for project-scoped `tech-lead`
sessions and isolation; do not expose a shared-host agent endpoint yet.
**Required capabilities:** Working host-configured OpenCode model/auth, installed
`tech-lead` definition, isolated runtime facility and test projects.

### Done looks like
- Demonstrate a pinned, documented integration that starts/resumes a session,
  streams answers, handles a question/permission request and reads the agent's
  proposed file changes. Record actual protocol and failure/reconnect behavior.
- Demonstrate that a session cannot read a sibling workspace, host home/secrets,
  database socket or Docker socket; if this is not achievable, record blocker and
  do not claim shared-server readiness or implement an unsafe fallback.

### Verification
- Automated adapter contract tests plus a manual live `tech-lead` transcript and
  denial tests on the intended host; identify version and tested config without
  logging credentials.

**Documentation impact:** AGENTS.md verified integration setup, PROJECT.md
boundary changes only if the proven contract differs.
**Open decisions:** Runtime/API mechanism depends on measured OpenCode behavior;
do not assume `opencode run` or a JS SDK is a resumable Python web adapter.
**Blocker:** No approved secret-safe model access or proven isolated agent runtime;
live session protocol and containment tests remain unverified. No shared-host endpoint.
**Checkpoint:** One bounded probe: OpenCode 1.18.32/`tech-lead` available;
`bwrap` 0.6.1 empty namespace smoke passed, but no live model session or agent
denial tests ran. Resume only with an approved broker and fail-closed runtime.
**Personal-release recovery proposal (2026-09-29, not requeued):** Owner chose
the current PC for a one-owner first release, but **did not accept** unconfined
product-agent access to its home files, other projects or Docker. Try the
installed `bwrap` first as a fail-closed per-project worker under the actual
launcher identity, paired with a trusted host-side, model-only relay using the
owner's already configured OpenCode model access **outside** the worker. The
owner approves bounded synthetic live model and image-input tests; do not ask
for credentials in chat or copy host auth/config into worker, repo, DB, browser
or logs. First verify the operator-managed secret channel and worker launch/
resource/network controls on this PC; neither the bare namespace smoke nor
`run-tonight.sh` establishes this. Then measure a pinned OpenCode start/resume,
stream, question, denied permission, proposal, reconnect/failure contract;
prove child-tool denial of sibling project, home/canaries, Docker/DB sockets
and unintended network destinations. Relay outage or isolation failure denies
chat rather than falling back to host execution. Record real synthetic image
support/limits for later media planning without claiming it from a model name.
No broker, service-identity isolation or live protocol is verified yet. Keep
`[!]` until an operator-safe credential channel and runnable isolation proof
are actually available and the owner approves the revised readiness; this is
not a way to defer security for a LAN-accessible tool-using agent.
**Owner priority update (2026-09-29; future work, not a requeue):** Continue
development on this PC with the existing host runner and independently eligible
human-only application slices; do not ask the owner to create service accounts,
enter credentials or configure an unimplemented relay now. Investigate reuse of
the runner's optional `sbx` approach later, but do not treat it as a proven
product-agent boundary: `run-tonight.sh` copies host OpenCode auth/config into
the sandbox when available and falls back to direct host execution if sandbox
creation fails. The most recent batch used direct host OpenCode. This priority
decision neither accepts unconfined product-agent access nor changes the
first-release chat/security acceptance above. Keep IMP-002 `[!]` and its chat
dependents ineligible; any changed release or security contract needs a separate
explicit owner decision. The technical work must establish and verify actual
operator setup commands before asking the owner to run them.

---

## [x] IMP-003 — Admin-provisioned login and private project access

Type: feature
**Depends on:** IMP-001
**Scope:** Users/admin bootstrap, no-signup login/logout, admin user management,
server sessions, project creator/administrator policy and minimal accessible UI.
**Required capabilities:** Migrated PostgreSQL, operator-controlled initial admin.

### Done looks like
- Operator can bootstrap an admin offline; signed-in admin can add, deactivate and
  reset user credentials; there is no public user-creation route. Passwords are
  hashed, sessions expire/revoke, and auth mutations enforce CSRF/rate controls.
- Two distinct users cannot enumerate or access each other's private projects,
  including guessed IDs; administrator access is explicit and auditable.

### Verification
- Automated login failure/session-expiry, CSRF, unauthorized user-management,
  cross-project access and deactivation tests; browser check for login/admin flow.

**Documentation impact:** Operator bootstrap/recovery instructions (without
passwords or test credentials in Git).
**Open decisions:** None for first-release behavior; establish real bootstrap/check
commands under IMP-001 before promoting implementation.
**Verified commit:** `e4558ae` on `feature/impostr-v1` (local only); API,
PostgreSQL migration/integration, web, toolkit, and local browser checks passed.
External proxy/TLS, agent isolation, backup/restore, and dependency audit remain
release gates, not shared-server readiness.

---

## [x] IMP-004 — Seed projects and versioned Markdown drafts

Type: feature
**Depends on:** IMP-001, IMP-003, IMP-015
**Scope:** Authenticated project creation and DB document history for the three
root starter examples; no Git/repo initialization or runner launch.
**Required capabilities:** Root `.example` files accessible to server; DB and
private project workspace storage.

### Done looks like
- Creating a named project records opaque ID, name, UTC creation time, creator and
  template provenance; three draft documents are available. Duplicate/invalid
  names fail visibly; names cannot select paths or overwrite another project.
- Human or agent draft edits create immutable versions with expected-revision
  checks; simultaneous stale edits are rejected with both versions recoverable.
  Workspace changes are proposals, never automatic DB approval.

### Verification
- DB migration and create/reload/restart tests, template provenance and
  traversal/symlink denial tests, two-tab revision race and cross-user checks.

**Documentation impact:** Data model and backup/restore notes at stable batch end.
**Open decisions:** None; use PROJECT.md as the canonical draft/workspace contract.
**Blocker:** Independent review still finds draft-navigation/history races after three implementation attempts; rendered review and documentation remain pending. Uncommitted partial work is preserved on `feature/impostr-v1`.
**Recovery authorization (2026-09-25):** Owner approved one additional focused
substantive repair attempt on this same item and its existing uncommitted branch
work. Preserve the three prior attempts and the blocker above; do not restart
implementation, commit unfinished work, or treat the earlier passing checks as
final acceptance. Resolve dirty/conflicted edit navigation, save-in-flight history,
conflict history versus displayed head, and stale selection after pagination.
Obtain independent re-review and rendered browser review, complete affected docs,
run final API/PostgreSQL/web gates, and only then commit and mark `[x]`. If this
attempt fails, record `[!]` with new evidence and stop dependent work.
**Fourth-attempt blocker:** Independent re-review NEEDS WORK: delayed creation and
project-list refresh can strand or discard edits; concurrent history reads can show
a head behind listed revisions; normalized long names can exceed the DB key column.
Mock-browser review could not verify the authenticated app; docs and final gates
remain pending. Uncommitted work preserved; no dependent work or delivery commit.
**Fifth-attempt recovery authorization (2026-09-25):** Owner approved one more
focused repair of this same item, reusing its uncommitted work on
`feature/impostr-v1`; the original blocker, four attempts and partial work above
remain the recovery record, not completed delivery. First inspect the current
diff and prior review evidence. Repair and regression-test delayed creation and
project-list refresh against dirty or in-flight edits, concurrent history head/
revision consistency on PostgreSQL, and the Unicode-normalized name-key length
boundary (including migrated data). Do not weaken cross-project authorization,
revision checks or workspace isolation to make tests pass. Obtain independent
re-review of the full IMP-004 diff and a rendered review of the authenticated app
at the agreed viewports; a mock preview does not count. Finish affected data and
operator docs and run the final API, isolated PostgreSQL migration/integration,
web and toolkit gates on the repaired result. Only after all acceptance and gates
pass may the runner commit and mark IMP-004 `[x]`; otherwise record `[!]` with
new evidence and stop its dependents. IMP-002 stays blocked; passing IMP-004
allows the human-only IMP-013 path, not chat or shared-server release.
**Fifth-attempt blocker:** Independent full-diff re-review NEEDS WORK: a delayed
create response after sign-out can disclose the prior account's project metadata
in another account's list; concurrent conflict-proposal pagination can skip or
duplicate proposals without a head change. Focused API/PostgreSQL/web/toolkit
checks passed on the uncommitted repair, but authenticated rendered review,
final documentation and delivery gates remain pending. No commit or dependent work;
owner decision required before another substantive repair.
**Sixth-recovery decision (2026-09-28):** Owner authorizes one more bounded repair
of this same uncommitted item, not a restart, but wants development and testing
to be automatic rather than requiring interactive sign-in. Keep `[!]` until the
owner-approved IMP-015 proves a safe real-app authenticated review path; review
actual readiness before requeueing this item. Repair and regression-test the
cross-account delayed-create response after logout/login, including
project list, selection, editor and notices; the server must still deny foreign
IDs. Make conflict-proposal pagination enumerate every previously listed row
once despite concurrent inserts without a new document revision; newly inserted
proposals may appear on a fresh history load. Preserve immutable proposals,
authorization and revision behavior. Then repeat independent full-diff review,
authenticated rendered review at 1440/1024/768/375px on the real app, affected
data/operator docs, and final API, isolated PostgreSQL migration/integration,
web and toolkit gates before any commit or `[x]`. No model/chat or shared-server
claim. The existing five attempts, failed review and partial work above remain
the recovery record; do not run IMP-013/014 until this item is actually `[x]`.
**Candidate-review scope and readiness approved (2026-09-29):**
The existing IMP-015 fixture archives committed `HEAD`, which excludes IMP-004's
uncommitted code; its checks also reject the candidate's root API build context
and migrations `0003`/`0004`. The owner wants this **same ID**, not a replacement
task. Before using rendered review as IMP-004 evidence, establish an opt-in,
fail-closed candidate preview: an explicitly reviewed list of changed tracked/
untracked runtime inputs layered over the pinned committed base; reject secrets,
unrelated planning files, symlinks, traversal, missing/unexpected files and
oversized inputs; fingerprint the exact candidate. Keep IMP-015's default
committed-HEAD behavior unchanged. Prove safe Compose/loopback/owned-resource
checks for the candidate layout, a fresh single Alembic head at
`20260925_0004`, normal
Member sign-in, project creation and three drafts, and cleanup before claiming
the mode usable. Its first preflight is infrastructure evidence, **not** a
browser review of the repaired IMP-004 result. Then fix both fifth-review
defects above, regression-test and independently review the full combined diff,
and use that same candidate snapshot for authenticated `ui-designer` review;
changed candidate hashes require another rendered review. Finish the original
API/PostgreSQL/web/toolkit gates and docs before any result commit or `[x]`.
No candidate-preview command is verified; if the safe snapshot cannot be
proved, stop with `[!]` instead of testing old HEAD or publishing partial code.
The owner reviewed the expanded same-ID acceptance and explicitly approved
one `[ ]` sixth attempt; retain the five failed attempts and all partial work.
This does not requeue IMP-002 or its dependents.
**Sixth-attempt blocker (2026-09-29):** Candidate infrastructure preflight passed
at fingerprint `cddff4032738abb736e1d9ca59946038b4df499543d647bebb70e06a278ff30a`
with fresh migration `0004`, synthetic Member creation/three drafts, cross-Member
denial and owned cleanup. The two fifth-review defects were repaired and focused
API/PostgreSQL/web checks passed; toolkit passed 96 tests (one gated skip).
Independent full-diff review is INCOMPLETE: authenticated rendered review of the
repaired candidate is missing. A candidate launch's Member handoff read was denied;
its later sanitized cleanup status was readable and reports verified removal.
The required harmless-marker write in the approved private handoff channel is
denied by the current edit rule, so no further credential setup or alternate
transport was attempted. Docs, final acceptance and commit remain pending;
preserve all uncommitted work and stop dependents pending owner permission/decision.
**Same-ID rendered-review recovery authorization (2026-09-29):** The owner has
temporarily changed the installed `overnight` agent to `edit: allow` and explicitly
approves one `[ ]` retry of this existing partial work through the **root
single-branch batch runner**. The owner accepts that broad coordinator checkout
edit permission can remain effective for this entire local batch, including
newly dependency-eligible IMP-013/007/014/009/010 if IMP-004 first becomes `[x]`;
this is not product-agent isolation or a waiver of any task's acceptance.
Keep the private external-directory handoff allowance narrowly scoped. First
prove a harmless write/read in that channel with permitted tools before any
new credentials. The coordinator, **not** a developer subagent, must launch the
candidate fixture, read only the generated short-lived Member login, complete
normal authenticated browser/`ui-designer` review and read sanitized cleanup.
Check the candidate fingerprint against the **current repaired bytes**, rerunning
the safe preflight and rendered review if it changes; the earlier preflight hash
is historical evidence, not sign-off on later edits. Independently re-review
the entire final diff, finish affected docs and actual API/PostgreSQL/web/toolkit
gates, and stage/commit only verified IMP-004/fixture-related files. Do not use
the owner's accounts or copy privileged settings/logs. If any gate fails, record
`[!]` with the existing six attempts and partial work intact. A successful code
task may be `[x]` after its own verified commit and gates; restoration of the
operator's coordinator edit allowlist is **post-batch operator hygiene**, not a
substitute for app acceptance or a new IMP-004 completion gate. The owner should
restore the restrictive agent rule after this batch ends and before any later
separate run; do not claim it has already been restored. IMP-002 remains `[!]`.
**Verified outcome (2026-09-29):** Local commit `60e9480` on
`feature/impostr-v1` contains the private project/draft API, migrations, UI,
candidate fixture repairs, tests and operator data/recovery notes. Current
candidate fingerprint `a7675f6dff0144907c67baebb40c6ca9bddd4e70fdee2fc95ac7a8fd168737c0`
passed fresh migration `0004`, three template drafts, cross-Member denial,
normal authenticated browser review at 1440/1024/768/375 (designer PASS), and
verified owned cleanup. API 51 passed/9 PostgreSQL-only skipped with static
checks; isolated PostgreSQL 9 passed, web 35 passed with lint/format/typecheck/
build, toolkit 98 passed/1 gated skip. Independent full-diff review APPROVED
after history-cache and docs corrections. No push/PR, chat, agent isolation,
backup restore drill or shared-server release claimed; IMP-002 stays blocked.

---

## [ ] IMP-005 — Project-scoped resumable planning chats

Type: feature
**Depends on:** IMP-002, IMP-004
**Scope:** Authenticated API gateway for `tech-lead` plus separate project session
tabs; import proposed document diffs as versioned drafts, not approvals.
**Required capabilities:** Proven isolation and session protocol from IMP-002.

### Done looks like
- Project opens its last used conversation by default, allows new-session tabs,
  streams responses and resumes history after restart/reconnect without crossing
  project boundaries. Users can answer agent questions; permission requests obey
  a bounded server policy, with sensitive requests denied by default.
- Concurrent file-writing turns on the same project cannot silently overwrite
  direct edits or each other; an agent error/timeout preserves chat and draft text.

### Verification
- Adapter-backed integration and browser reconnect tests; forged cross-user
  session/event/reply IDs denied; race and timeout tests preserve DB revisions.

**Documentation impact:** Operator agent-runtime support and failure diagnostics.
**Open decisions:** None after IMP-002 establishes compatible transport/isolation.

---

## [ ] IMP-006 — Integrate chat with first-stage document review

Type: feature
**Depends on:** IMP-005, IMP-013
**Scope:** Integrate resumable `tech-lead` chat and agent-proposed document changes
beside the human review/pair-approval surface delivered by IMP-013. The direct
editor and atomic human approval belong to IMP-013, not this item.
**Required capabilities:** Rendered browser review with `ui-designer`.

### Done looks like
- User can ask `tech-lead` for changes and review its proposed revisions without
  losing manual edits or invalidating approval silently. Agent output can never
  approve or overwrite a newer human revision.
- Chat, question/permission handling, document review and approval remain usable
  together on desktop/narrow layouts, including streaming, conflict, reconnect and
  approval-pending states.

### Verification
- Agent-proposal versus human-revision/approval race and authorization tests,
  rendered chat-and-review checks around 1440/1024/768/375px, keyboard, contrast
  and reduced motion. Reuse IMP-013's human approval tests rather than duplicating.

**Documentation impact:** User guide for project setup at stable UI batch end.
**Open decisions:** Final design tokens follow `ui-designer` review; product behavior
is specified in PROJECT.md. Owner approved extraction into IMP-013; do not count
the already delivered human approval surface again here.

---

## [x] IMP-007 — Validate and edit runner-compatible backlog

Type: feature
**Depends on:** IMP-004, IMP-013
**Scope:** Backlog document API, parser-compatible task model and direct task
edits/status transitions; the human task-list UI is in IMP-014, not here. No
runner outcome management or live agent integration.
**Required capabilities:** Root `scripts/backlog.py` as compatibility oracle.

### Done looks like
- Tasks have stable unique IDs, editable title/body/dependencies, acceptance and
  verification fields; generated items remain `[-]`. Reject malformed headings,
  duplicate IDs/titles, unknown/self/cyclic dependencies and stale revisions.
- Ready and dependency-eligible are displayed separately. Preserve Markdown
  outside edited tasks and any pre-existing `[~]`/`[x]`/`[!]`/Branch/PR metadata;
  browser may not synthesize execution outcomes.

### Verification
- Fixture tests against root helper for heading/dependency semantics; API tests
  for forbidden transitions, round-trips, conflicts and dependency badges.

**Documentation impact:** Backlog editing/status help (not a copy of templates).
**Open decisions:** None; treat cycle rejection as an additional editor safeguard
beyond the helper's current eligibility checks.
**Interrupted partial-work handoff (2026-09-29):** An implementation handoff was
cancelled when the owner clarified that the separate root runner, not this manual
session, should continue. Preserve the uncommitted/untracked backlog parser,
task API, raw-save guard, read-only summary and tests in `api/` and `web/`; they
have **not** passed focused checks, independent review or acceptance. The runner
must inspect the complete dirty diff and reconcile this partial work before
editing or claiming success. IMP-007 remains `[ ]` for the runner to claim; do
 not treat the handoff as an attempt that passed, or reset IMP-013's `[x]`.
**Current blocker (2026-09-30):** Independent full-change review still NEEDS WORK after the initial developer pass, focused repair and senior escalation: a dependency declared beneath a later non-task H2 is reported by the root-compatible parser but cannot be edited through the task API. Partial API/parser/UI/tests remain uncommitted; developer-reported API 122 passed/11 skipped plus static checks, web 61 plus checks, isolated PostgreSQL migration 0005/concurrency 1 and toolkit 117 passed/1 skipped are not final acceptance. Rendered review, affected docs and commit remain pending. Preserve the dirty work pending owner-approved bounded repair; IMP-014/009 remain dependent.
**Owner-authorized same-ID recovery (2026-09-30; exactly one bounded attempt):**
Preserve the dirty partial work and all blocker/attempt evidence. Repair the
root-compatible dependency beneath a non-task H2 that GET reports but PUT cannot
edit; regression-test GET, edit and validation against `scripts/backlog.py` while
preserving surrounding Markdown and runner metadata. If a product-contract
decision is needed, stop and ask the owner rather than guessing. Require
independent full-diff review, focused and established API/web/isolated PostgreSQL/
toolkit checks, authenticated rendered review, affected docs and a verified local
commit before `[x]`; otherwise return to `[!]` with a precise blocker. No other
item is requeued by this authorization.
**Recovery blocker (2026-09-30):** H2 dependency GET/PUT repair and regressions remain uncommitted; independent full-diff re-review NEEDS WORK: a task PUT without a trailing newline can merge a preserved non-task H2 into the edited body, and raw PUT can change compact `Branch:`/`PR:` metadata without detection. Developer-reported API 128 passed/11 PostgreSQL skips plus static checks are not final acceptance. Web, isolated PostgreSQL, toolkit, authenticated rendered review and affected docs remain pending; preserve partial work and stop IMP-014/009 pending owner decision.
**Further bounded same-ID recovery decision (2026-09-30; not requeued):**
Owner approves one further focused IMP-007 repair of the preserved dirty work,
not a restart or a waiver of the earlier full-diff review, final gates, docs and
verified-commit requirements. Keep edits within IMP-007's task boundary: task
PUT must not absorb a following non-task H2 or alter its Markdown; raw PUT must
reject changes to runner-owned metadata, including compact `Branch:`/`PR:` lines.
Regression matrix: task PUT and raw PUT with LF and CRLF, final task-body newline
present/absent, compact and spaced Branch/PR forms, and current versus stale
document revisions; verify byte-preservation of untouched sections/metadata,
stale-revision rejection and root-helper parsing parity. Stop for a product-contract
decision rather than broadening task-edit or runner-outcome authority.
**Rendered-review scope blocker (2026-09-30):** The fixture has only pinned
IMP-004 and IMP-013 candidate profiles; default committed-HEAD review excludes
dirty IMP-007. Extending its fingerprint-pinned security allowlist to the exact
IMP-007 runtime/test/fixture inputs is additional scope requiring explicit owner
approval **before any fixture change or IMP-007 requeue**. No prior candidate
fingerprint or committed-HEAD browser result signs off this dirty work. Retain
`[!]`, all earlier attempts and partial work; IMP-014/009 stay dependent.
**Owner-approved candidate-browser scope and same-ID requeue (2026-09-30):**
The owner now explicitly approves one narrowly scoped local synthetic IMP-007
candidate-browser profile and requeues **only IMP-007** as `[ ]` for the existing
root single-branch runner. The immediately preceding scope blocker and all prior
attempts remain historical evidence, not permission to reuse an IMP-004/013
fingerprint or to review committed HEAD instead of dirty IMP-007. Pin the profile
to committed base `31d0f8f97bcf857b28d4e3f0c7bf51db8f7bf759` and this exact
scoped input inventory (dirty paths plus the planned fixture extension):
runtime/build `.dockerignore`, `api/Dockerfile`,
`api/app/main.py`, `api/app/project_documents.py`,
`api/app/backlog_markdown.py`, `api/app/backlog_tasks.py`,
`web/src/ProjectWorkspace.tsx`; test-only
`api/tests/test_backlog_markdown.py`, `api/tests/test_backlog_tasks.py`,
`api/tests/test_backlog_tasks_postgres.py`,
`web/src/ProjectWorkspace.test.tsx`; host-only fixture
`scripts/local_browser_fixture.py` (profile extension) and
`scripts/test_local_browser_fixture.py` (already dirty). The committed root
`scripts/backlog.py` is the unchanged compatibility oracle, not an overlay.
Reconcile this inventory with the full actual diff before modifying the fixture;
no other IMP-004/013 profile changes or unrelated scoped inputs are approved.
Retain the existing fingerprint, size, secret, safe-path and fail-closed checks;
use a disposable loopback stack, fresh synthetic Member normal sign-in, auth
denials and verified owned cleanup. Independently review the fixture boundary
and full resulting change. After any candidate input changes, repeat exact-byte
preflight, authenticated rendered review and `ui-designer` sign-off; earlier
preflight or committed-HEAD review is not acceptance of the current snapshot.
**Bounded IMP-007 repair and acceptance handoff:** Preserve the uncommitted
implementation and all failed-review findings above; do not restart or change
runner/parser semantics. A later non-task H2 remains a separate section even
when the root helper's task interval spans it: validate the fully assembled task
PUT before persistence so a body without a terminal newline cannot swallow that
heading. Reject the unsafe edit with `422`, **not** silent newline insertion;
preserve all untouched bytes except an explicitly edited dependency value, and
allow a valid task ending at actual EOF. For raw backlog PUT, protect line-oriented
`Branch:`/`PR:` metadata in compact, spaced, bold, list and indented forms across
the full helper task interval, including planning tasks; fenced or inline prose
mentioning those labels is not runner metadata. Cover LF/CRLF, EOF versus next
heading, empty body/body newline, horizontal rules, fenced and unclosed fences,
metadata variants, project authorization and PostgreSQL concurrency. A rejected
`422` must create no revision, mutation, history row or conflict proposal; a stale
expected revision still returns `409` with the existing conflict behavior. Check
GET/PUT/helper parity and byte preservation without changing `scripts/backlog.py`.
Require independent approval of the full baseline-to-result diff, focused and
full API/web/isolated PostgreSQL/toolkit gates, exact-candidate authenticated
rendered/`ui-designer` review, affected docs and a verified local commit before
`[x]`. Otherwise record `[!]` with the new blocker and preserve partial work.
IMP-009/014 remain ineligible until IMP-007 is actually `[x]` on this branch;
no push or PR is authorized by this recovery.
**Local outcome (2026-09-30):** Verified and committed as `e2cabfd` on `feature/impostr-v1`. Full-diff reviewer APPROVED; API 177 passed/11 profile skips plus static checks, isolated PostgreSQL migration 0005/11 passed, web 62 plus checks, toolkit 128 passed/1 gated skip. Exact candidate `a2621b7…d4a2e` passed fresh preflight, normal synthetic Member rendered review and `ui-designer` PASS at 1440/1024/768/375, authorization denials and owned cleanup. Affected docs included; no push/PR or merge. IMP-014/009 remain separate work.

---

## [ ] IMP-008 — Integrate live chat with backlog planning layout

Type: feature
**Depends on:** IMP-005, IMP-006, IMP-014
**Scope:** Add chat and live agent-added/updated task indicators beside the
collapsible human backlog rail delivered by IMP-014. The direct-edit/toggle rail
belongs to IMP-014, not this item.
**Required capabilities:** Rendered browser review with `ui-designer`.

### Done looks like
- Agent-added/updated tasks appear without losing the active chat composer or
  direct edit; the already delivered rail still permits direct edits and on-row
  readiness toggles. Conflict explains which version won without dropping text.
- Empty, waiting-on-dependencies, saving, streaming, validation and disconnect
  states remain usable on desktop and narrow screens; no horizontal overflow at
  the agreed viewport fixtures.

### Verification
- Browser interaction tests for agent updates during direct edits, focus order and
  screen-reader states; rendered desktop/mobile chat-and-rail design review. Reuse
  IMP-014's direct-edit/collapse/status tests rather than duplicating delivery.

**Documentation impact:** Stage 2 task-list guidance with IMP-006 UI batch.
**Open decisions:** None for state authority; only the owner decides task readiness.
Owner approved extraction of human backlog rail into IMP-014.

---

## [!] IMP-009 — Approve backlog and serve immutable downloads

Type: feature
**Depends on:** IMP-013, IMP-007
**Scope:** Human backlog approval, snapshot manifest, and individual file downloads
for approved `PROJECT.md`, `AGENTS.md`, `BACKLOG.md` versions; no repo write.
**Required capabilities:** Versioned document and authorization contracts.

### Done looks like
- Human approves exactly one valid backlog revision after the first two files are
  approved. Any changed member of the approved three-file set makes final handoff
  pending re-review. No inherited template placeholders or invalid task metadata
  can be presented as a runnable approved document.
- Downloads use the recorded three-revision manifest and exact UTF-8 filenames;
  repeated downloads match bytes. Draft/foreign/stale revisions cannot be fetched
  through a changed URL or guessed ID.

### Verification
- Revision race, mutation invalidation, access denial, invalid backlog and
  deterministic download hash/filename tests; audit approval actor/timestamp.

**Documentation impact:** Explain approval versus runner readiness to users.
**Open decisions:** None; first release has no draft downloads or automatic exports
  into Git checkouts.
**Current blocker (2026-09-30):** Partial API/migration/tests remain uncommitted after developer implementation, focused repair and senior escalation. Independent full-change re-review NEEDS WORK: an undecided child heading inside a ready task's verification section can pass final approval. Latest reported API 227 passed/12 profile skips plus static checks and isolated PostgreSQL migration 0006/focused test passed, but these are not final acceptance. No affected docs, commit or approved downloads claim; preserve partial work pending a bounded owner recovery decision.
**Owner-approved same-ID recovery (2026-09-30; requeued `[ ]`):** Preserve the
three substantive attempts and dirty API/migration/tests; do not restart from
the committed IMP-007 baseline or stage IMP-014's unrelated web edits. Allow
up to three **additional** substantive attempts on this ID,
counted across runner sessions. First prove an undecided nested heading such as
`#### Pending: PostgreSQL concurrency` in a ready task's verification cannot
reach final approval; cover fenced examples, completed headings, stale revisions
and the three-file manifest/download invariants without rejecting legitimate
finished work. Require independent full-diff approval, isolated PostgreSQL and
established API/toolkit checks, affected docs and a verified local commit before
`[x]`. Only an in-scope fix with remaining budget may continue `[~]` between
sessions under the approved AGENTS.md policy; genuine blockers stay `[!]`.
**Recovery blocker (2026-09-30):** The three additional substantive attempts
(six cumulative) repaired pending nested verification/scope headings and several
section-boundary bypasses in the preserved API/tests, but independent full-diff
re-review still NEEDS WORK: an empty ready-task Scope can borrow a following
`**Depends on:** None` as evidence, and `#### PostgreSQL concurrency unresolved`
can pass with completed verification text. Both could permit an incomplete
approved/downloadable backlog. Senior-reported API 241 passed/12 PostgreSQL
profile skips plus static checks, isolated PostgreSQL migration 0006/focused 4
passed, and toolkit 128 passed/1 gated skip are intermediate evidence, not final
acceptance. No affected docs, verified commit, or approved-download claim.
Preserve IMP-009 API/migration/tests and unrelated IMP-014 web edits. Further
implementation requires an owner decision/new finite budget; independent approval,
final gates, docs and commit remain pending.
**Owner-directed structural recovery (2026-09-30; requeued same ID):** The owner
authorizes up to **two additional substantive attempts** (#7-8 cumulative),
counted across sessions; retain the six prior attempts, both reviewer findings,
all uncommitted IMP-009 API/migration/tests and unrelated IMP-014 web/planning
edits. Before broad implementation, add a bounded regression matrix for the
ready-task field and Markdown-section boundaries: empty `**Scope:**` must not
borrow a following `**Depends on:**` or other task metadata, and explicit
unfinished child headings such as `#### PostgreSQL concurrency unresolved` must
prevent final approval even when another verification step is complete. Include
the prior prefix-pending, Scope, post-H2, fenced-example, completed-heading and
valid substantive continuation cases. Verify both refusal to create an approval
manifest/download for invalid snapshots and acceptance of valid snapshots;
preserve project access, stale revision, root-helper dependency and draft-edit
behavior. Repair the structural boundary rather than special-casing the two
reviewer strings, then obtain focused independent feedback before the final
full-diff review. Reuse valid earlier evidence only for unchanged inputs; run
the actual focused and established API/PostgreSQL/toolkit gates, affected docs
and verified local commit before `[x]`. A distinct in-scope fix with remaining
budget may checkpoint `[~]` under AGENTS.md; repeated uncorrected findings,
missing capability or exhausted budget return `[!]`, not a waiver or silent
new budget. Do not stage IMP-014's dirty UI or push/open a PR.
**Structural recovery blocker (2026-09-30):** Attempts #7–8 exhausted the
owner's additional budget. Tests-first boundary repairs remain uncommitted;
independent full-diff review still NEEDS WORK: empty Scope can borrow
`**Documentation impact:**` or `**Open decisions:**`, and an unresolved
verification child heading with trailing explanation can permit an approved,
downloadable snapshot. Developer-reported final API 258 passed/12 profile
skips plus static checks, isolated PostgreSQL migration 0006/12 passed, and
toolkit 128 passed/1 gated skip are intermediate, not final acceptance.
Preserve the IMP-009 API/migration/tests and unrelated IMP-014 web/planning
edits. Further implementation requires an owner decision/new finite budget;
independent approval, final coordinator gates, affected docs and verified
commit remain pending. No push or PR.

**Owner-authorized interactive recovery (2026-09-30; same ID, not requeued):**
After the connection interruption, the owner selected **Repair here**: the
interactive tech-lead is the sole recovery coordinator, delegating implementation
to senior-developer and review to a separate independent reviewer; overnight is
not an intermediary. Authorize at most two additional substantive attempts
(#9–10 cumulative across sessions), preserving attempts #1–8 and all dirty work
at baseline `e2cabfdc42f6a6a84ea0dcb85cdbd36f0927dccf` on
`feature/impostr-v1`. Keep IMP-009 `[!]` during direct recovery; do not run the
ordinary runner concurrently or change IMP-014's ordering gate.

Repair final-approval Scope field boundaries so canonical metadata, including
Documentation impact and Open decisions, cannot supply a missing Scope; reject
explicit unfinished child-heading status even with trailing explanation. Start
with failing HTTP regressions and a bounded positive/negative matrix rather than
two literal-string exceptions. Preserve legitimate multiline/colon-labeled Scope,
completed and subject-word headings, masked Markdown examples, draft saves,
root-helper parity, project authorization, stale revisions, immutable manifests
and exact three-file downloads. Invalid input must create no manifest and enable
no downloads. Primary repair ownership: `api/app/project_approval_manifests.py`
and `api/tests/test_project_approval_manifests.py`; the full existing IMP-009
routes/model/migration and PostgreSQL/migration tests remain in review/delivery
scope. Do not change shared parsers, pair-approval behavior, fixture profiles or
IMP-014 UI without an owner scope decision.

Require separate independent review of the entire IMP-009 baseline-to-result
material, final API/static gate, fresh disposable PostgreSQL migration `0006`
and all established PostgreSQL suites including manifest concurrency, toolkit
gate, affected human-facing docs and verified selective local task then outcome
commits. Formatting-only corrections and final review/docs/delivery do not consume
a new substantive attempt; failed gates are not waived. If actionable logic
findings remain after #10, or scope/capability changes, retain `[!]` with evidence
and ask the owner. No unrelated UI staging, push, PR, merge, deployment, real-data
access, tooling installation or automatic runner restart. After verified local
delivery, report the next eligible task and a safe owner-run command.

**Interactive recovery checkpoint (2026-09-30; #9–10 exhausted):** Both
authorized attempts preserved the existing work and repaired the earlier metadata,
trailing-heading and compound-subject findings. Senior-reported final API gate:
441 passed/12 PostgreSQL-profile skips plus Ruff/format/mypy; focused manifest/
migration 266 passed; toolkit 128 run/1 gated skip. Independent full-change
re-review still NEEDS WORK: checkbox-prefixed canonical metadata can supply absent
Scope, acceptance or verification because boundary and evidence normalization
disagree. A subsequent read-only, filesystem-write-denied in-memory HTTP probe
confirmed all six checked/unchecked cases save and pair-approve, then wrongly
return final approval 200, persist one manifest and allow all three exact-byte
downloads; no additional implementation attempt was used. HEAD remains `e2cabfd`.
No final PostgreSQL gate, affected-docs pass, task/outcome commit, push or runner
restart. Retain `[!]`, ten cumulative attempts and all dirty IMP-009/014/planning
material. Further logic repair requires renewed finite owner authorization;
passing existing tests does not override this reproduced approval bypass.

**Owner-requested split proposal (2026-09-30; not approved for execution):**
Propose replacement IMP-020 for inert manifest persistence, followed by IMP-021
for integrated validation/approval/download enforcement. Keep this original `[!]`
while the replacement plan is draft; retain all ten cumulative attempts, partial
files, blockers and branch evidence above. Splitting is not completion or a
budget reset. Only after owner approval and execution prerequisites are proven,
mark this original `[-]` with superseded-by links and promote executable
replacements to `[ ]`. Proposed additional ceiling: three substantive attempts
total across the lineage (#11–13), at most one persistence/test-hardening attempt
and two integrated-enforcement attempts. Mechanical packaging/review/formatting/
reruns/docs/delivery do not consume a logic attempt; new test expectations or
contract/schema/logic changes do. Scope and verification proposals follow below.

---

## [-] IMP-020 — Verify inert three-document manifest persistence

Type: feature
**Depends on:** IMP-013
**Scope:** Finish and verify the existing IMP-009 manifest model and migration
without registering final-approval/status/download routes. Preserve migration
identity `20260930_0006` and its `20260929_0005` parent; reuse valid partial work.
**Required capabilities:** Owner-approved bounded direct recovery; separate senior
implementation and independent review; local Docker/Compose checks against a
non-serving exact source snapshot containing committed baseline plus only the
reviewed persistence paths, and a fresh disposable PostgreSQL project. Snapshot
method is proposed, not verified; do not certify a dirty full-app build as this
standalone slice. No browser candidate-profile expansion is proposed.

**Current review arrangement (owner-requested rethink):** Independent reviewer
reads the assigned implementation/tests in this repository through permitted tools.
Reviewer access to the temporary snapshot directory is not required. Coordinator
owns baseline-to-result reconciliation, actual snapshot/source-byte equivalence,
sanitized check results and selective delivery; independent review remains required
for the schema/approval changes. Do not forward denied snapshot files or retry the
denied marker through another tool. A digest inventory/check result is verification
bookkeeping, not permission to transport denied content or claim OS isolation.

**Additional current prerequisite:** Root-example deletion now breaks API packaging.
Reconcile the selected new bundle's integration with this exact standalone source
contract before resuming. A committed-baseline snapshot may keep the historical
templates internally, without restoring worktree files or adopting new templates.
Current-worktree build/release remains broken; this does not require IMP-022 before
baseline-scoped persistence verification. Template migration is not implicitly
authorized by #11–13; actual snapshot construction/source mapping remains unproved.

### Done looks like
- ORM and migration agree; fresh upgrade, populated-0005 upgrade, disposable
  downgrade/re-upgrade preserve pair approvals and document history. No final
  approvals are backfilled. PostgreSQL verifies the existing pair-snapshot
  composite foreign key and uniqueness with valid and mismatched/duplicate inserts.
- Existing authentication, drafts, task editing and pair approval still work on
  the exact standalone slice. The final-approval router is not registered there;
  approval and download requests remain unavailable. Do not activate unfinished
  routes to make schema tests pass.
- This slice establishes persistence only. The backlog-revision foreign key
  establishes revision existence, not project/kind authorization; IMP-021 must
  enforce the authorized locked-head contract. No validation, approved-download,
  UI, chat, security-boundary or release-completion claim follows from `[x]` here.

### Verification
- Independent review of complete persistence material relative to `e2cabfd`,
  including untracked migration and new test material. Run existing migration
  tests plus scoped PostgreSQL preservation/constraint regressions and applicable
  established PostgreSQL suites on fresh owned storage at migration `0006`.
- Run relevant existing API regressions and static checks for changed Python on
  the exact standalone snapshot; toolkit checks only if helper/fixture inputs change.
  Confirm tested source bytes match intended delivery, and record the
  snapshot method/exact commands once proved. Use documented Compose check and
  integration profiles, not existing databases; verify owned cleanup.
- Reviewed file ownership: `api/app/models.py`,
  `api/migrations/versions/20260930_0006_project_approval_manifests.py`,
  `api/tests/test_migrations.py`, `api/tests/test_postgres_integration.py`; proposed
  new persistence-only PostgreSQL tests in
  `api/tests/test_project_approval_manifest_schema_postgres.py`. Keep main.py
  activation, approval module and HTTP/concurrency tests pending for IMP-021.
- Local task commit precedes `[x]` outcome/bookkeeping; preserve pending IMP-021,
  IMP-014 and unrelated changes. IMP-020 completion does not unblock IMP-014.

**Documentation impact:** Additive schema migration, no approval backfill, and
disposable downgrade limits in `docs/local-development.md`; update durable
current-state claims only after verified delivery.
**Open decisions:** Owner approval of scope, shared #11–13 ceiling, direct
coordinator/local delivery, and bounded non-serving snapshot setup under
`/tmp/opencode/` without host secrets, tooling installation or external serving.
**Recovery lineage:** Proposed persistence replacement for IMP-009; ten prior
substantive attempts remain exhausted. At most one additional substantive
persistence/test-hardening attempt within the shared three-attempt ceiling, if
approved; no default per-ID reset. No implementation authorized by this draft.

**Owner approval (2026-09-30):** Owner selected **Yes, finish it** for this
two-task direct recovery and at most three additional substantive attempts total
(#11–13 cumulative), with the previously described bounded snapshot/local checks
and selective local commits, no deployment or automatic runner restart. Tech-lead
coordinates senior-developer implementation and separate independent review.
Review must focus on demonstrable agreed-contract defects, not speculative prose
semantics, polish or redesign; reproduced approval/security defects remain gates.
This approval supersedes the draft's no-implementation statement within the
bounded assignment. Establish the non-serving exact-source prerequisite before
queue promotion/supersession; preserve all prior evidence and unrelated work.

**Prerequisite checkpoint (2026-09-30):** Senior-developer verified parent
`/tmp/opencode`, but effective external-directory permissions denied creation of
`/tmp/opencode/impostr-imp020-prereq-20260930`. No snapshot, helper, fingerprint,
configuration, DB or application changes were created; no substantive #11 attempt
used. Stop without another tool/path/agent bypass. Owner-authorized split remains
approved but not executable: retain both replacements `[-]` and original `[!]`
until narrowly scoped snapshot access is available and proved. Preserve HEAD
`e2cabfd`, dirty/untracked material and unchanged budget. Needed capability is
senior-developer read/write/setup access only to that owned snapshot directory,
plus independent reviewer read access, not broad host or private-handoff access.

**Owner-requested prerequisite retry after restart (2026-09-30):** Owner declined
new IMP-022 integration and requested existing approval items first. Senior-developer
successfully created/read a harmless marker at
`/tmp/opencode/impostr-imp020-prereq-20260930/prerequisite-marker.txt` through permitted
file tools. Independent reviewer Read of the same marker was denied; no alternate
tool/path was used. Git inspection was also denied to the subagents; coordinator
verified unchanged HEAD `e2cabfd` and preserved dirty work. Reviewer inspected the
four existing persistence files and identified no concrete schema defect, but exact
baseline-to-snapshot equivalence and reviewer snapshot access remain unproved.
No source snapshot, DB checks, application implementation or commits occurred;
#11 is unused. Historical committed templates may exist only inside the bounded
baseline snapshot, not be restored to the worktree or treated as new-template
adoption. Both replacements remain `[-]`; original IMP-009 stays `[!]`. Next step
is permitted independent-review access to this exact owned snapshot directory;
do not widen to host secrets, bypass the denial, or launch the general runner.

**Superseding plan after owner's rejection of the access detour:** Remove the
reviewer-directory gate above. Keep the denied access as history, not a request for
broader permissions. Reviewer inspects all assigned repo code/tests; coordinator
verifies the actual frozen source against committed baseline plus the narrow task
overlay and the eventual selective commit, with focused tests on owned PostgreSQL.
Only sanitized baseline/path/digest/check/cleanup bookkeeping is supplied for review;
no denied file contents, private configuration or credentials. If coordinator cannot
prove mapping through its permitted tools, stop at that actual capability gap.
No new infrastructure task is required. IMP-020/021 scope, #11–13 budget and existing
markers remain unchanged until actual source prerequisites are established. IMP-022
stays deferred and is not a prerequisite for this historical-baseline test path.

---

## [-] IMP-021 — Enforce valid approval and immutable three-file downloads

Type: feature
**Depends on:** IMP-020, IMP-007
**Scope:** Finish preserved IMP-009 validation, approval/status and exact-download
implementation as one integrated acceptance boundary. Repair inconsistent
checkbox framing without changing shared parser/pair-approval behavior or IMP-014
UI. Do not extract a new validator architecture merely to change task labels.
**Required capabilities:** Owner-approved bounded senior-developer recovery;
separate independent review; verified committed IMP-020 on this same branch;
established API/static/toolkit checks and disposable PostgreSQL gates.

### Done looks like
- Failing-before/passing-after HTTP regressions cover checked/unchecked canonical
  metadata in otherwise empty Scope, Acceptance and Verification, including
  supported formatting. Boundary/evidence normalization agree without six-string
  exceptions. Keep genuine checkbox/multiline/colon-labeled/list/table evidence,
  completed subject/compound headings, masked examples and draft-save behavior.
- With valid current preconditions, invalid backlog approval returns `422`, status
  stays unapproved, no manifest or success-approval audit is created and all three
  downloads return `409`. Approval refusal creates no document revision, head
  change or conflict proposal. Rate-limit writes and required admin-access audits
  are not incorrectly forbidden by these assertions.
- Existing invalid manifests fail closed on status, idempotent POST and every
  download; historical metadata is not downloadable current approval. Current
  approved pair/exact backlog preconditions, stale `409`, identical-byte-save
  invalidation, idempotent duplicate approval and single success audit remain.
- Downloads return the recorded current tuple's exact UTF-8 bytes and canonical
  filenames. Every endpoint enforces account/session/project/CSRF/Origin boundaries;
  guessed foreign/history IDs, changed authorization and stale snapshots cannot
  retrieve a draft or bypass approval. Preserve transaction/commit-failure and
  PostgreSQL concurrent-approval/save-race safety.
- This completes IMP-009's remaining API contract, not IMP-010/014 UI, chat,
  isolation, private LAN access, full integration or release readiness.

### Verification
- Actual save → pair approval → invalid final approval → status/persistence/all
  three download denials, valid repeated bytes/hash/filename cases, and relevant
  approval regressions. Independent review covers combined original `e2cabfd`
  baseline-to-result IMP-020/021 material, including tracked/untracked files.
- Focused API approval/status/download checks and changed-Python static checks;
  toolkit checks only for helper/fixture changes. Fresh disposable PostgreSQL
  upgrade/current `0006`, relevant PostgreSQL suites including manifest
  concurrency and IMP-020 schema tests, and verified owned cleanup. Earlier
  dirty-candidate pass counts or twelve profile skips are not final acceptance.
- Reviewed file ownership: `api/app/project_approval_manifests.py`,
  `api/app/main.py`, `api/tests/test_project_approval_manifests.py`,
  `api/tests/test_project_approval_manifests_postgres.py`; affected
  `docs/local-development.md` after code stabilizes. Any schema/shared-parser/UI
  change outside owning scope requires reconciliation, not an implicit budget.
- Verify selective local task and bookkeeping commits before `[x]`. Only its
  verified committed result establishes IMP-014's later candidate base; no preview
  of unresolved dirty approval code, waived authenticated rendering or runner
  restart is authorized here.

**Documentation impact:** Human-only final approval versus task readiness and
dependency eligibility, approved-only exact downloads, stale/invalid recovery and
source-tested versus deployed claims. Update PROJECT.md/AGENTS.md after delivery.
**Open decisions:** Owner approval/readiness and finite shared recovery budget,
not new product or Markdown security semantics.
**Recovery lineage:** Proposed remaining replacement for IMP-009. At most two
additional substantive enforcement attempts within the shared #11–13 ceiling,
if approved; retain all ten prior attempts and new cumulative numbers. New logic
findings after budget exhaustion, unavailable checks or scope changes stop `[!]`.

**Owner approval (2026-09-30):** Included in the same **Yes, finish it**
authorization recorded under IMP-020; retain the shared #11–13 maximum and direct
coordinator/reviewer/local delivery limits. No per-task fresh budget. Await verified
committed IMP-020 before this implementation; drafts await execution prerequisites.

**Proposed consumer rewiring after approval (not applied yet):** IMP-010 and
IMP-011 replace IMP-009 with IMP-021; IMP-014 replaces its execution-only IMP-009
gate with IMP-021's verified commit while preserving all candidate-profile,
authenticated browser/design, permissions and cleanup requirements. Original
IMP-009 becomes `[-]` superseded by IMP-020 and IMP-021, never `[x]` from splitting.

---

## [ ] IMP-010 — Three-file final review experience

Type: feature
**Depends on:** IMP-014, IMP-009
**Scope:** Stage 3 version/status overview with three simultaneous desktop document
panes and accessible narrower-screen review/download flow.
**Required capabilities:** Rendered browser review with `ui-designer`.

### Done looks like
- User can compare all three approved revisions side by side at wide desktop
  width, identify readiness versus approval state, and download each individually.
  If revisions change, downloads disable with a precise return-to-review path.
- Narrow screen navigation preserves position and focus, with readable document
  measures, text status indicators, no covered controls and no horizontal overflow.

### Verification
- End-to-end browser approve/edit-invalidates/re-approve/download flow and
  rendered viewport, keyboard, reduced-motion and contrast review.

**Documentation impact:** First-release user handoff guide with final UI batch.
**Open decisions:** None.

---

## [-] IMP-011 — One-owner private-access release and recovery acceptance

Type: feature
**Depends on:** IMP-003, IMP-005, IMP-008, IMP-009, IMP-010, IMP-016, IMP-018
**Scope:** Integrate the full planning/chat/attachment/approval/download flow on
this PC for one owner, including private HTTPS access from another device,
isolated agent operation, synthetic-data DB/media restore, independent security/
design review and operator docs. Fix defects in owning slices rather than
substituting this item for their acceptance. This is **not** multi-user server
qualification.
**Required capabilities:** IMP-016's operator-provisioned private HTTPS route,
IMP-002's tested brokered worker, two synthetic accounts/projects, browser tools
and a disposable recovery dataset. No route or backup procedure is verified yet.

### Done looks like
- One-owner walkthrough from the PC and a real phone/other device covers private
  project creation, live resumed/new-tab chat, image and text-only PDF/DOCX
  attachments actually included in turns, pair/backlog approval, edit/conflict
  states and three byte-identical approved downloads. Keep two synthetic users/
  projects for negative access checks; do not call this multi-user qualification.
- Restart and synthetic restore retain revision/approval/chat history and retained
  media; private HTTPS/Origin/CSRF, bounded tool/model access, upload abuse and
  authorization denials, dependency/secret checks and the operator runbook pass.
  Any unavailable gate blocks the personal release rather than being declared
  postponed hardening.

### Verification
- Run established app/unit/integration/browser/security checks on the delivered
  revision, independent reviewer and `ui-designer` sign-off, owned synthetic
  DB/media restore, agent escape/failure checks and a remote-device smoke through
  the actual private HTTPS route. Never expose Docker, DB, worker or relay ingress.

**Documentation impact:** Final operations, recovery and user guides for the
stable release; do not store secrets or private chat in reports.
**Open decisions:** Operator must provision and verify the private HTTPS route
and synthetic restore resources. Exact URL/certificate/proxy commands and model/
media limits are not established. Multi-user server deployment is deferred to
IMP-019. Owner approved this draft scope, not its `[-]` readiness.

---

## [ ] IMP-012 — Verify work branch and open single development PR

Type: release-finalization
**Depends on:** IMP-011
**Scope:** Integrated checks and the one GitHub PR from `feature/impostr-v1` to
`development` for the **one-owner private-access** release; no implementation on
`v1` and no automated merge. Do not claim multi-user server readiness.
**Required capabilities:** All in-scope feature items verified and locally
committed in the same branch, actual app checks, independent review, and usable
GitHub branch push/PR tooling and auth.

### Done looks like
- All intended feature outcomes are `[x]` and integrated on the current feature
  branch (or the owner explicitly removed an item from scope). Verify that exact
  branch head with established tests and security/UI gates; a moved head requires
  retest. A `[!]` prerequisite cannot be passed off as delivered.
- Push only the checked feature branch and open/reuse a normal review-ready PR
  with explicit source `feature/impostr-v1` and destination `development`; record
  URL and evidence and leave merge to a human. If push or PR submission fails,
  preserve local commits and report blocked delivery rather than claiming success.

### Verification
- Inspect commits and outcomes on the work branch, run full release checks on
  its current head, verify the published head and confirm PR base/head and content.

**Documentation impact:** Release summary and outstanding owner merge action.
**Open decisions:** GitHub CLI/auth are verified for read access here; branch
push/PR-write access remains to be proven at delivery without bypasses.

---

## [x] IMP-013 — Human-only first-stage document review and pair approval

Type: feature
**Depends on:** IMP-004
**Scope:** Extract the direct PROJECT.md/AGENTS.md review, edit,
diff and atomic human pair approval from IMP-006. No OpenCode session, model
credential or agent proposal may be assumed; this is a partial product slice,
not a chat-enabled first release.

### Done looks like
- Authorized creator/admin can compare saved versions, edit both drafts, and
  approve exactly the current pair after starter validation; stale saves or
  approvals fail without losing either edit, and later changes invalidate approval.
- Accessible desktop/narrow review and conflict states work without agent chat.
  IMP-006 is narrowed to chat integration; pair approval is not delivered or
  counted twice.

### Verification
- Authorization, stale-version and atomic approval tests plus rendered keyboard,
  viewport and conflict review. No model or live-session claim.

**Documentation impact:** Explain partial human-only workflow and later chat gate.
**Decision:** Owner approved this extraction and IMP-006/007/009 dependency
changes on 2026-09-25. This is a verifiable intermediate slice, not the complete
chat-enabled first release; do not mark IMP-006 delivered from this item's work.
**Blocker (2026-09-29):** Independent full-diff re-review still NEEDS WORK: a
required decision wrapped in paired custom HTML can approve `TBD`, and a pair
refresh racing history can regress the clean editor's saved head. Existing
uncommitted implementation, migration, fixture and tests are preserved; reported
API 63/10 skipped, isolated PostgreSQL 10, web 47 and toolkit 117/1 skipped
passed at different repair checkpoints, not final acceptance. The last repair
changed candidate inputs; fresh preflight, authenticated rendered review, docs,
final gates and commit remain pending. Stop dependent work pending owner decision.
**Local human-only recovery proposal (not requeued):** Reuse IMP-013 and its
preserved partial work; no model credential, relay or product-agent integration
is needed. Regression-test rejection of undecided required decisions inside
paired custom HTML and the reverse-order history/pair-refresh response race
without regressing legitimate markup, immutable revisions or unsaved edits.
Obtain independent full-diff re-review, then fingerprint and review the exact
final candidate through normal synthetic Member sign-in and rendered viewports;
finish affected docs and actual API/PostgreSQL/web/toolkit gates before a
verified commit. Keep `[!]` until the owner explicitly approves another bounded
attempt; do not start IMP-007/014 or count passing intermediate checks as done.
**Bounded recovery blocker (2026-09-29):** Focused custom-HTML TBD and pair-refresh/history race repairs and regressions remain uncommitted. Independent full-diff review NEEDS WORK: four-space-indented code can satisfy required approval decisions, and a delayed stale-approval conflict response can regress a head already advanced by history. Developer-reported API 63 passed/10 skipped with static checks and web 49 passed with checks are not final acceptance. Per the owner stop rule, no further repair, fresh candidate preflight/authenticated rendered review, docs, isolated PostgreSQL or toolkit/final coordinator gates were attempted. Preserve the existing partial work and all prior attempts; keep dependents blocked pending owner decision.
**Owner-authorized bounded continuation (2026-09-29; one attempt, no runner requeue):**
Preserve the same IMP-013 ID, uncommitted implementation and all failed-review
evidence. Repair and regression-test both new review findings: four-space-indented
Markdown code must not satisfy required decisions in either document (while real
prose, lists and tables still can), and a delayed stale-approval `409` must not
move any visible saved head behind a revision already found by history. Preserve
the original stale pair for comparison, unsaved editor text, explicit reapply,
authorization and atomic approval semantics. Obtain independent review of the
whole baseline-to-result diff before further acceptance work. If it passes,
preflight and authenticate the exact final candidate for rendered review, then
finish affected docs and actual API, isolated PostgreSQL, web and toolkit gates
before any verified commit/outcome. Any failed gate stops this attempt with a
new checkpoint; prior passing checkpoints are not final evidence. No IMP-002,
chat, host-secret setup, dependent work, push or PR. Keep `[!]` while this
manual recovery is in progress; the coordinator, not a developer subagent, owns
status and delivery after all required gates pass. Do not start another root
runner against this partial checkout.
**Continuation blocker (2026-09-29):** Focused indented-code and delayed-409 repairs with regressions remain uncommitted. Independent full-diff review NEEDS WORK: HTML comment-only sections/fields can still satisfy required decisions, and a later saved-pair refresh replaces the original submitted stale pair in the conflict comparison. Developer-reported API 64 passed/10 PostgreSQL-only skipped with static checks and web 51 with checks passed, but are not final acceptance. Stopped before fresh preflight, authenticated rendered review, affected docs, isolated PostgreSQL, toolkit and coordinator final gates. Preserve all partial work and prior attempts; IMP-013 and dependents remain blocked pending owner decision.
**Owner-directed immediate recovery (2026-09-29; same ID, manual continuation):**
Prioritize finishing IMP-013 on this host without another owner-approval round
for each ordinary, in-scope review defect. Before patching individual examples,
establish one reviewable contract and regression matrix: only visible, substantive
Markdown decisions may satisfy required sections/fields (not fenced/indented
code, HTML comments, markup-only or undecided values); genuine visible prose,
lists, tables and legitimate markup must remain usable. Keep the originally
submitted stale pair immutable for comparison, advance current saved heads
monotonically across history, pair refresh and approval responses, and reset
review confirmation when the latest comparison target changes; never erase
unsaved text or silently rebase a save. Repair and independently re-review the
whole diff against that contract. Correctable in-scope NEEDS WORK findings may
be repaired and re-reviewed in this same authorized continuation, rather than
stopping for another owner permission; stop for an unresolved product decision,
unavailable capability, unsafe access or an acceptance gate that cannot pass.
After APPROVED review, rerun exact-candidate preflight and authenticated rendered
review, affected docs and actual API/isolated PostgreSQL/web/toolkit/final gates.
The owner requested speed and offered to accept risk, but no specific change to
approval/version safety requirements was agreed: do not bypass validation,
conflict protection or failed gates, or claim an unsafe implementation complete.
Preserve the `[!]` checkpoint and all partial work while recovering; no root
runner, unrelated IMP-002 work, dependent tasks, push or PR. Only the coordinator
records a verified IMP-013 outcome after its actual acceptance passes.
**Interrupted continuation checkpoint (2026-09-29):** Independent review then
found that `opacity:0` and `font-size:0` could conceal text counted as required
decisions. The follow-up repair handoff was cancelled; the current dirty tree
contains HTML-scanner/style tests, but there is no evidence that this snapshot
passed review or any final gate. Fresh candidate preflight, authenticated
rendered review, docs, isolated PostgreSQL and toolkit remain outstanding.
**Owner-approved fail-closed evidence boundary (2026-09-29; not a requeue):**
The required-decision check is a bounded Markdown evidence rule, not an HTML/CSS
visibility detector. Save raw HTML in drafts unchanged, but text inside *any*
raw HTML element, including an unstyled paired custom tag, never supplies a
required PROJECT.md or AGENTS.md decision. Supported Markdown-native headings,
prose, lists and table data, including ordinary inline formatting and link
labels, may supply evidence; code examples, comments, attributes, image alt
text, reference definitions, undecided values and ambiguous constructs do not.
An explicit undecided required value still blocks approval. This supersedes the
earlier expectation that text inside legitimate raw HTML could satisfy a
decision; revise those positive tests rather than adding more CSS synonyms.
Before further review, test a compact positive/negative matrix in both documents
and verify that raw HTML alone fails approval while substantive Markdown outside
it remains eligible. Keep approval, current approval status, immutable revisions
and stale-conflict behavior aligned; independently review the whole resulting
diff before candidate/browser/docs/isolated-PostgreSQL/toolkit/final gates.
The interrupted local checkout contains unverified scanner and style/class tests;
do not treat those edits or earlier test counts as accepted or discard them
without inspecting the diff. Existing IMP-013 `[!]`, attempts and dependency
blocks remain; the prior owner-directed manual continuation may proceed under
this now-settled boundary, not through an automatic root-runner requeue.
**Verified local checkpoint (2026-09-29):** The existing dirty implementation now
follows the bounded Markdown rule; independent full-diff code and final-evidence
reviews returned APPROVED. Exact-candidate fingerprint `9afbbc5e…859b6` passed
fresh `0005` preflight, normal synthetic Member rendered review at 1440/1024/768/
375 px, real two-tab stale-save conflict review, and owned cleanup. Final isolated
PostgreSQL migration and 10 tests, API 81 passed/10 profile-skipped plus static
checks, web 60 plus static/build, and toolkit 116 passed/1 gated skip all passed;
affected operator docs were updated. No commit was requested in this continuation,
so this verified candidate is still uncommitted and IMP-013 stays `[!]` pending
explicit local delivery authorization. Do not start dependents; no push or PR.
**Owner local-delivery authorization (2026-09-29; outcome still pending):** The
runner/coordinator may commit the verified IMP-013 implementation, migration,
tests, fixture, affected local-development docs and narrowly relevant planning/
outcome hunks on the existing `feature/impostr-v1` branch. First inspect the
current diff and evidence against the exact reviewed candidate; if runtime
inputs changed or a gate cannot be substantiated, stop rather than commit from
stale evidence. Exclude unrelated dirty planning edits, `.opencode` logs,
browser state and credentials. Record `[x]` only as part of a successfully
verified local delivery commit, preserving the earlier blocker/attempt history;
if commit fails, leave `[!]` and report it. After the verified local commit, the
runner may continue dependency-eligible work under the existing single-branch
batch rules. This authorizes no push, PR, merge or first-release claim. A
planning note alone does not complete IMP-013 or make dependents eligible.
**Verified local delivery (2026-09-29):** Commit `888e53c` on
`feature/impostr-v1` contains the exact reviewed approval API/migration/tests,
candidate fixture, responsive UI, operator docs and bounded Markdown contract.
The pre-commit IMP-013 candidate fingerprint matched the reviewed
`9afbbc5e3083f3dde00822e27bfc198fea8511da2454f7e312da723d638859b6`;
the commit's app/docs paths have no post-commit worktree changes. Independent
full-diff and final evidence reviews APPROVED. Fresh migration `0005`, 10 isolated
PostgreSQL tests, API 81 passed/10 profile skips plus checks, web 60 plus checks,
toolkit 116/1 gated skip, normal synthetic Member rendered review at
1440/1024/768/375, two-tab stale-save conflict and owned cleanup passed. Earlier
failed attempts and blockers above remain history, not current defects. This is
local human-only approval, not chat, exports, agent isolation or release readiness;
no push/PR/merge.

---

## [ ] IMP-014 — Human-only collapsible backlog planning layout

Type: feature
**Depends on:** IMP-007, IMP-013, IMP-009
**Execution ordering:** IMP-009 is a prerequisite for this checkout's
commit-pinned IMP-014 candidate review, not a product/API dependency of the
human backlog rail. Its verified commit must establish the preview base so the
candidate cannot silently include IMP-009's unresolved dirty API/migration.
**Scope:** Extract direct task-list UI from IMP-008: collapsible
rail, editable task title/body/dependencies, on-row draft/ready controls and
conflict handling. Does not stream or display agent-added task updates.

### Done looks like
- Human edits and list/document views agree at the saved revision; conflicts
  preserve unsaved text and no execution status can be synthesized. Desktop and
  narrow keyboard-accessible layouts handle empty, saving and invalid states.
- IMP-008 retains chat and live agent-update integration on top of this rail
  rather than counting the same direct-edit UI twice.

### Verification
- Browser interaction and rendered responsive/keyboard review for direct editing,
  collapse, readiness toggle and stale revisions; no model integration claim.

**Documentation impact:** Human-only backlog editing guidance, not a release claim.
**Decision:** Owner approved this extraction and IMP-008/010 dependency
changes on 2026-09-25. Do not mark live agent updates or IMP-008 delivered from
this item's work.
**Earlier blocker (2026-09-30; preserved):** Uncommitted web task rail/editor and tests passed 71 web tests, lint, format, typecheck and build; independent code re-review found no remaining defect but returned INCOMPLETE without authenticated rendered interaction/design review at the agreed viewports. The committed-HEAD browser fixture excludes this dirty UI and its approved candidate profiles do not include IMP-014. Preserve partial work; obtain an owner-approved exact-candidate review path, then rendered sign-off, affected docs and final gates before a local commit or `[x]`.
**Owner-approved same-ID requeue (2026-09-30; ready but waiting for IMP-009):**
Preserve the dirty UI/tests and prior review evidence. The owner authorizes
extending the existing local-only candidate fixture for IMP-014 over the
actual committed base after IMP-009 passes, with an independently reviewed
inventory limited to runtime
`web/src/App.tsx`, `web/src/ProjectWorkspace.tsx` and
`web/src/BacklogPlanning.tsx`; tests `web/src/App.test.tsx`,
`web/src/ProjectWorkspace.test.tsx` and `web/src/BacklogPlanning.test.tsx`;
host fixture `scripts/local_browser_fixture.py` and
`scripts/test_local_browser_fixture.py`. Reconcile the full diff first and
exclude unverified IMP-009 API/migration changes from the preview. Existing
fingerprint, size, path, secret and cleanup guards remain mandatory. Recompute
the fingerprint
and repeat the normal synthetic Member sign-in, authorization denial, actual
rendered interaction at agreed viewports, keyboard/focus and ui-designer sign-off
after any candidate input changes; a committed-HEAD or IMP-007 profile review is
  not evidence for the dirty UI. Require focused web editing/readiness/conflict/navigation
  checks and toolkit checks for the fixture extension; API checks only for actual
  affected behavior. Independently review the substantial UI/fixture change and
  focused repairs, update useful affected docs, and verify a local commit before `[x]`.
The already verified IMP-007 opt-in candidate mechanism and approved input scope
make the profile extension implementable **within this item**; the IMP-014
profile itself is not yet built or reviewed. Once IMP-009 is `[x]`, inspect its
actual commit and the remaining dirty diff before doing any candidate work.
First establish a reviewed exact-base profile and pass fingerprinted preflight;
if that cannot be done without unrelated inputs, stop `[!]` with the capability
gap rather than bypassing the fixture. A profile or preflight is not completed
browser review: all authenticated rendered gates still belong to IMP-014.
Allow up to three substantive recovery attempts on this ID in addition to its
recorded prior work; use AGENTS.md's bounded continuation only with a distinct
in-scope next step and remaining budget. No push/PR or chat claim.

---

## [x] IMP-015 — Prove automated authenticated local browser review

Type: test-infrastructure
**Depends on:** IMP-001, IMP-003
**Scope:** Establish a repeatable, operator-controlled disposable local test
fixture using the real Compose front door, migrations, normal offline admin
bootstrap and authenticated member creation. Supply a real signed-in browser
context for automated checks and `ui-designer` review. Only newly generated,
short-lived member credentials/session may be visible in that test browser or
private run logs. Never deliberately give the reviewer admin, database, provider,
host or real-user credentials or real project data. The owner explicitly accepts
the residual risk of an **unconfined** shared browser-tool server on this personal
development host; do not claim it cannot access Docker, host secrets or another
stack. Do not change production authentication or claim agent-runtime isolation.
This proof uses the committed IMP-003 sign-in/account surface; IMP-004's
uncommitted project behavior is not an IMP-015 acceptance dependency or part of
its commit.
**Required capabilities:** Operator-controlled Docker/Compose host, a fresh
disposable test database and browser tools; no existing test login is reused.

### Done looks like
- A trusted test supervisor creates unique disposable stack/storage and per-run
  credentials, brings up migrations and the real app, creates two member accounts
  through normal auth, and proves the reviewer can interact with an authenticated
  context at the local front door. No admin, DB, provider or host credentials
  enter command arguments, reviewer prompts/browser-tool calls or logs, and no
  credential values enter tracked files.
  Disposable member login/session material may be visible in browser tool calls,
  network inspection and private local logs; it is never committed, reused or
  presented as safe outside the test stack. No test-only auth bypass or externally
  published service is added.
- Only synthetic data is intentionally placed in the disposable test stack.
  The reviewer browser process is **not** OS-confined or proven unable to reach
  host resources; this local-only owner risk acceptance is not evidence of a
  privileged-agent boundary. Keep logs private, revoke both member sessions,
  and remove only resources the supervisor created on normal exit and failure;
  retained logs may hold revoked disposable tokens. Never clean up the owner's
  existing interactive-test stack. Failed setup, sign-in or teardown fails
  closed rather than substituting a mock preview.

### Verification
- Demonstrate repeatable fresh setup, real member sign-in and authenticated
  UI interaction, denial of member-only requests to admin endpoints, browser
  context handoff and rendered interaction at the agreed viewports. IMP-004 later
  tests project creation and cross-user project denial using this fixture. Record
  the actual supported setup/check commands after running them; exercise
  member-to-admin API denial, expired/revoked session denial and cleanup without
  touching existing developer data. Independently review test-credential handling,
  resource ownership, no intentional privileged access, failure paths and the
  explicitly accepted unconfined-host limitation; `ui-designer` confirms the
  context is the real signed-in app.

**Documentation impact:** AGENTS.md verified fixture/check procedure and local
operator guide once proven, with no credential values or reusable login secrets.
**Decision (2026-09-28):** Owner approved this independent, ready prerequisite
for IMP-004's sixth recovery and wants automatic development/testing without
manual sign-in. It is not delivered application behavior. If safe
browser-context handoff cannot be proved with the available tools, leave IMP-004
blocked and ask for a revised execution decision; do not silently use credentials
in agent prompts or a fake UI. Because IMP-004's partial files already dirty this
checkout, stage/commit only IMP-015's own verified changes and plan outcome; never
include IMP-004 code, migrations, docs or test artifacts in that commit.
**Blocker (2026-09-28):** The designer shares the coordinator's browser page, but
no operator-only secret-safe browser attachment is verified; available reviewer
browser tools can inspect HttpOnly session cookies and raw login requests. No
fixture, authenticated review or cleanup proof ran. Owner must approve a restricted
reviewer interface or revise the disposable-session exposure requirement; IMP-004
remains blocked.
**Recovery authorization (2026-09-28):** Owner explicitly accepted visibility of
generated, short-lived, isolated **member-only** credentials/session to the
reviewer browser and private logs; this does not apply to the manually created
`imp004member` account or any real/admin/DB/provider secrets. The old browser
visibility objection is narrowed, not evidence of a fixture or a safe browser
process. Reuse this ID and the shared-page marker evidence; do not claim an
operator-only handoff or remove the blocker until a trusted supervisor,
reviewer-process confinement, real sign-in and teardown are independently
verified. Owner reviewed the revised acceptance and explicitly approved this
item's `[ ]` requeue for one bounded attempt. If any boundary cannot be proved,
record a new `[!]` outcome rather than weakening it; IMP-004 remains `[!]`.
**Bounded recovery blocker (2026-09-28):** No verified way to attach `ui-designer`
to an OS-confined reviewer/browser-tool server; the available shared Playwright
server permits server-process code execution and `--isolated` does not establish
host/Docker/other-stack denial. Independent review found the boundary incomplete.
No fixture, credentials, stack, sign-in, denial/teardown proof or commit ran;
operator-provisioned confined reviewer attachment is required before retrying.
**Local-only recovery authorization (2026-09-28):** The owner explicitly accepts the
residual host-level risk of the unconfined shared Playwright tool server for a
personal, synthetic IMP-015 and later IMP-004 test run, rather than provisioning
OS confinement. The prior confinement requirement is superseded **only for this
local test**; the historical blocker and failed attempt above remain recorded.
This decision does not demonstrate host/Docker denial or relax IMP-002,
production or shared-server security. Do not use the owner's `imp004member`
password. A trusted supervisor must still create per-run Member logins and a
fresh disposable stack, automate
normal sign-in, show real authenticated rendering to `ui-designer`, prove app
authorization/session revocation and safe cleanup, and obtain independent review.
No fixture or authenticated review has been delivered. The owner reviewed this
revised acceptance and explicitly approved one `[ ]` local-only recovery attempt.
If verification fails, record a new `[!]` outcome; IMP-004 remains `[!]`.
**Local-only recovery blocker (2026-09-28):** The disposable committed-HEAD
fixture remains uncommitted in `scripts/local_browser_fixture.py` and its tests.
Forty toolkit tests passed, but the first real Compose run failed at offline
administrator bootstrap (exit 1, diagnostic output suppressed); the supervisor
reported removal of its own containers, networks, volume and images. No member
handoff, authenticated browser/design review, session-denial proof, repeat run or
post-handoff teardown was verified. Independent review NEEDS WORK. This bounded
recovery is exhausted; diagnose the bootstrap safely and seek owner authorization
before retrying. Preserve IMP-004's dirty work and blocked status.
**Focused recovery authorization (2026-09-28):** Reuse the
existing uncommitted supervisor/tests and IMP-015 ID; do not restart or requeue
IMP-004. The generated admin and member usernames contain `_`, which the
committed `normalize_username` regex rejects even though its message and local
guide claim it is allowed. Use valid synthetic names and regression-test all
generated account names against the committed-app rule; do not alter product
authentication in this fixture recovery. Treat that documentation/validator
mismatch as a separate product-contract discrepancy for later owner triage.
Because the bootstrap terminal output was suppressed, verify the actual failure
cause on a fresh disposable run with bounded, redacted diagnostics only; never
print or persist admin, DB or provider credentials. Prove an unattended fixture
stays available throughout normal browser sign-in and `ui-designer` review,
instead of ending when the runner's PTY stdin closes. Verify repeatable setup,
authorization/session denials, owned-resource cleanup on success and failure,
and no interference with the owner's existing local stack. Obtain independent
full-diff review, affected operator docs and established toolkit checks; commit
only independently verified IMP-015 changes, not IMP-004 or prior unrelated
planning edits. If any gate cannot be proven, keep `[!]` with fresh evidence.
Owner reviewed this same-ID recovery and explicitly approved one `[ ]` requeue;
the previous failure and partial work remain recorded above. IMP-004 stays `[!]`
until this item's real authenticated review and independent gates are verified.
**Focused recovery blocker (2026-09-28):** Fresh disposable committed-HEAD
Compose runs found `alembic upgrade head` exited 0 but `alembic current` was
empty and the `users` table absent (bootstrap SQLSTATE 42P01). Migration revision
files exist in the image; the Alembic head-discovery exception is unclassified.
The committed username validator actually accepts `_`, so the earlier rejection
explanation is incorrect. Partial fixture/tests remain uncommitted; 46 toolkit
tests and Python compilation passed, but independent review NEEDS WORK. Failed
runs reported owned-resource removal; no successful setup, member sign-in,
browser/design handoff, session-denial proof, repeat run, final docs or commit.
Diagnose Alembic discovery with bounded, redacted evidence before another
owner-approved recovery. IMP-004 stays blocked.
**Correction and diagnosis authorization (2026-09-28):** Retract the earlier assertion in
the focused recovery authorization that `_` is rejected: the committed and dirty
username patterns both accept it. Generated names are not an established cause
of bootstrap failure; the associated documentation discrepancy was also a false
claim. Preserve the older attempt text above as history, not current direction.
On the existing uncommitted IMP-015 fixture, first classify why the fresh
committed-HEAD app's Alembic upgrade reports success without a current revision
or the `users` table. Inspect only the supervisor-owned disposable stack;
compare configured script location, discovered revision IDs/head, image contents,
same DB/schema identity and table presence using bounded allowlisted outputs.
Never dump environment files, URLs, raw migration logs, admin/DB credentials or
another stack. Reconcile with the previously verified committed-app migration
path before changing anything; if an app migration or trust boundary change is
needed, stop for owner scope. If a fixture-only cause is established, repair it
in this same ID, then prove two fresh runs, real Member sign-in, ui-designer
authenticated review, session/authorization denials, owned teardown after
handoff and failure, independent review, docs and final checks. No IMP-004 or
unrelated dirty files in an IMP-015 commit. The owner reviewed this bounded,
redacted diagnosis-first plan and explicitly approved one `[ ]` requeue of the
same ID; if cause or gates remain unverified, record a new `[!]` outcome.
IMP-004 stays `[!]` until IMP-015 is actually verified.
**Diagnosis-first recovery blocker (2026-09-28):** The migration failure was
fixture-only: restrictive supervisor umask left archived `migrations/versions`
unreadable by the container runtime, so Alembic discovered no revisions.
Restoring nested archive directory permissions produced a fresh disposable
migration probe with head/current `20260925_0002` and `users` present; one full
setup reportedly reached synthetic-member handoff and API denials. Coordinator
access to the private handoff log was denied, so browser sign-in, same-page
`ui-designer` review, second full run and post-handoff teardown were not verified.
The supervisor was signaled and exited, but its cleanup report was inaccessible.
Review found partial-account/admin-session failure paths; fixture-only repairs
and tests remain uncommitted and need re-review. Toolkit tests passed (56);
no affected docs, delivery commit, push or PR. Preserve the partial scripts and
IMP-004 work; obtain an authorized accessible disposable-member handoff and
repeat live gates before another owner-approved requeue. IMP-004 remains blocked.
**Permitted-handoff recovery authorization (2026-09-28):** Owner authorizes a narrowly
coordinator-readable private handoff limited to the supervisor's generated,
short-lived Member login and a sanitized owned-stack cleanup status. This does
not authorize access to the previously denied nested log by another tool,
generic reads of temporary directories, owner-created accounts or privileged
secrets. Before provisioning credentials, prove that the proposed channel is
actually readable through its permitted tool using a harmless marker; if it is
denied, stop and ask for explicit permission rather than switching transports.
Keep handoff private and short-lived; neither credentials nor cookies enter Git,
application files or public output. A reviewer receives only the disposable
Member login through the existing local-only risk exception. Run two fresh
committed-app setups, normal browser sign-in in the coordinator's shared page,
real `ui-designer` rendered review, member/admin and revoked-session denials;
verify supervisor-owned account/session teardown and exact resource removal
**after** handoff, plus failure cleanup and unaffected owner stacks. Re-review
the final fixture diff including prior partial-account/admin-session repairs,
update operator docs and run established checks. Stage/commit only verified
IMP-015 work without IMP-004 or unrelated dirty planning edits. If any gate
fails or the output channel remains denied, record `[!]` and preserve evidence.
Owner reviewed this same-ID recovery and explicitly approved one `[ ]` requeue;
IMP-004 stays `[!]` until all IMP-015 acceptance and delivery gates pass.
**Permitted-handoff recovery blocker (2026-09-29):** The required pre-credential
harmless-marker write to the proposed private `/tmp/opencode/` handoff channel was
denied by tool permission. No alternate transport or denied-path read was attempted;
no credentials, stack, browser run, cleanup proof, docs or commit resulted. Grant
explicit access to a private coordinator-readable handoff channel before requeueing;
IMP-004 remains blocked.
**Channel proof and owner-authorized recovery (2026-09-29):** In a fresh manual
`overnight` OpenCode session, the owner temporarily allowed the coordinator's
`edit` tool and retained a narrow external-directory allowance for
`/tmp/opencode/impostr-review-handoff/`. Its file-writing tool created a harmless
`marker.txt` and its `Read` tool returned `MARKER-OK`. This proves that tool
write/read path, **not** synthetic account handoff, authenticated review or
cleanup. The broader `edit` permission can modify any checkout file; keep this
exception to one bounded IMP-015 attempt, preserve IMP-004 and unrelated dirty
work, and restore the original restrictive coordinator edit rule afterward
whether the attempt passes or blocks. Do not widen external-directory access.
The owner explicitly approved one same-ID `[ ]` requeue. Use the permitted
private channel only for generated short-lived Member login and sanitized owned
cleanup status, never owner accounts or privileged data. Still prove two real
authenticated browser runs, reviewer/design sign-off, authorization/session
denials, post-handoff teardown, docs and final checks before an isolated commit
or `[x]`. If any gate fails, record `[!]` with evidence; IMP-004 remains `[!]`.
**Current handoff (2026-09-29):** Two fresh committed-app browser runs, independent
review and operator docs passed; fixture/docs committed locally as `2d71c1b`.
The installed agent's temporary broad edit rule
cannot be restored through this session's permitted external-directory tools.
Owner must restore its restrictive rule before completion; IMP-004 remains blocked.
**Verification-only recovery authorization (2026-09-29):** The owner reports
restoring the installed `overnight` agent's restrictive edit allowlist and
explicitly approves one `[ ]` same-ID verification-only pass. In a **fresh**
agent process, verify the effective rule denies broad checkout edits and permits
only its original planning/outcome files, without printing unrelated config or
credentials. Recheck commit `2d71c1b`, its intended paths and the recorded
real-browser, independent-review and cleanup evidence. Do not redo feature
implementation or treat a commit alone as completion. If the permission and
existing gates hold, the coordinator may record `[x]` for IMP-015; otherwise
record `[!]` with the remaining reason. Do not change IMP-004's `[!]` outcome
in this verification pass; its separate sixth repair still requires readiness
review and all its own acceptance gates. No push or PR.
**Verified outcome (2026-09-29):** Fresh-process edit probe denied a broad
checkout write and allowed only the original planning/outcome paths. Commit
`2d71c1b` contains only the fixture, its tests and operator docs; recorded real
Member browser/designer PASS, 403/401 denials, owned cleanup, independent
APPROVED review and live SIGKILL recovery remain valid. Toolkit recheck passed
82 tests (one gated live test skipped). Local-only; no push or PR. IMP-004
remains blocked pending its own sixth-recovery readiness review and gates.

---

## [-] IMP-022 — Integrate the simplified nested project templates

**Depends on:** IMP-004, IMP-007, IMP-013

Use `overnight-agent/{PROJECT,AGENTS,BACKLOG}.md.example` as inputs for new projects,
as selected by the owner. Preserve existing immutable starter bytes, provenance,
document history and approval records. This is compatibility work, not reopening
completed tasks or accepting partial IMP-009/014 implementation.

### Acceptance
- Source discovery and narrowly allowlisted Docker packaging load exactly the three
  selected inputs; canonical export filenames remain unchanged. No global toolkit
  configuration, credentials or unrelated repository contents enter the API image.
- Trusted legacy and simplified approval profiles retain substantive required
  decisions, starter/placeholder rejection and the existing bounded Markdown evidence
  grammar. Select profiles from immutable starter provenance, never user-selected
  headings or the current installed bundle; unknown/inconsistent profiles fail closed.
  Existing projects remain usable without rewriting their seed revisions/approvals.
- Simplified backlog tasks populate scope, acceptance and verification consistently
  in the editor and approval contract, retaining stable IDs and planning-only markers.
  Prefer concise compatible framing in the selected starter over a permissive parser
  fallback; do not replace root parser semantics with the expanded nested helper.
- Tests and committed/candidate browser snapshot inventories use the selected bundle
  coherently. Changed preview inputs require reviewed exact-input profiles and fresh
  fingerprints; earlier profiles are not approval to preview new template inputs.

### Verification
- Focus on source/packaged discovery, exact seed bytes/digests, legacy/new-profile
  valid approval and missing/undecided/hidden-evidence rejection, starter rejection,
  task extraction/edit preservation, authorization and stale revisions. Use frozen
  legacy fixtures rather than whichever toolkit template happens to be newest.
- Independently review approval/profile interpretation and build/snapshot boundaries.
  Use owned synthetic storage only; prove restart does not rewrite existing projects.
  Check affected Python and helper/fixture tests when those inputs change; no automatic
  full web/API suite or browser infrastructure rebuild for unrelated paths.

**Readiness:** Draft integration plan, not execution approval or a new repair budget.
Fresh API builds currently fail because Docker still copies the deleted root inputs;
redirecting paths alone cannot satisfy the legacy approval schema. Coordinate ordering
with the exact-source IMP-020/021 recovery before implementation; neither its budget
nor its snapshot permission is expanded here. No runner launch, push or installation.

---

## [-] IMP-016 — Prove private HTTPS LAN access

Type: feature
**Depends on:** IMP-001, IMP-003
**Scope:** Permit the one owner to reach the existing same-origin app on this PC
from a phone/another computer through an operator-managed private HTTPS route.
Keep backend, database, model relay and OpenCode worker off browser/LAN ingress;
do not bind raw HTTP publicly as a shortcut.
**Required capabilities:** Operator-selected LAN/VPN reachability, private HTTPS
origin/certificate and trusted proxy/firewall policy, plus a second test device.
None is specified or verified; no network changes are authorized now.

### Done looks like
- Only the approved private HTTPS origin serves authenticated UI/API; exact
  Origin/CSRF, secure session cookies, Host/forwarded-header handling and logout
  work through the trusted route. Unapproved HTTP/origins and direct privileged
  service ingress fail; existing loopback development remains supported.
- Operator instructions state what is actually configured, how to revoke access
  and the limits of one-owner private access. No public or multi-user claim.

### Verification
- Test normal and negative sign-in/CSRF/Host/session cases from an actual phone or
  other computer on the approved private route; confirm no direct DB/worker/
  relay exposure and that streaming still works when chat is integrated. Review
  the rendered phone UI. Do not invent an address, certificate or command.

**Documentation impact:** Verified private-access setup/recovery in the operator
guide; PROJECT.md release boundary once the route is real.
**Decision:** Owner approved this draft first-release LAN scope but defers
network provisioning for now and selected private HTTPS instead of plain HTTP.
Remain `[-]` until actual operator route/certificate and execution checks exist.

---

## [-] IMP-017 — Ingest and privately store project attachments

Type: feature
**Depends on:** IMP-004
**Scope:** Authenticated, project-scoped private media intake, processing and
lifecycle for PNG/JPEG, UTF-8 text/Markdown, selectable-text PDF and text-only
DOCX. IMP-018 binds chosen media to a live conversation; no chat/model inclusion
is delivered by this item.
**Required capabilities:** Private retained storage with synthetic backup/
restore plan and a networkless, resource-bounded processing boundary. Tested
file/turn/page/pixel/storage caps must be chosen before readiness.

### Done looks like
- Opaque attachment IDs and server project authorization protect upload,
  processing status, preview/fetch and deletion. Originals and derived text
  remain private with the project until explicit deletion; IMP-018 records and
  authorizes their conversation usage. Backup/restore includes retained media.
  No original or unsafe active preview enters the public web root.
- Validate bytes as well as type/size, reject traversal, symlinks, active SVG/
  HTML, macros/archives and abusive PDFs/DOCX/images. Extract only bounded
  selectable PDF/DOCX text in a restricted, networkless process. No scanned PDF
  or embedded DOCX-image understanding is claimed; no remote URL fetch.

### Verification
- API/storage tests for cross-project/session IDs, size/type spoofing, parser
  exhaustion and failure cleanup, retained/deleted content, and synthetic
  restore. Independent security review of the processing and data lifecycle;
  no model-media claim from an uploaded filename or successful extraction.

**Documentation impact:** Supported formats, actual measured limits, deletion
semantics and recovery instructions after proof.
**Decision:** Owner approved this draft scope, formats and private retention,
not numeric limits or a verified parser boundary. Not runner-eligible yet.

---

## [-] IMP-018 — Attach verified media to planning chat

Type: feature
**Depends on:** IMP-005, IMP-017
**Scope:** Accessible attachment composer and project-session model handoff.
Only explicitly selected, validated derivatives enter a turn; agent-proposed
Markdown still uses the existing revision/approval rules.
**Required capabilities:** IMP-002's measured OpenCode/relay/model input contract
for actual PNG/JPEG pixels and extracted UTF-8 PDF/DOCX/text. Unsupported
modality or absent live proof is a blocker, not a simulated success.

### Done looks like
- Per-file **Uploading**, **Processing**, **Ready**, **Failed** and retry/remove
  states show type and applicable bounds before send. After send, distinguish
  **Stored** from **Included in this model turn** and **Not included** using the
  real gateway result. Explain text-only PDF/DOCX limitations and that deletion
  cannot retract content already sent to a model.
- Resumed/new-tab chat preserves server-known attachment state and avoids
  duplicate turns on reconnect. Wrong-project/session or deleted attachment IDs
  fail server-side; failed extraction or unsupported model input cannot be
  presented as model-visible content.

### Verification
- Synthetic image question answerable only from pixels, selectable PDF/DOCX/
  text turns, honest failures for scans/embedded images, revoke/delete/reconnect
  and cross-project denial tests against the actual model adapter. Rendered
  keyboard/screen-reader/phone review at 1440/1024/768/375px; independent
  review of media provenance and authorization.

**Documentation impact:** User-visible support/retention/fidelity and provider
handoff limitations; no attachment in the three approved Markdown downloads.
**Decision:** Owner approved this draft first-release media scope and bounded
synthetic model tests, but no actual image/attachment protocol is verified yet.
Remain `[-]` until the model capability and prior slices are real.

---

## [-] IMP-019 — Qualify a later multi-user shared-server release

Type: release-hardening
**Depends on:** IMP-011
**Scope:** Later release qualification for multiple real users and a supported
server deployment, not part of the one-owner personal PR. Preserve the current
application's role/ownership checks; do not interpret the local browser-server
risk exception or a personal LAN smoke as this outcome.
**Required capabilities:** Operator-provisioned intended server, isolation and
relay under its service identity, private TLS/network policy, two disposable
accounts and backup/restore facility.

### Done looks like
- Host-run agent, tenant/session, model-secret and ingress denials; bounded
  resources, dependency/secret checks, backup/recovery runbook and independent
  security review pass on the actual server. Two-user end-to-end private project,
  approvals/chat/attachment/download tests demonstrate no cross-user access.

### Verification
- Perform the full negative/access/recovery drill on the eventual server;
  carry over no unverified proof from this PC. Keep blocked or draft until
  operator setup and a separate owner-approved release plan exist.

**Documentation impact:** Multi-user deployment, operations and residual risks.
**Decision:** Owner wants to envision the complete one-owner app first; this
future item is intentionally `[-]`, not a current blocker or completed gate.
