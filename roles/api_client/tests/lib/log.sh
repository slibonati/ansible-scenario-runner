#!/usr/bin/env bash
# Logging + output sanitization for the api_client test harness.
# Sourced by run.sh / run-all.sh (after env.sh). Do not execute directly.
#
# Sanitization (applied to log files only; console keeps raw stream):
#   - Decode as UTF-8 (replace undecodable bytes)
#   - Strip ANSI / CSI escape sequences (colors, cursor moves)
#   - Drop other C0/C1 control chars except newline and tab
#   - Normalize CRLF → LF

: "${TESTS_DIR:?TESTS_DIR must be set before sourcing lib/log.sh}"

export LOGS_DIR="${LOGS_DIR:-${TESTS_DIR}/logs}"

# UTC timestamp; all logs from a suite share this prefix.
log_timestamp() {
  date -u +%Y%m%dT%H%M%SZ
}

# Sanitize a filename fragment (scenario / suite labels).
log_safe_name() {
  local s="$1"
  s="${s//\//_}"
  s="${s// /_}"
  printf '%s\n' "$s" | tr -cd 'A-Za-z0-9._+@=-' | head -c 120
}

# Ensure logs/ exists (committed via .gitkeep; *.log gitignored).
ensure_logs_dir() {
  mkdir -p "$LOGS_DIR"
}

# Reserve each log atomically, including when sanitized labels collide.
reserve_log_path() {
  ensure_logs_dir || return 1
  python3 - "$LOGS_DIR" "$1" <<'PYLOG'
import os
import sys
from pathlib import Path

index = 1
while True:
    suffix = "" if index == 1 else f"_{index}"
    path = Path(sys.argv[1]) / f"{sys.argv[2]}{suffix}.log"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        index += 1
        continue
    os.close(fd)
    print(path.absolute())
    break
PYLOG
}

scenario_log_path() {
  local name="$1" ts
  ts="${2:-$(log_timestamp)}"
  reserve_log_path "${ts}_$(log_safe_name "$name")"
}

suite_log_path() {
  local ts
  ts="${1:-$(log_timestamp)}"
  reserve_log_path "${ts}_suite-summary"
}

# Sanitize stdin → stdout (UTF-8 safe, strip ANSI + non-printables).
# Uses python3 -c so real stdin is the stream to sanitize (not the program text).
sanitize_stream() {
  python3 -c '
import re
import sys

_ANSI = re.compile(
    r"(?:\x1B[@-Z\\-_]"
    r"|\x1B\[[0-?]*[ -/]*[@-~]"
    r"|\x1B\][^\x07\x1B]*(?:\x07|\x1B\\)"
    r"|\x9B[0-?]*[ -/]*[@-~])"
)

def sanitize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _ANSI.sub("", text)
    out = []
    for ch in text:
        o = ord(ch)
        if ch in "\n\t" or (32 <= o <= 126) or o >= 160:
            out.append(ch)
    return "".join(out)

data = sys.stdin.buffer.read()
sys.stdout.write(sanitize(data.decode("utf-8", errors="replace")))
'
}

# Append a short header to a log file, then run a command:
#   - console: raw stdout/stderr (unchanged)
#   - logfile: sanitized copy of the same stream
# Sets global LAST_LOG_FILE. Returns the command's exit status, or 1 on log failure.
#
# Usage: run_with_sanitized_log <logfile> <label> -- <command...>
run_with_sanitized_log() {
  LOG_CAPTURE_SUCCEEDED=0
  local logfile="$1"
  local label="$2"
  shift 2
  if [[ "${1:-}" == "--" ]]; then
    shift
  fi

  ensure_logs_dir || return 1
  LAST_LOG_FILE="$logfile"

  # Check each logging operation explicitly; preserve the caller's shell options.
  if ! {
    printf '# %s\n' "$label"
    printf '# started: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf '# command:'
    printf ' %q' "$@"
    printf '\n# ---\n'
  } | sanitize_stream >>"$logfile"; then
    echo "cannot write run log: $logfile" >&2
    return 1
  fi

  local tmp rc=0 log_rc=0
  tmp="$(mktemp "${TMPDIR:-/tmp}/api-client-run.XXXXXX")" || return 1
  "$@" >"$tmp" 2>&1 || rc=$?
  cat "$tmp" || log_rc=1
  sanitize_stream <"$tmp" >>"$logfile" || log_rc=1
  {
    printf '# ---\n'
    printf '# finished: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf '# exit_code: %s\n' "$rc"
  } | sanitize_stream >>"$logfile" || log_rc=1
  rm -f "$tmp" || log_rc=1
  if [[ "$log_rc" -ne 0 ]]; then
    echo "failed to capture run evidence: $logfile" >&2
    return 1
  fi
  LOG_CAPTURE_SUCCEEDED=1
  return "$rc"
}
