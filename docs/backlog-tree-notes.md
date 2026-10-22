# Hierarchical backlog and visual planning — discussion notes

Recorded: 2026-10-14. **Exploration only, not an approved implementation plan.**
The owner requested notes, not application changes or changes to the current run.
This file does not alter PROJECT.md, AGENTS.md, BACKLOG.md, task readiness, runner
assignments, or Git publication permissions. The active native-PDF batch is separate.

## Problem and owner-requested direction

A single BACKLOG.md becomes difficult to navigate and expensive to load into an
agent's context for larger or harder projects. Editing one item should not require
loading or rewriting the whole backlog.

The proposed product direction has two connected parts:

- A directory/subdirectory tree of Markdown plans. At the root, a master plan
  identifies the backlog. Each item has its own directory and a local plan that
  describes the item and what its subdirectory contains. Items can represent
  features, bug fixes, or general tasks; more detailed categorization is undecided.
- A Figma-like, zoomable canvas showing items, their place in the hierarchy and
  their dependencies. Selecting an item opens a side editor for its content,
  potentially including functional/nonfunctional requirements, definition of done,
  use cases and other sections permitted by the eventual format.

The intended benefit is focused context: load the relevant item, necessary parent
context and relevant dependencies, rather than every specification in the project.

**Owner clarification, 2026-10-14:** This is a complete overhaul: the whole system
is to use compartmentalization, not merely a visual wrapper over BACKLOG.md.
This includes Impostr planning/editing and the toolkit/runner representation.
Exact boundaries for specifications, operating rules, context handoffs, approval
and export remain design work. This confirms the direction, not executable task
scope or permission to change any of those systems during the current run.

### Owner response to research — specialized system, selective inspiration

The owner clarified the following preferences on 2026-10-14:

- **OpenSpec is the strongest reference.** Its approach is considered excellent;
  investigate its compartmentalized specifications/change packages as primary
  inspiration. This is not a decision to adopt its CLI, exact format or full workflow.
- **Superpowers planning patterns are worth borrowing.** Select useful plan structure,
  task boundaries, interface contracts and focused handoff ideas. Any actual copying
  needs appropriate license/attribution checks; its process rules are not adopted.
- **GitHub Spec Kit is a secondary reference.** Some pieces may help, but the owner
  finds the overall approach messy. Inspect specific useful parts rather than
  importing its complete structure or ceremony.
- **Beads may be too heavy or a poor fit.** Do not use it as the planned foundation
  or assume its database, CLI or orchestration should become dependencies. Retain
  the research as a comparison; any small conceptual lesson remains optional.
- **The goal is a specialized system, not a combination of existing frameworks.**
  Compartmentalization and visual backlog editing are only the tip of the iceberg.
  Further capabilities have not yet been described; do not invent them or treat
  this initial discussion as the complete product specification.

Earlier examples, recommendations and planning order are provisional. Continue
capturing the owner's broader needs before locking the complete model, schema,
architecture or executable backlog. All research sources and objections below
remain useful context, not a selected stack or permission to implement.

## Recommendation: a hierarchy plus a dependency graph

These are different relationships and should remain distinguishable:

- **Contains:** a parent breaks work down into children. One item has one location
  in the tree; moving it does not change its identity.
- **Depends on:** an item requires another item before execution. Dependencies can
  cross folders and need not follow the parent/child tree.

Do not duplicate a shared prerequisite under every feature that uses it. Keep one
item and link to it. Dependency cycles must be diagnosed, not hidden by the layout.
Folder order and canvas position should not silently determine execution order.

### Illustrative disk layout, not a selected format

```text
BACKLOG.md                         # master overview and entry points
backlog/
  WORK-100-account-management/
    PLAN.md                        # this item's scope and child index
    WORK-101-sign-in/
      PLAN.md                      # one executable item's details
    WORK-102-password-reset/
      PLAN.md
  WORK-200-reporting/
    PLAN.md
    WORK-201-export-report/
      PLAN.md                      # can depend on WORK-101 in another branch
```

