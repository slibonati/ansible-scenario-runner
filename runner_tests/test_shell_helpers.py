"""Exercise lifecycle, credential permissions, and log allocation in isolation."""
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'roles/api_client/tests'


class HelperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.harness = self.root / 'tests'
        shutil.copytree(SOURCE, self.harness, ignore=shutil.ignore_patterns(
            'vault.yml', '.vault_pass', '*.log', '.mock_api.*', '__pycache__'))
        self.env = dict(os.environ)
        for key in ('MOCK_API_HOST', 'MOCK_API_PORT', 'MOCK_API_TOKEN', 'VAULT_PASS', 'LOGS_DIR'):
            self.env.pop(key, None)
        self.env['MOCK_API_HOST'] = '127.0.0.1'

    def run_script(self, path, *args):
        return subprocess.run(['bash', str(self.harness / path), *args],
                              env=self.env, capture_output=True, text=True, timeout=15)

    def api(self, action):
        return self.run_script('mock_api/start.sh', action)

    def free_port(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            return str(sock.getsockname()[1])

    def test_api_start_status_restart_stop(self):
        self.env['MOCK_API_PORT'] = self.free_port()
        self.addCleanup(self.api, 'stop')
        for action in ('start', 'status', 'start', 'restart', 'stop', 'stop'):
            with self.subTest(action=action):
                result = self.api(action)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotEqual(self.api('status').returncode, 0)
        self.assertFalse((self.harness / 'mock_api/.mock_api.ready').exists())

    def test_stale_or_unrelated_pid_is_never_signalled(self):
        proc = subprocess.Popen(['sleep', '30'])
        try:
            for value in (str(proc.pid), f'{proc.pid} ' + 'a' * 32, '0 ' + 'a' * 32):
                with self.subTest(value=value):
                    (self.harness / 'mock_api/.mock_api.pid').write_text(value + '\n')
                    self.assertNotEqual(self.api('status').returncode, 0)
                    self.assertEqual(self.api('stop').returncode, 0)
                    self.assertIsNone(proc.poll())
        finally:
            proc.terminate()
            proc.wait()

    def test_occupied_port_fails_and_cleans_process_record(self):
        # A healthy unrelated HTTP service must not satisfy this launcher's readiness.
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            self.env['MOCK_API_PORT'] = str(server.server_port)
            result = self.api('start')
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn('failed to become healthy', result.stderr)
            self.assertFalse((self.harness / 'mock_api/.mock_api.pid').exists())
            self.assertFalse((self.harness / 'mock_api/.mock_api.ready').exists())
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def vault_stub(self, body):
        bins = self.root / 'bin'
        bins.mkdir()
        stub = bins / 'ansible-vault'
        stub.write_text('#!/bin/sh\n' + body)
        stub.chmod(0o755)
        self.env['PATH'] = str(bins) + ':' + self.env['PATH']

    def test_encryption_failure_leaves_only_private_files(self):
        self.vault_stub('exit 1\n')
        result = self.run_script('setup-vault.sh', '--demo')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('may still contain plaintext', result.stderr)
        for filename in ('.vault_pass', 'vault.yml'):
            self.assertEqual((self.harness / filename).stat().st_mode & 0o777, 0o600)

    def test_existing_credentials_are_restricted(self):
        self.vault_stub('exit 1\n')
        for filename in ('.vault_pass', 'vault.yml'):
            path = self.harness / filename
            path.write_text('dummy')
            path.chmod(0o644)
        self.run_script('setup-vault.sh')
        for filename in ('.vault_pass', 'vault.yml'):
            self.assertEqual((self.harness / filename).stat().st_mode & 0o777, 0o600)

    def test_missing_vault_tool_creates_no_credentials(self):
        bins = self.root / 'bin'
        bins.mkdir()
        # The script only needs dirname before its dependency preflight.
        (bins / 'dirname').symlink_to(shutil.which('dirname'))
        result = subprocess.run([shutil.which('bash'), str(self.harness / 'setup-vault.sh'), '--demo'],
                                env=dict(self.env, PATH=str(bins)), capture_output=True, text=True)
        self.assertEqual(result.returncode, 127, result.stderr)
        self.assertFalse((self.harness / '.vault_pass').exists())
        self.assertFalse((self.harness / 'vault.yml').exists())

    def test_vault_symlink_is_rejected(self):
        self.vault_stub('exit 0\n')
        target = self.root / 'untouched'
        target.write_text('keep')
        (self.harness / '.vault_pass').symlink_to(target)
        result = self.run_script('setup-vault.sh', '--demo')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(target.read_text(), 'keep')

    def test_log_names_are_unique_even_with_identical_prefix_and_labels(self):
        result = subprocess.run(['bash', '-c', '''
set -euo pipefail
source "$1/env.sh"
source "$1/lib/log.sh"
scenario_log_path 'a/b' fixed
scenario_log_path 'a_b' fixed
scenario_log_path 'suite-summary' fixed
suite_log_path fixed
suite_log_path fixed
''', 'bash', str(self.harness)], env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        paths = result.stdout.splitlines()
        self.assertEqual(len(set(paths)), 5)
        for path in paths:
            self.assertTrue(Path(path).exists())
            self.assertEqual(Path(path).stat().st_mode & 0o777, 0o600)
