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

# ISO-ish UTC stamp safe for filenames: 20260820T212800Z
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

# Path for a single-scenario run log.
scenario_log_path() {
  local name="$1"
  local ts="${2:-$(log_timestamp)}"
  printf '%s/%s_%s.log\n' "$LOGS_DIR" "$ts" "$(log_safe_name "$name")"
}

# Path for a run-all suite summary log.
suite_log_path() {
  local ts="${1:-$(log_timestamp)}"
  printf '%s/%s_suite-summary.log\n' "$LOGS_DIR" "$ts"
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
# Sets global LAST_LOG_FILE. Returns the command's exit status.
#
# Usage: run_with_sanitized_log <logfile> <label> -- <command...>
run_with_sanitized_log() {
  local logfile="$1"
  local label="$2"
  shift 2
  if [[ "${1:-}" == "--" ]]; then
    shift
  fi

  ensure_logs_dir
  LAST_LOG_FILE="$logfile"

  # Keep errexit off in this helper so a non-zero ansible rc can be returned
  # to the caller (set -e + return N would otherwise abort the whole script).
  set +e

  {
    printf '# %s\n' "$label"
    printf '# started: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf '# command:'
    printf ' %q' "$@"
    printf '\n# ---\n'
  } | sanitize_stream >>"$logfile"

  local tmp rc
  tmp="$(mktemp "${TMPDIR:-/tmp}/api-client-run.XXXXXX")"
  "$@" >"$tmp" 2>&1
  rc=$?

  # Console: raw (may include ANSI if present)
  cat "$tmp"
  # Log file: sanitized
  sanitize_stream <"$tmp" >>"$logfile"
  {
    printf '# ---\n'
    printf '# finished: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf '# exit_code: %s\n' "$rc"
  } | sanitize_stream >>"$logfile"

  rm -f "$tmp"
  return "$rc"
}
