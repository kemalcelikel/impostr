# Impostr — product and technical plan

## Purpose and release boundary

**Current verified chat UI:** Phase-three synthetic UI is delivered in `b72e98c`:
conversation tabs, rendered questions/once-only permissions, proposal comparisons,
human-save conflict preservation and actual front-door incremental output. Normal
generated Member rendered review and narrow/desktop design checks passed. Full
integrated workflow/operator relay handoff remains phase four; no live chat activation
or real provider compatibility is claimed. Exact development handoff disclosure/tamper
risk is owner-accepted only for temporary synthetic Member login/cleanup, not secrets.

**Current verified chat backend:** IMP-024 phases one/two are delivered locally
(backend `a39a2f4`): confined planning interactions/proposals plus authenticated durable
API/DB/broker flow, actual restart/outage/no-duplicate recovery, concurrent human-save
protection, approval invalidation and active revocation. Joined synthetic acceptance
and owned cleanup passed. Chat UI/front-door stream rendering and final operator
handoff remain phase-three/four work; no live model/account acceptance or release claim.
Older prototype-only/nonintegrated wording below records previous checkpoints, not
the current backend capability. Default Compose still has no live chat activation.

**Latest approved preparation:** Build the complete local text-chat path through
synthetic end-to-end verification (IMP-024), reusing delivered IMP-023. Live access
remains disabled until a reviewed human-operated fixed model connection and existing
live acceptance pass. Use a restricted host broker/private authenticated Unix channel
to the API; namespace-local OpenCode server/driver and shim; trusted model-only relay.
Neither API nor worker receives host/provider credentials or a general OpenCode proxy.
An explicit operator-owned endpoint/deployment/auth contract replaces reliance on the
parked host-configuration resolver. A human may provide a secret through reviewed
no-echo input into relay memory, never command arguments/environment/DB/browser/worker.
Exact setup and supported account facts remain execution work, not invented settings.

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

Impostr's first usable release is a **one-owner, private-access planning app**
hosted on this PC. The owner may use it from another device on the LAN through
a tested private HTTPS route; the app's trusted backend remains unexposed. A
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
PNG/JPEG images, selectable-text PDFs, text-only DOCX extraction, and UTF-8
text/Markdown. The model must actually receive an attached image before the UI
claims it saw it; scanned/visual PDF pages and embedded DOCX images are not
supported in this first version. Attachments persist privately with the project/
conversation until explicit deletion; deleting later cannot retract bytes already
sent to a model. The phone/other-device route and full planning workflow must
pass the personal-release gates before calling this version complete. The UI is
a dark, modern terminal-inspired *application*, not a terminal emulator.

During implementation, the human-only document review/approval and backlog
editor may be verified before live agent chat. These intermediate slices are not
a substitute for the first release above: chat, session recovery, containment,
end-to-end approvals and downloads remain release gates.

**Not in the first release:** multi-user shared-server qualification, public
Internet exposure, scanned/visual PDF or embedded DOCX-image understanding,
macros, or Office formats other than bounded DOCX text. It also excludes creating
a Git repository for a planned project, installing agents or skills, launching/
monitoring `run-tonight.sh` in the browser,
running implementation agents from the web, Git pushes/PRs/merges, shared project
collaboration/invitations, public signup, and importing runner outcomes. Downloaded
files are planning artifacts, not evidence that a repository is ready to run. The
owner continues to prepare application repositories and launch the runner manually.

### Current implementation boundary (human-only planning and approval on work branch)

The checkout has a limited application slice; the first-release scope above is
not yet implemented. The current UI supports operator-provisioned sign-in,
administrator-managed accounts, own-password changes, project creation with
private drafts for `PROJECT.md`, `AGENTS.md`, and `BACKLOG.md`, human pair
approval, collapsible backlog task editing for title, body, dependencies, and
`[-]`/`[ ]` readiness, and Stage 3 final review of the saved three-file tuple with
individual exact approved downloads. The API validates task edits. Conflicts retain local edits
and show the newer saved version for review and explicit reapplication rather than
silently overwriting either version. This remains human-only: no chat, agent proposals, runner
outcomes, or setting runner status markers.
The first administrator is created or recovered through an offline CLI; there is no public
signup or network recovery route. Administrators can create, reset, and deactivate
accounts. Members can access projects they own; administrators can access all
projects, and administrator access is audited. Consult `docs/local-development.md`
for implemented project, revision, workspace-cache, and operator behavior and
`BACKLOG.md` for committed delivery outcomes. IMP-014 candidate and rendered
acceptance has been verified locally; consult BACKLOG.md for delivery references.
IMP-020/021 verified manifest persistence and human-only final approval/status/
exact-download API behavior; IMP-010's Stage 3 UI and candidate review also passed
locally. This work branch is not a merged release; do not infer chat, agent gateway
or release readiness from it.

