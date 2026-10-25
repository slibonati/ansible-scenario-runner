"""Verify the shell/playbook contract with real Ansible and an isolated role."""
import json
from pathlib import Path
import shutil
import unittest

import test_runner


@unittest.skipUnless(shutil.which('ansible-playbook'), 'ansible-playbook required')
class ExpectedFailureTests(unittest.TestCase):
    setUp = test_runner.RunnerTests.setUp
    run_script = test_runner.RunnerTests.run_script
    suite = test_runner.RunnerTests.suite

    def prepare(self, tasks=None):
        role_tasks = self.harness.parent / 'tasks'
        role_tasks.mkdir(exist_ok=True)
        (role_tasks / 'main.yml').write_text(json.dumps(tasks or [
            {'name': 'Reject invalid input', 'ansible.builtin.fail': {'msg': 'invalid input'}}]))
        # Translate navigator arguments to local Ansible so the real playbook
        # writes evidence. Container startup failures are covered separately.
        nav = self.root / 'bin/ansible-navigator'
        nav.write_text('''#!/usr/bin/env python3
import subprocess, sys
args = sys.argv[3:]
command = ['ansible-playbook', sys.argv[2]]
i = 0
while i < len(args):
    arg = args[i]
    if arg in ('-e', '-i', '--vault-password-file'):
        command.extend(args[i:i+2]); i += 2
    elif arg in ('--eei', '--pp', '--mode', '--pae', '--eev'):
        i += 2
    elif arg.startswith('--co='):
        i += 1
    else:
        command.append(arg); i += 1
sys.exit(subprocess.call(command))
''')
        nav.chmod(0o755)

    def expected(self, **overrides):
        settings = dict(EXPECTED_FAILURE='1', EXPECTED_FAILURE_TASK='Reject invalid input',
                        EXPECTED_FAILURE_RESULT='{"msg":"invalid input"}')
        settings.update(overrides)
        return self.run_script('run.sh', 'happy-path', **settings)

    def test_matching_failure_passes_and_temporary_evidence_is_removed(self):
        self.prepare()
        result = self.expected()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('expected failure verified', result.stdout)
        self.assertFalse(list(self.harness.glob('.scenario-result.*')))

    def test_wrong_task_or_result_fails(self):
        self.prepare()
        for overrides in ({'EXPECTED_FAILURE_TASK': 'Another task'},
                          {'EXPECTED_FAILURE_RESULT': '{"msg":"different error"}'}):
            with self.subTest(overrides=overrides):
                result = self.expected(**overrides)
                self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_unexpected_success_fails(self):
        self.prepare([{'name': 'Normal success', 'ansible.builtin.debug': {'msg': 'ok'}}])
        result = self.expected()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('role succeeded', result.stdout)

    def test_ordinary_failure_remains_failure(self):
        self.prepare()
        self.assertNotEqual(self.run_script('run.sh', 'happy-path').returncode, 0)

    def test_invalid_role_cannot_be_an_expected_failure(self):
        self.prepare()
        (self.harness.parent / 'tasks/main.yml').write_text('[bad YAML')
        self.assertNotEqual(self.expected().returncode, 0)

    def test_missing_evidence_and_engine_failure_never_pass(self):
        for rc in ('0', '125'):
            with self.subTest(rc=rc):
                self.assertNotEqual(self.expected(STUB_RC=rc).returncode, 0)

    def test_manifest_contract_reaches_playbook(self):
        self.prepare()
        result = self.suite('''scenarios:
  - name: happy-path
    expected_failure: true
    expected_failure_task: Reject invalid input
    expected_failure_result:
      msg: invalid input
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('passed=1 failed=0', result.stdout)

    def test_api_suite_with_verified_404(self):
        import importlib.util
        import threading
        self.prepare()
        source = test_runner.ROOT / 'roles/api_client'
        shutil.copy(source / 'tasks/main.yml', self.harness.parent / 'tasks/main.yml')
        shutil.copytree(source / 'defaults', self.harness.parent / 'defaults')
        spec = importlib.util.spec_from_file_location('expected_failure_mock', source / 'tests/mock_api/server.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.EXPECTED_TOKEN = 'change-me'
        server = module.ThreadingHTTPServer(('127.0.0.1', 0), module.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            (self.harness / 'vault.yml').write_text(json.dumps({
                'api_token': 'change-me',
                'api_base_url': f'http://127.0.0.1:{server.server_port}',
            }))
            result = self.run_script('run-all.sh')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('passed=5 failed=0', result.stdout)
            self.assertIn('expected failure verified: unknown-path', result.stdout)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
