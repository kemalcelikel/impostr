---
name: sprint-workflow
description: Use ONLY when project instructions or the user explicitly select
  sprint-workflow for sprint-based feature/bug branches and pull requests. Covers
  approved tech-lead planning pushes, Bitbucket Cloud delivery, human-only merges,
  and final sprint pull requests.
---

# Sprint workflow

This is an opt-in project workflow. `tech-lead` plans interactively with the owner
and may publish approved planning files to the declared sprint. The runner-launched
`overnight` coordinator handles task delivery: developer implements and proposes
branch names; reviewer performs independent review; overnight manages task Git,
PRs, and outcomes. The skill does not install tools, grant tool permissions, or
change reviewer behavior.

## Project context

Read AGENTS.md for commands, access setup, repository details, and any explicit
project exceptions. Read PROJECT.md for product/contracts and BACKLOG.md for the
active sprint and assignments. A minimal backlog header is:

```markdown
# Sprint v29

Sprint branch: sprint-v29
Version control: Bitbucket Cloud
```

The owner starts the sprint from `development` and publishes its baseline. Do not
assume master and development have identical commits; use the declared sprint.
Feature/bug PRs target that sprint. The final sprint PR always targets `development`.
Use the project's `BACKLOG.md` rather than inventing a separate configuration.
Start new task branches from the fetched sprint tip. After a human merges a task
PR, confirm the sprint contains its delivered backlog outcome before assigning
dependent work. Do not copy task-branch backlog state over newer sprint work.

Discover the repository from the configured Git remote and reconcile it with any
declared workspace/repository. Default remote is `origin`. Missing or contradictory
sprint/repository details must be resolved before Git writes or PR submission.
The sprint branch must exist remotely before opening PRs against it. `tech-lead`
may update an existing sprint with approved planning files, but no agent creates
or pushes a missing sprint baseline to fix setup.

## Git permissions and ownership

- Never merge locally or through a hosting API, enable auto-merge, or approve your
  own PR on behalf of a human. Humans perform every feature/bug and sprint merge.
- Do not use pull, rebase, or cherry-pick to bypass that rule. Fetching refs and
  creating/checking out task branches are allowed when the working state permits.
- For implementation, push only the assigned `feature/*` or `bug/*` branch after
  verification. `overnight` never pushes to the declared sprint branch. Only
  `tech-lead` may directly publish owner-approved planning changes there as below.
  Never force-push, push multiple refs at once, push tags, or push to `development`,
  `master`, or any other integration branch.
- Selecting this workflow authorizes those narrowly scoped task-branch pushes and
  PR submissions unless project instructions are stricter. The global `overnight`
  agent permits explicit `origin` feature/bug pushes; other remotes need owner-provided
  tool permissions. Report a permission block; never modify your own permissions or
  use a different transport/API to bypass it.
- Preserve user changes, other branches, and backlog status when switching branches.
  One coordinator owns a checkout. If switching cannot be done safely, report the
  blocker rather than discarding, force-switching, or copying a stale backlog over it.

## Planning on the sprint (tech-lead only)

The owner can work interactively with `tech-lead` to establish or revise PROJECT.md,
AGENTS.md, and future BACKLOG.md work. After owner approval, `tech-lead` may commit
**only those planning files** directly on the already published sprint branch named
in BACKLOG.md and push that branch. This is the sole direct-sprint-push exception;
implementation, bug fixes, and task outcomes still arrive through human-merged PRs.

Before editing, fetch and confirm the checkout is on the declared sprint and matches
its remote-tracking tip. Do not edit an active runner's checkout or switch from
partial task work. Preserve completed/blocked status, task IDs, branch/PR links,
and attempts; replan future work without overwriting newer delivery outcomes.
Before pushing, inspect the planning-only commit and fetch again. If the sprint has
moved, stop for owner reconciliation without pull/rebase/merge or force. Push one
explicit refspec, `git push origin HEAD:refs/heads/<SPRINT_BRANCH>`, substituting the
actual declared branch; verify the published head and refresh the remote-tracking
ref so it matches local HEAD before starting the runner. The global tech-lead permission
allows this `origin` form but denies known integration and task destinations. A
different remote requires owner-provided tool permission. The runner starts only
when local sprint HEAD and its remote-tracking ref agree.

## Feature or bug delivery

The runner starts new work from an aligned sprint checkout and does not require a
clean working tree. Inspect and preserve existing edits; do not commit broken work
merely to launch it. Keep interrupted partial task-branch work in its checkout
rather than force-switching back to the sprint.

1. Read the assigned item and dependencies. Use `Type: feature` or `Type: bug` and
   an explicit `Branch:` when provided. Otherwise, developer may propose a short
   descriptive name such as `feature/accounts` or `bug/monitoring`; coordinator
   creates it after checking for existing work with that name. Resume the correct
   existing branch rather than overwriting or recreating it.
2. Fetch `origin` and inspect the current sprint tip. Create new work from the
   up-to-date sprint, for example `git switch -c feature/accounts origin/sprint-v29`.
   Record the exact starting commit for review. A dependency's `[x]` is insufficient
   if its PR is unmerged: required code must be in the sprint before dependent work
   starts. Do not silently stack branches or copy/cherry-pick the missing feature.
3. Wait for the project's existing verification and reviewer approval before
   delivery. Follow the agent/project instructions for that work.
