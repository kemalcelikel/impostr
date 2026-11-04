# Impostr — backlog

IMP-030 through IMP-036 preserve the implemented, checked and locally refreshed
frontend candidate. The owner has rejected its visible design; functional checks do
not establish owner design acceptance. Preserve the candidate, markers and history;
the rejection/checkpoint is recorded with IMP-036. IMP-037 through IMP-041 are now
approved for interactive corrective implementation. The first checkpoint is an actual
workbench preview for owner assessment before broad app changes. Preserve the existing
candidate and functionality. The owner authorized a local checkpoint commit of the
work completed so far; no runner, branch change or publication is authorized.

## [!] IMP-002 — Prove safe OpenCode web-session integration

**Depends on:** None
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

**Owner-authorized next repair (2026-10-01):** The latest batch at `d74ee13`
finished IMP-014/010 and stopped normally with zero eligible tasks. Owner selected
**Fix chat safety first**, authorizing interactive tech-lead coordination, senior
implementation and three new focused substantive attempts for a non-serving local
worker/model-relay prototype. Preserve prior history and blocked marker; this is
not authorization to claim full IMP-002 acceptance from a prototype or restart the
runner automatically. No product gateway, installs, credential disclosure, host
fallback, network exposure, push/PR or unrelated HTTPS/attachment implementation.

Start with actual non-root launcher identity, pinned OpenCode/bwrap dependencies,
isolated configuration and available aggregate memory/process/CPU/scratch controls.
Use synthetic workspace/home/sibling/socket canaries, never real secret/DB/Docker
probes. Missing enforceable controls stop child-tool/live execution. Proposed boundary:
private worker network, a local shim through a per-run Unix socket to a trusted
fixed-upstream model-only relay; no host OpenCode server proxy or copied auth.
Exact routes/protocol/settings must be measured before implementation claims.
Focused denial/failure, configuration-injection, bounded relay/stream/cancellation
checks and independent boundary review precede any short synthetic live session.
The reviewed relay alone uses an operator-managed existing credential channel;
unknown auth or upstream metadata is an operator checkpoint, not permission to read
private configuration. Pin actual setup and verify owned child/socket/state cleanup.

Prototype scope: operator-only scripts and focused tests; no API/web/Compose changes.
Document verified operating instructions after proof. Full session streaming,
resume/questions/permission replies and revision-safe proposal import remain this
item’s acceptance, not presumed properties of `opencode run`. Budget used: 0/3.

**Capability checkpoint:** Senior inspection verified launcher UID/GID 1000:1000
(non-root), Linux 6.8.0-138-generic x86_64 and bwrap 0.6.1. Effective Read permissions
denied `/proc/self/cgroup`, `/proc/self/status` and `/proc/self/mountinfo`; no alternate
tool was used to retrieve denied contents. Aggregate control delegation remains
unknown, not disproved. No worker, relay, live model or substantive attempt occurred.
Next: narrowly scoped read-only access to these process facts, relevant
`/sys/fs/cgroup` hierarchy and runtime executable/dependency metadata, or sanitized
operator-supplied results. Establish enforceable memory/PID/CPU and bounded scratch
before execution. Missing delegation then requires operator provisioning, not host
fallback or Docker access. Runner remains ineligible; 0/3 attempts used.

**Later owner decision:** Owner explicitly declined resource-quota checks for this
personal non-serving prototype and accepts possible PC freeze/resource exhaustion,
to address if it occurs. Aggregate memory/CPU/process/scratch verification and
provisioning are no longer a prerequisite for this prototype; the earlier checkpoint
is history, not a demand for operator cgroup access. Keep practical time/output/relay
bounds where available and report aggregate containment as unproved. File, credential,
socket/network isolation, no host fallback, synthetic testing and pre-live independent
review remain required; denied reads remain denied. This does not waive release or
attachment-processing requirements. Worker/relay implementation and actual protocol
proof are still missing; zero runner-eligible tasks and 0/3 attempts used.

**Preparation outcome (2026-10-01, local task commit `ae1fab8`):** Implemented `scripts/imp002_prototype.py`,
`imp002_worker.py`, `imp002_relay.py` and `test_imp002_prototype.py`. Coordinator
independently passed 9 focused unit tests and `synthetic`, `probes`, `outage`,
`timeout` launcher modes; all report owned-state removal. Independent review
APPROVED **synthetic-only**, with no important reproduced defect. Actual runtime
is UID/GID 1000:1000, bwrap 0.6.1, Python 3.10.12 and OpenCode 1.18.34, with binary
and library digests pinned in the launcher (OpenCode `9ca0b995…64c4c2`).

Attempt 1 established mandatory namespace/minimal-runtime containment and stub
relay; read-only config avoided dependency setup, while measured route differed
from the assumed query route. Attempt 2 matched `POST /openai/v1/responses` and
native text/cache-hint shapes; inference/outage/timeout passed, but a project plugin
executed despite disable flags. Attempt 3 masked `.opencode`, `.claude`, `.agents`
with empty read-only mounts; the injection regression and all focused checks passed.
Budget now exhausted: **3/3 substantive attempts**; earlier 0/3 entries are history.

This is an executable synthetic-check handoff, not runner readiness. No credentials,
live provider, app gateway or host fallback; SSE is bounded/buffered, not actual
incremental chat streaming. Full start/resume/questions/permissions and revision-safe
proposal import remain missing. IMP-002 stays `[!]`; root eligibility is still zero.
Next proposed continuation: bounded text-only operator live relay with privately
established fixed HTTPS endpoint/route/deployment/API-version/auth mechanism,
normalized inference-only traffic, streamed cancellation/error handling, separate
pre-live review and one isolated synthetic live turn. Settings/auth are unknown;
do not invent them or request secrets in chat. Renewed scope/budget authorization
is required before further implementation. No runner launch, push/PR or deployment.

