#!/bin/bash
# run-tonight.sh
#
# Reads BACKLOG.md and runs overnight agent sessions until all
# eligible [ ] items are complete, blocked by dependencies, or progress stops.
#
# Prerequisites:
#   - AGENTS.md, PROJECT.md, BACKLOG.md filled out in this directory
#   - scripts/backlog.py present alongside this script (dependency-aware queue parser)
#   - Agent .md files in ~/.config/opencode/agents/
#   - opencode.json configured in ~/.config/opencode/
#   - runs opencode directly; opt in to sbx with RUNNER_USE_SBX=1
#
# Usage:
#   chmod +x run-tonight.sh
#   nohup ./run-tonight.sh > .opencode/run.log 2>&1 &
#
# Morning review:
#   cat DONE.md
#   cat BACKLOG.md              ← item-by-item status
#   git log --oneline
#   cat .opencode/run.log

set -euo pipefail

# ─── Configuration ────────────────────────────────────────────────────────────

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_NAME="$(basename "$PROJECT_DIR")"
SCRIPT_DIR="$PROJECT_DIR/scripts"
BACKLOG_FILE="$PROJECT_DIR/BACKLOG.md"
LOG_DIR="$PROJECT_DIR/.opencode"
SANDBOX_NAME="${PROJECT_NAME}-$(date +%Y%m%d-%H%M)"
PHASE_TIMEOUT=7200          # 2 hours per session
ITEMS_PER_SESSION=3         # backlog items per OpenCode session
                            # set to 1 for large or complex items
SPRINT_REMOTE="${SPRINT_REMOTE:-origin}"
AGENT="overnight"
SBX_OPENCODE_BIN="${SBX_OPENCODE_BIN:-/usr/local/share/npm-global/lib/node_modules/opencode-ai/node_modules/opencode-linux-x64/bin/opencode}"

SESSION_FAILURES=0
SESSION_COUNT=0
NO_PROGRESS_SESSIONS=0
STOPPED_FOR_REVIEW=0
USE_SBX=0
SPRINT_ARGS=()
RESUME_ARGS=()

# ─── Setup ────────────────────────────────────────────────────────────────────

mkdir -p "$LOG_DIR"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_DIR/run.log"
}

backlog() {
  python3 "$SCRIPT_DIR/backlog.py" "$@"
}

return_to_sprint() {
  # The agent must finish task delivery before we change checkouts.
  if [ -n "$(git -C "$PROJECT_DIR" status --porcelain)" ]; then
    log "Partial/uncommitted task work preserved; cannot switch to another sprint task. Recover this checkout before relaunching."
    return 1
  fi
  local outcome_file="$LOG_DIR/session-outcomes.log"
  cp "$BACKLOG_FILE" "$outcome_file"
  if ! git -C "$PROJECT_DIR" fetch "$SPRINT_REMOTE"; then
    log "Could not refresh sprint; preserving the current task checkout."
    return 1
  fi
  local remote_ref="refs/remotes/$SPRINT_REMOTE/$SPRINT_BRANCH"
  local local_ref="refs/heads/$SPRINT_BRANCH"
  if ! git -C "$PROJECT_DIR" merge-base --is-ancestor "$local_ref" "$remote_ref"; then
    log "Local sprint has divergent/unpublished commits; reconcile before continuing."
    return 1
  fi
  # Fast-forward the inactive local reference, without a merge/rebase or history rewrite.
  if [ "$(git -C "$PROJECT_DIR" branch --show-current)" = "$SPRINT_BRANCH" ]; then
    if [ "$(git -C "$PROJECT_DIR" rev-parse HEAD)" != "$(git -C "$PROJECT_DIR" rev-parse "$remote_ref")" ]; then
      log "Session unexpectedly remained on an outdated sprint; reconcile before continuing."
      return 1
    fi
  else
    # branch -f refuses a branch checked out in another worktree; update-ref does not.
    git -C "$PROJECT_DIR" branch -f "$SPRINT_BRANCH" "$remote_ref" || return 1
    git -C "$PROJECT_DIR" switch "$SPRINT_BRANCH" || return 1
  fi
  backlog reconcile "$BACKLOG_FILE" "$outcome_file"
}

