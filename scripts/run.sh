#!/bin/bash
# ETF Weekly Brief — portable cron / launchd wrapper.
#
# Who this is for:
#   - Users who want to run the brief on a schedule and keep logs in one
#     place. The lock + stale detection + EXIT trap below are reusable
#     even if you invoke a different driver than Claude CLI.
#
# Optional environment variables:
#   ETF_BRIEF_ROOT        — repo root (auto-detected from this script's
#                            location if unset).
#   ETF_BRIEF_PYTHON      — path to the python3 interpreter that has
#                            the runtime deps installed. Defaults to
#                            whatever python3 is first on PATH. For
#                            cron/launchd, point this at your venv's
#                            python.
#   ETF_BRIEF_DRY_RUN=1   — exercise the lock + logging path without
#                            running the actual driver (useful for tests).
#
# Logs go to $ETF_BRIEF_ROOT/logs/cron.log. Rotation is handled by the
# Python scraper's loguru setup; this shell log is append-only (rotate
# with a separate logrotate entry if you care).
#
# Lock strategy: mkdir-based lock directory (portable, atomic on APFS
# and common POSIX FS). A stale lock (dead PID or older than 6 hours) is
# cleared automatically. The lock is released via an EXIT trap.
#
# NOTE: This wrapper does not invoke the brief itself — the `/etf-brief`
# slash command runs inside Claude Code. Users who want to trigger it
# from cron need a headless driver (e.g. `claude -p "/etf-brief" …`) or
# can replace the DRIVER line below with their own invocation.

set -euo pipefail

ETF_BRIEF_ROOT="${ETF_BRIEF_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
LOG_DIR="$ETF_BRIEF_ROOT/logs"
LOG_FILE="$LOG_DIR/cron.log"
LOCK_DIR="/tmp/etf-brief.lock.d"
LOCK_MAX_AGE_SECONDS=$((6 * 60 * 60))  # 6 hours

# Python interpreter override — respect ETF_BRIEF_PYTHON if set, else
# use whatever python3 is first on PATH. Users with a venv should
# point this at their venv's interpreter when invoking from cron.
PYTHON_BIN="${ETF_BRIEF_PYTHON:-python3}"
# Resolve to the absolute path so the log records exactly which
# interpreter the run used — catches cases where two shells had
# different PATHs.
RESOLVED_PYTHON=$(command -v "$PYTHON_BIN" 2>/dev/null || echo "$PYTHON_BIN")

mkdir -p "$LOG_DIR"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG_FILE"
}

log "Using Python: $RESOLVED_PYTHON"

# --- Dependency pre-flight ---
# Fail loudly if required packages aren't importable. Far cheaper than
# taking the lock, running for 30s, and discovering the import error
# in a partial log.
check_dependencies() {
    if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
        log "ERROR: '$PYTHON_BIN' not found on PATH. Set ETF_BRIEF_PYTHON or install python3."
        echo "ERROR: '$PYTHON_BIN' not found on PATH." >&2
        echo "Set ETF_BRIEF_PYTHON to your venv's python, or install python3." >&2
        return 3
    fi
    if ! "$PYTHON_BIN" -c "import pydantic, yaml, loguru, requests, bs4" >/dev/null 2>&1; then
        log "ERROR: required Python packages missing. Run 'pip install -r requirements.txt' after activating your venv (see docs/INSTALL.md)."
        echo "ERROR: required Python packages missing." >&2
        echo "Run: pip install -r requirements.txt" >&2
        echo "(from the repo root, after activating your venv or conda env)." >&2
        echo "See docs/INSTALL.md for details." >&2
        return 3
    fi
    return 0
}

# --- Lock acquisition (mkdir is atomic on APFS) ---
acquire_lock() {
    if mkdir "$LOCK_DIR" 2>/dev/null; then
        echo "$$" > "$LOCK_DIR/pid"
        return 0
    fi

    # Lock exists — check if stale.
    local lock_pid=""
    if [[ -f "$LOCK_DIR/pid" ]]; then
        lock_pid=$(cat "$LOCK_DIR/pid" 2>/dev/null || echo "")
    fi

    local stale=0
    if [[ -n "$lock_pid" ]] && kill -0 "$lock_pid" 2>/dev/null; then
        # PID is alive. Check age as a safety net.
        local now mtime age
        now=$(date +%s)
        mtime=$(stat -f %m "$LOCK_DIR" 2>/dev/null \
                || stat -c %Y "$LOCK_DIR" 2>/dev/null \
                || echo "$now")
        age=$((now - mtime))
        if (( age > LOCK_MAX_AGE_SECONDS )); then
            stale=1
        fi
    else
        stale=1
    fi

    if (( stale == 1 )); then
        log "Removing stale lock (pid='$lock_pid')"
        rm -rf "$LOCK_DIR"
        if mkdir "$LOCK_DIR" 2>/dev/null; then
            echo "$$" > "$LOCK_DIR/pid"
            return 0
        fi
    fi

    return 1
}

release_lock() {
    # Only remove if we own it (our PID).
    if [[ -f "$LOCK_DIR/pid" ]]; then
        local owner
        owner=$(cat "$LOCK_DIR/pid" 2>/dev/null || echo "")
        if [[ "$owner" == "$$" ]]; then
            rm -rf "$LOCK_DIR"
        fi
    fi
}
trap release_lock EXIT

if ! check_dependencies; then
    # check_dependencies already logged + printed a clear message.
    exit 3
fi

if ! acquire_lock; then
    log "Another etf-brief run is in progress — skipping this invocation"
    # Clear the EXIT trap so we don't remove someone else's lock.
    trap - EXIT
    exit 0
fi

log "Starting ETF brief (pid $$, root=$ETF_BRIEF_ROOT, python=$PYTHON_BIN)"

cd "$ETF_BRIEF_ROOT"

if [[ "${ETF_BRIEF_DRY_RUN:-0}" == "1" ]]; then
    log "DRY RUN — skipping driver invocation"
    # Hold the lock briefly so concurrent tests can observe contention.
    sleep 2
    log "DRY RUN complete"
    exit 0
fi

# Users: invoke `/etf-brief` from Claude Code, or replace this with
# your own driver. The lock mechanism and log rotation above are
# reusable whatever you do here.
#
# Example (Claude CLI, assumes auth + budget configured):
#
#   claude -p "/etf-brief" \
#       --permission-mode bypassPermissions \
#       --max-budget-usd 5 \
#       >> "$LOG_FILE" 2>&1

log "No driver configured — edit scripts/run.sh to wire one in, or set ETF_BRIEF_DRY_RUN=1 for a dry-run."