The owner approved splitting blocked IMP-009 into independently verified
persistence and integrated enforcement slices. IMP-020 adds only inert
manifest schema; IMP-021 finishes valid final approval and exact downloads.
The recovery used #11 for persistence and #12 for enforcement; #13 was not needed.
Independent combined review and focused actual API/PostgreSQL checks passed; current
BACKLOG.md records verified local commits. Historical snapshot access denial remains
history, not an active reviewer-folder gate. The split changes delivery
boundaries, not the product's approval, authorization or Markdown-evidence rules;
schema-only delivery must not enable unfinished final-approval routes. See
BACKLOG.md for preserved partial work, attempts and the capability checkpoint.

The API uses Argon2id password hashing, server-side cookie sessions, CSRF and exact
Origin checks on unsafe requests, and database-backed rate limits. These are
implemented local-app controls, not evidence of a shared-server security boundary.
The agent-runtime gate is still blocked: installed OpenCode agents and a bare
`bwrap` 0.6.1 namespace smoke test do not demonstrate a brokered, secret-safe
isolated agent integration. Local setup and account recovery instructions are in
[`docs/local-development.md`](docs/local-development.md). Do not infer TLS,
reverse-proxy, backup/restore, production, or shared-server readiness from this
slice.

An operator-only synthetic worker/relay prototype now exists under
`scripts/imp002_*.py`. Pinned bwrap/OpenCode launch, synthetic file/socket/network
denials, configuration-injection denial, stub inference, outage/timeout and owned
cleanup passed focused checks and independent synthetic-only review. The continuation
adds a reviewed operator-only fixed HTTPS model transport and private resolver, plus
bounded incremental text SSE with synthetic cancellation/error proof. Neither operator
inspection nor live inference has run; actual account compatibility remains unknown
and the app is not integrated. Full session streaming, resume/questions/permissions
and revision-safe proposal import remain unproved. The owner accepts aggregate resource-exhaustion
risk and defers memory/CPU/process/scratch quotas for this non-serving prototype
only. This does not waive credential/project isolation or release/attachment rules.
See BACKLOG.md for the prior three-attempt checkpoint and current continuation scope.

Following private resolver compatibility failures, the owner selected independent
synthetic session-protocol work instead of further operator troubleshooting. IMP-023
has now proved confined synthetic server startup, text streaming/history/reconnect,
interrupt handling and in-worker server restart with a fake inference upstream.
Generated authentication is namespace-local, mDNS is disabled, and no host ingress
is exposed; the host relay remains inference-only and unchanged. This proof does not
include SSE replay or full worker-restart durability, and aggregate resource quotas
remain deferred. No private inputs, operator modes or live model operation were used.
This is not a product gateway or host service: questions/permissions/proposals,
product integration, actual-model behavior and product chat acceptance remain
unproved IMP-002 work. Synthetic protocol proof does not unblock chat or certify the
host account/model connection.

IMP-024 phase one now separately proves native canonical planning reads, questions
and replies, once-only edit permissions, unapproved proposal capture, forbidden-tool
denial, cancellation cleanup/stale-reply denial and terminal inference errors through
the synthetic host relay. Independent boundary and affected repair reviews passed;
the four confined scenarios and owned cleanup passed. This remains a non-serving
preparation checkpoint: the private product broker, durable API/proposal import,
chat UI and human-only connection entrypoint are not yet delivered. Earlier IMP-002
and IMP-023 acceptance boundaries remain unchanged.

### Current implementation versus planned application

- This checkout contains root `scripts/backlog.py` and `run-tonight.sh`, plus an
  `overnight-agent/` distribution carrying templates, helper, runner and agent definitions.
  The owner deleted the root examples and selected the simplified nested bundle.
  The IMP-001/003/004 application work is in `api/`, `web/`, and `compose.yaml`;
  supported local commands and the
  boundary between baseline checks and candidate review are in
  `docs/local-development.md`.
- `overnight-agent/{PROJECT,AGENTS,BACKLOG}.md.example` are the selected canonical
   **input templates** for new Impostr-created projects. IMP-022 integrates exact
   nested discovery/packaging and coherent fixture inventories. Approval selects
   frozen legacy/simplified profiles from the immutable three-file starter provenance,
   never submitted headings or the installed bundle; unknown/mixed provenance fails
   closed. Existing starters/history/approvals are not rewritten; partially seeded
   projects remain explicitly incomplete rather than mixing versions. The root helper is
  the compatibility reference for exported backlog syntax. These root planning
  files describe Impostr itself and are not the templates for user projects.