prepare_sandbox_opencode() {
  local host_auth="$HOME/.local/share/opencode/auth.json"
  local host_config_dir="$HOME/.config/opencode"
  local tmp_env_file="/tmp/opencode/opencode-sbx-persistent.sh"

  log "Preparing sandbox OpenCode config..."

  mkdir -p "/tmp/opencode"

  if ! sbx exec "$SANDBOX_NAME" sh -lc 'mkdir -p /home/agent/.local/share/opencode /home/agent/.config/opencode && rm -rf /home/agent/.config/opencode/agents'; then
    log "Sandbox prep warning: could not create OpenCode directories inside sandbox."
    return 1
  fi

  if [ -f "$host_auth" ]; then
    if ! sbx cp "$host_auth" "$SANDBOX_NAME:/home/agent/.local/share/opencode/auth.json"; then
      log "Sandbox prep warning: failed to copy auth.json into sandbox."
    fi
  else
    log "Sandbox prep warning: host auth.json not found at $host_auth"
  fi

  if [ -f "$host_config_dir/opencode.json" ]; then
    if ! sbx cp "$host_config_dir/opencode.json" "$SANDBOX_NAME:/home/agent/.config/opencode/opencode.json"; then
      log "Sandbox prep warning: failed to copy opencode.json into sandbox."
    fi
  fi

  if [ -d "$host_config_dir/agents" ]; then
    if ! sbx cp "$host_config_dir/agents" "$SANDBOX_NAME:/home/agent/.config/opencode/agents"; then
      log "Sandbox prep warning: failed to copy agent definitions into sandbox."
    fi
  else
    log "Sandbox prep warning: host agent directory not found at $host_config_dir/agents"
  fi

  if [ -n "${AZURE_RESOURCE_NAME:-}" ]; then
    printf 'export AZURE_RESOURCE_NAME="%s"\n' "$AZURE_RESOURCE_NAME" > "$tmp_env_file"
    if ! sbx cp "$tmp_env_file" "$SANDBOX_NAME:/etc/sandbox-persistent.sh"; then
      log "Sandbox prep warning: failed to copy sandbox-persistent.sh into sandbox."
    fi
    if ! sbx policy allow network "${AZURE_RESOURCE_NAME}.openai.azure.com" --sandbox "$SANDBOX_NAME" >/dev/null; then
      log "Sandbox prep warning: failed to allow Azure endpoint network access."
    fi
  else
    log "Sandbox prep warning: AZURE_RESOURCE_NAME is not set on the host."
  fi

  if ! sbx policy allow network models.opencode.ai --sandbox "$SANDBOX_NAME" >/dev/null; then
    log "Sandbox prep warning: failed to allow models.opencode.ai network access."
  fi

  return 0
}

# ─── Session runner ───────────────────────────────────────────────────────────

