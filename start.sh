#!/usr/bin/env bash
# Start the markdown-reader2 server in the foreground (Ctrl+C to stop).
# The process id is tracked in data/server.pid so ./stop.sh can also stop it
# from another terminal.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
mkdir -p data

PID_FILE="data/server.pid"

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "Already running (pid $(cat "$PID_FILE")) -- stopping it first."
  ./stop.sh
fi

PORT="${PORT:-5001}"
LAN_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)

uv run python app.py &
PID=$!
echo "$PID" >"$PID_FILE"

# Give it a moment to either come up or fail fast, so we can report which.
sleep 2
if ! kill -0 "$PID" 2>/dev/null; then
  echo "Server failed to start."
  rm -f "$PID_FILE"
  exit 1
fi

echo "Running (pid $PID). Press Ctrl+C to stop (or run ./stop.sh from another terminal)."
echo "  Local:  http://localhost:$PORT"
if [ -n "$LAN_IP" ]; then
  echo "  LAN:    http://$LAN_IP:$PORT"
fi

# Only remove the pid file once the server process has actually exited --
# NOT on every shell exit (a trap on EXIT here would delete the pid file if
# this terminal/shell dies while the background server is still running,
# leaving stop.sh unable to find an orphaned but live process).
wait "$PID" || true
rm -f "$PID_FILE"