Suggested responsibilities:

- Root master: overall goals, short workstream summaries and links. It defines
  the whole backlog through the linked hierarchy, not by repeating every body.
- Local plan: one item's actual specification plus short links to direct children.
  A leaf has no child index. A small item should remain a small document.
- Global lookup: a compact, derived ID-to-path/parent/dependency index allows full
  project search and dependency resolution without loading all item bodies into
  model context. Avoid a second hand-maintained copy of item status/specifications.
- IDs stay stable across title changes and moves. Filenames, display labels and
  canvas coordinates are not identity. The exact ID/path convention is open.

There must be one authority for each field. For example, an item's status lives
with that item and is summarized elsewhere, not independently edited in three plans.
Long outcome histories should not turn every master overview into another giant
backlog; keep useful history linked and preserved separately from current scope.

## Focused agent context

A future loader could start from a selected ID and assemble:

1. Relevant project-wide rules and constraints; isolation must not omit these.
2. Brief ancestor summaries explaining why this item exists.
3. The selected item's full scope, requirements, acceptance and verification.
4. Relevant dependency contracts/outcomes, with deeper details loaded on demand.

Do not recursively load every transitive prerequisite by default: that could
recreate the original context problem. Discovery/validation may inspect the full
index locally without passing every specification to the model. The loader should
identify included revisions and omissions; never silently cut required contracts
to fit a context limit. Editing should target the selected item, with explicit
related edits when dependencies or parent scope also need to change.

## Canvas and side editor

Suggested interaction, not finalized UI acceptance:

- Show a hierarchical overview with expand/collapse, pan, zoom, fit-to-selection,
  search by ID/title and a breadcrumb for the selected item's ancestry.
- At overview scale show groups, short labels and summarized state; reveal more
  detail as the user zooms or selects. Do not render entire Markdown bodies on nodes.
- Use different visual treatment for containment and dependency links. Prefer
  selected-item incoming/outgoing dependencies or a dependency-view toggle over
  showing every edge at once on a large canvas.
- Open a side panel for the selected item's Markdown/structured fields. Show ID,
  type, scope, dependencies, child links and saved revision alongside relevant
  specification sections. Preserve unsaved text during canvas navigation.
- Keep an accessible outline/list alternative and keyboard selection/editing;
  a freeform canvas must not be the only way to use the backlog.
- Keep layout state separate from requirements. Moving a node visually must not
  change its parent, dependencies or readiness without an explicit semantic action.

Start with automatic readable layout plus pan/zoom and a side editor. Figma-like
navigation does not necessarily require a full drawing tool, multiplayer editing,
freeform annotations or a new canvas library; none of those is selected here.

## Content structure and completion semantics

Use a small common core: stable ID, title, item type, scope/outcome, dependencies,
readiness, acceptance/definition of done and focused verification. Functional and
nonfunctional requirements, use cases, rationale and supporting links can be
appropriate optional sections. Avoid forcing every bug fix to fill a feature-sized
form. Exact schema and Markdown-versus-form round-trip rules remain undecided.

Distinguish a grouping/container item from executable work. A parent's completion
could summarize children, require its own integration acceptance, or both; this
needs an explicit rule. In particular, a child must not be blocked on completion
of its own parent if that parent can complete only after the child. Human readiness
and actual execution eligibility must remain distinct.

Preserve the existing principle that agents propose work but humans approve scope
and readiness. Editing content or arranging the graph must not manufacture runner
completion or human approval.

## What the actual repository would need to accommodate later

This is not just moving Markdown into folders:

- Root scripts/backlog.py and run-tonight.sh currently read/claim items in one
  BACKLOG.md. The nested overnight-agent toolkit is a separate consumer, not an
  automatically synchronized implementation. A visual split alone would not give
  existing runners focused context or hierarchical execution.
