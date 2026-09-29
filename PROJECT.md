# Impostr — product and technical plan

## Purpose and release boundary

Impostr is a private, shared-server planning workspace for people who use the
`overnight-agent` toolkit but do not want to copy starter files, edit Markdown in
Vim, or conduct project setup entirely in a terminal. A signed-in user creates a
project, plans with the installed OpenCode `tech-lead`, reviews and approves
`PROJECT.md` and `AGENTS.md`, plans a backlog with a live task list, and downloads
the exact approved versions of all three Markdown files. The product name is
**Impostr** (without an “e”).

**First release includes:** admin-created accounts without signup; private projects;
project metadata and immutable Markdown revisions in PostgreSQL in Docker;
resumable project-scoped chat with multiple session tabs; version-bound two-file
approval, backlog editing and approval, three-file review, and individual approved
downloads. The UI is a dark, modern terminal-inspired *application*, not a terminal
emulator.

**Not in the first release:** creating a Git repository for a planned project,
installing agents or skills, launching/monitoring `run-tonight.sh` in the browser,
running implementation agents from the web, Git pushes/PRs/merges, shared project
collaboration/invitations, public signup, and importing runner outcomes. Downloaded
files are planning artifacts, not evidence that a repository is ready to run. The
owner continues to prepare application repositories and launch the runner manually.

### Current implementation boundary (IMP-001/003)

The checkout has an earlier, limited application slice; the first-release scope
above is not yet implemented. The current UI supports operator-provisioned sign-in,
administrator-managed accounts, own-password changes, and reads of project
metadata. The first administrator is created or recovered through an offline CLI;
there is no public signup or network recovery route. Administrators can create,
reset, and deactivate accounts. Members can read metadata for projects they own;
administrators can read all project metadata, and administrator metadata reads are
audited. Project creation is not implemented, so a new database can contain no
projects. Planning documents, project workflow, chat, approvals, downloads, and an
agent gateway are not part of this slice.

The API uses Argon2id password hashing, server-side cookie sessions, CSRF and exact
Origin checks on unsafe requests, and database-backed rate limits. These are
implemented local-app controls, not evidence of a shared-server security boundary.
The agent-runtime gate is still blocked: installed OpenCode agents and a bare
`bwrap` 0.6.1 namespace smoke test do not demonstrate a brokered, secret-safe
isolated agent integration. Local setup and account recovery instructions are in
[`docs/local-development.md`](docs/local-development.md). Do not infer TLS,
reverse-proxy, backup/restore, production, or shared-server readiness from this
slice.

### Current implementation versus planned application

- This checkout contains the root `PROJECT.md.example`, `AGENTS.md.example`,
  `BACKLOG.md.example`, `scripts/backlog.py`, and `run-tonight.sh`; a nested
  `overnight-agent/` distribution carries duplicates and global agent definitions.
  The limited IMP-001/003 application is in `api/`, `web/`, and `compose.yaml`;
  its supported local commands are in `docs/local-development.md`.
- Root `.example` files are the canonical **input templates** for Impostr-created
  projects; retain their identity/version for each created project. The nested
  distribution is a reference, not a second source of truth. The root helper is
  the compatibility reference for exported backlog syntax. These root planning
  files describe Impostr itself and are not the templates for user projects.
- OpenCode agents are installed for the current CLI environment (including
  `tech-lead`, `architect`, `ui-designer`, `developer`, and `overnight`), but a
  working web-session API and brokered, secret-safe isolated runtime have **not**
  been demonstrated. The bare `bwrap` 0.6.1 namespace smoke test is not proof of such an
  integration; session events/questions, permission handling, and denials remain
  unverified. This repository uses GitHub and an existing `v1` planning baseline.
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
   documents from the root examples, records template provenance, creator, and
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
  revisions. A temporary per-project agent workspace is a **proposal surface**;
  reconcile file changes into new DB revisions after validation, never treat edits
  to a workspace file as an automatic approval. Use DB migrations and backup/
  restore procedures before relying on this as durable storage.
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

## Architecture and technical direction

