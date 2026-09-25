# Impostr v1 — owner-approved single-branch batch

- Base branch: origin/v1
- Sprint branch: v1
- Work branch: feature/impostr-v1 (create after approved plan is published)
- Final PR: feature/impostr-v1 → development (human merge)
- Version control: GitHub

Canonical scope/contracts: `PROJECT.md`; execution/check policy: `AGENTS.md`.
The owner approved all 12 slices and one final merge. This workflow transition
and its `[ ]` markers must be published before running; dependency eligibility
and real checks still gate work. The `Sprint branch` field retains the declared
planning-publication target from the previous workflow; the new runner uses the
work branch and does not select sprint mode. Permanent IDs and
`## [state] ID — Title` headings follow the root helper's format.
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
the evidence to establish during implementation. No runner assignments exist yet.
Queueing every item does not guarantee overnight completion: actual checks,
isolation and operator inputs remain gates at the relevant item.

---

## [ ] IMP-001 — Bootstrap app and database baseline

Type: feature
**Depends on:** None
**Scope:** Impostr frontend/API skeleton, PostgreSQL Docker service, Nginx routing,
Alembic migration baseline and reproducible development checks; do not add project
or OpenCode behavior yet.
**Required capabilities:** Operator-provisioned Docker/Compose on a development
host (unavailable in this shell); pinned Python/Node dependencies.

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

---

## [ ] IMP-002 — Prove safe OpenCode web-session integration

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

---

## [ ] IMP-003 — Admin-provisioned login and private project access

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

---

## [ ] IMP-004 — Seed projects and versioned Markdown drafts

Type: feature
**Depends on:** IMP-001, IMP-003
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

## [ ] IMP-006 — Review and jointly approve first two documents

Type: feature
**Depends on:** IMP-004, IMP-005
**Scope:** Stage-aware dark UI for chat beside PROJECT.md/AGENTS.md, direct Markdown
review/edit and API for atomic, human-initiated version-bound pair approval.
**Required capabilities:** Rendered browser review with `ui-designer`.

### Done looks like
- User sees clear revision/diff/unsaved status for each file, can ask `tech-lead`
  for changes, and approves the exact pair only after invalid starter placeholders
  and unresolved setup notes are removed. Later edits invalidate the prior pair
  approval; an agent message can never approve it.
- Stage 1 supports desktop and narrow layouts, keyboard-only review/approval and
  meaningful saving, streaming, conflict, error and approval-pending states.

### Verification
- Approval transaction/stale-revision/unauthorized tests; rendered checks around
  1440/1024/768/375px, keyboard, contrast and reduced motion.

**Documentation impact:** User guide for project setup at stable UI batch end.
**Open decisions:** Final design tokens follow `ui-designer` review; product behavior
is specified in PROJECT.md.

---

## [ ] IMP-007 — Validate and edit runner-compatible backlog

Type: feature
**Depends on:** IMP-004, IMP-006
**Scope:** Backlog document API, parser-compatible task model, direct task edits
and human-only `[-]`/`[ ]` readiness transitions; no runner outcome management.
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

---

## [ ] IMP-008 — Live chat and collapsible backlog planning layout

Type: feature
**Depends on:** IMP-005, IMP-006, IMP-007
**Scope:** Stage 2 UI: standard chat next to collapsible task rail with on-row
draft/ready toggles, expand/edit task detail, and live agent-change indicators.
**Required capabilities:** Rendered browser review with `ui-designer`.

### Done looks like
- Agent-added/updated tasks appear without losing the active chat composer or
  direct edit; user can collapse the list, expand a task, change its title/body,
  and toggle only draft/ready on the row. Conflict explains which version won
  without dropping unsaved text.
- Empty, waiting-on-dependencies, saving, streaming, validation and disconnect
  states remain usable on desktop and narrow screens; no horizontal overflow at
  the agreed viewport fixtures.

### Verification
- Browser interaction tests for agent update/direct edit/status toggle/collapse,
  focus order and screen-reader states; rendered desktop/mobile design review.

**Documentation impact:** Stage 2 task-list guidance with IMP-006 UI batch.
**Open decisions:** None for state authority; only the owner decides task readiness.

---

## [ ] IMP-009 — Approve backlog and serve immutable downloads

Type: feature
**Depends on:** IMP-006, IMP-007
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

---

## [ ] IMP-010 — Three-file final review experience

Type: feature
**Depends on:** IMP-008, IMP-009
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

## [ ] IMP-011 — Shared-server security and recovery acceptance

Type: feature
**Depends on:** IMP-003, IMP-005, IMP-008, IMP-009, IMP-010
**Scope:** Integrated release verification, independent security/design review,
backups/restore, operational documentation and gates; fix defects in owning slices
or track them explicitly rather than treating this as a substitute for unit checks.
**Required capabilities:** Private TLS-capable deployment host, container runtime,
isolated OpenCode model access, two provisioned test accounts and browser tools.

### Done looks like
- Two-user walkthrough covers private projects, admin provisioning, resume/new
  session tabs, pair/backlog approval, editing/conflict states and byte-identical
  approved downloads; no cross-user access or host credential leakage.
- Restart and restore retain revision/approval/chat history; negative security
  tests, real OpenCode isolation evidence, dependency/secret checks and operator
  runbook pass, or each unavailable gate is explicitly blocked before release.

### Verification
- Run recorded app/unit/integration/browser/security checks on delivered revision,
  independent reviewer and `ui-designer` sign-off, backup/restore drill and an
  operator-led smoke on the private server.

**Documentation impact:** Final operations, recovery and user guides for the
stable release; do not store secrets or private chat in reports.
**Open decisions:** Operator must provision deployment host, credentials, TLS and
agreed security tooling; release cannot be called ready until these are tested.

---

## [ ] IMP-012 — Verify work branch and open single development PR

Type: release-finalization
**Depends on:** IMP-011
**Scope:** Integrated checks and the one GitHub PR from `feature/impostr-v1` to
`development`; no implementation on `v1` and no automated merge.
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
