# Impostr v1 — owner-approved single-branch batch

- Base branch: origin/v1
- Sprint branch: v1
- Work branch: feature/impostr-v1
- Final PR: feature/impostr-v1 → development (human merge)
- Version control: GitHub

## How to use this backlog

Product and security contracts: `PROJECT.md`. Setup, focused checks, selective
review, permissions and Git limits: `AGENTS.md`. Full previous task specifications,
owner decisions and attempt/delivery evidence: [backlog history](docs/backlog-history.md).
The earlier simplification changed no IDs, task order, dependencies, readiness or budgets.
The owner-requested runner preparation below promotes the already approved split
after source proof and applies its approved consumer dependency rewiring.

Markers: `[-]` draft/deferred; `[ ]` owner-approved ready; `[~]` claimed;
`[x]` locally verified and committed; `[!]` blocked. The root parser selects ready
tasks in file order only when all dependencies are `[x]` in the same work branch.
Ready does not mean currently eligible. Human project editors control draft/ready
only, never runner outcomes. These tasks build Impostr, not its users' projects.

This is **single-branch mode**, not sprint mode; the Sprint branch field is retained
for compatibility with the earlier planning baseline. Preserve dirty IMP-009/014,
other existing changes and private logs. No concurrent runner, automatic restart,
new push or merge is authorized by this document edit.

## Current position

- Delivered locally: app/database, login, private projects/drafts, pair approval,
  backlog task API and disposable authenticated browser fixture.
- Approval/download API is locally verified through IMP-020/021 after the preserved
  ten failed attempts. #11 persistence and #12 enforcement passed; #13 was not needed.
  Local commits are not merged release or ordinary-worktree build readiness.
- IMP-014 has partial UI/tests and is now eligible after verified approval; it needs its own
  exact-candidate authenticated rendered review. Existing pass counts are not acceptance.
- Chat is blocked by IMP-002 isolation/relay proof. Media/private HTTPS work remains
  draft. Fresh worktree API builds are broken by root-template deletion; IMP-022
  is blocked pending its explicit integration scope. No chat or release-readiness claim is valid.

**Continuation after stopped-runner repair:** IMP-020/021 are verified local work;
IMP-014 is the sole eligible task. At the next owner-started runner, `overnight`
resumes sole coordination; interactive tech-lead will not implement concurrently.
Use committed approval base `72e37e9` (or verify any later changed head). Build/review
the exact IMP-014 candidate profile first; no earlier fingerprints, API-only harness
templates or committed-but-unaccepted UI alone establish its preview/rendered safety.
Other blockers retain their recorded unmet prerequisites. No automatic restart,
new template integration, network provisioning or attachment limits are implied.

## [x] IMP-001 — Bootstrap app and database baseline

**Depends on:** None

Delivered frontend/API/PostgreSQL/Nginx skeleton, Alembic baseline and pinned local
setup/checks. Verified local commit `af0c9e7`; bootstrap, restart and recovery passed.
Commands and environment limits are in `docs/local-development.md` and `AGENTS.md`.
No shared-server release or Python dependency audit claimed.

## [!] IMP-002 — Prove safe OpenCode web-session integration

**Depends on:** IMP-001
**Scope:** Prove project-scoped `tech-lead` sessions and fail-closed worker isolation
before exposing a product-agent gateway.

### Acceptance

- A pinned integration starts/resumes, streams, handles questions/permissions,
  imports proposals and documents reconnect/error behavior.
- Per-project workers cannot access siblings, host home/secrets, Docker/DB sockets
  or unintended network destinations. Relay/isolation failure denies chat; no host fallback.

### Verification and next step

Use adapter tests plus bounded synthetic live sessions and child-tool denial tests
under the actual launcher identity. Owner chose `bwrap`-first workers with a trusted
host model-only relay; host OpenCode auth stays outside worker/repo/DB/browser/logs.
Establish actual safe setup before asking the owner for operator actions.

**Blocker:** CLI/agents available; `bwrap` 0.6.1 bare namespace smoke passed, but no
relay, secret-safe channel, usable isolated worker or live protocol/denial proof.
Owner permits independently eligible human-only development, not unconfined product
agents. The runner's optional `sbx` copies host auth and can fall back to host execution;
it is not this boundary. Keep blocked until revised readiness is explicitly approved.

