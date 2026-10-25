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
uses Python 3 for the mock server, `curl` for its health check, and the Linux
utilities `flock` (util-linux) and `ps` for lifecycle locking and process checks. The execution
environment reaches the host mock API through host networking, configured by
`NAVIGATOR_CONTAINER_OPTIONS` in `env.sh`.

The playbook loads the role by path, so collection installation is optional.
Start from the repository root after cloning (see [Start here](../README.md#start-here)).
After the vault setup step, stay in
`roles/api_client/tests/` for the remaining commands.

Before starting, check that the host tools are available:

```bash
bash --version
python3 -c 'import yaml; print("PyYAML available")'
ansible-navigator --version
ansible-vault --version
curl --version
command -v flock ps
podman info  # use docker info if Docker is your configured engine
```

The bundled networking setup assumes the execution environment can reach the
host's `127.0.0.1:8765` through `--network=host`. If your container engine runs
inside a VM, that address may refer to the VM rather than your workstation;
adapt the networking and API address before running the scenarios.

The default execution environment image is `quay.io/ansible/creator-ee:latest`.
The first run may need to pull it. To use an image already available in your
environment, export `EE_IMAGE` before running the scripts; it must contain the
Ansible dependencies needed by the role.

## Walkthrough

### 1. Start the mock API

The mock API runs at `http://127.0.0.1:8765` and uses `demo-token` as its default
Bearer token. The example vault already contains this value, so no credential
changes are needed to run the demo. The server uses only Python's standard
library; no additional Python packages are needed for it.

You can optionally set `MOCK_API_TOKEN` to use a different token. If you do,
set `api_token` in your local vault to the same value.

```bash
roles/api_client/tests/mock_api/manage.sh start   # stop | status | restart
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
# asks you to choose and confirm a new vault password, then writes .vault_pass,
# copies the example,
# then runs: ansible-vault encrypt vault.yml --vault-password-file .vault_pass
```

When prompted, **choose a new vault password**, then enter it again to confirm.
You do not need an existing password for a fresh checkout. Nothing appears as
you type. The demo API token is already configured in the example vault and
is separate from this password. If the entries differ, the script stops without
creating credential files; run it again to retry.

Later runs reuse `.vault_pass` without prompting. If an encrypted `vault.yml`
already exists but `.vault_pass` is missing, the script asks for that vault's
existing password instead.

Manual equivalent, from the same tests directory:

```bash
printf '%s\n' 'your-password' > .vault_pass && chmod 600 .vault_pass
cp vault.example.yml vault.yml
# edit api_token / api_base_url in vault.yml if needed
ansible-vault encrypt vault.yml --vault-password-file .vault_pass
```

Edit later: `ansible-vault edit vault.yml --vault-password-file .vault_pass`

The example vault already matches the mock API's default address and token.
The vault password you enter protects the local vault; it is separate from the
API token. The setup script creates credential files with owner-only access.
If encryption fails, it reports the failure and leaves the restricted file
available for correction; do not treat that file as encrypted.
If you change `MOCK_API_TOKEN` or the server address, update the
corresponding vault values too.

If you created a local vault with an earlier checkout, pulling updates does not
change it. To use the current demo default, run
`ansible-vault edit vault.yml --vault-password-file .vault_pass` and set
`api_token: demo-token`, then restart the mock API with `./mock_api/manage.sh restart`.

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
| `unknown-path` | Request a missing endpoint while the role expects HTTP 200; the suite expects failure |
| `happy-path-check` | Apply native check mode to the role |

The check-mode scenario sets `scenario_check_mode: true` in its own YAML file.
Ansible skips the `uri` request in check mode. The role also skips response
assertions and the response summary, so this case does not validate a live API
response. Use the normal scenarios for that validation.

The `unknown-path` scenario requests a missing endpoint while the role expects
HTTP 200. The manifest marks that case with `expected_failure: true`, so the
nonzero command exit counts as a pass. To use the same expectation individually:

```bash
EXPECTED_FAILURE=1 ./run.sh unknown-path
```

Running `./run.sh unknown-path` without that setting returns failure, because
single runs do not read the manifest. The separate `missing-path` scenario
illustrates the alternative: accepting HTTP 404 in the role and asserting the
error body as a normal successful test. It is not part of the default suite.

### 4. Run the suite and review evidence

```bash
./run-all.sh
./run-all.sh --clean-logs
```

The second command removes existing `logs/*.log` before running. The suite
includes all five scenarios above. `unknown-path` passes when the command exits
nonzero. This does not verify why it failed: inspect its log for the expected
HTTP 404 rather than a connection, authentication, or container error.
A successful suite ends with `passed=5 failed=0` and returns exit status 0.
The check-mode case passes without sending an API request, as described above.
Review the timestamped scenario logs and suite summary in `logs/`.

If a case fails, open the scenario log printed by the runner. Check that the
mock API is running (`./mock_api/manage.sh status`), the vault values match it,
and the execution environment can reach the API. For a case marked
`expected_failure: true`, even a container startup or image pull error can count
as a pass because only the command exit status is checked.

See the [runner reference](../README.md#running-tests-and-reading-results) for
verbosity, environment overrides, logging, and direct Ansible invocation.

### 5. Stop the mock API

From the tests directory:

```bash
./mock_api/manage.sh stop
```

The launcher verifies the recorded process identity before stopping it and
waits for shutdown before restarting. Old PID-only records cannot establish
ownership and are not used to signal a process. If upgrading from an earlier
checkout with the mock API still running, stop it with the old launcher first.

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
