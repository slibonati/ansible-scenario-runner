#!/usr/bin/env bash
# Run every scenario listed in scenario-suite.yml (order = list order).
# Usage: ./run-all.sh [--clean-logs] [manifest]
#
#   --clean-logs   delete logs/*.log before the suite (keeps logs/.gitkeep)
#   CLEAR_LOGS=1   env equivalent of --clean-logs
#   manifest       path to suite YAML (default: scenario-suite.yml under this dir)
#
# Sources env.sh; per-entry playbook / inventory / vault / verbosity overrides
# are applied when invoking ./run.sh.
#
# Logs: per-scenario under logs/<ts>_<name>.log plus logs/<ts>_suite-summary.log
set -euo pipefail

TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "${TESTS_DIR}/env.sh"
# shellcheck source=lib/log.sh
source "${TESTS_DIR}/lib/log.sh"

usage() {
  echo "usage: $0 [--clean-logs] [manifest]" >&2
  echo "  --clean-logs   delete logs/*.log before running (keeps logs/.gitkeep)" >&2
  echo "  CLEAR_LOGS=1   env equivalent of --clean-logs" >&2
  echo "  default manifest: $TESTS_DIR/scenario-suite.yml" >&2
}

CLEAN_LOGS=0
if [[ "${CLEAR_LOGS:-0}" == "1" ]]; then
  CLEAN_LOGS=1
fi

MANIFEST_ARG=""
for arg in "$@"; do
  case "$arg" in
    -h|--help)
      usage
      exit 2
      ;;
    --clean-logs)
      CLEAN_LOGS=1
      ;;
    -*)
      echo "unknown option: $arg" >&2
      usage
      exit 2
      ;;
    *)
      if [[ -n "$MANIFEST_ARG" ]]; then
        echo "unexpected argument: $arg" >&2
        usage
        exit 2
      fi
      MANIFEST_ARG="$arg"
      ;;
  esac
done
MANIFEST_ARG="${MANIFEST_ARG:-scenario-suite.yml}"

