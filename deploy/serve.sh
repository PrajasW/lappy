#!/usr/bin/env bash
# Serve the dashboard (site/) on port 8787. Safe to call repeatedly: starts it only if not running.
DIR="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${LAPPY_PORT:-8787}"
mkdir -p "$DIR/site" "$DIR/logs"
if ! ss -ltn 2>/dev/null | grep -q ":$PORT "; then
  nohup "$DIR/.venv/bin/python" -m http.server "$PORT" --bind 0.0.0.0 --directory "$DIR/site" \
    >> "$DIR/logs/server.log" 2>&1 &
  echo "dashboard server started on port $PORT"
fi