## [x] IMP-003 — Admin-provisioned login and private project access

**Depends on:** IMP-001

Delivered offline admin bootstrap/recovery, no-signup login/logout, admin user
management, expiring/revocable sessions, CSRF/rate controls and private-project
authorization. Verified local commit `e4558ae`; API, PostgreSQL, web, toolkit and
browser checks passed. TLS/proxy, agent isolation, restore and audit remain release work.

## [x] IMP-004 — Seed projects and versioned Markdown drafts

**Depends on:** IMP-001, IMP-003, IMP-015

Delivered private project creation, immutable starter provenance and three DB-backed
Markdown drafts with expected-revision/conflict/history behavior. No repo initialization
or runner launch. Local commit `60e9480`, after six implementation attempts and a
rendered-review retry; prior findings/authorizations remain in history.

Independent review APPROVED. Exact candidate `a7675f6d…168737c0`, migration `0004`,
normal synthetic Member browser/designer PASS at 1440/1024/768/375, cross-Member
denial and owned cleanup passed. API 51/9 skipped, PostgreSQL 9, web 35 and toolkit
98/1 skipped plus applicable static/build checks passed. Existing starter provenance
remains immutable; selected-template integration is IMP-022.

## [ ] IMP-005 — Project-scoped resumable planning chats

**Depends on:** IMP-002, IMP-004
**Scope:** Authenticated `tech-lead` gateway and project session tabs; proposals
become versioned drafts, never approvals.

### Acceptance

- Open last-used chat, create tabs, stream/resume after restart/reconnect and answer
  questions under a bounded, default-deny permission policy.
- Session boundaries and serialized file-writing turns preserve human revisions;
  errors/timeouts preserve chat and draft text.

### Verification

Adapter/browser reconnect, forged cross-user session/event/reply denials, concurrent
edits and timeout preservation. Requires IMP-002's proven transport/isolation.

## [ ] IMP-006 — Integrate chat with first-stage document review

**Depends on:** IMP-005, IMP-013
**Scope:** Add chat/proposals beside the delivered human pair-review surface.

### Acceptance

- Proposed revisions cannot overwrite newer human edits or silently invalidate/approve
  them. Chat, questions, review and approval work together during conflicts/reconnect.
- Desktop/narrow layouts remain accessible during streaming and approval-pending states.

### Verification

Proposal/human-revision/approval races and authorization; authenticated rendered
chat/review spot-checks at 1440/1024/768/375, keyboard, contrast and reduced motion.
Reuse IMP-013 approval evidence; do not count its delivered UI again.

## [x] IMP-007 — Validate and edit runner-compatible backlog

**Depends on:** IMP-004, IMP-013

Delivered parser-compatible task API and draft/ready edits with unique IDs,
dependency validation, stale-revision handling and preservation of surrounding
Markdown/runner metadata. Root `scripts/backlog.py` remains the compatibility oracle;
no runner outcome management or live-agent integration.

Verified local commit `e2cabfd`. Independent review APPROVED; API 177/11 skipped,
PostgreSQL migration `0005`/11 tests, web 62, toolkit 128/1 skipped and applicable
checks passed. Exact candidate `a2621b7…d4a2e` passed synthetic authenticated
rendering/designer review, authorization denials and owned cleanup. Interrupted work,
boundary/metadata repair findings and candidate authorizations remain in history.

## [ ] IMP-008 — Integrate live chat with backlog planning layout

**Depends on:** IMP-005, IMP-006, IMP-014
**Scope:** Add chat and agent-added/updated task indicators beside IMP-014's rail.

### Acceptance

- Agent updates preserve active composer/manual edits; conflicts explain the saved
  version without dropping text. Direct-edit and readiness controls keep working.
- Empty, dependency-waiting, saving, streaming, validation and disconnect states
  remain usable on desktop/narrow screens without overflow.

### Verification

Updates during edits, focus/screen-reader states and authenticated rendered chat/rail
review. Reuse IMP-014's direct-edit/collapse/status checks, not duplicate delivery.