if [[ "$MANIFEST_ARG" == /* ]]; then
  MANIFEST="$MANIFEST_ARG"
else
  MANIFEST="$TESTS_DIR/$MANIFEST_ARG"
fi

if [[ ! -f "$MANIFEST" ]]; then
  echo "manifest not found: $MANIFEST" >&2
  exit 1
fi

# Expand suite into TSV rows (one scenario per line) for bash.
# Columns: name, scenario, playbook, inventory, vault_file, verbosity
if ! SCENARIO_DATA="$(
  python3 - "$MANIFEST" "$TESTS_DIR" <<'PY'
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("PyYAML required to parse scenario-suite.yml (pip install pyyaml)\n")
    sys.exit(2)

manifest_path = Path(sys.argv[1])
tests_dir = Path(sys.argv[2])
try:
    data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
except (OSError, yaml.YAMLError) as exc:
    sys.exit(f"invalid suite manifest: {exc}")
if not isinstance(data, dict):
    sys.exit("suite manifest must be a mapping")
defaults = data.get("defaults", {})
if not isinstance(defaults, dict):
    sys.exit("defaults must be a mapping")
scenarios = data.get("scenarios") or []
if not isinstance(scenarios, list) or not scenarios:
    sys.stderr.write("scenario-suite.yml: scenarios must be a non-empty list\n")
    sys.exit(1)

def as_str(v, default=""):
    if v is None:
        return default
    return str(v)

def resolve(p: str) -> str:
    path = Path(p)
    if path.is_absolute():
        return str(path)
    return str(tests_dir / path)

def expected_failure(v):
    if v is not False:
        sys.exit("expected_failure must be false or omitted; assert the expected error in Ansible instead")


d_playbook = as_str(defaults.get("playbook"), "test.yml")
d_inventory = as_str(defaults.get("inventory"), "inventory.yml")
d_vault = as_str(defaults.get("vault_file"), "vault.yml")
d_verbosity = as_str(defaults.get("verbosity"), "0")

seen = set()
for i, entry in enumerate(scenarios):
    if not isinstance(entry, dict):
        sys.stderr.write(f"scenarios[{i}]: expected a mapping\n")
        sys.exit(1)
    name = as_str(entry.get("name")).strip()
    if not name:
        sys.stderr.write(f"scenarios[{i}]: name is required\n")
        sys.exit(1)
    if name in seen:
        sys.exit(f"duplicate scenario name: {name}")
    seen.add(name)
    scenario = entry.get("scenario") or entry.get("file") or f"scenarios/{name}.yml"
    playbook = entry.get("playbook", d_playbook)
    inventory = entry.get("inventory", d_inventory)
    vault_file = entry.get("vault_file", d_vault)
    verbosity = entry.get("verbosity", d_verbosity)
    expected_failure(entry.get("expected_failure", False))
    if str(verbosity) not in ("0", "1", "2", "3", "4", "5", "-v", "-vv", "-vvv", "-vvvv", "-vvvvv"):
        sys.exit(f"scenarios[{i}]: invalid verbosity")
    for value in (name, scenario, playbook, inventory, vault_file):
        if not isinstance(value, str) or not value.strip() or any(c in value for c in "\t\r\n"):
            sys.exit(f"scenarios[{i}]: names and paths must be non-empty single-line strings without tabs")
    row = "\t".join(
        [
            name,
            resolve(as_str(scenario)),
            resolve(as_str(playbook)),
            resolve(as_str(inventory)),
            resolve(as_str(vault_file)),
            as_str(verbosity, "0"),
        ]
    )
    print(row)
PY
)"; then
  echo "suite manifest validation failed; no scenarios were run" >&2
  exit 2
fi
mapfile -t SCENARIO_ROWS <<<"$SCENARIO_DATA"

if [[ "$CLEAN_LOGS" -eq 1 ]]; then
  ensure_logs_dir
  # Delete log files only; keep logs/ and logs/.gitkeep.
  shopt -s nullglob
  removed=("${LOGS_DIR}"/*.log)
  shopt -u nullglob
  if ((${#removed[@]})); then
    rm -f "${removed[@]}"
    echo "cleaned ${#removed[@]} log file(s) under $LOGS_DIR"
  else
    echo "no log files to clean under $LOGS_DIR"
  fi
fi

SUITE_TS="$(log_timestamp)"
SUITE_LOG="$(suite_log_path "$SUITE_TS")"
ensure_logs_dir

{
  echo "# suite run"
  echo "# manifest: $MANIFEST"
  echo "# started: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "# scenarios: ${#SCENARIO_ROWS[@]}"
  echo "# ---"
} | sanitize_stream >"$SUITE_LOG"

echo "suite: $MANIFEST (${#SCENARIO_ROWS[@]} scenarios)"
echo "suite log: $SUITE_LOG"

passed=0
failed=0
declare -a RESULTS=()

for row in "${SCENARIO_ROWS[@]}"; do
  IFS=$'\t' read -r name scenario playbook inventory vault_file verbosity <<<"$row"

  SCENARIO_LOG="$(scenario_log_path "$name" "$SUITE_TS")"
  echo
  echo "=== [$name] ==="

  set +e
  PLAYBOOK="$playbook" \
    INVENTORY="$inventory" \
    VAULT_FILE="$vault_file" \
    EXPECTED_FAILURE=0 \
    LOG_FILE="$SCENARIO_LOG" \
    "$TESTS_DIR/run.sh" "$scenario" "$verbosity"
  rc=$?
  set -e

  if [[ "$rc" -eq 0 ]]; then
    status="PASS"
    ((passed++)) || true
  else
    status="FAIL"
    ((failed++)) || true
  fi
  RESULTS+=("$status"$'\t'"$name"$'\t'"$rc"$'\t'"$SCENARIO_LOG")
  {
    echo "$status  name=$name  exit=$rc"
    echo "  log: $SCENARIO_LOG"
  } | sanitize_stream >>"$SUITE_LOG"
done

{
  echo "# ---"
  echo "# finished: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "# passed: $passed"
  echo "# failed: $failed"
} | sanitize_stream >>"$SUITE_LOG"

echo
echo "=== suite summary ==="
for line in "${RESULTS[@]}"; do
  IFS=$'\t' read -r status name rc slog <<<"$line"
  printf '  %-4s %s (exit %s)\n' "$status" "$name" "$rc"
done
echo "passed=$passed failed=$failed"
echo "suite log: $SUITE_LOG"

if [[ "$failed" -gt 0 ]]; then
  exit 1
fi
exit 0