**Renewed continuation:** Owner then directed “get back to me when i can run the
runner,” authorizing continued bounded coordination/repair from the saved prototype.
New budget: three focused substantive attempts (0/3 used); retain previous 3/3 above.
Scope is the smallest non-serving real model transport/session preparation necessary
for an honest executable handoff, with unchanged isolation, quota deferral, synthetic
data, pre-live independent review, private operator-only credential resolution and
no push/PR/installation/network provisioning/automatic restart. Never inspect host
auth/config through agent tools or infer live settings from the synthetic deployment.
If existing access cannot be resolved safely, finish a reviewed operator step and
stop for that essential capability; owner request is not permission to bypass it.
Keep `[!]` until actual acceptance or an explicitly scoped approved handoff is proved.

**Continuation checkpoint (local code/docs commit `4ef6a3c`):** Attempt 1 added `scripts/imp002_transport.py` and
focused transport tests, fixed-upstream verified HTTPS/native text SSE, incremental
relay/shim delivery, cancellation/deadlines, sanitized errors and a narrow private
operator resolver. Independent review found a provider-level `api` override accepted
but ignored, potentially binding credentials to a different endpoint. Attempt 2
reproduced it, rejected that override and added a failing-before/passing-after
regression. Affected review APPROVED the human operator steps. Coordinator verified
22 unit tests and all five synthetic modes (`synthetic`, `synthetic-stream`, `probes`,
`outage`, `timeout`) with owned cleanup. New budget used **2/3**; prior **3/3** remains.

Essential next step is human-only, not agent private-file inspection: from repository
root in a plain terminal run
`/usr/bin/python3 -I -B scripts/imp002_prototype.py operator-inspect`.
It performs no network operation and emits only a nonsecret contract fingerprint or
generic capability failure. If successful, operator may use that fingerprint in
`/usr/bin/python3 -I -B scripts/imp002_prototype.py operator-live --contract-sha256 <returned-fingerprint>`.
Only sanitized results may be shared. Unsupported settings or drift stop privately;
no new config/credential copies, fallback or invented settings. Neither mode has run;
actual existing account compatibility is unknown. Full isolated session event/restart/
resume/question/permission and revision-safe proposal tests remain missing, so IMP-002
stays blocked and runner eligibility zero. Remaining attempt retained pending operator
outcome; no automatic runner restart.

**Reported operator failure and diagnostic repair (local commit `43af33e`):** Human returned
`{"success": false, "operator_capability_unavailable": true}` from offline inspection.
Cause remains unknown; do not infer invalid credentials or missing model from it.
Continuation attempt 3 added only allowlisted coarse `reason_code` values for offline
inspection failures, with `network_used:false`; arbitrary exception details, private
paths, environment names/values and settings are never printed. Configuration/auth
support and live failure/success contracts remain unchanged. Independent affected
review APPROVED; coordinator 28 tests passed using synthetic/injected errors only.
Continuation **3/3 consumed**, earlier **3/3 preserved**. Human next step: rerun
`/usr/bin/python3 -I -B scripts/imp002_prototype.py operator-inspect` from this repo,
share sanitized JSON only. No resolver run by agents, live model operation, settings
changes, push/PR or runner launch; IMP-002 remains blocked/eligibility zero. Further
implementation requires reason-specific renewed bounded authorization.

**Environment guard continuation:** Human rerun reports `environment_override` and
`network_used:false`, from an SSH terminal. Actual triggering variable is unknown;
SSH itself is not established as the cause. Prefix-wide XDG denial can reject ordinary
session metadata. Owner approved “go ahead” for the proposed guard repair with up to
three focused attempts (0/3 used), preserving both previous 3/3 budgets. Narrow scope:
distinguish benign session metadata from actual configuration/auth/endpoint changes
using pinned runtime facts, synthetic negative/positive checks and affected independent
review. No environment/config value disclosure or agent resolver execution, auth/config
support expansion, installations, network changes, push/PR or runner launch. After
review the human reruns the same offline inspection; live/account and full session
acceptance remain unproved, IMP-002 blocked and eligible count zero.

**Guard repair outcome (local commit `596b96c`):** Attempt **1/3** reproduced benign session rejection and
added an exact seven-name XDG session allowlist; actual XDG directory overrides,
unknown XDG names and all `OPENCODE_*`/`AZURE_*` names remain denied. Public pinned
OpenCode/xdg-basedir source establishes allowed names do not select config/auth
directories. Independent affected review APPROVED human offline inspection;
coordinator 29 focused tests passed, including benign SSH metadata and negative
directory/config/auth override regressions. No agent environment values/private
configuration inspected, resolver/live run or supported auth/config expansion.
Next human reruns `operator-inspect` unchanged; original triggering name and actual
account remain unknown. Keep blocked/eligible zero; **2/3** guard attempts remain.

**Diagnostic reassessment authorized:** A second SSH-terminal inspection still reports
`environment_override`/no network; which setting triggered it remains unknown. Owner
approved one reviewed human-run offline category diagnostic, not further speculative
allowlist changes. New diagnostic-only budget 0/3; preserve prior 3/3 + 3/3 and guard
1/3 history. Identify rejected environment/input-source categories, literal versus
expanded settings, authentication mechanism and potential endpoint/model precedence
ambiguity, only where bounded safe reads establish them. Unsupported/unknown sources
remain explicitly unknown; do not claim full OpenCode effective config resolution.
Agents use synthetic inputs and never run the private diagnostic. Human output is a
fixed sanitized schema with no values/arbitrary names/paths/URLs/secrets. No config
loader/plugins/reference expansion/arbitrary file traversal/network, supported auth
expansion, setup changes, push/PR or runner launch. After the operator result, approve
a measured compatibility addition or explicit operator-owned relay contract separately.
IMP-002 remains blocked; diagnostic success does not prove live model/session acceptance.

**Diagnostic preparation outcome (local commit `f604ad7`):** New `scripts/imp002_diagnostic.py` and
`scripts/test_imp002_diagnostic.py` provide fixed environment/source/auth categories,
bounded literal parsing, nofollow directory/file reads and strict output projection.
Path-overridden trees and references stay uninspected; no loader/plugin/network or
effective precedence claim. Independent boundary review APPROVED; coordinator 40
focused tests passed with fake inputs, including nondisclosure and no traversal.
Diagnostic attempt **1/3** used, retaining earlier histories. Human now runs
`/usr/bin/python3 -I -B scripts/imp002_diagnostic.py` from repository root and shares
only sanitized JSON. Agents have not run the diagnostic or inspected private inputs.
Wait for that result before selecting supported configuration/auth changes; no live
model or runner restart. IMP-002 remains blocked/eligible zero.

