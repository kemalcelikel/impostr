# Impostr — product and architecture

## Purpose and scope

Impostr is a one-owner, same-PC planning application for projects that use the
`overnight-agent` toolkit. Users plan with OpenCode's `tech-lead`, edit and approve
three Markdown documents, and download the exact approved versions.

The current scope includes admin-managed accounts, private projects, versioned
documents, resumable conversation tabs, native PDF attachments, human approvals,
backlog editing, approved downloads and a sample card canvas. Ordinary Compose
starts with chat disabled; planning chat requires an explicit foreground provider
connection. Canvas does not require that connection.

Outside this version: public signup, project sharing, phone/LAN/public access,
multi-user server qualification, non-PDF uploads, local OCR/conversion, browser-run
implementation agents, runner monitoring/outcome import, Git operations and tooling
installation for exported projects. Downloads do not initialize a repository or
demonstrate that it is ready to run.

Setup and operator commands: [local development](docs/local-development.md).
Active task scope/state: [BACKLOG.md](BACKLOG.md). Completed task checks/outcomes:
[backlog archive](docs/backlog-completed.md). Earlier decisions are retained in the
existing [history documents](docs/agent-history.md).

## People and workflow

- An operator bootstraps/recovers the first administrator offline. Administrators
  create, deactivate and reset accounts; there is no public registration/recovery
  route. A project's creator and administrators may discover, read, edit, chat in,
  approve and download it. Administrator access is privileged and audited.
  Deactivation revokes sessions/access; opaque project/session IDs confer no access.
- Creating a project records its creator and UTC creation time, assigns server IDs
  and seeds drafts from the selected template with immutable provenance. Names do
  not select filesystem paths; collisions have an explicit response.
- **Specify:** support chat and editing `PROJECT.md` and `AGENTS.md`, with revisions
  and diffs. A human explicitly approves their exact saved pair before backlog
  planning. Changing either document invalidates the pair approval.
- **Plan:** support chat and backlog/task editing. Humans edit
  title/body/dependencies and toggle `[-]`/`[ ]`; Markdown and list stay synchronized.
  Whole-backlog approval is separate and binds one saved revision. Editing it makes
  that approval stale; the planning UI cannot set `[~]`, `[x]` or `[!]`.
- **Review:** make all three files and their revision/approval status available.
  Downloads are individual UTF-8 `PROJECT.md`, `AGENTS.md` and `BACKLOG.md`, from the
  approved tuple only. Missing/stale/invalid approval blocks download with a recovery
  path.
- **Conversations:** restore the last used tab after refresh/re-login. New tabs have
  separate conversations/history but share project documents. Preserve context and
  user input through recoverable disconnects; visibly reject/queue simultaneous
  document-writing turns per project rather than merging their writes.

Approval is a server-recorded action by an authorized human, never agent text or a
file edit. It does not imply task eligibility or installation of the exported files.

## Markdown and data contracts

- PostgreSQL owns projects, users/sessions, conversation mappings/transcripts/events,
  immutable document revisions, approvals and audit records. Revisions retain exact
  content, kind, version, author/origin, timestamp and template provenance.
  `/workspaces` is a private bounded disposable mirror of the three DB heads, not
  an agent workspace or authority. Worker file edits are proposals for new revisions.
- Saves and approvals check expected revisions. Conflicts retain local/proposed and
  newer saved versions for comparison/reapplication; generated output never silently
  overwrites human edits. The approved export is a frozen three-revision tuple, with
  repeat downloads returning identical bytes.
- Approval validation is server-side. Reject unchanged starter instructions,
  unresolved required decisions/placeholders, malformed backlogs and unauthorized
  marker changes. A run/test command is not verified just because agent text says so.
- Bounded drafts may contain raw HTML and are saved byte-for-byte. Required decisions
  must be substantive decided text in supported Markdown headings, prose, list items
  or table cells; emphasis, inline-code values and link labels can contribute. Raw
  HTML elements/descendants, comments, attributes, link destinations, image alt text,
  reference definitions, fenced/indented examples and markup alone cannot establish
  evidence. A decided value alongside an undecided one does not rescue it. Uncertain
  evidence blocks approval, not saving; do not guess CSS/rendered visibility.
- Validation selects frozen legacy/simplified profiles from immutable three-file
  starter provenance, not submitted headings or the installed bundle. Unknown/mixed
  provenance fails closed. Do not rewrite existing starters/revisions/approvals or
  mix a partially seeded project; repository planning files are not user templates.
- Backlog headings use `## [state] ID — Title`, with unique permanent letter-prefixed
  IDs ending in a hyphen and digits. Dependencies use `**Depends on:** None` or a
  comma-separated ID list. Root `scripts/backlog.py` defines compatibility: reject
  duplicate IDs/titles/dependency lines, unknown/self dependencies, cycles and invalid
  markers. Preserve imported execution/Branch/PR metadata. New tasks start `[-]`;
  `[ ]` readiness differs from eligibility, which requires all dependencies `[x]`.

## Chat and native PDFs

- PostgreSQL owns ordered durable events, interactions, turn reservations and
  revision-safe proposals. Commit events before browser delivery; reconnect replays
  DB events, not assumed OpenCode SSE replay. Validate per-project runtime snapshots.
  Unknown dispatch or corrupt recovery is visibly interrupted, never blindly retried.
  Snapshot document heads before inference and reconcile proposals in short,
  revision-checked transactions; agents cannot approve or activate tasks.
