# Impostr — product and technical plan

## Purpose and release boundary

**OpenCode runtime policy (owner changed 2026-10-22):** No exact OpenCode release or
fixed executable hash is required. Use the existing fixed executable path with safe
availability checks and an observational digest; reject incompatible health/protocol/
behavior without an automatic fallback. Keep bwrap/Python/library pins, isolation,
credential handling and exact candidate-source/frozen-input verification. Installed
1.19.0 passed confined synthetic startup/planning/access-denial checks; native PDF and
real provider acceptance remain separate. Earlier 1.18.34 references record tested
source/history, not an active version requirement or a need to approve every update.

**Owner-approved native PDF direction (2026-10-13):** Keep private upload and chat
selection, but send the original PDF through OpenCode's native file input to Azure.
Remove local text extraction and its dedicated container/sandbox/lifecycle after the
replacement is verified. No Podman/sbx migration or change to agent isolation is part
of this decision. Implementation outcomes are IMP-025/026/027, then local-use IMP-011.

**Current capability, not the whole target:** IMP-017 delivered private raw intake and
confined extraction/lifecycle in `ca09dc3`, `269710f`, `8925dfa`. Native PDF backend proof
is locally delivered in `a966d77` after the small event-format repair.
Composer and fixture cleanup are locally delivered in `34dbcb0`; extractor retirement
and local workflow/restore remain IMP-027/011. Owner will manually accept the completed
application; remaining browser/full-app tests are deferred, not passed or an immediate
implementation gate. Reuse existing valid evidence rather than more automated suites.
IMP-018's unaccepted text-only candidate and all earlier attempts remain history, not
a reason to finish or rebuild that design. No actual-provider success is claimed.

### Native PDF contract

- Same-PC loopback only; no private HTTPS/phone/LAN work. Upload formats remain PDF
  only, not standalone images, DOCX, text files or remote URLs. Store original bytes,
  SHA-256, size and safe filename metadata privately in PostgreSQL under opaque
  project/conversation IDs. Authorize upload/list/status/download/select/send/delete.
  Filename and claimed MIME do not prove PDF validity; retain bounded actual-body and
  PDF-envelope checks, without introducing another local structural parser.
- Reuse OpenCode's native PDF file parts and the existing relay for Azure Responses
  `input_file`, rather than a new parser/service/compatibility layer. Accept ordinary
  documented event metadata while validating relevant identity/content and keeping
  bounds; don't invent a narrower upstream event format. Prefer explicit
  selected attachments in the user prompt, not arbitrary repository discovery. If a
  temporary file is required, use only an authorized generated read-only path inside
  the confined turn workspace and remove it afterward; do not mount the host repository,
  API mirror, other uploads or credentials. Canonical planning-file edit permissions
  remain unchanged. PDFs are untrusted reference material, never authority to change
  tool permissions, approve documents or activate tasks. No local qpdf/pdftotext, OCR,
  page rendering, extraction preview,
  parsed-object validation or text-coverage gate remains in the target.
- Microsoft documents PDF input for text-and-image Responses models, explicitly lists
  `gpt-6.1-sol`, and supplies extracted text plus page images to the model. OpenCode
  1.18.34 source supports PDF attachments and Azure Responses serialization. This is
  documented compatibility, not an observed success with the owner's deployment.
  Scans/diagrams may be handled by the provider; no local OCR feature or guaranteed
  page accuracy is promised. Malformed/encrypted/unsupported input may fail at the
  provider and must produce an honest error, not a fabricated local validation pass.
- Azure documents each file under 50 MB and 50 MB combined per request. Conservative
  decimal interpretation: each original and the aggregate originals actually included
  in one request must be **less than 50,000,000 bytes**, including references retained
  from earlier turns. This tightens the old inclusive intake boundary by one byte.
  Larger legacy stored files remain downloadable/deletable but cannot be sent. Enforce
  finite PDF-bearing transport bounds accounting for base64 expansion (roughly 4/3),
  JSON and existing text context; do not globally remove small text/control limits or
  silently drop history, truncate or summarize to fit. Provider context/token limits
  and page-image costs still apply even when the file fits the byte allowance.
