# Repository agent rules: Impostr

## Sources and current state

- `PROJECT.md` is the product, data, security and UI contract; `BACKLOG.md` holds
  future slices and readiness. Root `.example` files are the canonical _inputs_
  for Impostr-created projects, not Impostr's live instructions. Root
  `scripts/backlog.py` defines the compatible backlog parser/eligibility behavior.
- `overnight-agent/agents/` contains the distribution agent definitions. The
  current OpenCode CLI can list the installed `tech-lead`, `architect`,
  `ui-designer`, `developer`, `senior-developer`, `reviewer`, `docs` and `overnight`.
  `overnight` is runner-only; web planning uses `tech-lead`.
- This checkout has no Impostr application manifests, DB schema, Compose file, UI
  tests, configured app URL, or test login. Do not substitute the toolkit's fake
  runner tests for application tests. Record concrete setup/check commands here
  when bootstrap has implemented and verified them; never execute a placeholder.
- The current branch is `v1`; root Git remote is GitHub `origin`. After the owner
  published the first draft, local `v1` and `origin/v1` were observed aligned at
  `7fca090`. Fetch and recheck before future Git writes/publication; do not assume
  this alignment persists. The installed sprint skill is selected with the GitHub
  exceptions below, not its Bitbucket-specific API examples.

## Start of work and delegation

Read the assignment and relevant project contract; inspect `git status --short`
and recent history before changing files. Preserve existing/untracked work and
record the baseline. `tech-lead` and owner decide future backlog scope/readiness;
`architect` resolves new trust/contract boundaries, `ui-designer` sets material UI
direction and reviews rendered screens, developer implements, and reviewer
independently reviews significant behavior, especially identity, multi-project
authorization, agent isolation, revisions and export. Docs follows a stable feature
batch. Subagents do not independently change task status or commit. No agent
installs/updates skills or tooling to make missing capabilities appear present.

Generated items are `[-]` until owner approval of their readiness. Do not claim
or reset another run's `[~]`, or requeue `[!]` without owner approval. The root
runner is **not selected to implement this draft backlog**: although this repo
already has an aligned published sprint branch and a committed first draft, it
still needs owner-approved `[ ]` items and verified Docker, isolated agent access,
checks and GitHub PR capability. Do not run it just because it exists here. For
future user-created projects, exporting files does not initialize a repo or make
its runner safe to launch. Avoid two writers in the same checkout or the same
project's planning files.

## Verified commands and capability gaps

Commands below were observed on this checkout; app-specific commands do not
exist yet. Run from repository root unless otherwise stated.

| Purpose                                                                                     | Command                                                                      | Observed status / limitation                                                                                          |
| ------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| Toolkit runner regression                                                                   | `python3 -m unittest discover -s scripts -p 'test_*.py'`                     | Verified: six passing tests with fake OpenCode, not Impostr app tests.                                                |
| Backlog parser smoke                                                                        | `python3 scripts/backlog.py list-all BACKLOG.md.example`                     | Verified against starter backlog; use `BACKLOG.md` for the live plan after drafting.                                  |
| Inspect agent availability                                                                  | `opencode agent list`                                                        | Verified CLI responds and includes relevant agents; not a live web integration test.                                  |
| Toolchain inspection                                                                        | `python3 --version`; `node --version`; `npm --version`; `opencode --version` | Observed Python 3.10.12, Node v24.12.0, npm 11.6.2, OpenCode 1.18.32 on this host; not the planned runtime baselines. |
| Docker/Compose, PostgreSQL                                                                  | Not runnable in this shell (`docker` not found)                              | Operator must provision and verify the deployment host.                                                               |
| GitHub PR tooling                                                                           | `gh` not found in this shell                                                  | Owner must provision usable GitHub CLI/auth or agree a supported, permitted alternative before PR delivery.           |
| App install/start, migrations, focused/integration/UI tests, lint, format, typecheck, build | Not defined: no app exists                                                   | Bootstrap slice must implement and verify exact commands, fixtures and services before promoting dependent work.      |
| Secret/dependency/security/container checks                                                 | Not configured                                                               | Define tested commands and severity/finding policy before shared-server release; do not claim passing gates.          |

