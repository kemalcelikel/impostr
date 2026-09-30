---
name: sprint-workflow
description: Use ONLY when the project/user selects sprint-workflow for task branches, human-merged PRs, and approved sprint planning updates.
---

# Sprint workflow

Read AGENTS.md for commands/provider/access and BACKLOG.md for the existing sprint:

```markdown
Sprint branch: sprint-v29
```

Default remote is origin (runner override: SPRINT_REMOTE). Task PRs target this sprint;
the final sprint PR targets development. Humans perform all merges. Never force-push,
rewrite history, skip hooks, deploy, or use pull/rebase/cherry-pick to integrate.
Use existing authentication; never expose tokens or install tools to bypass a blocker.

## Planning

Tech-lead may commit/push owner-approved PROJECT.md, AGENTS.md, and BACKLOG.md updates
on the existing declared sprint. Fetch and confirm aligned baseline before editing;
fetch again before publishing. Stop if the sprint moved. Stage only intended planning
files and push git push origin HEAD:refs/heads/<SPRINT_BRANCH>; verify the head.
Do not overwrite task outcomes, work in an active runner checkout, or create a missing
sprint baseline. Other remotes need matching tool permissions.

## Task delivery

1. Read the assignment and inspect partial work. Start new task branches from the
   fetched sprint tip. Use an explicit Branch when supplied, otherwise a descriptive
   feature/* or bug/* name. Resume the correct existing branch; never overwrite it.
   Dependencies must be integrated into the sprint, not merely in open PRs.
2. Implement and run focused/essential checks. Independent review is selective,
   following agent/project policy; optional suggestions do not block delivery.
3. Commit intended task changes. Selecting this workflow authorizes overnight to push
   its assigned task branch and submit a PR unless the project is stricter. Push one
   explicit destination: git push origin HEAD:refs/heads/feature/<name> (or bug/<name>).
   Verify published HEAD. Never push the sprint or protected branches for task delivery.
4. Reuse an existing source-to-sprint PR or create one with explicit destination.
   Include a short summary and actual check results. After uncertain API errors check
   for an existing PR before retrying. Record Branch/PR and mark [x] only after delivery.
5. Commit/push final backlog outcome/PR metadata and the brief DONE.md session entry
   on the same task branch. Verify the published head. Metadata-only changes do not
   invalidate code checks/review.
   If delivery fails, preserve the code and record the remaining step as a blocker.

## Continue the run

One task per sprint session, many sessions per run. Leave a completed session on its
clean, fully committed/published task branch. The runner fetches and returns to the
aligned sprint for the next independent task. It reconciles terminal task records by
ID (or unique legacy title) from the just-finished branch so submitted/blocked tasks are not selected again;
those reconciled records reach the sprint through subsequent planning/task commits.
Never replace the entire sprint backlog with an older task copy.

Waiting on a human merge is normal: skip dependent tasks and keep working on eligible
independent tasks. Stop when none remain. If dirty partial task work prevents switching,
preserve it and stop for recovery rather than stashing/resetting or committing broken
code. Clean committed partial work stays on its task branch; record its branch/checkpoint.

The runner checks completion records in the fetched sprint before claiming consumers;
locally carried outcomes from unmerged tasks are waiting. Old completed tasks need no
PR/branch metadata. The coordinator still checks prerequisite code actually exists.
Unknown/prose dependencies wait for reconciliation while independent work continues.
At a later launch fetch/align the declared sprint first. Do not launch from an unfinished
task checkout; ask tech-lead to recover that task in place.

## Hosting

For Bitbucket Cloud use existing configured authentication (for example
BITBUCKET_API_TOKEN) with https://api.bitbucket.org/2.0/repositories/{workspace}/{repo}:
GET /pullrequests to find an existing PR; GET /pullrequests/{id} to check state;
POST /pullrequests with title, description, source.branch.name, and explicit
destination.branch.name. Git and API credentials can be different. No merge endpoint.
For another selected provider use its configured CLI/API; never guess the destination
or send credentials to another host. Authentication failure is a delivery blocker.

## Sprint finalization

Only when assigned, confirm intended task PRs are merged and run focused combined
integration checks plus explicit release gates. Open/reuse sprint-to-development PR
with the explicit destination. Optional review notes do not restart the sprint.
Record the URL and report delivery; humans merge/release. Do not push the sprint to
record implementation outcomes or treat open task PRs as integrated work.

For new finalization tasks use ordinary comma-separated dependency IDs. Tech-lead can
reconcile older prose dependencies in place without rebuilding the backlog.
Keep operational notes short; no duplicate plans, reports, or tracking systems.
