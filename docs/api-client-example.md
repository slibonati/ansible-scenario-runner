# API client example

This walkthrough demonstrates the [Ansible Scenario Runner](../README.md)
using a local mock REST API. The API client and mock server are example
components; substitute your own role and target system when adopting the harness.

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

## Prerequisites

Install the [framework prerequisites](../README.md#prerequisites). This demo also
uses Python 3 for the mock server and `curl` for its health check. The execution
environment reaches the host mock API through host networking, configured by
`NAVIGATOR_CONTAINER_OPTIONS` in `env.sh`.

The playbook loads the role by path, so collection installation is optional.
Start from the repository root. After the vault setup step, stay in
`roles/api_client/tests/` for the remaining commands.

## Walkthrough

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

Manual equivalent, from the same tests directory:

```bash
printf '%s\n' 'your-password' > .vault_pass && chmod 600 .vault_pass
cp vault.example.yml vault.yml
# edit api_token / api_base_url in vault.yml if needed
ansible-vault encrypt vault.yml --vault-password-file .vault_pass
```

Edit later: `ansible-vault edit vault.yml --vault-password-file .vault_pass`

### 3. Run individual scenarios

```bash
./run.sh happy-path
./run.sh happy-path 2
./run.sh echo-payload -vv
./run.sh scenarios/health-no-auth.yml
./run.sh happy-path-check
```

| Scenario | Purpose |
| --- | --- |
| `happy-path` | Validate the authenticated message response |
| `echo-payload` | POST a JSON body and validate the response |
| `health-no-auth` | Exercise the public health endpoint |
| `unknown-path` | Expect failure for a missing endpoint |
| `happy-path-check` | Apply native check mode to the role |

The check-mode scenario sets `scenario_check_mode: true` in its own YAML file.
Ansible skips the `uri` request in check mode. The role also skips response
assertions and the response summary, so this case does not validate a live API
response. Use the normal scenarios for that validation.

To run the negative case individually with its expected outcome:

```bash
EXPECTED_FAILURE=1 ./run.sh unknown-path
```

### 4. Run the suite and review evidence

```bash
./run-all.sh
./run-all.sh --clean-logs
```

The second command removes existing `logs/*.log` before running. The suite
includes all five scenarios above and marks `unknown-path` with
`expected_failure: true`. Review the timestamped scenario logs and suite
summary in `logs/`.

See the [runner reference](../README.md#running-tests-and-reading-results) for
verbosity, environment overrides, logging, and direct Ansible invocation.

### 5. Stop the mock API

From the tests directory:

```bash
./mock_api/start.sh stop
```

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

## Collection install (optional)

To use the FQCN instead of a role path, install or link this repo as
`ansible_collections/demo/scenarios` on `ANSIBLE_COLLECTIONS_PATH`, then set
the playbook role to `demo.scenarios.api_client`.
