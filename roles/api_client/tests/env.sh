#!/usr/bin/env bash
# Harness environment for api_client tests. Sourced by run.sh (and run-all.sh).
# You can also source it before a manual ansible-navigator run:
#
#   source ./env.sh
#   ansible-navigator run "$PLAYBOOK" -i "$INVENTORY" \
#     --eei "$EE_IMAGE" --pp "${EE_PULL_POLICY:-missing}" \
#     --mode stdout --pae false \
#     --eev "$(cd "$TESTS_DIR/.." && pwd):$(cd "$TESTS_DIR/.." && pwd):Z" \
#     --co=--network=host \
#     --vault-password-file "$ANSIBLE_VAULT_PASSWORD_FILE" \
#     -e @"$VAULT_FILE" \
#     -e scenario_vars=scenarios/happy-path.yml
#
# Override any export before or after sourcing, e.g.:
#   EE_IMAGE=localhost/my-ansible-ee:dev source ./env.sh

TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Paths relative to this harness directory
export TESTS_DIR
export INVENTORY="${INVENTORY:-${TESTS_DIR}/inventory.yml}"
export PLAYBOOK="${PLAYBOOK:-${TESTS_DIR}/test.yml}"
export VAULT_FILE="${VAULT_FILE:-${TESTS_DIR}/vault.yml}"
export LOGS_DIR="${LOGS_DIR:-${TESTS_DIR}/logs}"
# Default ansible verbosity for run-all.sh / scenario-suite.yml defaults
export DEFAULT_VERBOSITY="${DEFAULT_VERBOSITY:-0}"

# Standard Ansible env var — also used by run.sh as --vault-password-file.
# Points at the gitignored password file next to this script.
export ANSIBLE_VAULT_PASSWORD_FILE="${ANSIBLE_VAULT_PASSWORD_FILE:-${TESTS_DIR}/.vault_pass}"

# Ansible Execution Environment image for ansible-navigator (--eei).
# Prefer a local tag for demos (creator-ee / community-dev-tools pulls are large).
#
# Examples (override as needed):
#   export EE_IMAGE=localhost/ansible-ee:latest
#   export EE_IMAGE=localhost/my-lab-ee:dev
#   export EE_IMAGE=ghcr.io/ansible/community-ansible-dev-tools:latest
#   export EE_IMAGE=quay.io/ansible/creator-ee:latest
export EE_IMAGE="${EE_IMAGE:-quay.io/ansible/creator-ee:latest}"

# navigator --pp (pull policy): missing | never | always | tag
# "missing" avoids re-pulling when a local image already exists.
export EE_PULL_POLICY="${EE_PULL_POLICY:-missing}"

# Extra container engine flags for navigator (--co). Default host networking so
# the EE can reach the mock API on the host at 127.0.0.1:8765.
# Clear to disable: NAVIGATOR_CONTAINER_OPTIONS= ./run.sh happy-path
export NAVIGATOR_CONTAINER_OPTIONS="${NAVIGATOR_CONTAINER_OPTIONS---network=host}"