run_session() {
  local num="$1"
  local prompt="$2"
  local session_log="$LOG_DIR/session-${num}.log"
  local code
  local quoted_bin
  local quoted_project_dir
  local quoted_agent
  local quoted_prompt

  log "━━━ Session $num starting ━━━"
  SESSION_COUNT=$((SESSION_COUNT + 1))

  set +e

  if [ "$USE_SBX" -eq 1 ]; then
    printf -v quoted_bin '%q' "$SBX_OPENCODE_BIN"
    printf -v quoted_project_dir '%q' "$PROJECT_DIR"
    printf -v quoted_agent '%q' "$AGENT"
    printf -v quoted_prompt '%q' "$prompt"

    timeout "$PHASE_TIMEOUT" \
      sbx exec "$SANDBOX_NAME" bash -lc \
        "$quoted_bin run --dir $quoted_project_dir --agent $quoted_agent $quoted_prompt" \
      < /dev/null \
      2>&1 | tee -a "$session_log" "$LOG_DIR/run.log"
    code=${PIPESTATUS[0]}
  else
    timeout "$PHASE_TIMEOUT" \
      opencode run --agent "$AGENT" "$prompt" \
      < /dev/null \
      2>&1 | tee -a "$session_log" "$LOG_DIR/run.log"
    code=${PIPESTATUS[0]}
  fi

  set -e

  if   [ "$code" -eq 0 ];   then log "Session $num completed."
  elif [ "$code" -eq 124 ]; then
    log "Session $num timed out after ${PHASE_TIMEOUT}s — inspecting outcomes before continuing."
    SESSION_FAILURES=$((SESSION_FAILURES + 1))
  else
    log "Session $num exited with code $code."
    SESSION_FAILURES=$((SESSION_FAILURES + 1))
  fi

  sleep 10
}

# ─── Preflight ────────────────────────────────────────────────────────────────

[[ -f "$PROJECT_DIR/PROJECT.md" ]] \
  || { log "ERROR: PROJECT.md not found."; exit 1; }

[[ -f "$PROJECT_DIR/AGENTS.md" ]] \
  || { log "ERROR: AGENTS.md not found."; exit 1; }

[[ -f "$BACKLOG_FILE" ]] \
  || { log "ERROR: BACKLOG.md not found."; exit 1; }

[[ -f "$SCRIPT_DIR/backlog.py" ]] \
  || { log "ERROR: scripts/backlog.py not found."; exit 1; }

if ! command -v opencode >/dev/null 2>&1; then
  log "ERROR: opencode not found in PATH."
  exit 1
fi

if [ "$(git -C "$PROJECT_DIR" rev-parse --is-inside-work-tree 2>/dev/null)" != "true" ]; then
  log "ERROR: an existing Git checkout is required; refusing to initialize or commit a new repository."
  exit 1
fi
if ! git -C "$PROJECT_DIR" rev-parse --verify HEAD >/dev/null 2>&1 ||
   [ "$(git -C "$PROJECT_DIR" rev-parse --show-toplevel)" != "$PROJECT_DIR" ]; then
  log "ERROR: an initial commit and project-root Git checkout are required."
  exit 1
fi

log "Starting overnight run: $PROJECT_NAME"
# Tools and the queue helper must use the same checkout even when launched elsewhere.
cd "$PROJECT_DIR"

SPRINT_WORKFLOW=0
if grep -Fxq 'Use the installed `sprint-workflow` skill for branching and pull requests.' "$PROJECT_DIR/AGENTS.md"; then
  SPRINT_WORKFLOW=1
  ITEMS_PER_SESSION=1
  SPRINT_BRANCH=$(backlog sprint-branch "$BACKLOG_FILE")
  SPRINT_ARGS=(--sprint-ref "refs/remotes/$SPRINT_REMOTE/$SPRINT_BRANCH")
  BRANCH=$(git -C "$PROJECT_DIR" branch --show-current)
  if [ "$BRANCH" != "$SPRINT_BRANCH" ]; then
    log "ERROR: Start sprint work on $SPRINT_BRANCH after reconciling merged BACKLOG.md; currently on ${BRANCH:-detached HEAD}."
    exit 1
  fi
  if ! git -C "$PROJECT_DIR" rev-parse --verify "refs/remotes/$SPRINT_REMOTE/$SPRINT_BRANCH" >/dev/null 2>&1 ||
     [ "$(git -C "$PROJECT_DIR" rev-parse HEAD)" != "$(git -C "$PROJECT_DIR" rev-parse "refs/remotes/$SPRINT_REMOTE/$SPRINT_BRANCH" 2>/dev/null)" ]; then
    log "ERROR: Fetch and align the local sprint branch with $SPRINT_REMOTE/$SPRINT_BRANCH before running."
    exit 1
  fi
  log "Sprint workflow selected: one task per session; continue independent work on $SPRINT_BRANCH."
