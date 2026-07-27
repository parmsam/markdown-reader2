#!/usr/bin/env bash
# Stop the markdown-reader2 server started by start.sh.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"
PID_FILE="data/server.pid"

if [ -f "$PID_FILE" ]; then
  PID=$(cat "$PID_FILE")

  if ! kill -0 "$PID" 2>/dev/null; then
    echo "Not running (stale pid $PID). Cleaning up $PID_FILE."
  else
    kill "$PID"
    for _ in $(seq 1 20); do
      kill -0 "$PID" 2>/dev/null || break
      sleep 0.5
    done

    if kill -0 "$PID" 2>/dev/null; then
      echo "Still running after 10s, forcing (kill -9 $PID)."
      kill -9 "$PID"
    fi
    echo "Stopped (was pid $PID)."
  fi

  rm -f "$PID_FILE"
else
  echo "No $PID_FILE found."
fi

# Fallback: the pid file can go stale relative to the real server (e.g. if
# the terminal running start.sh was killed while the background job survived
# it as an orphan). Sweep for the actual venv python process by its unique
# absolute path so a leftover server is still caught even without a pid file.
ORPHANS=$(pgrep -f "${PROJECT_DIR}/.venv/bin/python3 app.py" 2>/dev/null || true)
if [ -n "$ORPHANS" ]; then
  echo "Found orphaned server process(es): $ORPHANS -- killing."
  kill $ORPHANS 2>/dev/null || true
  sleep 1
  kill -9 $ORPHANS 2>/dev/null || true
fi
