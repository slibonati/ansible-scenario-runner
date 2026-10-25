#!/usr/bin/env bash
# Create gitignored vault.yml (ansible-vault encrypted) and .vault_pass.
#
# Usage:
#   ./setup-vault.sh              # ensure .vault_pass + encrypt vault.yml
#   ./setup-vault.sh --demo       # write demo password "demo-vault-pass" if missing
#   VAULT_PASS='secret' ./setup-vault.sh
#
# Typical first-time flow:
#   cp vault.example.yml vault.yml   # optional; setup-vault.sh copies if missing
#   # edit vault.yml (plaintext) if needed
#   ./setup-vault.sh
#   ansible-vault edit vault.yml --vault-password-file .vault_pass
set -euo pipefail
umask 077

TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$TESTS_DIR"

EXAMPLE="${TESTS_DIR}/vault.example.yml"
VAULT="${TESTS_DIR}/vault.yml"
PASS_FILE="${TESTS_DIR}/.vault_pass"
DEMO=0

for arg in "$@"; do
  case "$arg" in
    --demo) DEMO=1 ;;
    -h|--help)
      sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "unknown option: $arg" >&2
      exit 2
      ;;
  esac
done

if ! command -v ansible-vault >/dev/null 2>&1; then
  echo "ansible-vault not found in PATH; no credential files were created" >&2
  exit 127
fi
# Reject symlinks and restrict existing files as well as new ones.
for credential in "$PASS_FILE" "$VAULT"; do
  if [[ -L "$credential" || ( -e "$credential" && ! -f "$credential" ) ]]; then
    echo "credential must be a regular file, not a symlink: $credential" >&2
    exit 1
  fi
  if [[ -f "$credential" ]]; then chmod 600 "$credential"; fi
done

if [[ ! -f "$EXAMPLE" ]]; then
  echo "missing $EXAMPLE" >&2
  exit 1
fi

if [[ ! -f "$PASS_FILE" ]]; then
  if [[ -n "${VAULT_PASS:-}" ]]; then
    printf '%s\n' "$VAULT_PASS" > "$PASS_FILE"
  elif [[ "$DEMO" -eq 1 ]]; then
    printf '%s\n' 'demo-vault-pass' > "$PASS_FILE"
  elif [[ -t 0 ]]; then
    read -r -s -p "Vault password: " pw
    echo
    if [[ -z "$pw" ]]; then
      echo "empty password not allowed" >&2
      exit 1
    fi
    printf '%s\n' "$pw" > "$PASS_FILE"
  else
    echo "missing $PASS_FILE — set VAULT_PASS, use --demo, or run interactively" >&2
    exit 1
  fi
  chmod 600 "$PASS_FILE"
  echo "wrote $PASS_FILE (gitignored)"
else
  echo "using existing $PASS_FILE"
fi

if [[ ! -f "$VAULT" ]]; then
  cp "$EXAMPLE" "$VAULT"
  echo "copied vault.example.yml → vault.yml"
fi

if head -n1 "$VAULT" | grep -q '^\$ANSIBLE_VAULT'; then
  echo "vault.yml is already ansible-vault encrypted"
  exit 0
fi

if ! ansible-vault encrypt "$VAULT" --vault-password-file "$PASS_FILE"; then
  echo "encryption failed; $VAULT may still contain plaintext (restricted to owner access)" >&2
  exit 1
fi
echo "encrypted vault.yml"
echo "edit later: ansible-vault edit vault.yml --vault-password-file .vault_pass"