| Boundary | Planned choice / responsibility |
|---|---|
| Browser | Vite + React + TypeScript + Tailwind CSS; stage-aware client, accessible editor/list/chat, no secret storage. |
| Trusted API | Python + FastAPI (technical choice), typed request validation, auth and project authorization, revision transactions, streamed session gateway. |
| Persistence | Docker-hosted PostgreSQL; SQLAlchemy + Alembic migrations, database-owned approval/version history and project data. |
| Front door | Nginx, same-origin API/UI with TLS for shared-server access; DB and OpenCode endpoints are not exposed to browsers. |
| Agent runtime | Existing host-configured OpenCode models and `tech-lead` definition, launched with narrowly scoped, isolated per-project workspaces. No host home, sibling projects, Docker socket or database credentials inside an agent session. Agent runtime receives only required model access via operator-managed secret injection. |
| Templates | Versioned root starter examples are copied into project-scoped *draft* workspaces; the Markdown parser compatibility reference is root `scripts/backlog.py`. |

Choose supported, pinned dependency releases during bootstrap and commit lockfiles;
proposed baselines are Python 3.12, Node 22 LTS, PostgreSQL 17, React 19, Tailwind
CSS 4, and current maintained Vite/FastAPI/Alembic/Nginx releases. These are
**planned choices, not currently installed app dependencies**. The actual OpenCode
CLI is present at version 1.18.32 here; before building the gateway, prove the
compatible session/stream/question API and pin the working integration. A Python
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

## Security, operations, and acceptance

This is a private **multi-user** service with potentially sensitive product ideas,
transcripts and model credentials. Authenticated roles and project ownership must
be checked on every read, save, event stream, permission/question reply, approval,
and download; guessing another project/session ID must reveal nothing. Use
password hashing, server-side secure sessions with HttpOnly/SameSite cookies,
CSRF protection for cookie-authenticated mutations, rate limiting for login and
agent prompts, size/time/concurrency limits, and safe Markdown rendering. Keep
provider keys outside DB Markdown, browser storage, exports and logs. No public
signup or unauthenticated OpenCode/DB ingress. Secret handling, backup/restore,
account recovery and server TLS setup are operator responsibilities documented
before shared-server launch. Audit credential administration and approvals without
recording secrets. Test negative authorization cases and runtime escape attempts.

Completion of the first release requires an end-to-end browser demonstration of
two distinct users with private projects, resumed/new-tab chat, both approval
gates, direct edits plus agent proposals, stale-revision rejection, backlog status/
dependency validation, three revision-identical downloads, and failures/recovery.
Run actual app checks once bootstrap establishes them; review security-sensitive
changes independently and review rendered UI with `ui-designer`. Never equate a
successful mock integration test with an isolated, working OpenCode deployment.

## Decisions and remaining gates

| Topic | Status | Consequence / next action |
|---|---|---|
| Release boundary, shared-server/private projects, admin UI, root templates | Owner decided | Plan-and-export only; creator/admin access; no web runner. |
| Version-bound human approvals, planning-only marker buttons, resumable tabs, approved downloads only | Owner decided | Treat revision changes as stale approvals; reserve execution markers. |
| UI/backend/deployment stack | Owner decided / technical choice | Vite/React/Tailwind, Python/PostgreSQL/Alembic/Nginx; FastAPI/ORM and major-version baselines are technical proposals to confirm in bootstrap. |
| Safe live OpenCode integration | Open capability gate | Spike must prove session resume, events/questions, config/agent discovery, secret handling and isolation before gateway is implementation-ready. |
| Deployment environment, exact app commands and secrets provision | Local-only setup verified / release gate open | Docker/Compose setup, migrations, local account bootstrap/recovery, API health and database recovery commands are documented in `docs/local-development.md`. No separate host PostgreSQL install is required. Web-agent isolation, TLS/reverse-proxy handling, backup/restore, and release checks remain unverified. |
| This repository's execution/delivery policy | Owner approved / publication gate | Base from published `v1`; perform verified slices on one long-lived feature branch; continue independently eligible work after a blocker; submit one final PR to `development` for human merge. All 12 dependency-gated items are owner-approved ready; publish this changed execution contract before launch. |

Implementation slices, dependencies and verification are in `BACKLOG.md`; actual
verified repository commands and automation constraints are in `AGENTS.md`.
