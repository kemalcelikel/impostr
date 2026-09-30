# Team OpenCode agents

Shared agents, project templates, and optional skills for interactive and overnight work.

## What goes where?

| Location                                                                                                | Purpose                                                                                   |
| ------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| Project `PROJECT.md`                                                                                    | Product, architecture, contracts, and acceptance criteria                                 |
| Project `AGENTS.md`                                                                                     | Project rules, selected workflow, check commands, app URL, test login, and target devices |
| Project `BACKLOG.md`                                                                                    | Active sprint, tasks, dependencies, branches, and PR links                                |
| Project `opencode.json` / `opencode.jsonc`                                                              | Project-specific MCP tools and permission overrides, when needed                          |
| Global [`tech-lead`](agents/tech-lead.md)                                                               | Interactive technical planning, project setup, and approved sprint planning updates       |
| Global [`architect`](agents/architect.md) / [`reviewer`](agents/reviewer.md) / [`docs`](agents/docs.md) | Planning, independent review, and documentation after work stabilizes                     |
| Global [`developer`](agents/developer.md) / [`senior-developer`](agents/senior-developer.md)            | Implementation and checks; the senior developer handles escalated work                    |
| Global [`ui-designer`](agents/ui-designer.md)                                                           | Design decisions and rendered browser review                                              |
| Global [`overnight`](agents/overnight.md)                                                               | Runner-only execution coordination, task Git/PR delivery, and backlog outcomes            |
| Toolkit `project-skills/` → project `.opencode/skills/`                                                 | Opt-in skills, installed only in projects that need them                                  |

## 1. Install the agents

