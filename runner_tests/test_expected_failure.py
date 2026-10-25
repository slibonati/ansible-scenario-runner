"""Verify expected exit outcomes with real Ansible and an isolated role."""
import json
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
        # Translate navigator arguments to local Ansible to test real role exits.
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

    def test_role_failure_is_accepted_when_expected(self):
        self.prepare()
        result = self.run_script('run.sh', 'happy-path', EXPECTED_FAILURE='1')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('command failed as expected', result.stderr)

    def test_ordinary_failure_remains_failure(self):
        self.prepare()
        self.assertNotEqual(self.run_script('run.sh', 'happy-path').returncode, 0)

    def test_manifest_boolean_accepts_role_failure(self):
        self.prepare()
        result = self.suite('scenarios: [{name: happy-path, expected_failure: true}]')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('passed=1 failed=0', result.stdout)

    def test_api_suite_with_expected_failure(self):
        import importlib.util
        import threading
        self.prepare()
        source = test_runner.ROOT / 'roles/api_client'
        shutil.copy(source / 'tasks/main.yml', self.harness.parent / 'tasks/main.yml')
        shutil.copytree(source / 'defaults', self.harness.parent / 'defaults')
        spec = importlib.util.spec_from_file_location('expected_failure_mock', source / 'tests/mock_api/server.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.EXPECTED_TOKEN = 'demo-token'
        server = module.ThreadingHTTPServer(('127.0.0.1', 0), module.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            (self.harness / 'vault.yml').write_text(json.dumps({
                'api_token': 'demo-token',
                'api_base_url': f'http://127.0.0.1:{server.server_port}',
            }))
            result = self.run_script('run-all.sh')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('passed=5 failed=0', result.stdout)
            self.assertIn('command failed as expected (unknown-path', result.stderr)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