## [-] IMP-009 — Approve backlog and serve immutable downloads

**Depends on:** IMP-013, IMP-007
**Scope:** Human final backlog approval and immutable manifest/downloads for exactly
the approved PROJECT.md, AGENTS.md and BACKLOG.md tuple; no repo writes/draft downloads.

### Acceptance

- Only valid current revisions can be approved after pair approval. Changed members
  invalidate final handoff; placeholders/incomplete task evidence cannot be approved.
- Downloads enforce current approval/authorization and exact bytes/UTF-8 filenames;
  stale, draft and foreign revisions fail. Actor/time and manifest are recorded.

### Verification

Actual invalid/valid approval HTTP, status/audit/download invariants, access denials,
stale revisions, save races and deterministic bytes. Remaining work is specified in
IMP-020/021; no split task is complete merely because its label changed.

**Latest blocker:** Ten substantive attempts exhausted. A read-only synthetic HTTP
probe confirmed all six checked/unchecked metadata cases can supply absent Scope,
Acceptance or Verification, wrongly returning approval 200, creating a manifest and
enabling all three downloads. Passing intermediate tests do not waive this bypass.
Dirty API/model/migration/tests remain; HEAD `e2cabfd`, no delivery commit.

**Recovery history:** Initial #1–3; additional #4–6; structural #7–8; interactive
#9–10. Findings and exact authorizations/results are preserved in history. Owner
approved replacements with shared #11–13 budget, not a reset. Superseded by IMP-020
and IMP-021 after verified source preparation below. This is not completion: ten
failed attempts and partial work remain history; never mark `[x]` from splitting.

## [x] IMP-020 — Verify inert three-document manifest persistence

**Depends on:** IMP-013
**Scope:** Verify preserved manifest ORM/migration without registering final-approval,
status or download routes. Preserve `20260930_0006` and parent `20260929_0005`.

### Acceptance

- Fresh/populated-0005 upgrade and disposable downgrade/re-upgrade preserve pair
  approvals/history; no final-approval backfill. ORM/schema agree and PostgreSQL
  verifies pair-snapshot composite FK and uniqueness, including invalid inserts.
- Existing auth/drafts/task edits/pair approval still work on the standalone slice;
  final approval/download routes remain unavailable.
- Revision existence is not project/kind authorization; IMP-021 enforces locked
  authorized heads. Persistence alone does not unblock IMP-014 or deliver downloads.

### Verification and boundaries

Independent review against `e2cabfd`, exact standalone-source mapping, fresh owned
PostgreSQL migration/preservation/constraint checks, relevant existing API behavior
and changed-Python static checks. Toolkit tests only for helper/fixture changes;
record actual snapshot commands once proved and verify owned cleanup.

Owned paths: `api/app/models.py`, migration
`api/migrations/versions/20260930_0006_project_approval_manifests.py`,
`api/tests/test_migrations.py`, `api/tests/test_postgres_integration.py`, and proposed
`api/tests/test_project_approval_manifest_schema_postgres.py`. Leave main.py route
activation, approval module and HTTP/concurrency tests for IMP-021. Document schema,
no backfill and disposable downgrade limits after delivery; task commit precedes `[x]`.

**Authorization:** Owner approved “Yes, finish it”: initially direct tech-lead coordination,
senior implementation, separate review, bounded non-serving `/tmp/opencode/` snapshot,
disposable DB checks and selective local commits. Shared #11–13 ceiling: at most one
persistence/test-hardening and two enforcement attempts. New expectations/schema/logic
consume attempts; packaging/formatting/reruns/docs/delivery do not. No unrelated work,
push/PR/merge/deploy, real data, installation, new browser profile or runner restart.