**Measured resolver repair authorization:** Human category report completed offline:
Azure resource present, XDG directory/session present, other Azure/OpenCode/unknown
XDG categories false; inline config/auth absent, default files uninspected. This proves
source-category incompatibility, not which directories/resources or credential mechanism
are used. Owner approved narrow XDG/Azure-resource operator resolver compatibility,
new budget **0/3**; preserve prior 3/3 + 3/3, guard 1/3 and diagnostic 1/3 outcomes.
Validate privately selected XDG paths and bounded nofollow reads; establish exact
pinned OpenCode/SDK precedence for supported Azure resource inputs and bind credentials
to that endpoint. Tests and agents use synthetic inputs only. No arbitrary referenced
path expansion, loader/plugins, auth-mechanism expansion, setup changes, live agent
execution, installations, push/PR or runner restart. Independent affected boundary
review precedes human operator inspection. Unsupported sources remain explicit stops;
do not claim effective account/live/session compatibility without actual proof.

**Measured compatibility outcome (local commit `bb96721`):** Attempt **1/3** adds validated XDG config/data
selection, exact `AZURE_RESOURCE_NAME` interpretation, pinned global literal JSON merge
order/Remeda semantics and config-resource/baseURL/API-auth precedence. Reader pins
every nofollow ancestor, bounds inputs and rejects unsafe permissions/hardlinks/FIFOs,
references/plugins/unsupported auth. Other Azure names, including cognitive-services,
stay denied. Independent affected review APPROVED human inspection; coordinator **47
focused tests passed**. No agent private input inspection, resolver or live execution.
Human next runs `/usr/bin/python3 -I -B scripts/imp002_prototype.py operator-inspect`,
shares sanitized JSON and stops before live mode. Actual setup/model compatibility
remains unknown; keep blocked/eligible zero and **2/3** attempts remaining.

**File-safety outcome (local code commit `92bb00f`):** Human inspection advances to `file_permissions`, offline.
This category does not establish missing read permission: ownership, writable modes,
file type/hardlinks or symlink/non-directory ancestors can also trigger it. Attempt
**2/3** adds eight fixed reader detail codes and fixed config/auth source categories to
offline inspection only. No checks weakened, extra lookups or private values disclosed;
live/success contracts unchanged. Independent affected review APPROVED; coordinator
**51 focused synthetic tests passed**. Human reruns the same `operator-inspect`, shares
sanitized JSON then stops. Actual cause/path/account unknown; no chmod/config edits,
agent resolver/private reads, live/network or runner run. **1/3** attempt remains;
previous histories retained, IMP-002 blocked/eligible zero.

## [-] IMP-009 — Approve backlog and serve immutable downloads

**Depends on:** None
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

## [-] IMP-012 — Verify work branch and open single development PR

Publication deferred for this local-use batch; owner asked for usable application,
not a push/PR. Preserve earlier finalization specification below for later approval.

Type: release-finalization
**Depends on:** None
**Scope:** Verify integrated one-owner release and deliver one review-ready GitHub PR.

### Acceptance and verification

All intended features are verified/committed in `feature/impostr-v1` (or explicitly
removed by owner); inspect full branch and run release checks on that exact head.
A moved head requires retest; blocked prerequisites are not delivered. Only authorized
finalization may push the checked feature branch, verify published head and open/reuse
the PR to `development`. Record URL/content; humans merge. Auth/write capability is
not proved (latest GitHub read returned 401); failures preserve local work and block
delivery. No `v1` implementation/push, force-push or automated merge.

## [-] IMP-016 — Prove private HTTPS LAN access

**Cancelled for this version:** Owner removed private HTTPS until a future request.
No provisioning/device approval is needed for same-PC use; keep loopback, no LAN
HTTP substitute. Preserve earlier blocked scope/history below; not an active queue gate.

**Depends on:** None
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

## [-] IMP-018 — Attach verified media to planning chat

**Superseded by native PDF scope (2026-10-13), not delivered:** Owner chose original
PDF file input through OpenCode/Azure instead of extracted text. IMP-025/026/027 own
the replacement and removal. Preserve full uncommitted backend/receipt/delete/verifier
candidate and all histories below; reuse sound parts where useful. Old phase-four5/5,
phase-five2/5 and additional repair3/3 remain consumed. No renewal or formatter-only
repair assignment is implied. The historical blocker is not a native-plan prerequisite;
IMP-011 now depends on verified IMP-027 instead of this superseded outcome.

### Historical text-reference candidate and acceptance (superseded)

**Latest interactive outcome:** Additional repair **3/3 consumed**, historical
phase-four5/5 and phase-five2/5 preserved. Attempt1 added exact failure-line projection
and reconciled runtime-identical baseline4d46a40; attempt2 fixed the intermittent
receipt assertion selecting turns[0] after a follow-up with tied SQLite timestamps.
It now selects the original turn ID and still requires sent; deterministic reversed
UUID/timestamp regression rejects real receipt loss. Product deletion protections
were not relaxed. Attempt3 isolates fixed-file Ruff input/output via container Python;
actual output capture remains empty without its expected diagnostic metrics.

Coordinator repeatedly passed focused API tests, PostgreSQL3 capture/delete race and
Ruff lint; pure74 tests passed. Exact31 inputs validated, migration0010 passed. All
owned cleanup passed. Format mismatch remains in tests/test_chat_references.py and
the formatter's zero-output cause is unknown. Mypy and full synthetic inference/receipt/
purge verification were not reached; composer still unimplemented. Preserve candidate
uncommitted, no backend/whole-item delivery claim. Further full rebuild guessing is
not useful: next finite authorized check should isolate the one owned command/image/
output attachment with a fixed sentinel and source-only capture. No new installation,
private inputs, weakened fingerprints or automatic runner restart.

