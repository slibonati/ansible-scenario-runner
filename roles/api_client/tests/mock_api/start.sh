#!/usr/bin/env bash
# Start or stop the stdlib mock API used by api_client scenarios.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="${SCRIPT_DIR}/.mock_api.pid"
LOG_FILE="${SCRIPT_DIR}/.mock_api.log"
HOST="${MOCK_API_HOST:-127.0.0.1}"
PORT="${MOCK_API_PORT:-8765}"
TOKEN="${MOCK_API_TOKEN:-change-me}"

is_running() {
  if [[ -f "$PID_FILE" ]]; then
    local pid
    pid="$(cat "$PID_FILE")"
    if kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
    rm -f "$PID_FILE"
  fi
  return 1
}

start() {
  if is_running; then
    echo "mock API already running (pid $(cat "$PID_FILE")) on http://${HOST}:${PORT}"
    return 0
  fi
  MOCK_API_HOST="$HOST" MOCK_API_PORT="$PORT" MOCK_API_TOKEN="$TOKEN" \
    nohup python3 "$SCRIPT_DIR/server.py" >"$LOG_FILE" 2>&1 &
  echo $! >"$PID_FILE"
  # Brief wait + health check
  for _ in 1 2 3 4 5; do
    if curl -sf "http://${HOST}:${PORT}/health" >/dev/null 2>&1; then
      echo "mock API started (pid $(cat "$PID_FILE")) → http://${HOST}:${PORT}"
      echo "  logs: $LOG_FILE"
      echo "  expected Bearer token: ${TOKEN}"
      return 0
    fi
    sleep 0.2
  done
  echo "mock API failed to become healthy; see $LOG_FILE" >&2
  exit 1
}

stop() {
  if ! is_running; then
    echo "mock API is not running"
    return 0
  fi
  local pid
  pid="$(cat "$PID_FILE")"
  kill "$pid" 2>/dev/null || true
  rm -f "$PID_FILE"
  echo "mock API stopped (was pid $pid)"
}

status() {
  if is_running; then
    echo "running (pid $(cat "$PID_FILE")) http://${HOST}:${PORT}"
  else
    echo "stopped"
    exit 1
  fi
}

case "${1:-start}" in
  start) start ;;
  stop) stop ;;
  status) status ;;
  restart) stop; start ;;
  *)
    echo "usage: $0 {start|stop|status|restart}" >&2
    exit 2
    ;;
esac