- The native OpenCode server/driver uses bounded, identity-validated upstream events.
  The model-only relay streams bounded literal-key-safe text prefixes, holds tool/
  terminal output for validation and preserves partial text on late failures. This
  is not protection against every encoded/semantic form of secret disclosure.
- Uploads are **PDF only**. Store private original bytes, SHA-256, size and safe
  filename under authorized project/conversation IDs. All upload/list/status/download/
  select/send/delete operations enforce ownership. Check actual body bounds and PDF
  envelope, not claimed MIME/filename; no local structural parser, OCR, extraction,
  text-coverage preview, page renderer or inline viewer.
- Explicitly selected originals travel through native file parts and the existing
  relay as Azure Responses `input_file`. PDFs are untrusted references, not authority
  to change tools, planning permissions, approval or readiness. Temporary copies use
  authorized generated read-only paths inside the confined turn workspace and cleanup.
- Each original and the aggregate originals in the actual request must be **less
  than 50,000,000 bytes**, including retained-history occurrences and tool follow-ups.
  Oversized legacy files stay downloadable/deletable but cannot be sent. Account for
  base64, JSON and text/context transport overhead; retain smaller control limits and
  do not silently drop/truncate/summarize history. Page images add cost/context usage.
- Capture, idempotency and dispatch bind exact ordered original IDs/hashes. Revalidate
  authorization, availability and bytes before each submission. Trusted receipts
  identify the serialized request and distinguish stored/selected/queued, sent,
  failed-before-send and uncertain. Sent proves transport, not provider acceptance,
  parsing success or comprehension; provider errors remain visible.
- Deletion fences future use and clears original/legacy-derivative, broker, native
  session and temporary copies. Active turns require confirmed stop or visible conflict;
  outage cleanup stays visibly pending. Preserve non-content receipt/idempotency
  tombstones and quotations; old provider requests/quotes and backups cannot be
  retracted. Old extracted-text receipts remain distinct from native-file receipts.
  Keep binary data out of routine lists/events/logs and approved Markdown exports.

## Sample card canvas

- Project-scoped sample canvas; navigation preserves
  unsaved document/task/chat state and in-flight turns.
- Independent predefined boards retain project-local positions, selection and viewport
  in page-session memory; refresh resets them. Keep content IDs, hierarchy and visual
  coordinates separate: moving a card changes only position, never relationships,
  readiness, approvals or Markdown.
- The current prototype has no content/connection editing, add/delete/reparent,
  real directories, Markdown loading, localStorage or API/database persistence.
  Future directory/content loading and durable layouts require separate contracts.

## Stack and boundaries

| Component | Current responsibility |
|---|---|
| `web/` | Vite, React, TypeScript, Tailwind; React Flow for the canvas. |
| `api/` | FastAPI, SQLAlchemy, Alembic; authorization, revision transactions, chat gateway. |
| PostgreSQL | Authoritative private data, immutable revisions, approvals and originals. |
| Nginx / Compose | Same-origin API/UI on loopback; no DB/worker/relay browser ingress. |
| OpenCode worker | Bubblewrap confinement, native server/driver and namespace-local shim. |
| Host broker/relay | Private authenticated Unix channel; narrow model transport, not a general OpenCode proxy. |
| `overnight-agent/` | Immutable selected starter inputs; root backlog parser remains authoritative. |

Pin application runtimes/dependencies in existing lockfiles/container inputs.
OpenCode uses a fixed executable path but has no exact version/hash lock; safe
availability and health/protocol/behavior compatibility checks reject unsupported
operation without a host fallback. Keep Bubblewrap, other runtime pins and isolation.
Workers receive neither host home/sibling projects nor Docker/DB sockets, API secrets
or copied provider auth. Tool permissions/prompts alone are not confinement;
`opencode run` alone is not the product's resumable chat transport.

The API uses Argon2id, server-side HttpOnly/SameSite cookie sessions, CSRF/exact-Origin
checks, DB rate limits and bounded inputs/time/concurrency. Every read, save, stream,
reply, approval and download is server-mediated and authorized; browser IDs never
choose filesystem paths or DB access. Use safe Markdown rendering and auditable
administration/approvals without logging secrets. These controls do not qualify a
shared-server deployment.

## Interface behavior

- Expose empty/streaming/saving/approval/validation/disconnection/conflict states and
  compare/reapply recovery.
- Attachment UI distinguishes uploading, stored/available, selected, sending,
  sent/not-sent/uncertain and specific failures. Preserve composer text/selections
  through navigation/reconnect; explain original-PDF submission and deletion limits.

## Local operations

- Provider settings come from explicit operator-supplied endpoint/deployment/version
  and API-key facts through the foreground connection. Keys stay in host transport,
  outside API/worker/browser/DB/transcripts/exports/logs; no automatic host-auth reuse.
- Forward migrations preserve originals/history and fence retired extraction work.
  Private backup/fresh-target restore includes users, projects, originals/metadata,
  chats, revisions and approvals; disposable mirrors/runtime scratch are not authority.
- Personal text chat has no aggregate resource-quota prerequisite; practical admission,
  size/time/output/concurrency bounds and filesystem/credential/network isolation remain.
  PDF limits and future shared-server qualification are separate.
