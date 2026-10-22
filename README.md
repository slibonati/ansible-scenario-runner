# ansible-scenario-runner

A lightweight execution model for scenario-based validation, built on Ansible
playbooks, roles, variables, and native check mode. Run one scenario while
iterating or an ordered suite for regression testing, with timestamped logs
for each run.

## Motivation

This started with a practical problem: development runs and role tests used
different execution paths. Scenarios ran individually, evidence capture was
manual, and reproducing a previous run required reconstructing its inputs.

The runner makes the role's `tests/` directory the shared execution location.
Scenario files declare inputs, a suite manifest declares order and expected
outcomes, and the scripts capture results as files. The playbook, inventory,
and scenarios live alongside the role in Git. Secrets stay local.

Molecule was explored, but setup friction in the target environment and the
complexity needed for this use case led to a smaller harness built directly
on Ansible primitives.

## How it works

The framework lives in each role's `tests/` directory. Its reusable scripts
currently reside under `roles/api_client/tests/` in this repository, alongside
the worked example.

1. `run-all.sh` reads the suite manifest and calls `run.sh` in the declared order.
2. `run.sh` invokes `ansible-navigator` with the execution context and scenario path.
3. `test.yml` loads scenario variables and invokes the enclosing role, applying
   the scenario's native check-mode setting.
4. Each run produces a timestamped log. Suite runs continue across failures
   and produce a pass/fail summary.

The baseline is one playbook and one inventory, with explicit overrides for
cases that need a different execution context. The wrappers are optional:
the playbook and scenario files can also be used directly with Ansible.

### Framework files

The following layout is the pattern to use inside your own role:

```text
roles/<your-role>/tests/
  run.sh                 # run one scenario
  run-all.sh             # run an ordered suite
  env.sh                 # paths and execution environment
  lib/log.sh             # log capture and text cleanup
  test.yml               # load scenario variables and invoke the role
  inventory.yml          # default target inventory
  scenario-suite.yml     # ordered scenarios and execution overrides
  scenarios/*.yml        # role inputs, expected results, check-mode setting
  vault.example.yml      # credential template without real secrets
  setup-vault.sh         # create the local encrypted vault
  .gitignore             # exclude credentials and runtime artifacts
  logs/.gitkeep          # retain the empty log directory in Git
```

Commit the harness, scenarios, inventory, and credential template. Keep the
local `vault.yml`, `.vault_pass`, and runtime logs out of Git. The supplied
scripts currently require a vault file and password file for each run.

### Prerequisites

- Bash and Python 3, with PyYAML for suite manifest parsing.
- `ansible-navigator` and a container engine such as Podman or Docker.
- An Ansible execution environment image containing the role's dependencies.
- `ansible-vault` for local vault setup.

Versioned inputs make reruns easier to reproduce. Results still depend on the
target system, secrets, and execution environment. Pin the environment image
when consistent dependencies matter.

## Scenario configuration

### Inputs and assertions

A scenario is a YAML variables file under `scenarios/`. It supplies the role's
inputs and any expected values used by your assertions. The role or test
playbook owns the assertion logic; the runner uses Ansible's exit status.

`run.sh` passes the scenario path as `scenario_vars`. The supplied `test.yml`
resolves it relative to the playbook directory, checks that it exists and stays
under that directory, then loads it with `include_vars`. Credentials are loaded
separately from the vault.

### Native check mode

Set this variable in a scenario file to apply Ansible's native check mode to
the role:

```yaml
scenario_check_mode: true
# Add the role's inputs and expected values here.
```

Use a filename qualifier such as `-check` to make the intent visible. The
variable controls execution; the filename is only a convention. Single runs
and suite runs load the same setting without additional shell flags.

After loading the scenario, the playbook invokes the role with:

```yaml
roles:
  - role: "{{ playbook_dir }}/.."
    check_mode: "{{ (scenario_check_mode | default(false)) or ansible_check_mode }}"
```

Omitting the variable or setting it to `false` uses normal execution unless
Ansible was explicitly invoked with `--check`. Use YAML booleans `true` and
`false`, not quoted strings. The built-in `ansible_check_mode` reflects the CLI
flag; the scenario variable selects the role's keyword setting.

Check-mode behavior depends on the modules used by the role. Some predict
changes; others skip execution. Assertions that depend on skipped tasks must
account for missing results. Adapted playbooks must retain the variable loading,
validation, and role keyword if they need this behavior.

### Suite manifest and expected failures

`scenario-suite.yml` declares defaults and an ordered list of cases. This
illustrative manifest assumes matching scenario files exist:

```yaml
defaults:
  playbook: test.yml
  inventory: inventory.yml
  vault_file: vault.yml
  verbosity: 0

scenarios:
  - name: baseline
  - name: baseline-check
  - name: invalid-input
    expected_failure: true
  - name: alternate-target
    scenario: scenarios/baseline.yml
    inventory: inventory-alternate.yml
```

| Entry field | Behavior |
| --- | --- |
| `name` | Required case name; default vars file is `scenarios/<name>.yml` |
| `scenario` or `file` | Explicit scenario vars file |
| `playbook` | Override the default test playbook |
| `inventory` | Override the default inventory |
| `vault_file` | Override the default vault |
| `verbosity` | Override verbosity, from 0 to 5 |
| `expected_failure` | A nonzero Ansible exit counts as a pass |

Manifest paths resolve relative to the role's `tests/` directory unless
absolute. Check mode belongs in the scenario variables file, not the manifest.
Expected failure checks the exit status, not the specific cause of failure;
an unexpected success fails that case.