When the app exists, document its exact working directory, pinned runtime and
lockfiles, Compose commands, migration commands, test account setup, dev/prod
URLs, browser viewports, and check/CI commands here. Do not commit secrets, DB
dumps, private transcripts, provider config or `.opencode/progress.md`/runner logs.
Use real locally provisioned model credentials, never copied sample secrets.
The installed `ui-ux-pro-max` and `ui-styling` skills are optional design aids;
the `ui-designer` may use them without reinstalling them. Browser rendering tools
are available to this planning environment, but app URL and browser-test command
are unconfigured until bootstrap.

## Implementation and review boundaries

- Follow `PROJECT.md` for ownership, revision/approval invariants, agent runtime
  isolation and export behavior. A browser check or client-side state restriction
  never replaces server authorization; test cross-user/project/session access and
  stale-version behavior. Keep privileged model/DB/network configuration outside
  agent workspaces and Git.
- Protect root templates and runner/parser compatibility; if changing their
  semantics, separately scope regression tests and migration/compatibility work.
  Keep user-created project workspaces away from other projects and this repo's
  live planning files. Do not hand-edit generated lockfiles or compiled assets.
- Pin actual dependencies and commit manifests/lockfiles during bootstrap. Use
  Alembic migrations for schema changes with upgrade/recovery evidence. For
  security findings, report reproducible impact and blocked checks; only the
  owner may explicitly accept residual risk. Do not disable checks to pass CI.
- Review the entire baseline-to-result change, run relevant focused tests plus
  established gates, then obtain independent review for security/data-contract
  changes and rendered design review for material UI changes. Update operational
  docs once the feature batch stabilizes. A task is complete only after its own
  acceptance and actual verification pass; report unavailable services honestly.

## Git, workflow and reporting

Use the installed `sprint-workflow` skill for branching and pull requests.
The active sprint is recorded in BACKLOG.md.

GitHub exceptions/owner decisions: the existing sprint branch is `v1` on `origin`;
feature/bug task PRs explicitly target `v1`, and a final sprint PR targets
`development`. All merges are human actions. Use existing GitHub authentication and
`gh` for listing, creating and inspecting PRs once verified; the Bitbucket Cloud
API/token instructions in the skill do not apply. Do not invent PR numbers, URLs,
credentials, a GitHub API transport, or a different remote to bypass a denial.
The owner prefers verified local commits if PR capability is unavailable; in that
case preserve the code/branch and report the delivery block rather than marking a
task `[x]` as PR-delivered or pushing to another destination. A GitHub PR is not a
merge; fetch and verify `v1` contains prerequisite code before a dependent task.

This workflow selects the runner's one-task sprint mode, **not** authorization to
run it now. All current items are owner-designated drafts; the owner must separately
approve ready IDs after their prerequisites and commands are verified. Planning
file commits/pushes to the existing aligned `v1` are limited to owner-approved
`PROJECT.md`, `AGENTS.md`, `BACKLOG.md` changes under the selected skill; do not
include task code or unrelated files. Never push `development`, `master`, `main`,
or `v1` on implicit authority; never merge or force-push. No agent initializes a
Git repo for an Impostr-created project merely because its files were exported.

The coordinator owns delivery outcomes: `[ ]` owner-approved ready, `[~]` claimed,
`[x]` verified complete under the chosen delivery policy, `[!]` blocked with
checkpoint, and `[-]` draft/deferred. `[-]` and `[ ]` are the first-release web
editor's only writable task markers. The root helper considers dependency-
eligible only a ready item whose declared prerequisites are `[x]`; a submitted PR
is not proof of integrated code. Preserve stable task IDs, previous attempts,
branch/PR references and other checkout changes when replanning.

For runner attempts, `.opencode/progress.md` is the compact recovery record and
`DONE.md` is the existing runner's batch summary; neither is an app transcript.
Finish with one concise report of changed paths, verification and blockers. No
application URL, CI job, credential name or deployment command is implied here.