- Extend the existing model-only relay narrowly for selected inline PDF data. Real
  credentials stay in the trusted host transport, never the API/browser/worker/DB.
  No public file URL, provider file-upload store or general media/proxy access is needed.
  Reusing host OpenCode authentication and changing sandbox technology remain separate
  unresolved choices; this work authorizes neither private-config discovery nor auth copies.
- Bind capture/idempotency/dispatch to exact ordered original IDs and hashes. Revalidate
  ownership, availability and bytes before every model submission, including reconstructed
  history and tool follow-ups. Trusted submission receipts identify the exact serialized
  request/files and distinguish stored/selected/queued/sent/failed-before-send/uncertain.
  Sent means actual transport submission, not provider acceptance or comprehension.
- Deletion fences future inclusion and clears structured original/legacy-derivative,
  broker payload, native-session and temporary-workspace copies. A still-active turn
  requires stop confirmation or a visible conflict; outage cleanup may stay visibly
  pending. Preserve non-content idempotency/receipt tombstones and user/assistant quotes.
  Prior provider requests/quotes cannot be retracted; older backups can retain deleted
  files until those backups are removed. Keep originals out of approved Markdown exports.
- Retire extractor wiring and derivative data with forward migration/preservation checks;
  never rewrite committed migrations or erase other project/chat/approval data. Synthetic
  local backup/restore covers originals, attachment metadata, conversations and approvals.
  Before exposing native availability, disable legacy extraction admission and drain or
  fence outstanding completions so old rejection/retry cleanup cannot delete originals
  selected for native use. Physical extractor removal can follow after native delivery.
  Historical extracted-text submission receipts remain distinguishable from native-file
  submissions; never relabel old evidence as proof that original PDF bytes were sent.
  Real-provider acceptance remains a later human test, not an immediate implementation gate.

