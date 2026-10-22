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

## Execution model

1. `run-all.sh` reads the ordered `scenario-suite.yml` manifest and calls
   `run.sh` for each entry. You can also run a scenario directly.
2. `run.sh` invokes `ansible-navigator` with the playbook, inventory, vault,
   execution environment, and scenario file path.
3. `test.yml` loads the scenario variables, validates the check-mode setting,
   and invokes the role with Ansible's native `check_mode` keyword.
4. The runner saves a timestamped scenario log. Suite runs continue across
   failures and produce a pass/fail summary.

The baseline is one playbook and one inventory. Explicit manifest overrides
allow a scenario to use another playbook, inventory, vault file, or verbosity.
A custom playbook must load the scenario variables and apply check mode if it
needs the same behavior. The shell wrappers remain optional: you can invoke
Ansible directly using the same playbook and scenario input.

Versioned inputs make reruns easier to reproduce. Results still depend on the
target system, secrets, and execution environment; pin the environment image
when you need consistent dependencies.

## Included demo

Collection **`demo.scenarios`** contains one demo role:

- **`api_client`** — calls a Bearer-authenticated REST API via `ansible.builtin.uri`
  (secrets from an ansible-vault–encrypted file; request shape from scenario files)

## Layout

```
galaxy.yml
meta/runtime.yml
roles/api_client/
  defaults/ / tasks/ / meta/
  tests/
    test.yml             # harness playbook (source of truth)
    inventory.yml        # committed localhost inventory
    vault.example.yml    # plaintext key template (committed)
    setup-vault.sh       # copy example → encrypt vault.yml
    env.sh               # EE_IMAGE, vault password file, inventory paths
    lib/log.sh           # sanitized run logging helpers
    scenario-suite.yml   # ordered suite manifest for run-all.sh
    scenarios/
    logs/                # run output (*.log gitignored; .gitkeep committed)
    mock_api/            # stdlib Python mock REST API
    run.sh               # single scenario
    run-all.sh           # full suite from scenario-suite.yml
```

Checkout-and-run artifacts under `roles/api_client/tests/`: **`test.yml`**,
`inventory.yml`, `scenarios/*.yml`, `scenario-suite.yml`, `vault.example.yml`,
`setup-vault.sh`, `env.sh`, `lib/log.sh`, `mock_api/`, `run.sh`, and
`run-all.sh`. Local-only (gitignored): encrypted **`vault.yml`**,
**`.vault_pass`**, and **`logs/*.log`**.

Role FQCN: `demo.scenarios.api_client`

---

## API client role (vault + mock API)

Needs **`ansible-navigator`** (plus podman or docker), **`ansible-vault`**
for vault setup, and **PyYAML** (`python3` + `yaml`) for `run-all.sh`
manifest parsing. Scenario runs go through an execution environment
(`EE_IMAGE`). The playbook loads the role by path, so you do not have to
install the collection first.

### 1. Start the mock API

Stdlib only (no pip). Default listen: `127.0.0.1:8765`, Bearer token
`change-me` (override with `MOCK_API_TOKEN`).

```bash
roles/api_client/tests/mock_api/start.sh start   # stop | status | restart
```

Endpoints:

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| `GET` | `/health` | none | `{"status":"ok"}` |
| `GET` | `/v1/message` | Bearer | `{"message":"Hello from mock API",...}` |
| `POST` | `/v1/echo` | Bearer | echoes JSON body |

### 2. Create an encrypted vault

`vault.example.yml` documents required keys and stays **plaintext + committed**.
Runtime secrets live in **encrypted** `vault.yml` (gitignored), unlocked via
**`.vault_pass`** (also gitignored).

```bash
cd roles/api_client/tests
./setup-vault.sh
# prompts for a vault password, writes .vault_pass, copies the example,
# then runs: ansible-vault encrypt vault.yml --vault-password-file .vault_pass
```

Manual equivalent:

```bash
cd roles/api_client/tests
printf '%s\n' 'your-password' > .vault_pass && chmod 600 .vault_pass
cp vault.example.yml vault.yml
# edit api_token / api_base_url in vault.yml if needed
ansible-vault encrypt vault.yml --vault-password-file .vault_pass
```

Edit later: `ansible-vault edit vault.yml --vault-password-file .vault_pass`

### 3. Run a scenario

