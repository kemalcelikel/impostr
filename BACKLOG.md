# Impostr — backlog

Completed specifications and delivery history are in `docs/backlog-completed.md`.
No runner, branch change or publication is authorized.

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
