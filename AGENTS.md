# Repository agent guide: Impostr

## Read first

- Product, architecture and domain rules: `PROJECT.md`.
- Active scope, task state and dependencies: `BACKLOG.md`.
- Completed task specifications and outcomes: `docs/backlog-completed.md`.
- Setup, Compose, chat and backup/restore: `docs/local-development.md`.
- Earlier decisions and verification constraints: `docs/agent-history.md` and the
  existing history documents. Historical checkpoints are not active assignments.

PROJECT.md contains current product contracts; this file contains operating conventions
and verified commands. Neither is a changelog. Update existing sections when behavior
changes; do not append dated notes, task histories, commit references, attempt counts
or delivery reports. Keep outcomes with their task; archive completed task blocks
intact in `docs/backlog-completed.md`, without summaries in the active backlog.
Completed prerequisites are satisfied; omit them from active dependency declarations.
Keep superseded decisions in the existing history documents, not duplicate handoffs.

## Keep execution simple

- Reuse existing code and dependencies; choose the smallest adequate change.
- Coordinator owns planning documents, task state, Git and Docker operations;
  delegate application implementation. Use one coordinator per checkout.
- Check changed behavior and realistic risks. Reuse valid evidence; no coverage targets,
  exhaustive matrices or mandatory whole-suite runs for every edit.
- Independently review substantial/security/data-sensitive changes. Concrete important
  defects block delivery; optional polish does not.
- Respect deferred browser/provider/restore acceptance in task records and the runbook. Do not
  claim it passed, reopen stopped verification or launch a runner unless requested.
- Ordinary formatting and focused checks need no extra approval. Preserve repair
  attempts; stop on exhausted scope or an essential tool denial, without bypasses.
- Finish with what changed, what was checked and what remains, usually five bullets or fewer.

## Verified commands

From the repository root, when relevant:

- Backlog parsing: `python3 -B scripts/backlog.py list-all BACKLOG.md`
- Queue eligibility: `python3 -B scripts/backlog.py count-eligible BACKLOG.md`
- Whitespace: `git diff --check` (focus paths when unrelated work is dirty).
- Native helper tests: `/usr/bin/python3 -B -m unittest discover -s scripts -p 'test_imp025_*.py'`

Use the root backlog parser/helper, not the nested toolkit's sprint defaults.
Native candidate/fixture checks retain their exact-input and cleanup requirements.

Web checks use the existing `web/Dockerfile` **checks** target with pinned
Node22.17.0/npm10.9.2. Inside `/web`: `npm run build` and
`npm run test -- src/canvasState.test.ts src/CardCanvas.test.tsx src/ProjectWorkspace.test.tsx`.
Use existing ESLint/Prettier for changed files. Do not use incompatible host Node24/npm11.

## Code and environment conventions

- API: `api/` (Python/FastAPI/SQLAlchemy/Alembic); UI: `web/` (Vite/React/TypeScript/Tailwind).
  Pin dependencies in existing manifests/locks; do not hand-edit generated lockfiles.
  Use forward migrations; preserve originals, approvals, revisions and template provenance.
- Generate npm locks in the pinned container; do not weaken engine-strict or install
  tooling/skills without authorization. Docker is not exposed to implementation agents.
- Starter inputs are `overnight-agent/{PROJECT,AGENTS,BACKLOG}.md.example`; keep them
  immutable. `/workspaces` is a disposable API mirror, not the agent workspace.
- Preserve the application's authorization, data and worker-isolation contracts in
  PROJECT.md. Shared Playwright is not OS-confined; do not use its incidental host access.

## Git and task state

- Work on the owner-selected branch, currently `feature/canvas`; do not use the old
  batch's branch or sprint fields as instructions to switch.
- Inspect status, intended diff and recent history before Git writes. Stage only
  intended files/hunks. Commit, push or change branches only when authorized.
- Subagents do not write Git or change task state. No merges, force pushes, history
  rewriting, skipped hooks, discarded user work or Git initialization for exports.
- Do not commit secrets, dumps, logins/cookies, private artifacts, runner logs or progress.md.
- Preserve stable task IDs, dependencies, completed work and attempt history. Markers:
  `[ ]` approved ready; `[~]` claimed; `[!]` blocked; `[-]` draft/deferred;
  `[x]` verified and locally committed, not necessarily merged or manually accepted.
- Do not reset another run's claim or requeue unrelated blockers. Keep progress.md and
  DONE.md as their existing compact checkpoint/summary, not new repeated handoffs.