## Running tests and reading results

Run commands from your role's `tests/` directory. The examples below use
`baseline` as a placeholder for a scenario you have created.

### Single scenario

```bash
./run.sh baseline
./run.sh baseline 2
./run.sh scenarios/baseline.yml -vv
EXPECTED_FAILURE=1 ./run.sh invalid-input
```

The interface is `./run.sh <scenario> [verbosity]`. A scenario can be a name,
filename, or path. Verbosity accepts `0`–`5` or `-v` through `-vvvvv`.
A normal run returns Ansible's exit code. `EXPECTED_FAILURE=1` maps an Ansible
failure to success and an unexpected success to failure.

### Full suite

```bash
./run-all.sh
./run-all.sh scenario-suite.yml
./run-all.sh --clean-logs
```

The suite runs in manifest order, continues after individual failures, and
returns nonzero if any case fails its expected outcome. Add new scenario files
and manifest entries to expand regression coverage without changing the scripts.

### Execution context

`env.sh` supplies defaults. Override these variables before invoking a runner:

| Variable | Purpose |
| --- | --- |
| `PLAYBOOK`, `INVENTORY` | Test playbook and target inventory |
| `VAULT_FILE` | Encrypted variables file |
| `ANSIBLE_VAULT_PASSWORD_FILE` | Local password-file path, default `.vault_pass` |
| `EE_IMAGE` | Execution environment image |
| `EE_PULL_POLICY` | Image pull policy, default `missing` |
| `NAVIGATOR_CONTAINER_OPTIONS` | Container options; bundled default is `--network=host` |
| `LOGS_DIR` | Output directory, default `logs/` |
| `LOG_FILE` | Explicit single-run log path |
| `SKIP_LOG` | Set to `1` to disable scenario log capture |

For example:

```bash
EE_IMAGE=localhost/my-ansible-ee:latest ./run.sh baseline
PLAYBOOK=alternate-test.yml INVENTORY=alternate-inventory.yml ./run.sh baseline
```

The bundled image default is `quay.io/ansible/creator-ee:latest`. Select an image
appropriate for your role. Suite manifest defaults and entry overrides determine
the playbook, inventory, vault, and verbosity passed to each scenario.

### Logs

| Artifact | Location |
| --- | --- |
| Scenario log | `logs/<UTC-timestamp>_<scenario>.log` |
| Suite summary | `logs/<UTC-timestamp>_suite-summary.log` |
| Logs from one suite | Share a timestamp prefix |

Scenario logs capture the command, timestamps, output, and exit status. Suite
summaries record each outcome. Use these files as review and handoff evidence.

`--clean-logs`, or `CLEAR_LOGS=1`, removes existing `logs/*.log` before a suite
run while retaining the directory and `.gitkeep`. Text cleanup strips terminal
formatting and control characters and normalizes line endings. It does not
redact secrets. Console output remains unchanged.

### Direct Ansible invocation

The wrappers provide execution defaults and evidence capture. From a configured
role's tests directory, the equivalent direct invocation is:

```bash
source ./env.sh
ansible-navigator run "$PLAYBOOK" -i "$INVENTORY" \
  --eei "$EE_IMAGE" --pp "$EE_PULL_POLICY" \
  --mode stdout --pae false \
  --eev "$(cd "$TESTS_DIR/.." && pwd):$(cd "$TESTS_DIR/.." && pwd):Z" \
  --co=--network=host \
  --vault-password-file "$ANSIBLE_VAULT_PASSWORD_FILE" \
  -e @"$VAULT_FILE" \
  -e scenario_vars=scenarios/baseline.yml
```

Adjust the container options for your environment. If the host has Ansible and
all required dependencies, you can also run the playbook directly:

```bash
source ./env.sh
ansible-playbook -i "$INVENTORY" "$PLAYBOOK" \
  --vault-password-file "$ANSIBLE_VAULT_PASSWORD_FILE" \
  -e @"$VAULT_FILE" \
  -e scenario_vars=scenarios/baseline.yml
```

## Using the framework with your own role

1. Copy the framework files listed above from `roles/api_client/tests/` into
   your role's `tests/` directory, including `lib/log.sh` and `.gitignore`.
2. Adapt `test.yml` for your target hosts and role assertions. The supplied
   playbook targets localhost and loads its enclosing role by path. Preserve
   scenario loading and check-mode handling.
3. Set your inventory, execution environment, and container options in `env.sh`.
4. Replace `vault.example.yml` with your credential template and run
   `./setup-vault.sh` to create the local encrypted vault and password file.
5. Create your scenario files and an ordered `scenario-suite.yml`. Run each
   new case individually, then run the full suite and inspect its logs.

The reusable harness is currently distributed inside the example role. Copy
only the framework files; provide your own role inputs, assertions, and any
required test services. Each role owns its test directory and execution context.

## Worked example: API client

The included `demo.scenarios.api_client` role illustrates the framework with a
local mock REST API, encrypted credentials, normal and negative scenarios, and
a check-mode variant.

Follow the [API client walkthrough](docs/api-client-example.md) for setup,
runnable commands, scenario details, and the API variable reference.

## Framework development

With `ansible-playbook` installed, run from the repository root:

```bash
python3 -m unittest discover -s tests -v
```

The tests use an isolated temporary role to verify that check mode predicts
file changes without writing, normal mode writes, the CLI check flag remains
effective, and invalid scenario settings fail before the role runs.