Sources checked 2026-10-13: [Azure Responses PDF input](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/responses#file-input),
[Azure model catalog](https://ai.azure.com/catalog/models/gpt-6.1-sol), and
[OpenCode 1.18.34 PDF Read support](https://github.com/anomalyco/opencode/blob/v1.18.34/packages/opencode/src/tool/read.ts).
Earlier text-readable-only limits and extraction requirements are superseded; their
delivery/attempt history is retained in BACKLOG.md and docs/local-scope-history.md.

**Owner-deferred real-model testing:** Provider compatibility is a planning assumption,
not observed acceptance. The owner will test the application later; retain the live
operator acceptance command but do not require it immediately. Synthetic preparation
and review/backlog chat integrations are delivered. Ordinary Compose still defaults
chat off. IMP-005 adds a reusable foreground explicit connection and optional
ordinary Compose overlay. Its boundary review and coordinator synthetic ordinary-stack
proof passed; real-provider operation remains untested and owner-deferred. See
`docs/local-development.md` for setup/lifecycle, bounded admission and incremental
literal-key-safe transport limits.
No reusable host/file credential setup has been implemented or secretly authorized.
Do not claim that default application chat works merely because its UI is delivered.

**Latest IMP-024 preparation:** Phases one and two (phase two's delivered 5/5 plus its
focused additional 1/3 repair) and phase three (5/5) are delivered. Phase four uses 3/5;
its integrated synthetic workflow/recovery proof, reviewed operator boundary, fresh
candidate profile and rendered approval/download/reapproval acceptance passed. The
rendered tests used a generated Member and synthetic project only; stop/cleanup verified
removal of accounts, login, stack/images, private and broker state. No real credentials
or live model operation were used. The retained later live-test command is the human-only
`/usr/bin/python3 -I -B scripts/imp024_operator.py setup-accept` from the repository
root in a plain terminal; it is not the current next step or a native implementation gate.
After the owner's later test, accept only a sanitized human outcome;
agents must not run it. It accepts only explicit public HTTPS:443 Responses/API-key
facts, with no guessed endpoint or settings, and fails closed if no-echo terminal input
is unavailable. Secret-in-memory handling is not protection against host swap/dumps or
memory copies. Actual deployment compatibility remains untested. IMP-024 delivered
buffered validation; IMP-005 streams bounded literal-key-safe prefixes, with tools/
terminal held until validation and late-failure partial text retained (not arbitrary
encoded/semantic-exfiltration protection). IMP-005/006/008 have since delivered their
synthetic implementation; the old IMP-002 live proof remains historical incomplete work,
not a queue gate. Preparation does not enable default live chat or satisfy real-provider
acceptance. Live remains disabled by default.

Earlier IMP-024 UI/backend checkpoints below describe delivered components and retain
their historical evidence; they are not the latest phase-four state. Exact development
handoff disclosure/tamper risk is owner-accepted only for temporary synthetic Member
login/cleanup, not secrets.

The implementation uses a restricted host broker/private authenticated Unix channel
to the API; namespace-local OpenCode server/driver and shim; and a trusted model-only
relay. Neither API nor worker receives host/provider credentials or a general OpenCode
proxy. An explicit operator-owned endpoint/deployment/auth contract replaces reliance
on the parked host-configuration resolver. Do not invent endpoint, deployment or
API-version settings; real-provider compatibility remains unknown.

The owner cancelled aggregate resource-quota prerequisites for personal-PC local
text chat, accepting possible host disruption/exhaustion. This replaces older
prototype-only deferral wording, not attachment/shared-server requirements or
filesystem/credential/network isolation and practical time/output/concurrency bounds.
History: `docs/local-resource-policy-history.md`. No quota provisioning is implied.

PostgreSQL remains authoritative for authorized conversations, ordered durable events,
pending interactions, turn dispatch reservations and revision-safe proposals. Commit
events before browser delivery; reconnect replays DB events, not assumed OpenCode SSE
replay. Persist only validated generated per-project runtime state; unknown dispatch or
corrupt recovery is visibly interrupted, never blindly resubmitted or silently replaced.
Snapshot document head IDs before inference; import proposals with short revision-checked
transactions. Concurrent human saves retain conflict proposals instead of overwrites;
agent edits cannot approve documents or activate draft tasks. Live activation is separate
from synthetic preparation and does not deliver private HTTPS/media or the first release.

Impostr's first usable release is a **one-owner, same-PC planning app**
hosted on this PC through loopback; phone/LAN access is outside this version. A
future multi-user server release needs separate qualification and is **not**
delivered by the personal release. The app serves people who use the
`overnight-agent` toolkit but do not want to copy starter files, edit Markdown
in Vim, or conduct project setup entirely in a terminal. A signed-in user
creates a project, plans with the installed OpenCode `tech-lead`, reviews and
approves `PROJECT.md` and `AGENTS.md`, plans a backlog with a live task list, and downloads
the exact approved versions of all three Markdown files. The product name is
**Impostr** (without an “e”).

**First release includes:** existing admin-created accounts without signup;
private projects; project metadata and immutable Markdown revisions in
PostgreSQL in Docker; resumable project-scoped chat with multiple session tabs;
version-bound two-file approval, backlog editing and approval, three-file review,
and individual approved downloads. Project conversation attachments include
only native PDF input under the file/aggregate limits above, with provider-side text/page
image understanding rather than local extraction. Attachments persist privately with the project/
conversation until explicit deletion; deleting later cannot retract bytes already
sent to a model. The local planning/PDF workflow and recovery checks must
pass before local use; real-provider testing is explicitly owner-deferred. The UI is
a dark, modern terminal-inspired *application*, not a terminal emulator.

During implementation, the human-only document review/approval and backlog
editor may be verified before live agent chat. These intermediate slices are not
a substitute for the first release above: chat, session recovery, containment,
end-to-end approvals and downloads remain release gates.

**Not in the first release:** multi-user shared-server qualification, public
Internet exposure, local OCR/conversion, standalone image/text uploads or Office formats.
It also excludes creating
a Git repository for a planned project, installing agents or skills, launching/
monitoring `run-tonight.sh` in the browser,
running implementation agents from the web, Git pushes/PRs/merges, shared project
collaboration/invitations, public signup, and importing runner outcomes. Downloaded
files are planning artifacts, not evidence that a repository is ready to run. The
owner continues to prepare application repositories and launch the runner manually.

### Current implementation

Accounts, private projects, versioned editors, human approvals/downloads, template
integration and synthetic text chat are delivered. Native PDF backend and composer are
delivered; BACKLOG.md records the evidence and owner-deferred browser acceptance.
Extractor retirement and restored local workflow remain the approved next outcomes.
Actual provider use remains owner-deferred. Earlier implementation narratives are
preserved in docs/agent-history.md, not mixed into current product requirements.

## People, permissions, and workflow

Roles: an operator bootstraps the first administrator offline; an administrator
creates/deactivates users and resets their credentials in the authenticated UI.
There is no registration endpoint or invitation flow. Each project has a creator
and creation timestamp (UTC). Only its creator and administrators may discover,
read, chat in, edit, approve, or download it; administrators may administer all
projects. Treat administrator access as privileged access to private project data.
Deactivated accounts lose access to existing sessions. A user may own multiple
projects and have multiple conversation tabs for one project.

1. **Sign in and create:** after authentication, a user names a project. The server
   chooses its internal ID and isolated workspace; it seeds *drafts* for the three
   documents from the selected template bundle, records template provenance, creator, and
   creation time. Do not run or install the toolkit as part of creation. A name
   collision is handled explicitly; a user-provided name never becomes an arbitrary
   filesystem path.
2. **Specify:** `tech-lead` asks questions and proposes changes to `PROJECT.md`
   and `AGENTS.md`. Show chat beside both reviewable files, their revisions and
   diffs; direct edits are possible. The human approves the exact **pair** of saved
   revisions in one explicit action. Only then does the UI advance to backlog
   planning. A changed member of the pair invalidates its previous approval and
   makes the final handoff pending re-review.
3. **Plan:** retain chat beside a collapsible backlog task list. Each task row has
   its immutable ID, editable title/body, dependencies and an on-row `[-]` draft /
   `[ ]` ready toggle. Selecting/expanding a task exposes its scope, acceptance,
   verification and dependency details. Agent suggestions and direct edits must
   update the visible Markdown and list together; do not silently overwrite one
   with the other. Human readiness is task-specific; a global backlog approval is
   a separate explicit action bound to one saved backlog revision. Changes after
   approval invalidate that approval. `[~]`, `[x]`, `[!]` are reserved for future
   runner reconciliation and cannot be set from this planning UI.
4. **Review and download:** at a wide desktop viewport, show the three files side
   by side with legible scroll regions, revision IDs and approval status; at
   narrower widths use an accessible switcher rather than unreadably thin columns.
   Offer individual `.md` downloads of exactly the jointly approved pair and
   approved backlog revision. No draft download, automatic Git write, or runner
   execution in this release. A stale, missing, or invalid approval blocks download
   with a clear recovery path.
5. **Sessions:** reopen the last used conversation by default after refresh or
   re-login; “new session” opens a new tab with a separate OpenCode conversation.
   Each tab shares project documents but not conversation history. Preserve chat
   context and user text after a recoverable disconnect. Serialize document-writing
   turns per project; reject/queue a conflicting turn visibly instead of merging
   simultaneous agent writes. Direct edits use revision checks even across tabs.

Approval means a server-recorded action by an authorized human, never a phrase in
agent output. Approval does not imply that dependency-eligible tasks exist or that
the exported files have been installed in a Git repository.

## Markdown and data contracts

- Store projects, creator/UTC creation time, user roles/status, session ownership,
  transcripts/session mappings, immutable Markdown revisions (content, document
  kind, version, author/origin, timestamp, template provenance), approvals, and
  audit events in PostgreSQL. The DB is authoritative for Impostr drafts/approved
  revisions. `/workspaces` is a private, bounded,
  disposable API mirror of the three current database heads, not an agent workspace
  or source of truth; reads can rebuild it from PostgreSQL. Agent workspaces are
  proposal surfaces and must reconcile validated changes into new DB
  revisions, never turn file edits into approval. Integrated backup/restore remains
  IMP-011; do not claim it passed from migration tests alone.
- Save each document with an expected current revision. A stale save or approval
  returns a conflict with the latest revision and preserves both versions for
  review. A generated revision does not overwrite a newer human edit. The approved
  export is one recorded tuple of three immutable revisions; repeated downloads
  return the same bytes. Do not store model/provider secrets in files or transcripts.
- Export plain UTF-8 `PROJECT.md`, `AGENTS.md`, and `BACKLOG.md` filenames. Before
  approval, reject unchanged starter instructions/placeholder fields, missing
  required decisions for the intended project, malformed backlog headings or
  dependencies, and unauthorized marker transitions. Do not claim any app-specific
  test/run command is verified unless it has actually been run for that project.
- **Pair-approval evidence rule:** Save bounded `PROJECT.md` and `AGENTS.md` drafts
  with their exact bytes, including raw HTML, but never use raw HTML elements or their descendants
  as evidence for a required decision, even when a tag has no style or class.
  Server-side approval requires substantive, decided text in supported Markdown
  headings, prose, list items or table data cells; ordinary Markdown emphasis,
  inline-code values and link labels may contribute. HTML comments, element
  attributes, link destinations, image alt text, reference definitions, fenced
  or indented examples and markup alone do not. An undecided required value is
  not rescued by a completed value alongside it. If the evidence boundary cannot
  be established, block approval rather than guessing at CSS/rendered visibility;
  do not reject saving the draft merely for containing HTML. Keep starter and
  unresolved-placeholder checks, project authorization, immutable revision
  binding and current approval-status checks server-side. This is a bounded
  evidence grammar, not a claim that arbitrary rendered HTML or CSS is visible.
- Backlog format is `## [state] ID — Title`, where unique permanent IDs start
  with letters and end in `-` plus digits, as parsed by `scripts/backlog.py`.
  `**Depends on:** None` or comma-separated task IDs is the canonical dependency
  line. Reject duplicate IDs/titles, unknown/self dependencies, repeated dependency
  lines, invalid markers, and dependency cycles in the editor; validate the final
  Markdown against the root helper's behavior. Preserve any existing non-planning
  status/Branch/PR metadata when displaying or revising an imported backlog later.
  The helper considers a `[ ]` task eligible only when its dependencies are `[x]`;
  readiness and *eligibility* are different badges. First-release drafts begin
  `[-]`; no runner completion is synthesized by the UI.
- The auth API, project/doc APIs, session gateway and file downloads are server-
  mediated and project-authorized; the browser never chooses a filesystem path,
  accesses the DB directly, or receives the OpenCode server/host credentials.
  Session and document IDs are opaque server IDs, not proof of authorization.
  Cross-origin and CSRF policy must match the actual deployment origin.
- Attachments follow the native PDF contract above: private originals and metadata,
  exact authorized file submissions and deletion fencing, no derivative requirement.
  Keep binary data out of routine metadata/event lists, logs and approved three-file
  exports. A stored or queued file is not a model submission. Provider parsing failure
  must remain visible; no claim that every page was understood follows from a receipt.

## Architecture and technical direction

| Boundary | Planned choice / responsibility |
|---|---|
| Browser | Vite + React + TypeScript + Tailwind CSS; stage-aware client, accessible editor/list/chat, no secret storage. |
| Trusted API | Python + FastAPI (technical choice), typed request validation, auth and project authorization, revision transactions, streamed session gateway. |
| Persistence | Docker-hosted PostgreSQL; SQLAlchemy + Alembic migrations, database-owned approval/version history and project data. |
| Front door | Nginx, same-origin API/UI, loopback only in this version; DB, worker and model relay have no browser ingress. Private HTTPS/LAN work is cancelled until a later owner request. |
| Agent runtime | Installed OpenCode runs in a `bwrap`-confined worker with native server/driver, namespace-local shim and private host broker/model relay; no exact OpenCode version/hash lock. Native PDF synthetic flow now passes; BACKLOG.md records its local delivery. No host home, sibling projects, Docker/DB sockets, API secrets or copied host auth. Real provider use remains owner-deferred; sandbox/auth-source redesign is outside this repair. |
| PDF input | Private PostgreSQL originals → explicit OpenCode file parts → narrow credential-protecting relay → Azure Responses inline PDF. No local extractor after IMP-027; original-byte identity, transport bounds and deletion still apply. |
| Templates | Selected simplified examples under `overnight-agent/` seed new drafts through delivered IMP-022 integration. Existing immutable starter revisions/provenance stay unchanged. The API maintains a private disposable workspace mirror. The application parser oracle remains root `scripts/backlog.py`; expanded nested parser semantics are not automatically adopted. |

Approval selects frozen legacy/simplified profiles from immutable three-file starter
provenance, never submitted headings or the installed bundle. Unknown/mixed provenance
fails closed; do not rewrite existing starters/history/approvals or silently mix a
partially seeded project. Root planning files describe Impostr, not user templates.

Pin app runtimes/dependencies in api/requirements.lock, api/requirements-dev.lock and
web/package-lock.json plus existing container inputs. OpenCode itself has no exact
version/hash lock. Its authenticated native server/driver and model-only relay provide
resumable planning; `opencode run` alone is not the product chat transport.
The API uses Argon2id, server-side cookie sessions, CSRF/exact Origin checks and DB rate
limits; these local-app controls do not establish shared-server readiness.

Agent tools and configuration need a project-scoped isolation design verified on
the deployment host. The bundled `tech-lead` definition can edit planning files
and use shell commands; tool permissions and prompt instructions alone are not a
filesystem or credential boundary. Do not expose a shared-host release if the
runtime can read another user's project, server secrets, or host files. No agent
installs skills or initializes Git as a repair for missing setup.

## Visual/interaction acceptance

- Dark layered surfaces, restrained green for affirmative actions, readable sans
  for prose and restrained monospace for filenames, IDs and status. Terminal flavor
  comes from structure and precision, not neon text, fake command syntax, or
  scanlines. Final palette/tokens should be established through `ui-designer` and
  rendered review, not inferred from these suggestions.
- At about 1440px, chat and review/editor have useful widths; stage 2 keeps a
  collapsible backlog rail and a usable task detail surface. At about 1024px,
  secondary metadata can collapse; at 768px and 375px, switch between primary
  chat/files/backlog regions without horizontal page scrolling or losing input.
- Display meaningful empty, streaming, saving, saved, approval pending, validation,
  disconnected, unauthorized, and version-conflict states. Stale edits offer a
  compare/reapply path, never silent overwrite. Status has text as well as color;
  keyboard focus, dialog focus return, and screen-reader names/states work.
  Normal text should meet 4.5:1 contrast, controls/focus 3:1; respect reduced
  motion. Owner will check rendered flows, including keyboard-only operation, manually
  after implementation; additional automated browser passes are not immediate gates.
- Native PDF attachments show **Uploading**, **Stored/Available to attach**, selected,
  sending and specific upload/provider failure states, not a local extraction spinner
  or text-coverage preview. Offer authorized download and filename/size information;
  no new inline PDF viewer. Distinguish actual sent/not-sent/uncertain per-turn status
  without claiming comprehension. Preserve composer input/selections through navigation
  and reconnect; provide usable desktop/narrow keyboard/screen-reader controls. Explain
  that Azure receives the original PDF, page images can increase cost/context usage,
  and deletion cannot retract prior provider input.

## Security, operations, and acceptance

The personal first release is a **one-owner private-access** service with
potentially sensitive product ideas, attachments, transcripts and model
credentials. Existing roles and project authorization remain mandatory; a
single intended owner is not an auth bypass, and synthetic second-user tests
remain required. Authenticated roles and project ownership must
be checked on every read, save, event stream, permission/question reply, approval,
and download; guessing another project/session ID must reveal nothing. Use
password hashing, server-side secure sessions with HttpOnly/SameSite cookies,
CSRF protection for cookie-authenticated mutations, rate limiting for login and
agent prompts, size/time/concurrency limits, and safe Markdown rendering. Keep
provider keys outside DB Markdown, browser storage, exports and logs. No public
signup or unauthenticated OpenCode/DB ingress. Do not publish raw HTTP for phone
access or assume a router is a security boundary. A future LAN release would need
verified private HTTPS/proxy/network handling; it is outside this same-PC version,
not a current setup or acceptance gate.
Secret handling, backup/restore and account recovery are personal release/
operational gates; later multi-user qualification is separate. Audit credential
administration and approvals without recording secrets. Test negative
authorization cases and runtime escape attempts.

Completion of the personal first release requires an end-to-end demonstration
of distinct projects, resumed/new-tab chat, both approval gates, direct edits
plus agent proposals, stale-revision rejection, backlog status/dependency
validation, three revision-identical downloads, and failures/recovery. Use
the owner's later manual acceptance for remaining browser/full-app walkthroughs;
do not demand another automated browser suite before finishing implementation. Use
synthetic second-user/project probes for authorization; these do not qualify a
multi-user server. Prove exact native PDF input through the synthetic inference
boundary, private attachment access/deletion and restored originals/metadata with
chat/revision/approval data. Native provider comprehension remains the owner's later
live test, not a synthetic pass. No standalone image/DOCX or remote-device HTTPS gate
remains in this version. Restore the DB from synthetic backups before local use.
Start with focused checks for changed behavior and realistic risks; broaden for
integration and the release demonstration above, not as a blanket per-task gate.
Independently review substantial or security/data-sensitive changes; `ui-designer`
spot-checks important rendered flows for substantial UI changes. Optional suggestions
do not add acceptance requirements. Never equate a
successful mock integration test with an isolated, working OpenCode deployment.

## Decisions and remaining gates

| Topic | Status | Consequence / next action |
|---|---|---|
| Release boundary, private projects, admin UI, selected templates | Owner revised / same-PC first release | Retain roles/authorization and plan-and-export workflow; simplified nested templates delivered by IMP-022. Native PDF workflow and synthetic restore remain IMP-025/026/027/011, actual provider testing owner-deferred. No LAN/public/multi-user server scope or web runner. |
| Version-bound human approvals, planning-only marker buttons, resumable tabs, approved downloads only | Owner decided | Treat revision changes as stale approvals; reserve execution markers. |
| UI/backend/deployment stack | Implemented local baseline | Vite/React/TypeScript/Tailwind, Python/FastAPI/SQLAlchemy/PostgreSQL/Alembic/Nginx; manifests/locks pin actual dependencies and container runtimes. |
| Safe OpenCode integration | Synthetic product integration delivered; live owner-deferred | IMP-024/005 deliver confined native worker/server/shim, private broker, model-only host relay, durable API/proposals and ordinary foreground connection. Keep credentials outside workers. Native PDF transport is IMP-025; no host-auth discovery or sandbox migration. Personal text-chat aggregate quota work remains cancelled. |
| Deployment environment, exact app commands and secrets provision | Local-only setup verified / workflow-restore pending | Docker/Compose setup, migrations, local account bootstrap/recovery, API health and database recovery are documented in `docs/local-development.md`. Confined synthetic product isolation is verified, not shared-server qualification. No host PostgreSQL install or current LAN/TLS gate; integrated backup/restore remains IMP-011. |
| Automated local browser-review credentials | Verified local fixture / residual host risk accepted | Prior exact-input reviews are delivered; native PDF composer needs its own refreshed profile/rendering. Shared Playwright is **not OS-confined**. Use owned synthetic stack/generated short-lived Member, revoke and clean up after review; never use owner's accounts/private data or claim host-secret/Docker denial or product isolation from browser proof. |
| First-release attachments | Backend/composer delivered; removal/manual acceptance pending | IMP-025/026 supply native PDF input and composer; IMP-027 removes extractor. Conservative decimal file/aggregate limits; browser and actual-provider acceptance remain owner-deferred. Preserve delivered IMP-017 and superseded IMP-018 history. |
| Phone/LAN access | Cancelled for this version | Same-PC loopback only. Any later private HTTPS/device setup requires a new owner request; no raw LAN shortcut. |
| This repository's execution/delivery policy | Single-branch local delivery; publication deferred | Preserve `feature/impostr-v1` commits, dirty candidate and task history. No concurrent/automatic runner, pushes/PRs or merges for this planning request/native local-use batch. IMP-012 retains later final PR specification for owner approval. Candidate evidence applies only to exact inputs; broad coordinator tools are not product isolation. |

Implementation slices, dependencies and verification are in `BACKLOG.md`; actual
verified repository commands and automation constraints are in `AGENTS.md`.