`test.yml` requires a **`scenario_vars`** extra-var (e.g.
`scenarios/happy-path.yml`). Relative paths resolve against **`playbook_dir`**
(not process cwd), so EE / alternate cwd runs stay reliable. The playbook
asserts the file exists and stays under the tests directory, then
`include_vars` loads it. Vault stays separate (`-e @vault.yml`).

From `roles/api_client/tests/`:

```bash
cd roles/api_client/tests

./run.sh <scenario> [verbosity]

./run.sh happy-path
./run.sh happy-path 2
./run.sh echo-payload -vv
./run.sh scenarios/health-no-auth.yml
```

- **scenario** — name (`happy-path`), file (`happy-path.yml`), or path
  (`scenarios/happy-path.yml`); resolved under `scenarios/`. `run.sh` passes
  `-e scenario_vars=scenarios/<name>.yml` (playbook loads the file).
- **verbosity** (optional) — `0`–`5` → ansible `-v` … `-vvvvv` (`0` = quiet),
  or ansible-style `-v` / `-vv` / … (passed through to navigator).
- **playbook / inventory / vault / EE** — from `$PLAYBOOK` / `$INVENTORY` /
  `$VAULT_FILE` / `$EE_IMAGE` in `env.sh`. Override via env, e.g.
  `EE_IMAGE=localhost/ansible-ee:latest ./run.sh happy-path`.
- **expected failure** — `EXPECTED_FAILURE=1 ./run.sh unknown-path` treats a
  non-zero ansible exit as success (and a zero exit as failure).
- **logging** — console shows the raw stream; a sanitized copy is written under
  `logs/<UTC-timestamp>_<scenario>.log`. Disable with `SKIP_LOG=1`.

`run.sh` sources **`env.sh`** and **`lib/log.sh`**, then runs
**`ansible-navigator run --mode stdout`**. `env.sh` exports
`ANSIBLE_VAULT_PASSWORD_FILE` (→ `.vault_pass`), `INVENTORY` / `PLAYBOOK` /
`VAULT_FILE` / `LOGS_DIR`, **`EE_IMAGE`** (default
`quay.io/ansible/creator-ee:latest` — **prefer a local tag**; creator-ee /
community-dev-tools pulls are large), and **`EE_PULL_POLICY`** (default
`missing`). `run.sh` always passes `--vault-password-file`, `--eei`,
`--pp`, `--pae false`, mounts the role dir into the EE (`--eev`), and uses
`--co=--network=host` by default so the EE can reach the host mock API.

Escape hatch (same args `run.sh` builds):

```bash
cd roles/api_client/tests
source ./env.sh
ansible-navigator run "$PLAYBOOK" -i "$INVENTORY" \
  --eei "$EE_IMAGE" --pp "$EE_PULL_POLICY" \
  --mode stdout --pae false \
  --eev "$(cd "$TESTS_DIR/.." && pwd):$(cd "$TESTS_DIR/.." && pwd):Z" \
  --co=--network=host \
  --vault-password-file "$ANSIBLE_VAULT_PASSWORD_FILE" \
  -e @"$VAULT_FILE" \
  -e scenario_vars=scenarios/happy-path.yml
```

Optional host-only fallback (not what `run.sh` uses):

```bash
source ./env.sh
ansible-playbook -i "$INVENTORY" "$PLAYBOOK" \
  --vault-password-file "$ANSIBLE_VAULT_PASSWORD_FILE" \
  -e @"$VAULT_FILE" \
  -e scenario_vars=scenarios/happy-path.yml
```

Scenario files hold **non-secret** vars (`api_path`, `api_method`, body,
expected status/message). Credentials stay in encrypted `vault.yml`.

### 4. Run the full suite (`scenario-suite.yml`)

```bash
cd roles/api_client/tests
./run-all.sh                 # default: scenario-suite.yml
./run-all.sh scenario-suite.yml
./run-all.sh --clean-logs    # delete logs/*.log first, then run suite
```

The manifest sets **defaults** (playbook, inventory, vault_file, verbosity) and an
**ordered** `scenarios:` list. Each entry can override playbook / inventory /
vault / verbosity and set `expected_failure: true` for negative cases (ansible
must fail for that entry to count as a suite pass).

The demo suite includes `unknown-path` (mock 404 vs expected 200) with
`expected_failure: true`, plus `happy-path-check` for native check mode.
Expected failure means a nonzero Ansible exit counts as a pass; it does not
verify the specific cause of failure.