fi

# Reset stale [~] items left over from any previous interrupted run
log "Checking for stale in-progress items..."
backlog reset-running "$BACKLOG_FILE"

if ! PENDING=$(backlog count "$BACKLOG_FILE"); then
  log "ERROR: could not read backlog item count."
  exit 1
fi
if [ "$PENDING" -eq 0 ]; then
  log "No [ ] items in BACKLOG.md. Add work items and run again."
  log ""
  log "Blocked items requiring attention:"
  backlog list-blocked "$BACKLOG_FILE" | tee -a "$LOG_DIR/run.log"
  exit 0
fi

log "Found $PENDING ready item(s). Running up to $ITEMS_PER_SESSION eligible items per session."

if ! ELIGIBLE=$(backlog count-eligible "$BACKLOG_FILE" "${SPRINT_ARGS[@]}"); then
  log "ERROR: could not evaluate backlog dependencies."
  exit 1
fi
if [ "$ELIGIBLE" -eq 0 ]; then
  log "No dependency-eligible items; ready items remain waiting for their prerequisites."
  backlog list-waiting "$BACKLOG_FILE" "${SPRINT_ARGS[@]}" | tee -a "$LOG_DIR/run.log"
  exit 0
fi

# ─── Sandbox (optional) ───────────────────────────────────────────────────────

if [ "${RUNNER_USE_SBX:-0}" = "1" ]; then
  if sbx ls >/dev/null 2>&1; then
    log "Creating sandbox: $SANDBOX_NAME"
    if sbx create --name "$SANDBOX_NAME" opencode "$PROJECT_DIR"; then
      USE_SBX=1
      prepare_sandbox_opencode || true
      log "Sandbox ready."
    else
      log "Sandbox creation failed — running opencode directly."
    fi
  else
    log "sbx not available — running opencode directly."
  fi
else
  log "Running opencode directly; set RUNNER_USE_SBX=1 to opt into sbx."
fi

# ─── Session loop ─────────────────────────────────────────────────────────────

SESSION_NUM=0