**Owner-approved deletion/recovery repair:** Owner directed “do it” after the
`4d46a40` stop. New three focused phase-four repair attempts0/3, retaining original
phase-four5/5 and phase-five2/5; all prior work/budgets preserved. Repair exact remaining
delete/outage assertion and verify pinned API/PostgreSQL/static plus actual PDF inference
receipt/purge behavior. Interactive tech-lead delegates code, selectively reviews
substantive fixes and owns synthetic runtime/cleanup checks. No broad redesign or
assertion removal; user and assistant quotations remain distinct from structured
attachment-text copies. Exact committed-base/input reconciliation required; no denied
tool bypass, private/live data, installs, pushes or automatic runner start. Composer
and rendered phase-five work remain incomplete. Keep blocked until genuine acceptance.

**Execution stop (2026-10-02):** Baseline `8324713`, existing `feature/impostr-v1`.
Phase four **5/5 exhausted**; phase five **2/5 used** (initial verifier plus provenance/
owner-overlay correction). Preserve all earlier PDF budgets. Uncommitted selected-reference,
receipt, dispatch/deletion and synthetic verifier candidate remains; composer is not implemented.
Independent product/API/harness and affected concurrency reviews PASS (static only).
Last coordinator `scripts/imp018_verify.py --api-only` passed exact source mapping, builds,
database and migration/current0010, then failed focused API
`test_delete_outage_is_fenced_pending_and_purge_recovers_without_scrubbing_quotes`
with a call-phase assertion. All owned cleanup passed. Earlier focused API passes are
not final acceptance; fresh PostgreSQL previously passed two tests and failed the
capture/delete race. Its reviewed fence-aware correction has no passing rerun yet.
Static gates, actual inference/full PDF proof and rendered composer acceptance remain
unproved. Owner renewal of bounded phase-four repair scope is required; do not borrow
phase-five attempts or automatically requeue. Preserve candidate; no live/private input,
push/PR or automatic starts. Affected local documentation records the unavailable feature.

**Depends on:** None
**Current owner scope: PDF text only.** Reuse ordinary chat and integrate selected
same-project/conversation ready PDF derivatives, no nativePDF/image provider support
or historical IMP002 gate. PDFphase4/5 budgets above apply, not a new reset.

Extend durable turn request/idempotency with selection and exact derivative hash/page
coverage. Quote extracted text as untrusted references, not agentpolicy/workspacefiles.
128KiBaggregate derivative per turn in rawUTF8 AND JSONescaped form; existing384KiB
assembled context/512KiBframe remains. Validate total before dispatch, explain no-fit
without dropping history/truncation. Preserve exact text reference for reconstructed
conversation while attachment exists. Server revalidates readiness/ownership/deletion
at capture/dispatch; UUID alone noauth. Record actual inference-submission receipt and
distinguish stored/selected/queued/sent/failed-before-send/uncertain; no comprehension
claim. Tests assert exact PDF text at synthetic inference boundary, not workerACK only.

Deletion serialized against capture/send; active-use deletion returns visible conflict
until stop, no future inclusion after deletion. Remove stored derivative/payload/history
attachment copies, including retained host-broker Turn.payload copies; preserve bounded idempotency/
replay tombstones without keeping deleted attachment text. Cover completed and queued
broker payloads as well as DB rows. Previous provider input and assistant quotations
cannot be retracted,
and old backups may retain files until backup deletion. Explain this in UI/docs.

Composer: upload/progress/processing/ready/failure, text preview/coverage, selection/
remove/delete, bounds/errors and perturn sent status; preserve active text/selections
across tabs/reconnect without duplicate turns. Narrow/desktop accessible review uses
fresh reviewed exactinput fixture pinned actualcommittedbase and ordinarysynthetic
connection, generatedMemberlogin, cross-user denial and ownedcleanup. Substantive
extractor/channel/data/receipt changes need review before new runtime scenarios.
Reuse priorUIevidence, don't reimplement editors. Real-provider testing remains deferred.

### Preserved earlier broader media acceptance (superseded)
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

## [-] IMP-019 — Qualify a later multi-user shared-server release

Deferred later scope, not part of owner's same-PC PDF/local-use batch.

Type: release-hardening
**Depends on:** None
**Scope:** Later real-user/server qualification, not this personal-release PR.

### Acceptance and verification

On the actual provisioned server/service identity, prove worker/tenant/session/model-
secret/ingress denials, bounded resources, dependency/secret checks, synthetic restore,
runbook and independent security review. Two-user private project/chat/media/approval/
download end-to-end denials must pass. Preserve role/ownership rules; local browser
risk acceptance and LAN smoke are not server proof. Deferred until separate owner
release approval, actual server/TLS/relay/isolation and recovery resources exist.

## [~] IMP-030 — Introduce coordinated light and dark themes

**Depends on:** None
**Scope:** Replace the single-mode foundation in `web/src/index.css` and add a theme
control available before and after sign-in, without an account-preference API.

### Acceptance

- Shared semantic colors cover surfaces, text, borders, actions, selection and
  feedback in both modes, including native controls and the React Flow canvas.
- Proposed direction: neutral off-white/light surfaces and slate/charcoal dark
  surfaces, with a controlled cool accent. Assess paired visual samples before
  propagating the treatment across the application; exact colors are not fixed here.
- Proposed preference behavior: follow the browser's color preference until the user
  chooses light or dark, then remember that choice in browser storage. Storage failure
  does not prevent use; switching modes does not reset application state.
- Apply the selected mode on initial load without a conspicuous wrong-theme flash.

### Verification

Focused theme/preference tests and browser checks of sign-in and one workspace in
both modes, including reload, readable control states and retained draft text.

### Implementation checkpoint

Theme foundation implemented; pinned build and 33 foundation/App/canvas tests passed.
Designer checked sign-in in both modes at desktop/narrow widths and dark preference
after reload; no important visual defect. Retained editor input is covered by App
tests; rendered workspace assessment follows its layout work. Initial bootstrap-test
URL/type issues were repaired without new dependencies. Verified work is uncommitted,
so the task stays claimed; do not reimplement it or start a runner.

## [~] IMP-031 — Build sharper shared controls and a coherent icon system

