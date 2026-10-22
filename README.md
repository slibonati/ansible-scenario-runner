# ansible-scenario-runner

Collection **`demo.scenarios`** with one demo role:

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

Demo suite includes `unknown-path` (mock 404 vs expected 200) with
`expected_failure: true`.

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

## Design notes

- **Per-role harness copy is intentional** — each role keeps a self-contained
  `tests/` tree (playbook, scenarios, mock, wrappers) so demos stay checkout-
  and-run without a shared mega-harness.
- **Wrappers are optional** — `./run.sh` / `./run-all.sh` are convenience only;
  they invoke **ansible-navigator**. The durable interface is the playbook plus
  `-e scenario_vars=…` under an EE.
- **Escape hatch** — slides and navigator use the same hook:
  `-e scenario_vars=scenarios/<name>.yml` (relative to `playbook_dir`).
- **Mock API stays on the host** — start it with `mock_api/start.sh`; the EE
  reaches it via host networking (`NAVIGATOR_CONTAINER_OPTIONS`).
- **Logs are portable artifacts** — sanitized files under `logs/` are meant to
  be skimmed or shared; console output stays raw.
- **Vault is still required for secrets** — scenario files never hold tokens;
  encrypt `vault.yml` and unlock via `.vault_pass` /
  `ANSIBLE_VAULT_PASSWORD_FILE`.

---

## Collection install (optional)

To use the FQCN instead of a role path, install or link this repo as
`ansible_collections/demo/scenarios` on `ANSIBLE_COLLECTIONS_PATH`, then set
the playbook role to `demo.scenarios.api_client`.