- OpenCode agents are installed for the current CLI environment (including
  `tech-lead`, `architect`, `ui-designer`, `developer`, and `overnight`), but a
  product-integrated web-session API and brokered, secret-safe runtime have **not**
  been demonstrated. IMP-023's synthetic session protocol proof is confined to its
  non-serving harness; it does not establish product authorization or actual model
  integration. The bare `bwrap` 0.6.1 namespace smoke test alone remains insufficient;
  questions, permission handling and proposals remain unverified. This repository
  uses GitHub and an existing `v1` planning baseline.
  The owner chose one work branch based on `v1`, ending in a single PR to
  `development`; this replaces the former per-task sprint-PR proposal. See
  `AGENTS.md` for the execution contract, effective after its publication.

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
  revisions. In the current IMP-004 slice, `/workspaces` is a private, bounded,
  disposable API mirror of the three current database heads, not an agent workspace
  or source of truth; reads can rebuild it from PostgreSQL. A later agent workspace
  remains a proposal surface and must reconcile validated changes into new DB
  revisions, never turn file edits into approval. The IMP-004 database restore
  drill is not verified; see `docs/local-development.md` before relying on this as
  durable storage.
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
- **Planned pair-approval evidence rule (owner decision, not delivered by
  IMP-004):** Save bounded `PROJECT.md` and `AGENTS.md` drafts with their exact
  bytes, including raw HTML, but never use raw HTML elements or their descendants
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
- Attachments have opaque project- and conversation-bound IDs. Authorize upload,
  status, preview/fetch, model inclusion and deletion on the server. Store
  originals and bounded safe derivatives outside the public web root and agent
  workspace, retaining them with the project until explicitly deleted and
  including them in the personal-release recovery drill. Reject spoofed content
  types, unsafe names, active/macro content and oversized or abusive documents;
  process PDF/DOCX/image inputs with bounded resources and no converter network
  access. Only explicitly attached, validated content reaches the model. Record
  what was actually included in a turn; a failed conversion cannot silently
  produce a success state. Attachments are not added to the approved three-file
  Markdown export. Actual byte/page/turn caps and selected model fidelity must
  be measured and approved before attachment work is marked ready.

## Architecture and technical direction

| Boundary | Planned choice / responsibility |
|---|---|
| Browser | Vite + React + TypeScript + Tailwind CSS; stage-aware client, accessible editor/list/chat, no secret storage. |
| Trusted API | Python + FastAPI (technical choice), typed request validation, auth and project authorization, revision transactions, streamed session gateway. |
| Persistence | Docker-hosted PostgreSQL; SQLAlchemy + Alembic migrations, database-owned approval/version history and project data. |
| Front door | Nginx, same-origin API/UI. Current Compose binds loopback only. A later operator-provisioned **private HTTPS** route must be verified from a phone/other device before the personal release; DB, worker and model relay have no browser ingress. No public Internet exposure. |
| Agent runtime | On this PC, try the already-installed `bwrap` under the actual worker identity as a fail-closed per-project boundary, not the empty namespace smoke or `run-tonight.sh`'s optional sandbox. A trusted host-side relay keeps existing model credentials outside the worker and allows bounded model traffic. No host home, sibling projects, Docker/DB sockets, API secrets, or copied host OpenCode auth in the worker; prove live operation and negative access tests before a product gateway is claimed. If this is unavailable, IMP-002 remains blocked. |
| Templates | Selected simplified examples under `overnight-agent/` will seed new drafts after IMP-022 integration. Existing immutable starter revisions/provenance stay unchanged. The API maintains a private disposable workspace mirror. The application parser oracle remains root `scripts/backlog.py`; expanded nested parser semantics are not automatically adopted. |

The implemented IMP-001/003 slice pins its container runtimes and actual app
dependencies in the manifests/locks listed in `AGENTS.md`. The host OpenCode
CLI was most recently observed at 1.18.33; before building the gateway, prove
the compatible session/stream/question API and pin the working integration. A Python
API may use the authenticated OpenCode HTTP interface or a controlled adapter;
do not assume the JS SDK or `opencode run` is a resumable web-chat transport.

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
  motion. Check the rendered flows in browser, including keyboard-only operation.
- Chat attachments must show **Uploading**, **Processing**, **Ready to send** or
  a specific failed/retry/remove state, then distinguish **Stored** from **Included
  in this model turn** and **Not included**. Never claim that a filename, upload
  success or extracted text alone proves the model saw an image. On mobile, keep
  the composer and attachment controls usable without overflow; announce failures
  and provide filename-specific keyboard/screen-reader controls. Explain that
  text-only PDF/DOCX excludes scans, diagrams and embedded images, and deletion
  cannot retract content already sent to a provider.

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
access or assume a router is a security boundary. Private HTTPS, exact Origin/
proxy handling and operator-managed network restrictions must be verified before
the personal LAN release, not configured or guessed during current local work.
Secret handling, backup/restore and account recovery are personal release/
operational gates; later multi-user qualification is separate. Audit credential
administration and approvals without recording secrets. Test negative
authorization cases and runtime escape attempts.