**Depends on:** IMP-030
**Scope:** Establish reusable frontend visual primitives instead of separate styling
recipes in every view; no large component-framework migration is required.

### Acceptance

- Consistent buttons, fields, selects, navigation tabs, badges, disclosures and
  feedback distinguish primary, secondary and destructive actions.
- Proposed geometry: small corner radii on controls and panels rather than large
  rounded containers throughout. Typography, spacing, dividers and subtle elevation
  establish clear toolbar, status and content layers.
- One consistent SVG icon family enriches navigation and existing document, history,
  attachment and action controls. Retain useful text labels; icon-only actions have
  accessible names. Any added application dependency follows the existing pinned locks.
- Hover, focus, active, disabled and selected states work in both themes; meaningful
  statuses remain distinguishable without relying on color alone.

### Verification

Check representative controls in a real view in both themes and exercise keyboard
focus, labels and disabled states. Run focused tests for behavior changed by extraction.

### Implementation checkpoint

Shared native control primitives and a local coherent SVG family are implemented,
with no dependency changes. Foundation tests/build and the paired designer check
above passed; ESLint passed and flagged formatting was corrected in the pinned
container. Remaining views adopt these exports in subsequent tasks. Work is verified
but uncommitted, so the task stays claimed.

## [~] IMP-032 — Separate existing destinations into a focused application shell

**Depends on:** IMP-031
**Scope:** Reorganize `App.tsx` and project navigation without introducing new product
actions or requiring a routing-framework replacement.

### Acceptance

- A compact shell provides project context, account access and theme control.
  Projects, the workspace, administrator Accounts and own account security are
  distinct destinations rather than sections of one long scrolling page.
- Existing projects lead the Projects view; creation remains available without a
  permanently dominant form or repeated welcome/identity blocks.
- Project navigation clearly distinguishes Planning, Review/downloads and the
  project-scoped sample canvas. Global account controls do not occupy the work area.
- Selecting a destination reveals the corresponding content at desktop and narrow
  widths. Navigation retains unsaved work, conversation state and in-flight turns;
  existing project-switch guards and role restrictions remain effective.

### Verification

Focused `App`/workspace navigation tests plus browser checks of destination selection,
role-specific navigation and retained input at wide, constrained and narrow widths.

### Implementation checkpoint

Focused shell destinations and a single mounted workspace are implemented. Pinned
build/ESLint and 101 relevant frontend tests passed, including account-role guards,
cross-destination editor/composer/pending-turn retention and session privacy. Designer
checked synthetic Projects, Accounts/security and workspace navigation at 1440/1024/
390px in both themes with no important defect. No live data/deployment was changed;
verified work remains uncommitted and claimed.

## [~] IMP-033 — Give document and backlog editing a usable working surface

**Depends on:** IMP-032
**Scope:** Rebalance `ProjectWorkspace.tsx` and `BacklogPlanning.tsx`; preserve the
existing Markdown editor, task actions and revision/conflict handling.

### Acceptance

- Document/task navigation, editing and Save are primary. Saved/unsaved/revision
  information is compact; history, provenance and comparison remain reachable.
- Pair-approval status and its review action no longer push the main editor below
  a large administrative block. Saving, task readiness and approval stay distinct.
- Backlog list/detail and Markdown modes remain available without a split inside
  an unusably narrow split. Constrained widths show one usable work region rather
  than forcing chat, task navigation and editing into cramped columns.
- Changing work regions preserves drafts, task edits and conflict proposals; moving
  or hiding a pane does not restart chat or submit writes.

### Verification

Focused workspace/backlog tests for navigation, dirty-state retention and conflicts.
Browser-check editing space and access to Save/history at the three representative widths.

### Implementation checkpoint

Editor-first work areas, space-aware region/list-detail layouts and compact expandable
pair review are implemented. The 101-test check above includes 56 workspace and 10
backlog tests; a mock-signature typing issue was repaired and the pinned build passed.
Designer confirmed usable widths, Review selection after Conversation, no page-wide
overflow and retained temporary local input across navigation/theme changes. No writes
were sent by browser checks. Work stays claimed pending authorized local commit.

## [~] IMP-034 — Make conversation and PDF controls one coherent workspace

**Depends on:** IMP-033
**Scope:** Improve `ProjectChat.tsx` and `AttachmentComposer.tsx` presentation without
changing conversation, upload, selection, receipt or provider behavior.

### Acceptance

- Conversation history and composer are adjacent parts of a usable work region;
  Send/Stop and existing conversation selection remain readily accessible.
- Compact PDF inventory and selected-reference treatment use the shared icons and
  controls. Selection ordering and stored-file actions remain available.
- Upload, selection and actual submission status remain distinct. Detailed limits
  and privacy consequences are available before sending without a permanent wall
  of explanatory text between history and composer.
- Existing streaming, interruption, question, permission and failure states receive
  clear treatment in both themes. Navigation/theme changes retain composer text and
  selections without duplicate sends.

### Verification

Focused chat tests and synthetic attachment/question/permission states. Browser-check
composer reachability, selected references and feedback; no live-provider call is needed.

### Implementation checkpoint

Conversation/composer layout, compact PDF inventory and selected-reference controls
are implemented with shared icons/statuses. All 23 chat tests passed, covering ordered
native-PDF sends, receipts/failures, disclosure input retention and stop/question flows;
pinned build and changed-file ESLint passed. Rendered integration follows IMP-036.
No live provider or owner-data writes were used. Work remains uncommitted and claimed.

## [~] IMP-035 — Make approvals and final downloads understandable at a glance

**Depends on:** IMP-033
**Scope:** Improve pair review and `FinalReview.tsx` presentation while retaining
the existing separate approvals, exact revisions, eligibility and download actions.

### Acceptance

- Clearly distinguish document-pair review, final three-file approval and task
  readiness; the current step and next existing action are easy to identify.
- Review prioritizes readable file content with a concise blocker/status summary;
  access to all three files and full validation/provenance details remains available.
- Approval/download controls show adjacent reasons when unavailable. Stale saves,
  unsaved edits and conflicts do not appear approved or downloadable.