- The application seeds, versions and mirrors exactly PROJECT.md, AGENTS.md and
  BACKLOG.md. Current final approval/download behavior binds those three revisions.
  A tree would require item-level persistence/revisions and an approved snapshot
  covering the authoritative hierarchy, contents and dependency relationships.
  A top-level approval cannot ignore later child edits.
- Existing task and document APIs, conflict handling, proposal import, template
  provenance, worker planning-file permissions and export all assume the present
  format. Any future implementation must revise these contracts deliberately.
- PostgreSQL remains the application's authority unless separately changed. A
  directory export can represent the same data without making live host files a
  second editable source of truth. Bundle/archive export is a possible direction,
  not an approved replacement for the current three downloads.
- Imports/migrations should preserve IDs, task states, attempts, outcomes and
  branch/PR references. Existing flat backlogs must not be rewritten or renumbered
  automatically. Generated flat compatibility output is an option to investigate,
  not proof that the current parser/runner will support the new workflow unchanged.
- Future concurrency should isolate unrelated item edits while validating shared
  hierarchy/dependency changes against current revisions. Linked paths must remain
  project-scoped; Markdown links are not permission for arbitrary filesystem reads.

## Open decisions for the next discussion

1. Scope is now confirmed as a complete system overhaul. How should durable product
   specifications, operating rules and executable work be compartmentalized without
   treating every document as the same kind of backlog item?
2. Are parent items only containers, or can they also have executable/integration
   work? How is their definition of done evaluated?
3. Should the side editor begin as Markdown with guided sections, structured forms
   with a lossless Markdown representation, or both?
4. Does approval stay a single whole-plan snapshot initially, or should independently
   reviewable items have their own approval? Item-specific approval is not assumed.
5. How should existing flat backlogs remain usable and how should a tree be exported?

Suggested order of future planning: settle representation/authority and parent
semantics, then focused-context/runner compatibility, then canvas editing and
approval/export behavior. These are discussion areas, not activated backlog tasks.

## Web research — related harnesses, skills and planning systems

Read on 2026-10-14, using public primary documentation and repository sources.
The ten harnesses below are a representative comparison set, **not a verified
top-ten popularity ranking**. These are documented capabilities, not installed
version/runtime tests. Current online OpenCode documentation, for example, does
not establish support in this project's pinned 1.18.34 worker.

### What the ten harnesses offer

