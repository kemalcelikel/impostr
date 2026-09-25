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
- The planning checkout is on `v1`; root Git remote is GitHub `origin`. Local
  `v1` and `origin/v1` were observed aligned at `1731c81`; fetch and recheck
  before publication or starting a work branch. The owner approved replacing
  the selected sprint flow with the single-branch batch contract below; do not
  run under the new contract until it has been published.

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
runner is **not yet authorized to implement this unpublished backlog**: publish the
approved batch contract and readiness markers, then create the work branch from
the aligned published baseline. Do not run it just because it exists here. For
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
| Docker/Compose baseline | `docker info --format '{{.ServerVersion}}'`; `docker compose version` | Verified in refreshed agent session: Docker server 29.8.0 and Compose v5.5.1. Owner separately exercised `docker run hello-world`. No Impostr DB/Compose service exists yet. Docker socket access is host-root-equivalent; web planning agents must not receive it. |
| GitHub PR tooling (read-only) | `gh --version`; `gh repo view --json nameWithOwner -q .nameWithOwner`; `gh pr list --state open --json number,headRefName,baseRefName --limit 20` | Verified GitHub CLI 2.101.0 is authenticated and can read `kemalcelikel/impostr`; PR creation and new branch push have not been exercised. Do not log tokens. |
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

Owner-approved workflow, pending publication: **single-branch batch,
not sprint mode**. The published `origin/v1` is the starting baseline. The owner
creates `feature/impostr-v1` from the fetched, aligned `origin/v1` after the plan
and readiness markers are published, and runs the root `run-tonight.sh` from that
work branch, not from `v1`. In non-sprint mode the runner can claim up to three
currently dependency-eligible tasks per session and continue while eligible work
remains; timeouts, failed checks and dependency blocks may stop it early.

Keep implementation, migrations, tests, and backlog outcomes on **the same work
branch**. After each item passes its actual checks and independent review where
required, verified local commits may record it. `[x]` means locally verified and
committed in that branch, not PR-submitted or merged. There are no per-task PRs
or pushes. Do not start a dependent item until its prerequisite's `[x]` code is
already in the same branch. Leave failed or unverified items `[!]` with blocker,
attempt and partial-work evidence; continue only independent eligible items. Do
not skip tests or claim unavailable services passed to drain the queue. A later
run resumes the same branch and reviews earlier outcomes. Do not reset another
run's active claim or requeue a blocker without the owner's decision.

After all in-scope feature items are verified on that branch, finalization checks
the whole branch. `overnight` may push only the checked
`feature/impostr-v1` head to `origin` and open/reuse **one** review-ready GitHub
PR with explicit source `feature/impostr-v1` and destination `development`, using
existing `gh` authentication. Verify the published head and PR contents/URL. If
push or PR submission fails, preserve local commits and mark final delivery
blocked; never substitute another transport. Humans perform every merge. No
agent pushes `v1`, `development`, `master` or `main`, force-pushes, or merges;
no agent initializes Git for an Impostr-created project on export.

The tech-lead may publish this **approved planning-only transition** on the
existing aligned `v1` under the *previously selected* sprint skill before the
work branch starts. This exception does not extend to code or runner outcomes.
After publication, the explicit single-branch policy above governs delivery.

The coordinator owns delivery outcomes: `[ ]` owner-approved ready, `[~]` claimed,
`[x]` verified/committed in the work branch, `[!]` blocked with
checkpoint, and `[-]` draft/deferred. `[-]` and `[ ]` are the first-release web
editor's only writable task markers. The root helper considers dependency-
eligible only a ready item whose declared prerequisites are `[x]`; a submitted PR
is not proof of integrated code. Preserve stable task IDs, previous attempts,
branch/PR references and other checkout changes when replanning.

For runner attempts, `.opencode/progress.md` is the compact recovery record and
`DONE.md` is the existing runner's batch summary; neither is an app transcript.
Finish with one concise report of changed paths, verification and blockers. No
application URL, CI job, credential name or deployment command is implied here.