- Correct misleading helper copy and ambiguous revision labels only after verifying
  their actual meaning; do not alter identifier or approval contracts to match a label.

### Verification

Focused final-review/workspace tests with valid, blocked and stale synthetic states.
Browser-check file navigation and understandable action eligibility in both themes.

### Implementation checkpoint

Readable keyboard-tabbed file review, compact eligibility/validation presentation and
API-confirmed Document ID/Revision ID labels are implemented. All 10 final-review tests
passed, including UTF-8 downloads and invalid/stale/unauthorized scenarios; build and
ESLint passed. A stale badge hidden by local-edit wording was corrected; its targeted
saved-head/dirty-input/disabled-approval regression passed. Integrated tests/browser
checks follow IMP-036. Work remains uncommitted and claimed.

## [~] IMP-036 — Finish remaining views and verify the integrated visual overhaul

**Depends on:** IMP-034, IMP-035
**Scope:** Complete shared treatment in sign-in, account forms and sample-canvas
cards/toolbars, then resolve concrete integration and usability defects.

### Acceptance

- Remaining views use the coordinated themes, geometry, icons and control hierarchy;
  no conspicuous remnants of the previous treatment remain in the shipped UI.
- Canvas styling and toolbar hierarchy improve without adding real project/task
  content, editing capabilities or durable layouts; existing movement/state survives.
- Representative desktop, constrained-desktop and narrow layouts keep navigation,
  working content, composer and consequential controls reachable in both themes.
- Theme/destination changes preserve drafts and composer input. Keyboard focus,
  dialog return and labelled icon actions are usable in the important flows.

### Verification

Run `npm run build` and affected existing Vitest tests in the pinned web checks
environment; use existing ESLint/Prettier for changed files. Designer spot-checks the
main rendered screens in both themes at approximately 1440, 1024 and 390px widths.
Use synthetic data for write/approval scenarios, not owner project edits or provider
calls. Address concrete important defects; no exhaustive state/device matrix or
reopening of unrelated historical release checks is required.

### Implementation checkpoint

All remaining views and the integrated frontend overhaul are implemented. Pinned
production build, all 142 web tests, ESLint and changed-file Prettier checks passed.
Independent source review approved with no material defect. Bounded final designer
review passed populated conversation/PDF, file review, sign-in and desktop sample
canvas in both themes, with representative 1440/1024/390px checks; canvas text
selection, movement, board switching, zoom and theme-aware arrow markers were checked.
Some width/view combinations were DOM-only, not a full device/gesture matrix.

Browser verification used an isolated frontend preview and synthetic intercepted
APIs; owner-data writes, provider calls and live approval/download actions were not
performed. Existing provider/restore/server acceptance remains deferred. The current
8081 stack was not replaced during verification. All redesign work is verified but
uncommitted on `redesign`; tasks remain claimed pending authorized local commit,
not new assignments or permission to restart the runner.

The owner subsequently authorized refreshing only the existing local frontend. The
`impostr-local` frontdoor was rebuilt and recreated on port 8081; API/database
container identities remained unchanged. Actual sign-in, project opening and both
themes were smoke-checked without project writes or provider calls, and dark preference
survived reload. The browser was signed out afterward. No Git commit or push occurred.

### Owner rejection and corrective checkpoint

The owner rejected the visual result as more amateurish, flat and poorly organized.
Reported defects include the lost green brand, missing M favicon, meaningless
unselected Workspace destination, wrapped Account security label, content-height
sidebar and undifferentiated workspace controls. Renewed live/source review also
found account pages retaining project context and excessive navigation/status layers
before useful content. Previous tests/reviews remain evidence of their checked
behavior, not acceptance of this composition. Preserve working state/data safeguards
and all uncommitted changes; do not reset or reimplement IMP-030 through IMP-036.

The current response is analysis and a fresh draft plan below. No application edits
or further deployment occurred during the reassessment. The designer used the
ui-ux-pro-max review guidance; its local catalogue query was denied, so no catalogue
recommendations were claimed or the denial bypassed. Corrective implementation and
visual-preview approval remain separate next steps.

## [~] IMP-037 — Preview a coherent project workbench

**Depends on:** None
**Scope:** Establish the composition through concrete anonymized previews before
another application-wide reskin. Do not modify the running application in this task.

### Acceptance

- Show realistic Planning previews at desktop width in both themes and a compact
  desktop variant, using current document, backlog, conversation and approval actions.
  Include the original green identity from IMP-038's scope, not placeholder branding.
- One full-height application rail, compact context header and dominant work surface
  distinguish navigation, attached document tabs, toolbar actions and status indicators.
  Documents and Conversation have visible titles and purposeful boundaries.
- Wide layouts provide usable companion conversation space; compact layouts switch
  Documents/Conversation explicitly. The first viewport includes current work/context,
  document selection and useful content rather than a stack of large button rows.
- Proposed material direction: quiet mineral/light document surfaces and layered
  forest-charcoal dark surfaces, restrained depth and green identity. Exact palette,
  proportions and geometry are assessed in the previews, not fixed by this prose.
- The owner assesses the actual composition before broad implementation. A passing
  test suite or no-clipping review is not a substitute for visual acceptance.

### Verification

Inspect paired previews with realistic labels/content and ask whether project, current
work, editable/saved content, status and next action are immediately distinguishable.
Use synthetic content; no owner documents, provider calls or app-data mutations.

### Preview checkpoint

A standalone synthetic workbench concept is served on loopback port 8082, separate
from the unchanged application on 8081. It includes the original green M/favicon,
full-height rail, project-aware navigation, attached document tabs and titled working
surfaces. Designer assessment covered both desktop themes and compact/narrow variants:
content begins around 250px and the previous competing button stack is removed.
Small capitalization, idle action-state and repeated compact-heading refinements were
applied. The owner is now assessing the paired actual previews before broad changes;
this did not establish application behavior. The owner then explicitly selected
"Implement this workbench", approving the paired actual composition for application
implementation. Keep the preview as the visual reference; broad corrective work may
now proceed without resetting the earlier candidate/history. Work is still uncommitted.

## [~] IMP-038 — Restore the green identity and add the M favicon