**Runner handoff (owner requested preparation):** `overnight` is the sole execution
coordinator for the next root-runner batch; tech-lead stops interactive implementation
coordination before launch. Delegate implementation to senior-developer and independent
review to reviewer. Local task/bookkeeping commits and bounded owned DB/source setup
remain authorized; no task push/PR, merge, deployment or installation. No concurrent
writer. Root helper assigns one eligible item per session; preserve cumulative attempts
across sessions, at most one persistence/test-hardening attempt and two enforcement
attempts (#11–13 total). Other ready items retain their actual prerequisites/gates.

**Verified preparation, not acceptance:** Coordinator pinned branch `feature/impostr-v1`
at full baseline `e2cabfdc42f6a6a84ea0dcb85cdbd36f0927dccf`. Allowed helper
`/tmp/opencode/impostr-imp020-prereq-20260930/prepare_snapshot.py` (SHA-256
`5602f458a203e6c33f1246a0ba4e7507f0dd8e59c7f5471da9861a8f5844bd02`)
ran `inventory`, then `prepare --summary` and `verify --summary` with full HEAD,
archive SHA-256 and four coordinator-measured overlay SHA-256 pins. Both source
operations returned `exact-source-bytes-match`; no app/DB tests or #11 logic attempt.
Independent in-repo preparation review returned READY FOR EXECUTION, not final acceptance.

- Owned archive: `/tmp/opencode/impostr-imp020-prereq-20260930/baseline.tar`, SHA-256
  `f3960928a0ccc991bdd4205df0a725702a560c5a5e987bc9bf9e549583a59ec8`;
  generated by coordinator's `git archive --format=tar --output=<archive> <full HEAD>`
  with exactly the 57 paths emitted by helper `inventory` (not a full repo archive).
- Read-only `baseline/` and `frozen/` trees under that same directory contain 57 and
  58 files. Frozen inventory SHA-256:
  `6b461659415bc2ec45928de9c9a9ebaf61a2431e153fe109c592554c527b8cb5`.
- `--overlay-sha256` pins for that initial snapshot:
  `api/app/models.py=55830d86896d600807ad0a831ddc190ae82d96d71508e0e918809528f32f8d0c`;
  `api/migrations/versions/20260930_0006_project_approval_manifests.py=88ee12bb30817f57d37c2b54bade9c2ff1bf2ccc41e0cec99ee04199dbb54433`;
  `api/tests/test_migrations.py=e13ca8859d4b0f374db355f3c27dbee1e8ed96e577d165c157d3f6c9727c7ead`;
  `api/tests/test_postgres_integration.py=8428b357a3a8f266b41ca7c92be18157d8fc0c61c2b3c42fdc1d14a1194b352a`.

This is API-only source proof: Compose/DB inputs are not included/pinned. During
execution, pin the necessary committed Compose/DB build inputs separately and prepare
the owned non-serving check setup; do not build the dirty checkout or copy its `.env`.
The proposed new persistence PostgreSQL test is execution work; include it and any
changed task input in refreshed exact-source proof before checks/delivery. The initial
helper is exclusive/no-overwrite and accepts only four overlays; it is not an
unchanging universal profile for future inputs. Preserve earlier artifacts, reconcile
any expanded task-test inventory, and record new actual hashes rather than reuse old ones.

Reviewer reads assigned in-repo code/tests only; the denied temporary marker remains
off limits. Coordinator owns actual baseline/overlay/frozen-byte mapping and sanitized
checks. Do not forward denied contents or bypass the denial. If source mapping or
essential checks cannot be performed through permitted tools, stop with that blocker.

Historical templates may remain **inside the committed-baseline snapshot only**;
do not restore deleted root files or adopt new templates. This allows baseline-scoped
checks without IMP-022, but current-worktree builds/release remain broken.

**Execution blocker (2026-09-30):** Actual branch HEAD is `e2412b1`, whose owner
commit includes formerly partial IMP-009/014 code, including the final-router import
and registration in `api/app/main.py`. Senior reconciliation and independent reviewer
confirm that this violates IMP-020's route-unavailability acceptance; testing only
`e2cabfd` plus persistence overlays cannot establish an inert current branch.
There is no repair within IMP-020's owned paths. Owner authorization is needed for
a narrow forward change deferring those two `main.py` additions to IMP-021 while
preserving all other code. No application changes, DB/app tests or new snapshots
were made; #11–13 remain unused. Existing source artifacts and code are preserved;
IMP-021 remains dependency-blocked. Affected-docs assessment found no delivered
schema behavior to document yet. No push/PR, merge, deployment or runner restart.

**Verified repair/delivery:** Owner requested checking/fixing the stopped runner.
The coordinator delegated the narrow forward route deferral plus persistence checks;
no history rewrite or discarded code. Local commit `d556043` removes only final-router
activation, adds inert HTTP and PostgreSQL schema/preservation regressions, and records
operating limits. The preserved approval module/UI remain for their owning items.
#11 consumed for persistence/test hardening; #12–13 remain for enforcement.
Failing-before HTTP returned 200 instead of 404; repaired candidate passed 110 focused
API tests plus Ruff/format/mypy, fresh PostgreSQL migration, 11 existing integration
tests and 2 schema/preservation/constraint tests with owned cleanup. Independent
in-repo review APPROVED; coordinator reverified exact current-source mapping
`8bd133696732496c567093e11a57bd2dab2de61ade1dde22d69b9873c7de4529` using
`check_current.py verify` (helper SHA-256
`731ff1767dbd95da32f48125eebe03518ca9a6cebe1be580f158fbd3d401e2c9`).
Legacy templates are harness-only, not restored or integrated. Initial schema setup
needed the generated disposable owner role; final owned check passed without widening
app-role grants. Historical runner blocker above is resolved, not erased. No push/restart.

## [x] IMP-021 — Enforce valid approval and immutable three-file downloads

**Depends on:** IMP-020, IMP-007
**Scope:** Finish preserved validation/approval/status/download code as one contract;
fix checkbox normalization, not shared parsers, pair approval, UI or a new architecture.

### Acceptance

- Checked/unchecked canonical metadata cannot supply absent Scope/Acceptance/Verification.
  Boundary/evidence normalization agree without literal-string exceptions. Genuine
  checkbox/multiline/colon/list/table evidence, completed headings, masked examples
  and draft saves still work.
- Invalid current approval returns `422`, stays unapproved, creates no manifest or
  success audit, revision/head change/conflict proposal; all downloads return `409`.
  Required rate-limit writes/admin-access audits remain allowed.
- Invalid existing manifests fail closed on status, idempotent POST and every download.
  Preserve current-pair/exact-backlog preconditions, stale `409`, identical-byte-save
  invalidation, duplicate approval idempotence and one success audit.
- Exact tuple bytes/canonical filenames, account/session/project/CSRF/Origin checks,
  changed-access/foreign/history denials, transaction/commit-failure safety and
  PostgreSQL approval/save concurrency hold. No UI/chat/release completion claim.

### Verification and next step

Actual save → pair approval → invalid final approval → status/persistence/download
denials, positive repeated bytes/hash/filename and relevant regressions. Independent
review covers combined IMP-020/021 material from `e2cabfd`; run focused API/static
checks and fresh owned PostgreSQL `0006`/schema/concurrency checks with cleanup.
Toolkit checks only if helpers/fixtures change; earlier skipped tests are not acceptance.

Owned paths: `api/app/project_approval_manifests.py`, `api/app/main.py`,
`api/tests/test_project_approval_manifests.py`,
`api/tests/test_project_approval_manifests_postgres.py`, and affected local-development
docs after stabilization. Reconcile out-of-scope changes, do not assume extra budget.
Update durable PROJECT.md/AGENTS.md claims only after selective verified local delivery.

**Readiness:** Ready under IMP-020's runner handoff/shared limits, but waits for
committed IMP-020 and its own refreshed exact integrated source proof. At most two enforcement attempts within #11–13;
exhaustion, missing capability or changed scope stops work.
**Consumer rewiring:** IMP-010/011 and IMP-014's execution-only base gate now depend
on IMP-021. Preserve IMP-014's entire candidate-review contract.

**Verified repair/delivery:** Local code/affected-doc commit `2e7a0e9` after committed
IMP-020. #12 fixed shared checkbox framing normalization for metadata boundaries and
substantive evidence; #13 unused. Restored only the two router lines after enforcement
passed and updated the prior inert-route regression to require current valid approval.
Before repair, 12 metadata-only HTTP cases failed while 3 valid controls passed;
after repair, 384 focused API tests plus Ruff/format/mypy passed. Fresh owned PostgreSQL
upgrade `0006`, 12 integration tests including concurrent approval/save, and 2 schema/
preservation/constraint tests passed; containers/volumes/networks cleanup verified.
Independent combined IMP-020/021 in-repo review APPROVED; coordinator exact current
API/Compose/DB byte verification passed with source-map SHA-256
`67194881602d79a1a93c193227e35d5bb4b8267dd3f90605e2b7fe8b63a33b02` via local
`check_imp021_12.py verify` (helper SHA-256
`3bfb80848ec567db63ab849e2ee86877b07959774a8bc1321bb7faf38009d331`).
Historical templates stayed harness-only: ordinary worktree build/template adoption
remain unresolved. No chat, UI/rendered acceptance, release, push or runner restart.

## [ ] IMP-010 — Three-file final review experience

**Depends on:** IMP-014, IMP-021
**Scope:** Stage 3 version/status overview: three simultaneous desktop panes and
accessible narrow-screen review/download flow.

### Acceptance

- Compare three approved revisions, distinguish readiness/approval and download
  individually. Changes disable downloads with a clear return-to-review path.
- Narrow navigation preserves position/focus and readable text; no hidden controls
  or horizontal overflow.

### Verification

Authenticated approve → edit-invalidates → reapprove → download browser flow;
rendered desktop/narrow, keyboard, contrast and reduced-motion review. Update user guide.

## [-] IMP-011 — One-owner private-access release and recovery acceptance

**Depends on:** IMP-003, IMP-005, IMP-008, IMP-021, IMP-010, IMP-016, IMP-018
**Scope:** Full planning/chat/media/approval/download flow on this PC for one owner
through verified private HTTPS; not multi-user server qualification.

### Acceptance

- PC and real phone/other-device walkthrough covers private projects, resumed/new-tab
  chat, actual image/text/PDF/DOCX model inclusion, approvals/conflicts and exact downloads.
- Restart and synthetic DB/media restore preserve history/content. Private HTTPS,
  Origin/CSRF, worker/model limits, upload abuse/authorization denials, dependency/secret
  checks and operator runbook pass. Missing release capability blocks release.

### Verification and readiness

Delivered-revision app/integration/browser/security checks, independent security and
design sign-off, two synthetic accounts/projects for denials, restore and agent failure/
escape drills, and actual remote-device HTTPS smoke. Never expose DB/Docker/worker/relay.
Owner approved draft scope only; route/certificate/proxy commands and restore procedure
are unverified. Fix owning slices rather than replacing their acceptance here.

## [ ] IMP-012 — Verify work branch and open single development PR

Type: release-finalization
**Depends on:** IMP-011
**Scope:** Verify integrated one-owner release and deliver one review-ready GitHub PR.

### Acceptance and verification

All intended features are verified/committed in `feature/impostr-v1` (or explicitly
removed by owner); inspect full branch and run release checks on that exact head.
A moved head requires retest; blocked prerequisites are not delivered. Only authorized
finalization may push the checked feature branch, verify published head and open/reuse
the PR to `development`. Record URL/content; humans merge. Auth/write capability is
not proved (latest GitHub read returned 401); failures preserve local work and block
delivery. No `v1` implementation/push, force-push or automated merge.

## [x] IMP-013 — Human-only first-stage document review and pair approval

**Depends on:** IMP-004

Delivered direct PROJECT.md/AGENTS.md review/edit/diff and atomic current-pair approval,
authorization, invalidation and stale-conflict protection. Required decisions use
bounded substantive Markdown evidence, not code/comments/raw HTML. Original stale pair
is preserved and displayed saved heads advance monotonically; unsaved text is retained.

Verified local commit `888e53c` (bookkeeping `31d0f8f`). Independent code/evidence review
APPROVED; exact candidate `9afbbc5e…859b6`, fresh `0005`, PostgreSQL 10, API 81/10
skipped, web 60, toolkit 116/1 skipped plus checks, synthetic Member viewport/two-tab
conflict review and owned cleanup passed. Failed recoveries and settled evidence-rule
decisions remain in history. Human-only intermediate slice, not IMP-006 chat or release.

## [ ] IMP-014 — Human-only collapsible backlog planning layout

**Depends on:** IMP-007, IMP-013, IMP-021
**Scope:** Direct task rail, title/body/dependency edits, draft/ready toggles and
conflicts; no chat or agent-update delivery.
**Execution ordering:** IMP-021 is a committed candidate-base prerequisite, not a
product dependency. Never include its unresolved dirty approval code in preview.

### Acceptance

- Rail/document agree at saved revision; conflicts retain edits and cannot synthesize
  execution outcomes. Collapsible desktop/narrow keyboard layouts handle empty,
  saving, invalid and readiness states. IMP-008 retains live-agent integration.
- Reviewed exact-input profile, pinned preflight, normal generated Member sign-in,
  authenticated rendered interaction/designer sign-off, denials and owned cleanup pass.

### Verification and next step

After the verified approval commit, reconcile full dirty diff and build/review a
profile over that actual committed base. Approved inventory: runtime
`web/src/{App,ProjectWorkspace,BacklogPlanning}.tsx`; corresponding `.test.tsx` files;
host fixture `scripts/local_browser_fixture.py` and `scripts/test_local_browser_fixture.py`.
Retain size/path/secret/fingerprint/cleanup guards. Changed inputs require fresh
preflight/rendering at 1440/1024/768/375 and keyboard/focus review; old profiles/HEAD
are not evidence. Unprovable profile blocks, never waives rendering.

Focused web editing/readiness/conflict/navigation checks, helper tests for fixture
changes, API only for affected behavior; selective independent UI/fixture review,
useful docs and verified local commit before `[x]`.
**Checkpoint:** Dirty UI/tests passed 71 web tests plus checks; code re-review found
no remaining defect but was INCOMPLETE without rendering. Owner approved profile
extension and up to three additional substantive attempts; profile not yet built.
Keep ready but waiting. No push/PR, runner restart or chat claim.

## [!] IMP-022 — Integrate the simplified nested project templates

**Depends on:** IMP-004, IMP-007, IMP-013
**Scope:** Adopt owner-selected `overnight-agent/{PROJECT,AGENTS,BACKLOG}.md.example`
for new projects without changing existing immutable starters/history/approvals.

### Acceptance

- Discovery/narrow Docker packaging loads exactly those inputs; canonical export
  filenames stay unchanged. No unrelated toolkit config/credentials enter images.
- Legacy/new approval profiles enforce substantive decisions, placeholder rejection
  and bounded Markdown evidence. Select by immutable provenance, not user headings
  or installed bundle; unknown/inconsistent profiles fail closed, existing seeds stay intact.
- Simplified scope/acceptance/verification work consistently in task editor/approval,
  preserving IDs/planning markers and root parser semantics. Snapshot inventories
  require coherent reviewed inputs/fresh fingerprints, not old-profile reuse.

### Verification and readiness

Discovery/packaging, exact seeds/digests, frozen legacy/new valid and missing/undecided/
hidden-evidence rejection, edit preservation, authorization/stale revisions and
restart preservation. Independent profile/build-boundary review; focused Python/helper
checks on owned synthetic storage. Draft only: owner deferred execution for approval
work first. Root deletion breaks fresh API builds; path redirection alone is insufficient.
Coordinate with IMP-020/021 without expanding its budget/permissions or restoring roots.

**Execution blocker (2026-09-30):** Runner claim does not override the explicit owner
deferral above and in AGENTS.md. Read-only reconciliation at `4b72ead` confirms discovery,
Docker packaging, approval profiles and snapshot inventories still use legacy inputs;
IMP-022 is not already delivered. Owner must explicitly authorize template integration
despite the unfinished approval work (IMP-020 blocked, IMP-021 waiting). No application
changes, build/DB checks or recovery attempts; existing code and runner logs preserved.
Only backlog/session bookkeeping is delivered locally; no push/PR or runner restart.

## [!] IMP-016 — Prove private HTTPS LAN access

**Depends on:** IMP-001, IMP-003
**Scope:** One-owner phone/other-PC access through operator-managed private HTTPS;
keep DB/backend/worker/relay off LAN ingress, no public raw-HTTP shortcut.

### Acceptance and verification

Approved same-origin auth/API, secure cookies, Origin/CSRF, Host/forwarded-header and
logout work; unapproved origins/HTTP/privileged ingress fail and loopback dev remains.
Test real-device positive/negative access, phone layout and eventual chat streaming;
document actual setup/revocation. Draft scope approved, provisioning deferred. No
verified origin/certificate/proxy/firewall route or network-change authorization.

**Execution blocker (2026-09-30):** At `00673df`, read-only reconciliation confirms
the front door remains loopback HTTP, with no delivered private HTTPS/device proof.
Runner assignment does not authorize the expressly deferred provisioning. Operator
must choose and provision/authorize the origin, certificate, proxy trust and network
restrictions, and provide a real test device before execution. Existing local docs
already state this gate; no setup/revocation procedure is invented. No application,
network or credential changes, live tests or substantive attempts; local outcome
bookkeeping only. Preserve all existing code/logs; no push/PR or runner restart.

## [!] IMP-017 — Ingest and privately store project attachments

**Depends on:** IMP-004
**Scope:** Private project PNG/JPEG, UTF-8 text/Markdown, selectable-text PDF and
text-only DOCX intake/storage/processing; model inclusion belongs to IMP-018.

### Acceptance and verification

Opaque IDs/server auth protect upload/status/fetch/delete. Retain originals/derived
text privately until deletion and include media in synthetic restore. Validate bytes/
types and bounded sizes; reject traversal/symlinks/active content/macros/archives and
parser abuse. Restricted networkless resource-bounded extraction only; no remote fetch,
scanned-PDF or DOCX-image understanding. Test cross-project/session denial, spoofing,
exhaustion/failure cleanup, retention/deletion/restore; independently review lifecycle.
Draft scope/retention approved; numeric file/turn/page/pixel/storage caps and processing
boundary must be measured/chosen before readiness. Upload success is not model proof.

**Execution blocker (2026-09-30):** At `a35a676`, developer read-only reconciliation
confirms committed IMP-004, but no attachment intake/lifecycle, measured approved
file/turn/page/pixel/storage caps or restricted networkless resource-bounded extractor.
Runner assignment does not waive this explicit readiness prerequisite. Owner must
approve measurement/design work and the resulting limits and processing boundary
before execution; existing Markdown/cache limits and internal Compose networking
are not attachment evidence. Existing project/local docs already state the planned
boundary; no caps, parser, storage or recovery procedure is invented. No application,
dependency or live-test changes or substantive implementation attempts; preserve all
existing code/logs. Local outcome bookkeeping only, no push/PR or runner restart.

## [ ] IMP-018 — Attach verified media to planning chat

**Depends on:** IMP-005, IMP-017
**Scope:** Accessible composer and authorized session/model handoff of selected,
validated media under IMP-002's measured input contract.

### Acceptance and verification

Show uploading/processing/ready/failed, retry/remove and bounds; distinguish stored
from actually included/not included using real gateway results. Explain text-only
PDF/DOCX limits and irreversible prior model sends. Resume/reconnect preserves server
state without duplicate turns; deleted/foreign IDs and unsupported inputs fail honestly.
Prove synthetic pixel-only questions and extracted PDF/DOCX/text live turns, scan/
embedded-image failures, delete/revoke/reconnect/authorization, and rendered accessible
desktop/phone review. No media in Markdown downloads. Draft scope/synthetic tests
approved, but no actual image/attachment model transport is verified yet.

## [ ] IMP-019 — Qualify a later multi-user shared-server release

Type: release-hardening
**Depends on:** IMP-011
**Scope:** Later real-user/server qualification, not this personal-release PR.

### Acceptance and verification

On the actual provisioned server/service identity, prove worker/tenant/session/model-
secret/ingress denials, bounded resources, dependency/secret checks, synthetic restore,
runbook and independent security review. Two-user private project/chat/media/approval/
download end-to-end denials must pass. Preserve role/ownership rules; local browser
risk acceptance and LAN smoke are not server proof. Deferred until separate owner
release approval, actual server/TLS/relay/isolation and recovery resources exist.