### Scenario-controlled check mode

Declare check mode in the scenario file itself. For example,
`scenarios/happy-path-check.yml` contains:

```yaml
scenario_check_mode: true
api_path: /v1/message
api_method: GET
api_expected_status: 200
api_message_field: message
api_expected_message: Hello from mock API
```

Run it individually or add its name to the suite:

```bash
./run.sh happy-path-check
```

```yaml
scenarios:
  - name: happy-path
  - name: happy-path-check
```

The `-check` suffix is a naming convention. The boolean variable controls
execution. `run.sh` already passes the scenario path to `test.yml`, so no
additional shell flag or suite setting is needed. After loading the variables,
the playbook applies this setting to the role:

```yaml
roles:
  - role: "{{ playbook_dir }}/.."
    check_mode: "{{ (scenario_check_mode | default(false)) or ansible_check_mode }}"
```

Omitting `scenario_check_mode`, or setting it to `false`, uses normal execution
unless Ansible was explicitly invoked with `--check`. Use YAML booleans
`true` and `false`, not quoted strings. The built-in `ansible_check_mode`
reflects the CLI flag; the scenario variable selects the role's keyword setting.

This uses Ansible's native module behavior. Modules that support check mode
can predict changes; others may skip execution. The demo's `uri` request is
skipped, so response assertions and the response summary are skipped as well.
A passing check-mode scenario does not validate a live API response.

### Adding scenarios and regression coverage

Create a file in `scenarios/` with the role inputs and expected results, then
add its name to `scenario-suite.yml`. Existing cases run again whenever you
invoke `./run-all.sh`; adding a scenario does not require changing the scripts.
Use a descriptive qualifier such as `-check` for variants so logs identify
what was exercised. Store credentials separately in the local vault.

Suite runs preserve the declared order, continue after failures, and return
nonzero if any scenario fails its expected outcome. Use the scenario logs and
suite summary as evidence when reviewing a change.

### Logs

| What | Where |
| --- | --- |
| Single run | `logs/<YYYYMMDDTHHMMSSZ>_<scenario>.log` |
| Suite summary | `logs/<YYYYMMDDTHHMMSSZ>_suite-summary.log` |
| Per-scenario (suite) | same timestamp prefix as the suite summary |

`./run-all.sh --clean-logs` (or `CLEAR_LOGS=1`) deletes `logs/*.log` before the
suite; `logs/` and `logs/.gitkeep` are kept. Flag may appear anywhere among args.

Sanitization (log files only): UTF-8 decode with replacement, strip ANSI/CSI
color codes, drop other control characters (keep newlines and tabs), normalize
CRLF → LF. Console output is not rewritten.

### API client variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `api_base_url` | `http://127.0.0.1:8765` | API root (usually from vault) |
| `api_token` | `""` | Bearer token (**required**; from vault) |
| `api_path` | `/v1/message` | Path appended to base URL |
| `api_method` | `GET` | HTTP method |
| `api_body` | `{}` | JSON body (non-GET) |
| `api_expected_status` | `200` | Passed to `uri` `status_code` |
| `api_message_field` | `message` | JSON field to assert when expected message set |
| `api_expected_message` | `""` | If non-empty, assert field equals this |

Without credentials the role fails with a clear assert pointing at
`./setup-vault.sh` / `vault.example.yml`.

---

## Reusing the harness

Each role keeps a self-contained `tests/` directory. Copy the harness into
another role, update its scenario inputs and assertions, and adjust the inventory
and execution environment for the target. The playbook loads its enclosing role
by path. Keep `scenario_check_mode` handling when adapting the playbook.

The mock API is specific to this example and stays on the host. The execution
environment reaches it through `NAVIGATOR_CONTAINER_OPTIONS` host networking.

## Harness regression tests

With `ansible-playbook` installed, run from the repository root:

```bash
python3 -m unittest discover -s tests -v
```

These tests use an isolated temporary role to verify that check mode predicts
file changes without writing, normal mode writes, the CLI check flag remains
effective, and invalid scenario settings fail before the role runs.

## Collection install (optional)

To use the FQCN instead of a role path, install or link this repo as
`ansible_collections/demo/scenarios` on `ANSIBLE_COLLECTIONS_PATH`, then set
the playbook role to `demo.scenarios.api_client`.