**Depends on:** IMP-037
**Scope:** Restore the owner-selected brand asset independently of theme/action colors
and supply an explicit browser icon; no application-state or product-flow changes.

### Acceptance

- Reuse the original M glyph and green identity rather than inventing a new mark.
  Preserve the original pale-green M on its dark-green backing in both themes.
- Brand colors are independent of button/action tokens, so changing a theme or accent
  does not recolor the logo again.
- Add an M favicon asset and explicit icon link; the mark remains recognizable at
  browser-tab size and the request no longer falls through to a missing favicon.

### Verification

Compare the restored mark to the original source and inspect it in both themes.
Check the built favicon URL/link, actual browser-tab rendering and reload behavior.

### Implementation checkpoint

Original green M/wordmark and explicit SVG favicon are implemented independently of
theme/action colors. Two brand/asset tests and theme tests passed; the pinned build
passed. An asset-test DOM-realm matcher issue was repaired without weakening glyph,
color or icon-link checks. Actual rendered favicon/theme assessment follows integration.
Work remains uncommitted and claimed.

## [~] IMP-039 — Make shell navigation project-aware and full-height

**Depends on:** IMP-037, IMP-038
**Scope:** Implement the approved workbench shell using existing destinations and the
single session-scoped workspace state owner; no new routes/features are required.

### Acceptance

- Projects is the global entry point. Remove the unconditional Workspace dead end;
  opening a project reveals its named Planning and Review/downloads navigation.
  Returning through that project group resumes existing in-page work, not reselection.
- Account-level pages show account context, not the last project's heading. Identity
  appears deliberately once; routine signed-in/status prose does not dominate work.
- Desktop navigation/background/divider extend to the viewport bottom with coherent
  header offsets and scroll behavior. Accounts/security utilities occupy a clear lower
  area. Account security is left-aligned and fits without awkward wrapping.
- Sample canvas stays a project-scoped demo utility, not a real planning-completion
  stage. Narrow navigation uses a concise labelled disclosure rather than several
  stacked rows of oversized destination buttons.
- Navigation preserves document/task/composer state, in-flight turns, project-switch
  guards and administrator visibility rules. No silent project auto-selection.

### Verification

Check navigation before/after project selection, account context and rail height with
realistic labels at desktop/constrained/narrow widths. Reuse focused role/session and
input-retention tests; check keyboard focus is not obscured by the shell.

### Implementation checkpoint

Full-height rail, project-aware navigation, scoped headers and mobile disclosure are
implemented. The single workspace owns navigation via a narrow command ref; a
prop-to-state effect was removed rather than suppressing lint. All 75 App/workspace
tests, pinned build and changed-file ESLint passed, with role/session, retained input,
review recovery and drawer focus coverage. Explicit Create still opens the created
project; no arbitrary existing project is selected initially. Its asynchronous rail
assertion now waits for the real project context. Visual integration follows; no live
frontend was replaced during this stage. Work remains uncommitted and claimed.

## [~] IMP-040 — Compose Planning as documents and conversation

**Depends on:** IMP-039
**Scope:** Replace the current control stack with the approved Planning workbench,
reusing existing editor, backlog, history, conversation and PDF behavior.

### Acceptance

- Attached Project/Agent rules/Backlog tabs belong to a titled Documents surface.
  Filename/revision, compact Save/Discard/History toolbar and content form one unit,
  visibly different from application/project navigation and status indicators.
- Pair state is concise near the Planning heading; full pair review is a bounded
  secondary region. Save/conflict feedback appears beside relevant work/actions,
  not only after a tall editor. Saving, task readiness and approval stay distinct.
- Conversation is a titled companion pane with useful width on wide desktop; the
  compact Documents/Conversation switch has consistent visible-surface semantics.
  Thread selection, history, composer and selected-PDF summary form one coherent area.
- Backlog's existing task/detail/Markdown choices are subordinate to document tabs,
  with a usable task-list/detail surface rather than another full-strength button row.
- Preserve manual saves, conflicts/reapply, exact revisions, attachment order/receipts,
  streaming/cancellation and input across all surface changes. No rich editor, autosave,
  new task actions or provider/approval changes.

### Verification

Compare rendered Planning against the accepted previews using synthetic realistic
documents/tasks/messages. Focused tests cover tab/surface transitions, dirty/task/
composer retention, conflicts and PDF selections; no live writes/provider are needed.

### Interruption and continuation checkpoint

Planning/conversation/backlog composition is implemented in the worktree and the
updated pinned checks image was built. The subsequent test/build invocations were
interrupted when the owner reported the PC failure; no pass is claimed for them.
The owner requested continuation. Branch, diff and image survived; the existing app,
API and database containers are running, with no old check containers left active.
The cause of the PC failure is not established.

Resume from these files, not a fresh implementation. New finite validation/repair
budget: three focused attempts (0/3 used), retaining all previous checks/history.
Run checks sequentially, with one Vitest worker and bounded temporary Docker resources
to reduce peak load. Do not restart a runner or change Git/deployment permissions.

Continuation attempt 1 passed all 109 affected App/workspace/chat/backlog tests, the
pinned production build and changed-file ESLint. Checks ran sequentially with one
worker and disposable containers capped at one CPU/1536MiB, without a repeat PC
failure. No source repair was needed. Budget used: 1/3; earlier interruption/history
remain intact. Rendered integration and remaining supporting views follow IMP-041.

## [~] IMP-041 — Align review and supporting views with the approved workbench

**Depends on:** IMP-040
**Scope:** Complete the coherent composition across existing Review/downloads,
sign-in, Accounts/security and demo canvas, then check the result as a designed product.

### Acceptance

- Review reuses the workbench frame: saved-file inspection and a clearly titled
  Approval/downloads region. Pair approval, final approval, readiness and immediate
  blockers are distinct; complete validation/provenance remains available.
- Supporting views use the same brand, navigation language, type/surface hierarchy and
  deliberate depth. Canvas remains explicitly sample data with existing movement,
  selection, zoom/fit and independent board/project memory.
- Both themes look intentional. Navigation, real tabs, secondary tools, static status
  and primary actions are distinguishable without relying on identical button boxes.