Install [OpenCode](https://opencode.ai/docs/) and configure your provider. From this
toolkit checkout:

```bash
mkdir -p "$HOME/.config/opencode/agents"
cp -i agents/*.md "$HOME/.config/opencode/agents/"
```

Each agent's Markdown frontmatter contains its `model`, `reasoningEffort`, and
permissions; edit that file to change the agent. Keep provider/resource settings
and global defaults in `opencode.json`, preserving your own authentication.
`opencode models` lists available IDs.

| Agent                   | Model      | Effort |
| ----------------------- | ---------- | ------ |
| Architect               | GPT-6 Sol  | High   |
| Tech lead               | GPT-6 Sol  | Medium |
| Developer               | GPT-6 Luna | Medium |
| Senior developer        | GPT-6 Sol  | High   |
| Reviewer                | GPT-6 Sol  | Medium |
| Overnight / UI-designer | GPT-6 Sol  | Medium |
| Docs                    | GPT-6 Luna | Low    |

`senior-developer.md` is a standalone agent with independently editable instructions.
Overnight gives routine findings one focused repair attempt, then escalates when
needed; both developers share the task's repair budget. Independent review is
selective: substantial or higher-risk changes, with concrete important defects
blocking delivery. Optional coverage and polish are notes.

The default interactive model is Sol; small utility tasks use Luna. Deployment IDs
are `gpt-6-sol` and `gpt-6-luna` on the same Azure resource. Model usage estimates:
`opencode stats --models --days 7`. Model routing is independent of project Git skills.
OpenCode's built-in `build` agent remains the default for ordinary interactive work.
Select `tech-lead` for interactive project setup or backlog replanning (for example,
`opencode --agent tech-lead`); `overnight` is selected only by the runner.

## 2. Prepare an application repo

From the application's root, set the toolkit path and copy the starters:

```bash
TOOLKIT=/path/to/opencode-team
cp -i "$TOOLKIT/PROJECT.md.example" PROJECT.md
cp -i "$TOOLKIT/AGENTS.md.example" AGENTS.md
cp -i "$TOOLKIT/BACKLOG.md.example" BACKLOG.md
mkdir -p scripts
cp -i "$TOOLKIT/scripts/backlog.py" scripts/backlog.py
cp -i "$TOOLKIT/run-tonight.sh" ./run-tonight.sh
```

Fill placeholders and remove irrelevant sections. Keep these Markdown files in
the application repo, not the global OpenCode directory. `backlog.py` is the only
helper and requires Python 3.10+.

Work with `tech-lead` to turn a spec or idea into PROJECT.md, AGENTS.md, and scoped
BACKLOG.md items; use `architect` for consequential design decisions.
Use `[ ]` ready, `[~]` running, `[x]` delivered, `[!]` blocked, and `[-]` draft/deferred.
The helper selects dependency-eligible items in file order; agents verify that
required code is actually integrated before working on dependents.
Initialize and commit the application repository yourself before launching the runner;
it will stop if there is no existing Git history or the project root is not the repo root.

## 3. Optional: install the sprint workflow

**Why `project-skills/`?** It is this toolkit's distribution folder, not an OpenCode
installation path. If the toolkit lives at `~/.config/opencode/`, naming it `skills/`
would make its contents globally discoverable. The project installation path is
**`.opencode/skills/<skill-name>/SKILL.md`**.

From the application root:

```bash
mkdir -p .opencode/skills/sprint-workflow
cp -i "$TOOLKIT/project-skills/sprint-workflow/SKILL.md" .opencode/skills/sprint-workflow/SKILL.md
```

Add to the project's `AGENTS.md`:

```markdown
Use the installed `sprint-workflow` skill for branching and pull requests.
The active sprint is recorded in BACKLOG.md.
```

In `BACKLOG.md`, declare the actual sprint branch (its name is not required to
start with `sprint-`):

```markdown
# Sprint v29

Sprint branch: <ACTIVE_SPRINT_BRANCH>
Version control: Bitbucket Cloud
```

The [skill](project-skills/sprint-workflow/SKILL.md) handles feature/bug → sprint →
development PR delivery. Provide existing Git authentication and Bitbucket API
access, such as `BITBUCKET_API_TOKEN`, outside Markdown. **Humans perform all merges.**
The runner detects the selected skill via the exact `AGENTS.md` line above. It requires
the checkout to start on the declared sprint branch at the local remote-tracking
`<remote>/<sprint>` tip; it does not fetch itself. Fetch before launching the runner.
It assigns one item per session and continues through independent tasks. After clean
task delivery, it fetches, fast-forwards the inactive local sprint reference, and
returns to that branch without merging. Terminal task records are reconciled by ID
so delivered/blocked work is not repeated; newer terminal sprint records are preserved.
The task branch's final backlog status/PR URL is committed and pushed. Dependent tasks
wait until prerequisite code is integrated; human merges remain required.
Set `SPRINT_REMOTE` when the project's configured remote is not `origin`.
The runner accepts uncommitted changes; do not commit broken work just to launch
it. For sprint runs it still requires the declared sprint branch aligned with its
remote-tracking tip. Preserve partial work on a task branch rather than switching
away from uncommitted changes; resolve that task in its checkout before starting
a new sprint run.

### Planning and task-branch pushes

After the owner approves the plan, `tech-lead` may commit only PROJECT.md,
AGENTS.md, and BACKLOG.md directly on the **existing declared sprint branch** and
push that branch using `git push origin HEAD:refs/heads/<ACTIVE_SPRINT_BRANCH>`
(substitute its real name). Fetch before editing and again before pushing; if the
sprint moved, stop for reconciliation. Leave the local sprint aligned so the runner
can begin. No PR is needed for planning-only updates to the sprint.

The global `overnight` agent allows the explicit `origin` feature/bug pushes required
by the skill; projects using `origin` need no project `opencode.json` for this.
Example: `git push origin HEAD:refs/heads/feature/accounts`. The coordinator verifies
the assigned branch; it never pushes the sprint. Neither agent pushes `development`
or `master`, force-pushes, or merges. A different remote needs owner-provided tool
permissions as well as `SPRINT_REMOTE`.

## 4. Optional: UI/UX Pro Max

The owner installs the [CLI](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill)
once, then initializes each desired application repo:

```bash
npm install -g ui-ux-pro-max-cli
uipro init --ai opencode
```

The generated skills live in that project's `.opencode/skills/`; agents never install
or initialize them. Use versions suited to the project and provide Python 3 for search.

## 5. Playwright MCP

This toolkit's global `opencode.json` already enables Playwright for projects without
a project config. If using this toolkit without its global config, add the following
to your global OpenCode configuration:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "playwright": {
      "type": "local",
      "command": [
        "npx",
        "-y",
        "@playwright/mcp@latest",
        "--headless",
        "--isolated"
      ],
      "enabled": true,
      "timeout": 20000
    }
  }
}
```

Provide Node.js 18+ and a supported browser; pin a verified package version for
repeatable installs. Developer starts the app. For substantial UI changes,
UI-designer spot-checks important flows, with screenshots for visual judgments.

Put the dev command, URL, test-login setup, and target viewports in `AGENTS.md`.
Coordinate browser use sequentially: `--isolated` does not give every agent a separate
browser. See [Playwright MCP](https://github.com/microsoft/playwright-mcp).

## 6. Verify and run

Restart OpenCode after agent, skill, or configuration changes. From the application:

```bash
opencode agent list
opencode debug skill
opencode mcp list  # if MCP is configured
nohup bash ./run-tonight.sh > .opencode/launcher.log 2>&1 &
```

Prepare dependencies/credentials first and run one runner per checkout. Ignore
`.opencode/progress.md` and runner logs in the application's `.gitignore`.

For non-sprint projects the runner uses three-item batches; sprint sessions assign
one task and continue through available independent work. Direct execution is the
default; set `RUNNER_USE_SBX=1` to opt into the sandbox. All sessions have a two-hour
timeout; the run has no overall deadline while tasks are being delivered or blocked.
After three consecutive sessions with no completed/blocked outcome, it stops rather
than retrying forever. Fixable unfinished tasks resume in place; dirty terminal task
work stops sprint branch transitions and is preserved for recovery.
Worktrees are optional. Review `DONE.md`, backlog outcomes, commits, and PRs
afterward; delivered work is not necessarily merged.

Testing defaults to focused checks of important changed behavior and realistic
failures, without coverage targets or exhaustive corner cases. Listed project commands
are not automatically mandatory gates. Reviews and docs passes are used when useful,
and reports stay brief. Default three substantive repair attempts per task, excluding
initial implementation, formatting, and check reruns. Requested owner recovery may
renew that budget without a separate formal approval process.

Sprint dependency selection reads completed task records from the fetched sprint,
without new API credentials or PR metadata requirements. Locally carried outcomes
from unmerged tasks remain waiting; the coordinator still checks actual prerequisite
code. Fetch before a new launch; the initial sprint alignment check still applies.

Updating this toolkit does not rewrite planning files or skills already copied into
application repositories. Refresh the installed runner/helper/sprint skill and have
tech-lead simplify existing AGENTS.md/PROJECT.md gates while preserving product scope
and backlog IDs/outcomes. Restart OpenCode to load updated agents.

### Existing and halfway-built projects

Keep the existing backlog: verbose task bodies, `Done looks like`/`Verification`
sections, extra metadata, and unique title-only headings remain supported. Stable IDs
are recommended for new work, not a migration requirement. Dependencies can reference
IDs or exact unique titles, with optional backticks. Missing/prose dependency references
leave that task waiting while independent tasks continue; tech-lead can reconcile only
those references. Keep the existing `## [state] ...` heading/status format.
Fenced examples and group-level text are excluded from task metadata. Ambiguous or
malformed dependency declarations leave only the affected task waiting.

Ask tech-lead: “Adopt the simplified workflow in this existing project. Keep product
requirements, completed work, task identities, and partial changes. Replace generic
testing/review gates with focused checks and selective review; reconcile dependencies
only where needed.” Old explicit project gates remain active until updated; global
agent changes cannot silently remove them. No complete backlog rewrite is necessary.

Resume dirty task-branch work in place through tech-lead recovery before a new sprint
launch. Within a running sprint, unfinished tasks are pinned to the same assignment
and branch even if queue order changes. Carried terminal records update status/delivery
metadata only, preserving current task descriptions and acceptance criteria.