Completion of the personal first release requires an end-to-end demonstration
of distinct projects, resumed/new-tab chat, both approval gates, direct edits
plus agent proposals, stale-revision rejection, backlog status/dependency
validation, three revision-identical downloads, and failures/recovery. Use
synthetic second-user/project probes for authorization; these do not qualify a
multi-user server. Also prove actual image model input, honest text-only PDF/
DOCX behavior, private attachment access and deletion, and the approved private
HTTPS route from an actual phone/other device. Restore the DB and retained media
from synthetic backups before release.
Start with focused checks for changed behavior and realistic risks; broaden for
integration and the release demonstration above, not as a blanket per-task gate.
Independently review substantial or security/data-sensitive changes; `ui-designer`
spot-checks important rendered flows for substantial UI changes. Optional suggestions
do not add acceptance requirements. Never equate a
successful mock integration test with an isolated, working OpenCode deployment.

## Decisions and remaining gates

| Topic | Status | Consequence / next action |
|---|---|---|
| Release boundary, private projects, admin UI, selected templates | Owner revised / personal first release | One owner on this PC; retain roles/authorization and plan-and-export workflow. Simplified nested templates are selected but await compatible application integration (IMP-022). A verified private HTTPS LAN route and full chat/media/approval/download flow are first-release gates. Public and multi-user server operation are later, not silently approved. No web runner. |
| Version-bound human approvals, planning-only marker buttons, resumable tabs, approved downloads only | Owner decided | Treat revision changes as stale approvals; reserve execution markers. |
| UI/backend/deployment stack | Implemented local baseline | Vite/React/TypeScript/Tailwind, Python/FastAPI/SQLAlchemy/PostgreSQL/Alembic/Nginx; manifests/locks pin actual dependencies and container runtimes. |
| Safe OpenCode integration | Owner chose `bwrap`-first / open capability gate | The non-serving IMP-024 phase-one synthetic harness now verifies native planning read/question/reply/edit-once permission and unapproved proposal capture, plus denied shell, abort cleanup and terminal-error handling inside the confined worker. It is not a product broker/API/UI or live model integration, and does not establish worker-restart durability or aggregate resource containment (personal text-chat quota work is cancelled). Next is broker Unix UID/authentication, durable DB state and proposals; IMP-002/005/006/008 acceptance remains open. Do not copy host auth into a worker. |
| Deployment environment, exact app commands and secrets provision | Local-only setup verified / release gate open | Docker/Compose setup, migrations, local account bootstrap/recovery, API health and database recovery commands are documented in `docs/local-development.md`. No separate host PostgreSQL install is required. Web-agent isolation, TLS/reverse-proxy handling, backup/restore, and release checks remain unverified. |
| Automated local browser-review credentials | Verified local fixture / residual host risk accepted | IMP-015 and exact-input IMP-004/013/007 reviews passed locally; IMP-014 still needs its own profile and rendering. The shared Playwright tool server is **not OS-confined** and may access host files, provider credentials or Docker. Use a fresh synthetic stack and generated short-lived Member login/session, revoke it after review, and never intentionally use owner's accounts or real project data. This is not host-secret/Docker denial, product isolation, shared-server readiness or an auth bypass. IMP-002 remains blocked. |
| First-release attachments | Owner decided / model fidelity and limits unverified | PNG/JPEG actual image input; text/Markdown and bounded selectable-text PDF/DOCX extraction. No scanned/visual PDF or embedded DOCX images in v1. Retain privately per project/conversation until explicit deletion; only explicitly attached validated derivatives reach the model. Provider/media support and numeric limits require measured proof before the media items become ready. |
| Phone/LAN access | Owner decided / operator setup later | Private HTTPS route on this PC, tested from another device, with backend/DB/worker/relay unexposed. No route, domain, certificate, trusted proxy or deployment command is verified; do not open raw LAN HTTP as a shortcut. Implementation can proceed locally before the access slice is ready, but the personal release cannot pass without it. |
| This repository's execution/delivery policy | Owner approved / in use | Base from published `v1`; verified slices on `feature/impostr-v1`, ending in one PR to `development` for human merge. IMP-001/003/004/007/013/015 are locally committed; IMP-002 remains blocked and IMP-009/014 remain partial. IMP-020/021 are approved but capability-blocked drafts. Candidate evidence applies only to exact inputs. Temporary broad coordinator edit for the local batch is not product isolation or an acceptance waiver; restrictive-rule restoration remains owner post-batch work. Media/LAN/multi-user and revised release checks remain draft scope. |

Implementation slices, dependencies and verification are in `BACKLOG.md`; actual
verified repository commands and automation constraints are in `AGENTS.md`.
