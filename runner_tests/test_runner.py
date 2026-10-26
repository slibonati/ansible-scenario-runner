"""Regression tests for runner outcomes and distributable collection contents."""
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.harness = self.root / 'role/tests'
        shutil.copytree(ROOT / 'roles/api_client/tests', self.harness,
                        ignore=shutil.ignore_patterns('vault.yml', '.vault_pass', '*.log', '.mock_api.pid'))
        (self.harness / 'vault.yml').write_text('{}')
        (self.harness / '.vault_pass').write_text('dummy')
        bins = self.root / 'bin'
        bins.mkdir()
        nav = bins / 'ansible-navigator'
        nav.write_text('#!/bin/sh\necho invoked >> "$PROBE"\necho command-output\nexit "${STUB_RC:-0}"\n')
        nav.chmod(0o755)
        self.probe = self.root / 'invocations'
        self.env = dict(os.environ, PATH=str(bins) + ':' + os.environ['PATH'],
                        PROBE=str(self.probe), LOGS_DIR=str(self.root / 'logs'))
        for key in ('EXPECTED_FAILURE', 'SKIP_LOG', 'LOG_FILE', 'PLAYBOOK', 'INVENTORY',
                    'VAULT_FILE', 'ANSIBLE_VAULT_PASSWORD_FILE', 'CLEAR_LOGS'):
            self.env.pop(key, None)

    def run_script(self, script, *args, **env):
        return subprocess.run([str(self.harness / script), *args],
                              env=dict(self.env, **env), capture_output=True, text=True)

    def suite(self, content):
        manifest = self.root / 'suite.yml'
        manifest.write_text(content)
        return self.run_script('run-all.sh', str(manifest))

    def test_invalid_manifests_never_execute_partial_suite(self):
        for content in ('scenarios: []', 'scenarios: [', '[]',
                        'defaults: []\nscenarios: [{name: happy-path}]',
                        'scenarios:\n - name: happy-path\n - missing_name: true',
                        'scenarios: [{name: happy-path, verbosity: 9}]',
                        'scenarios: [{name: happy-path, expected_failure: invalid}]',
                        'scenarios: [{name: happy-path}, {name: happy-path}]'):
            with self.subTest(content=content):
                result = self.suite(content)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertFalse(self.probe.exists())

    def test_suite_banner_shows_effective_settings_without_runtime_details(self):
        self.env['EE_IMAGE'] = 'localhost/review-ee:test'
        self.env['EE_PULL_POLICY'] = 'never'
        self.env['NAVIGATOR_CONTAINER_OPTIONS'] = '--network=host'
        result = self.suite('scenarios: [{name: happy-path}]')
        self.assertEqual(result.returncode, 0, result.stderr)
        banner = result.stdout.split('=== [happy-path] ===')[0]
        self.assertIn('SCENARIO SUITE', banner)
        self.assertIn(f'Manifest        : {self.root / "suite.yml"}', banner)
        self.assertIn('Scenarios       : 1', banner)
        self.assertIn('Execution image : localhost/review-ee:test', banner)
        self.assertIn(f'Logs directory  : {self.root / "logs"}', banner)
        self.assertNotIn('Pull policy', banner)
        self.assertNotIn('--network=host', banner)
        self.assertNotIn('vault', banner.lower())
        summary = next((self.root / 'logs').glob('*suite-summary.log')).read_text()
        self.assertIn('SCENARIO SUITE', summary)
        self.assertIn('Execution image : localhost/review-ee:test', summary)

    def test_suite_runs_all_cases_after_failure(self):
        result = self.suite('scenarios: [{name: happy-path}, {name: echo-payload}]')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.probe.read_text().splitlines()), 2)
        self.env['STUB_RC'] = '125'
        result = self.suite('scenarios: [{name: happy-path}, {name: echo-payload}]')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('passed=0 failed=2', result.stdout)

    def test_suite_expected_failure_counts_and_unexpected_success(self):
        manifest = 'scenarios: [{name: unknown-path, expected_failure: true}]'
        self.env['STUB_RC'] = '2'
        result = self.suite(manifest)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('FAIL unknown-path (expected)', result.stdout)
        self.assertIn('passed=0 failed=1', result.stdout)
        self.assertNotIn('unexpected_outcomes=', result.stdout)
        summary = next((self.root / 'logs').glob('*suite-summary.log')).read_text()
        self.assertIn('# failed: 1', summary)
        self.assertIn('FAIL unknown-path (expected)', summary)
        self.env['STUB_RC'] = '0'
        result = self.suite(manifest)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('passed=1 failed=0', result.stdout)
        self.assertIn('PASS unknown-path (unexpected—failure expected)', result.stdout)

    def test_suite_continues_after_unexpected_success_and_preflight_failure(self):
        result = self.suite('scenarios: [{name: unknown-path, expected_failure: true}, {name: happy-path}]')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('passed=2 failed=0', result.stdout)
        self.assertEqual(len(self.probe.read_text().splitlines()), 2)
        result = self.suite('scenarios: [{name: missing-file, expected_failure: true}, {name: happy-path}]')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('FAIL missing-file (runner error)', result.stdout)
        self.assertIn('passed=1 failed=1', result.stdout)

    def test_log_failure_prevents_execution(self):
        result = self.run_script('run.sh', 'happy-path', LOG_FILE=str(self.root / 'missing/run.log'))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.probe.exists())

    def test_log_failure_after_execution_is_reported(self):
        # First sanitizer writes the header; subsequent calls fail.
        with (self.harness / 'lib/log.sh').open('a') as file:
            file.write('\nsanitize_stream() { if [[ -f "$PROBE" ]]; then return 1; else cat; fi; }\n')
        result = self.run_script('run.sh', 'happy-path')
        self.assertTrue(self.probe.exists())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('failed to capture run evidence', result.stderr)

    def test_command_status_and_logs_are_preserved(self):
        for rc in (0, 2, 125):
            with self.subTest(rc=rc):
                log = self.root / f'run-{rc}.log'
                result = self.run_script('run.sh', 'happy-path', STUB_RC=str(rc), LOG_FILE=str(log))
                self.assertEqual(result.returncode, rc, result.stderr)
                self.assertIn('command-output', log.read_text())
                self.assertIn(f'# exit_code: {rc}', log.read_text())

    def test_expected_failure_accepts_nonzero_command_exits(self):
        for skip_log in ('0', '1'):
            for rc in ('2', '125'):
                with self.subTest(rc=rc, skip_log=skip_log):
                    result = self.run_script('run.sh', 'unknown-path', EXPECTED_FAILURE='1', STUB_RC=rc, SKIP_LOG=skip_log)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn('command failed as expected', result.stderr)

    def test_expected_failure_rejects_success(self):
        result = self.run_script('run.sh', 'unknown-path', EXPECTED_FAILURE='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('command succeeded', result.stderr)

    def test_expected_failure_does_not_hide_harness_errors(self):
        result = self.run_script('run.sh', 'unknown-path', EXPECTED_FAILURE='1', STUB_RC='2',
                                 LOG_FILE=str(self.root / 'missing/run.log'))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.probe.exists())
        (self.harness / 'vault.yml').unlink()
        self.assertNotEqual(self.run_script('run.sh', 'unknown-path', EXPECTED_FAILURE='1').returncode, 0)

    def test_expected_failure_does_not_hide_post_command_log_errors(self):
        with (self.harness / 'lib/log.sh').open('a') as file:
            file.write('\nsanitize_stream() { if [[ -f "$PROBE" ]]; then return 1; else cat; fi; }\n')
        result = self.run_script('run.sh', 'unknown-path', EXPECTED_FAILURE='1', STUB_RC='2')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.probe.exists())

    @unittest.skipUnless(shutil.which('ansible-galaxy'), 'ansible-galaxy required')
    def test_collection_excludes_local_credentials_and_logs(self):
        source = self.root / 'collection'
        source.mkdir()
        shutil.copy(ROOT / 'galaxy.yml', source)
        shutil.copy(ROOT / 'README.md', source)
        shutil.copytree(self.root / 'role', source / 'roles/api_client')
        local = source / 'roles/api_client/tests'
        (local / 'logs/probe.log').write_text('dummy')
        (local / 'mock_api/.mock_api.pid').write_text('123')
        result = subprocess.run(['ansible-galaxy', 'collection', 'build', str(source),
                                 '--output-path', str(self.root)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        with tarfile.open(next(self.root.glob('*.tar.gz'))) as archive:
            names = archive.getnames()
        for suffix in ('/vault.yml', '/.vault_pass', '/probe.log', '/.mock_api.pid'):
            self.assertFalse(any(name.endswith(suffix) for name in names), suffix)
        self.assertIn('roles/api_client/tests/vault.example.yml', names)