while true; do

  # Check if any pending items remain
  if ! REMAINING=$(backlog count "$BACKLOG_FILE"); then
    log "ERROR: could not read backlog item count; stopping without a success summary."
    exit 1
  fi
  if [ "$REMAINING" -eq 0 ]; then
    break
  fi

  if ! ELIGIBLE=$(backlog count-eligible "$BACKLOG_FILE" "${SPRINT_ARGS[@]}"); then
    log "ERROR: could not evaluate backlog dependencies; stopping without a success summary."
    exit 1
  fi
  if [ "$ELIGIBLE" -eq 0 ]; then
    log "No dependency-eligible items; stopping with $REMAINING ready item(s) waiting."
    backlog list-waiting "$BACKLOG_FILE" "${SPRINT_ARGS[@]}" | tee -a "$LOG_DIR/run.log"
    break
  fi

  SESSION_NUM=$((SESSION_NUM + 1))

  OUTCOMES_BEFORE=$(backlog count-outcomes "$BACKLOG_FILE")

  # Claim the batch and build its prompt from the same backlog snapshot.
  if PROMPT=$(backlog claim-batch "$BACKLOG_FILE" "$ITEMS_PER_SESSION" "${SPRINT_ARGS[@]}" "${RESUME_ARGS[@]}"); then
    :
  else
    CLAIM_STATUS=$?
    if [ "$CLAIM_STATUS" -eq 1 ]; then
      log "No dependency-eligible items remained when claiming; stopping with the current queue unchanged."
      backlog list-waiting "$BACKLOG_FILE" "${SPRINT_ARGS[@]}" | tee -a "$LOG_DIR/run.log"
      break
    fi
    log "ERROR: could not claim backlog batch (exit code $CLAIM_STATUS); stopping without a success summary."
    exit "$CLAIM_STATUS"
  fi
  if [ "$SPRINT_WORKFLOW" -eq 1 ]; then
    PROMPT+=$'\nThis session assigns one sprint task. The runner continues with other independent tasks after clean task delivery. Leave completed task changes and final backlog/PR metadata committed and published on the task branch. Preserve unfinished work and record a concrete next step; the runner may resume this same task in place. Never switch away from dirty partial work or implement unmerged dependencies.'
  fi

  # Run the session
  run_session "$SESSION_NUM" "$PROMPT"

  UNFINISHED=$(backlog count-running "$BACKLOG_FILE")
  if [ "$SPRINT_WORKFLOW" -eq 1 ] && [ "$UNFINISHED" -gt 0 ]; then
    cp "$BACKLOG_FILE" "$LOG_DIR/resume-assignment.log"
    RESUME_ARGS=(--resume-from "$LOG_DIR/resume-assignment.log")
  else
    RESUME_ARGS=()
  fi
  # Reset unfinished items for an in-place continuation; never erase partial code.
  backlog reset-running "$BACKLOG_FILE"

  OUTCOMES_AFTER=$(backlog count-outcomes "$BACKLOG_FILE")
  if [ "$OUTCOMES_AFTER" -gt "$OUTCOMES_BEFORE" ]; then
    NO_PROGRESS_SESSIONS=0
  else
    NO_PROGRESS_SESSIONS=$((NO_PROGRESS_SESSIONS + 1))
    log "No completed or blocked outcome in session $SESSION_NUM ($NO_PROGRESS_SESSIONS/3)."
    if [ "$NO_PROGRESS_SESSIONS" -ge 3 ]; then
      log "Stopping after three sessions without a completed or blocked outcome; inspect partial work and logs."
      STOPPED_FOR_REVIEW=1
      break
    fi
  fi

  if [ "$SPRINT_WORKFLOW" -eq 1 ]; then
    if [ "$UNFINISHED" -gt 0 ]; then
      log "Unfinished sprint task: continue in the current checkout within the no-progress limit."
    elif ! return_to_sprint; then
      STOPPED_FOR_REVIEW=1
      break
    fi
  fi

done

# ─── Summary ──────────────────────────────────────────────────────────────────

log ""

if [ "$STOPPED_FOR_REVIEW" -eq 1 ]; then
  log "━━━ STOPPED FOR REVIEW: no progress or checkout transition blocked ━━━"
elif [ "$SESSION_FAILURES" -eq "$SESSION_COUNT" ] && [ "$SESSION_COUNT" -gt 0 ]; then
  log "━━━ ALL $SESSION_COUNT SESSION(S) FAILED ━━━"
  log "Check .opencode/session-*.log before assuming anything was accomplished."
elif [ "$SESSION_FAILURES" -gt 0 ]; then
  log "━━━ Completed with $SESSION_FAILURES/$SESSION_COUNT session(s) failing ━━━"
else
  log "━━━ All sessions complete ━━━"
fi

log ""
log "Backlog status:"
backlog list-all "$BACKLOG_FILE" | tee -a "$LOG_DIR/run.log"

log ""
log "Blocked items (need your attention before next run):"
backlog list-blocked "$BACKLOG_FILE" | tee -a "$LOG_DIR/run.log"

log ""
log "Morning review:"
log "  cat DONE.md"
log "  cat BACKLOG.md"
log "  git log --oneline"

if [ "$USE_SBX" -eq 1 ]; then
  log ""
  log "When done reviewing:"
  log "  sbx rm $SANDBOX_NAME"
fi

if [ "$STOPPED_FOR_REVIEW" -eq 1 ]; then
  exit 1
fi

if [ "$SESSION_FAILURES" -gt 0 ]; then
  exit 1
fi