| Harness | Relevant documented pattern | What to borrow / important limitation |
| --- | --- | --- |
| Claude Code | [Skills](https://code.claude.com/docs/en/skills) load descriptions before full instructions/resources; [memory](https://code.claude.com/docs/en/memory) supports ancestor and just-in-time descendant CLAUDE.md guidance. | Small baseline, local scope, on-demand detail. Imports can eagerly load content; nested instructions are not a backlog scheduler or security boundary. |
| OpenAI Codex | [AGENTS.md](https://developers.openai.com/codex/guides/agents-md) builds an instruction chain from root to launch directory; [skills](https://developers.openai.com/codex/skills) use progressive disclosure. | Construct an explicit item handoff/working scope. Do not assume root-launched sessions automatically load every descendant PLAN.md. |
| Cursor | [Rules](https://cursor.com/docs/context/rules) can attach by file/path or relevance; [skills](https://cursor.com/docs/context/skills) load additional instructions/resources on demand. | Bind guidance to scope and keep references separate. Rule/skill folders do not themselves define work-item containment or prerequisites. |
| Gemini CLI | [GEMINI.md](https://geminicli.com/docs/cli/gemini-md/) supports hierarchical/just-in-time context; [skills](https://geminicli.com/docs/cli/skills/) advertise metadata and activate detailed content. | Visible context selection and local guidance. Loading/consent/access semantics are harness-specific, not a universal lazy-plan contract. |
| GitHub Copilot | [Repository/path instructions](https://docs.github.com/en/copilot/how-tos/configure-custom-instructions/add-repository-instructions) and [CLI skills](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-skills). | Separate conventions from reusable procedures. Support differs between CLI, IDE, cloud agent and review surfaces. |
| OpenCode | [Skills](https://opencode.ai/docs/skills/) advertise names/descriptions and load bodies on demand; [agents](https://opencode.ai/docs/agents/) provide delegation and parent/child sessions. | Reusable selected-item workflows and compact handoffs. No documented automatic execution of this proposed nested backlog format follows from skill support. |
| Cline | [Memory Bank](https://docs.cline.bot/best-practices/memory-bank) separates persistent Markdown context; [Agent Teams](https://docs.cline.bot/cli/agent-teams) documents coordination and shared task state. | Separate stable project knowledge from changing progress. Memory Bank is a methodology; its read-all-files example would defeat focused loading at large scale. Teams are not available identically on every surface. |
| Roo Code | [Skills](https://docs.roocode.com/features/skills) use progressive disclosure; [Boomerang Tasks](https://docs.roocode.com/features/boomerang-tasks) delegates a child and resumes the parent with its result. | Explicit downward context packages and upward summaries. This is real task delegation, not a general cross-branch dependency scheduler; conversation isolation is not filesystem isolation. |
| Aider | [Repository map](https://aider.chat/docs/repomap.html) ranks code symbols/files within a token budget; [conventions](https://aider.chat/docs/usage/conventions.html) can be loaded read-only. | Build a compact relevant planning map before reading item bodies. Its map is a code graph, not a backlog; these sources do not establish native SKILL.md discovery. |
| Goose | [Skills](https://goose-docs.ai/docs/guides/context-engineering/using-skills) load on demand; [subagents](https://goose-docs.ai/docs/guides/context-engineering/subagents) return focused results. | Parameterized work packages and concise results. Documented subagents cannot spawn further subagents, so recursive execution cannot simply mirror arbitrary folder depth. |

Common lesson: **policy, reusable procedure and work-item data are different.**
Use skills to teach operations such as selecting context or processing an item;
do not register every backlog item as a skill. A large skill catalog can consume
context just through descriptions before any item body is loaded.

The [Agent Skills specification](https://agentskills.io/specification) is especially
relevant: metadata first, then SKILL.md, then resources as needed. It recommends
focused references and avoiding deep reference chains. Borrow the disclosure
pattern, not the assumption that an arbitrary directory tree will load itself.

### Closest planning and visualization precedents

**OpenSpec — closest to self-contained change directories.**
[Concepts](https://github.com/Fission-AI/OpenSpec/blob/main/docs/concepts.md) separates
durable domain specs from proposed changes. A change folder contains proposal,
design, tasks and spec deltas; archiving preserves history and updates the current
specification. Borrow the distinction between current behavior and work that
changes it. Its artifact dependency graph orders preparation of documents, not
necessarily all executable backlog dependencies. Its normal tasks.md remains a
checklist, not one arbitrarily nested directory per task. Do not inherit its claim
that separate folders eliminate parallel conflicts: shared requirements still need
revision/merge checks.

**GitHub Spec Kit — closest to per-feature specification/plan bundles.**
The [plan template](https://github.com/github/spec-kit/blob/main/templates/plan-template.md)
places feature material under specs/<feature>/, with plan, research, contracts and
tasks. The [toolkit](https://github.com/github/spec-kit) provides skill-driven
workflows; bug fixing and idea assessment are separate entry points rather than
mandatory phases for every change. Borrow coherent feature packages and different
depth for different work. Do not copy every template/gate into tiny items, or assume
the default feature task list already solves arbitrary task hierarchies.

**Beads — closest to the task semantics and focused retrieval goal.**
The [repository](https://github.com/steveyegge/beads) explicitly targets messy
Markdown plans with a dependency-aware issue graph, hierarchical issues, single-item
lookup and work claims. Its [dependency documentation](https://github.com/steveyegge/beads/blob/main/docs/core-concepts/dependencies.md)
distinguishes relation types, ready/blocked queries and cycle checks, and documents
interactive HTML graph output. Borrow explicit edges, explainable eligibility and
durable claims/history. This is a third-party task system, not built-in Claude skill
behavior. Current docs describe Dolt-backed storage, not authoritative per-item
Markdown directories. Its parent-child blocking semantics and storage/sync policies
are not automatically the right choices for Impostr.

**BeadSpec — closest visual product found in this comparison.**
Its [README](https://github.com/boardthatpowder/BeadSpec) documents an interactive
dependency graph using React Flow/Cytoscape, workspace panes, Markdown editing and
OpenSpec artifact browsing. It is a community frontend over Beads, not a native
harness capability. Borrow graph-to-detail navigation and one write authority;
do not copy its Dolt/CLI infrastructure or treat it as a tested drop-in replacement.
Only docs were inspected; its interaction quality and large-plan performance were
not observed. The [Beads community catalog](https://github.com/steveyegge/beads/blob/main/docs/community-tools.md)
also lists tree/graph UIs and explicitly warns that old JSONL-reading viewers are
incompatible with current storage: a useful example of overhaul compatibility risk.

**Superpowers — concrete Claude-compatible skill ideas, not a task database.**
[Writing plans](https://github.com/obra/superpowers/blob/main/skills/writing-plans/SKILL.md)
recommends separate subsystem plans and explicit consumed/produced interfaces.
[Subagent-driven development](https://github.com/obra/superpowers/blob/main/skills/subagent-driven-development/SKILL.md)
uses selected-task briefs and per-plan execution records rather than making every
worker reread the whole plan. Borrow handoff completeness and surviving compaction.
Do not adopt its review loops, budgets, automatic decisions or Git policy wholesale;
those are workflow choices, not requirements for compartmentalization.

**Taskmaster — useful task/subtask model, with an adoption caution.**
[Task structure](https://tryhamster.com/docs/taskmaster/capabilities/task-structure)
documents IDs, dependencies, descriptions, details, test strategy and subtasks,
plus next/show operations. Individual text files are regenerated from tasks.json;
they are not independent writable authorities. Borrow selective retrieval and
explicit fields, not a second synchronized editable task store. Its
[license](https://github.com/eyaltoledano/claude-task-master/blob/main/LICENSE)
adds Commons Clause restrictions to MIT; do not assume unrestricted MIT reuse for
a competing/hosted product. Assess actual licensing before copying or embedding.

**BMAD — useful proportional planning, not a selected execution framework.**
The [method](https://github.com/bmad-code-org/BMAD-METHOD) packages planning and
delivery as skills and sizes the process to the work. Borrow the small-change path
and explicit durable decisions. The fetched main README distinguishes stable v6.12
from preview-alpha v7, so version-specific behavior must not be assumed stable.

**JSON Canvas / Obsidian — useful separation of files from layout.**
The [JSON Canvas 1.0 specification](https://jsoncanvas.org/spec/1.0/) defines text,
file and group nodes, coordinates and labeled edges. File nodes can reference
Markdown rather than duplicate it on the canvas. Borrow portable layout/reference
ideas. The format does not define task eligibility, typed requirement relationships,
approval, concurrent editing or execution; it is not the backlog model itself.

No reviewed primary source establishes the complete combination of this owner's
arbitrary-depth Markdown plan tree, coherent approvals, focused dependency-aware
execution and Figma-like editor. Several systems provide substantial pieces; this
is not a claim that no equivalent exists elsewhere.

### Devil's advocate: how this could fail

1. **Software is not a tree.** Authentication, privacy, performance and migrations
   cut across many features. Forcing each requirement into one branch hides relevant
   contracts; copying it into every branch causes drift. Countermeasure: one owning
   record plus explicit references and scope. A context reference is not necessarily
   a blocking prerequisite. Typed links need a small, understandable vocabulary.
2. **Less context can mean more wrong work.** A worker implementing report export
   may miss an authorization rule owned by another branch. A short generated parent
   summary can omit the decisive exception or become stale. Countermeasure: explicit
   required contracts with revisions, visible context selection, and permission to
   request more context. Summaries aid discovery; they must not silently replace
   binding rules. Compartmentalization should reduce irrelevant context, not needed
   context.
3. **The paperwork may multiply.** Root master, submaster, item requirements, use
   cases, plans and outcome files can require more maintenance than a flat list.
   Countermeasure: optional sections, shallow defaults, derived navigation/status
   and splitting only where there is a useful independent outcome. Do not create
   folders merely to make a diagram symmetrical.
4. **A beautiful graph can be less usable than a list.** Large graphs become edge
   tangles; zoom hides labels; hand-positioning nodes adds work without changing the
   plan. Countermeasure: collapsed groups, selected-neighborhood dependencies, search,
   automatic layout and a first-class outline/list. Measure whether users can find
   blocked work, not whether the screenshot looks impressive.
5. **Separate files do not mean separate changes.** Two items can modify the same
   database schema, API or source file. Every child updating a root status table also
   recreates a shared write hotspot. Countermeasure: item-local edits, derived rollups,
   revision-checked relationship updates and execution conflict checks based on actual
   shared code/contracts. Folders are organization, not concurrency isolation.
6. **Completion and approval can become misleading.** All children complete does
   not prove that the feature works together. Editing a shared spec may invalidate
   several previously approved items; closing a task does not prove its code is in
   the branch another worker uses. Countermeasure: distinguish planned/approved/
   executed state, item evidence and parent integration acceptance. Bind approval and
   execution to explicit content/code snapshots, not green nodes alone.
7. **Reorganization can rewrite meaning accidentally.** A moved node may acquire
   different inherited rules. Splitting an active item may lose attempt history or
   make an old completion appear to certify new scope. Countermeasure: stable IDs,
   preserved history and explicit rule/scope-change review; never encode identity or
   completion purely in a nested path/number. Canvas dragging must not silently
   change these meanings.
8. **The overhaul could cost more than it saves.** Parser, app database/API, worker
   context/permissions, templates, approvals, exports, imports and UI all need compatible
   changes. A new protocol plus ten harness adapters plus a canvas is several products'
   worth of surface if attempted together. Countermeasure: one harness-neutral model,
   explicit thin adapters, and staged delivery under a complete target design. A full
   target overhaul need not mean an all-at-once replacement. No staged tasks are
   approved or activated by these notes.

### Revised recommendation after research and owner response

Preserve the requested nested directory representation, but make the underlying
identity/relationship model explicit. The tree is an important organizing view;
it cannot be the only meaning of the data. UI, runner and exports should agree on
the same item/spec identities and relationships, without competing writable copies.

Use OpenSpec as the main conceptual reference and Superpowers as a source of
selected planning/handoff patterns. Review GitHub Spec Kit selectively. Beads is
not the intended foundation; Beads/BeadSpec and the other researched systems remain
optional comparisons, not components of a prescribed hybrid. Progressive disclosure
and compact context maps are useful techniques independent of framework adoption.

Design for the owner's specialized needs as they emerge, rather than forcing those
needs into any existing framework's model. No final architecture, format or dependency
selection has been made. Do not install or adopt a framework on the strength of this
research. Review licenses, security behavior and pinned interfaces before future reuse.

Before committing to a format, a later planning exercise should walk through a
small bug, a multi-part feature and a cross-cutting change. Show exactly which
documents a worker would read, which contracts must remain shared, what a move or
shared-rule edit invalidates, and what completion means at each level. Compare
context needed, navigation effort and maintenance against the current format.
This is a suggested way to test the idea, not a request to run a prototype now.

The success criterion is not "everything has its own folder." It is "people and
agents can safely work on one part without losing the constraints that make the
whole system correct."