4. Commit intended changes only, following the project convention. Do not make an
   empty commit for work that already exists and has been verified.
5. Inspect current branch, status, the complete task diff/commits, and the exact
   commit being delivered. Confirm it is the assigned task branch and contains
   no unrelated work. Push a single explicit destination, for example:

   `git push origin HEAD:refs/heads/feature/accounts`

   Use the corresponding `bug/…` destination for a bug. The destination must match
    the current assigned branch. Do not add force flags, extra refspecs, or use a
    different remote to get around a rejection. Verify the published head matches
    the tested local commit.
6. Look for an existing PR with this source and sprint destination before creating
   one. Open a normal review-ready PR, or a draft if the project explicitly requests
   one. Include the task IDs, concise delivery summary, and existing verification
   evidence. After an uncertain API failure,
   check whether the PR was created before retrying.
7. Record `Branch:` and `PR:` in the backlog item and mark `[x]` after PR submission.
   Commit this bookkeeping on the same task branch and push the updated head using
   the same explicit refspec. Verify the PR now contains the recorded outcome/URL
   and the published head; the code checks and review remain associated with the
   earlier code revision if only backlog metadata changed. This makes task state
   available to the sprint after the human merge. If either push, authentication,
   or PR submission is blocked, preserve the implementation and record `[!]` with
   the remaining delivery step locally; do not call it delivered.

## Bitbucket Cloud pull requests

For `bitbucket.org`, use the Bitbucket Cloud REST API with existing owner-configured
authentication. No new helper script or MCP server is required. Git authentication
and API authentication may be separate (for example SSH for Git and a scoped API
token for HTTP). Never place tokens in Markdown, remote URLs, PR text, or logs.

Repository endpoint:

`https://api.bitbucket.org/2.0/repositories/{workspace}/{repo_slug}`

- List/find PRs: `GET .../pullrequests`; follow pagination/filtering as needed.
- Read a recorded PR and its actual state: `GET .../pullrequests/{id}`.
- Create a PR: `POST .../pullrequests`, supplying title, description, source, and
  **explicit destination**. Omitting destination can target the repository's main
  branch instead of the sprint.
- Never call a merge endpoint or enable automatic merging. Do not escalate access,
  create tokens, fork a repository, or install tooling when authentication fails.

Example creation payload (request data, not a project configuration file):

```json
{
  "title": "TASK-001: Accounts management",
  "description": "Summary and actual verification results",
  "source": { "branch": { "name": "feature/accounts" } },
  "destination": { "branch": { "name": "sprint-v29" } }
}
```

Use the existing `BITBUCKET_API_TOKEN` environment credential when provisioned, or
the alternative authentication mechanism named in AGENTS.md. A scoped Bitbucket
Cloud API token needs PR read/write access for these operations, plus repository
read access for any commit/status queries. If that token is also used for Git
pushes, it needs the appropriate repository write scope. Credential setup belongs
to the owner; never expose a token while checking access.

If a project explicitly selects a different host, use its existing supported
CLI/API with the same explicit source/destination and no-merge rules. Do not send
Bitbucket credentials to another host. Missing provider instructions are a setup
question, not a reason to default to GitHub or create more tooling.

## Human integration and sprint completion

Humans merge feature/bug PRs into the sprint. `[x]` records submitted work, so the
coordinator must check actual PR states and sprint contents before declaring the
sprint ready. A declined PR or intentionally deferred item needs an explicit
scope decision; never silently treat it as integrated.

Run finalization only when assigned, either directly or as a final backlog item:

```markdown
## [-] TASK-099 — Validate sprint and open development PR
Type: sprint-finalization
Depends on: All intended feature/bug PRs merged into the active sprint

Done looks like:
- Existing project verification and review are complete for the combined sprint.
- A sprint-to-development PR is open and its URL is recorded.
```

1. Confirm all intended work is merged into the sprint, or explicitly removed from
   scope by the owner. If waiting on human merges, record the blocker and stop that
   stage; do not repeatedly implement completed tasks or wait indefinitely. The
   owner can reassign a blocked finalization item after completing the merges.
2. Fetch the current sprint and check its exact commit in a clean, appropriate
   checkout without merging/pulling. A detached checkout of the fetched sprint tip
   is acceptable for read-only verification; never implement or commit there.
3. Obtain the normal project verification and review outcome for this combined
   revision before delivery. If defects are found, route fixes through bug branches
   and PRs back to the sprint; do not patch or push the sprint directly.
 4. Confirm the remote sprint tip still equals the verified commit. If it moved,
   return the updated revision for normal verification. Open/reuse the PR with source
   equal to the active sprint and destination **`development`**. No sprint push is
    needed for this step: task updates arrived through human-merged PRs, while
    planning-only updates may have been published by `tech-lead`.
5. Report the PR and test evidence. Do not merge it, update development/master,
   or claim the sprint has been released. Humans complete those steps.

Use the existing backlog and brief progress/final summaries. Avoid duplicate PRs,
per-step writeups, a new queue format, or a parallel state-tracking system.

## References

- [Bitbucket Cloud pull requests API](https://developer.atlassian.com/cloud/bitbucket/rest/api-group-pullrequests/)
- [Bitbucket Cloud API token usage](https://support.atlassian.com/bitbucket-cloud/docs/using-api-tokens/)