- Designer and owner judge the rendered result against the agreed composition and
  actual work flow, not only presence of controls or passing functional tests.

### Verification

Use the pinned build and affected existing frontend tests for changed behavior; inspect
main rendered views in both themes at representative wide/compact/narrow widths.
Check the owner's seven reported issues explicitly, plus account context, working-area
prominence and actionable feedback. Retain data/approval safeguards; no exhaustive
matrix, unrelated provider/restore gates, commit or deployment is implied.

### Implementation checkpoint

Review now uses attached saved-file tabs and a titled Approval/downloads surface;
supporting account/sign-in and live sample-canvas views share the workbench treatment.
Planning/chat remain mounted across navigation, with the shared page-heading/focus
target retained. All 148 frontend tests, pinned production build, ESLint and changed-
file Prettier passed after the PC interruption, sequentially with one test worker and
bounded disposable containers. This verifies changed behavior, not final visual
acceptance. Independent source review and rendered comparison to the owner-approved
paired preview are next. Source stays uncommitted; the running frontend is unchanged
from before the corrective implementation.

### Second interruption and frontend-delivery blocker

Before the second reported PC restart, independent source review approved the current
candidate and bounded rendered comparison found the real workbench faithful to the
owner-approved paired previews. The favicon was linked and returned HTTP 200; no
provider, approval, save/send or account-write acceptance was claimed. Narrow reload/
return-banner compaction was noted as optional, not new scope.

The owner requested continuation again. Source, the checked image and compiled
preview assets survived; a lightweight capped source comparison matched the current
web inputs to the checked image. The stopped preview's assets were preserved as Docker
image `impostr-workbench-built`, including the verified JS/CSS bundle and favicon.
No compiler, tests or browser were restarted. Cause of the PC failures remains unknown.

New finite delivery/repair budget: three focused attempts; attempt 1 preserved and
validated the existing assets. Creating `/tmp/opencode/workbench-runtime.Dockerfile`
was denied by the planner's Markdown-only edit permission. No alternative write or
permission bypass was attempted. Frontend refresh is blocked on a permitted packaging
writer or the narrow missing capability; port 8081 still serves the earlier frontend.
API/database containers and all uncommitted work are preserved. No Git commit/push or
runner restart is authorized by this continuation.

Delivery attempt 2 resolved packaging through the application's existing permitted
implementation writer, which created only the exact temporary runtime recipe. The
planner's Markdown-only permission was not changed. The runtime image copied the
preserved compiled assets; no Node compilation, test suite or browser was restarted.
Only the existing `impostr-local` frontdoor was recreated on port 8081; API/database
container identities stayed unchanged. Static HTTP checks returned the expected
checked JS/CSS bundle and original green M favicon with correct content types.
The frontend-refresh blocker is resolved. Delivery budget used: 2/3; all interruption,
permission and validation history above remains. Source is still uncommitted and the
task stays claimed pending authorized local commit, not a fresh runner assignment.

## [~] IMP-042 — Center the sign-in group vertically

**Depends on:** None
**Scope:** Correct only the public sign-in frame's CSS, preserving the existing
branding, theme, authentication behavior and authenticated workbench.

### Acceptance

- Center the logo/theme row and login form as one group horizontally and vertically
  when they fit the viewport.
- Short viewports and expanded validation/error content scroll naturally with safe
  top/bottom space; fields and the access footer are not clipped or overlapped.
- Do not change the authenticated shell or add another login flow.

### Verification

Check the scoped layout rules and generate only the changed stylesheet in the pinned,
bounded container. Preserve the previously checked application JavaScript and reuse
its evidence; no full suite, TypeScript rebuild or new browser session is required.
Verify the local frontend serves the updated stylesheet after frontend-only refresh.

### Implementation checkpoint

Only the public-frame CSS changed: the header/form group now centers within the
viewport, with non-shrinking content, natural short-screen overflow and a separately
anchored access footer inside reserved space. Source/geometry review and Prettier passed.
A bounded CSS-entry Vite build retained vendor/workbench/utility selectors, generated
`index-BR5w7S6S.css`, and changed only the stylesheet href in the preserved built HTML.
The checked application JS `index-DDSo7KlT.js` was reused unchanged; no TypeScript,
full test suite or new browser session was run.

Only the local frontdoor was refreshed on 8081. After a transient startup connection
reset, HTTP checks confirmed the new CSS and preserved JS reference, and API health
returned OK. API/database container identities stayed unchanged. Browser pixel-level
reinspection was deliberately not restarted after the earlier PC failures. Source
remains uncommitted and the task stays claimed pending authorized local commit.

## [~] IMP-043 — Give password fields a full-width input

**Depends on:** None
**Scope:** Correct the shared password-field CSS without changing authentication,
visibility-toggle behavior, field labels or the centered sign-in frame.

### Acceptance

- Password inputs use the same full available width as adjacent text inputs.
- Place the existing Show/Hide control inside the input boundary with enough reserved
  text space; showing a password does not change field geometry.
- Keep the toggle keyboard-accessible and non-submitting in sign-in and existing
  account password forms, in both themes.

### Verification

Inspect the scoped CSS against the shared component and regenerate only the stylesheet
in the pinned bounded container. Reuse unchanged JavaScript and existing behavior
evidence; no full build/test suite or new browser session. Verify the refreshed frontend
serves the new CSS while preserving the application script.

### Implementation checkpoint

Only shared password-field CSS changed: the input now fills its field width, with
reserved text padding and the existing fixed-width Show/Hide control positioned inside
the input. The semantic wrapper selector stays matched when the password becomes text;
DOM, button type, ARIA, keyboard behavior and authentication JavaScript are unchanged.
The previous public-frame centering remains intact.

Source/cascade review and Prettier passed. Bounded stylesheet-only generation retained
vendor/workbench/utility selectors and emitted `index-ym64-53m.css`; the checked JS
`index-DDSo7KlT.js` was reused. Only the local frontend was refreshed; HTTP confirmed
the new stylesheet and API health, with API/database container identities unchanged.
No full suite, application-JS compilation or new browser session was run. Work stays
uncommitted and claimed pending authorized local commit.
