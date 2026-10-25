"""Exercise the real harness against a role that would create a file.

Run: python3 -m unittest discover -s runner_tests -v
Requires ansible-playbook on PATH.
"""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('ansible-playbook'), 'ansible-playbook is required')
class CheckModeTests(unittest.TestCase):
    def run_scenario(self, setting=None, global_check=False, valid=True):
        with tempfile.TemporaryDirectory(prefix='scenario-check-') as directory:
            role = Path(directory) / 'probe'
            tests = role / 'tests'
            tests.mkdir(parents=True)
            (role / 'tasks').mkdir()
            target = role / 'created.txt'
            shutil.copy(ROOT / 'roles/api_client/tests/test.yml', tests / 'test.yml')
            (role / 'tasks/main.yml').write_text(json.dumps([{
                'name': 'Create a file only in normal mode',
                'ansible.builtin.copy': {'dest': str(target), 'content': 'created\n'},
            }]))
            scenario = {} if setting is None else {'scenario_check_mode': setting}
            (tests / 'scenario.yml').write_text(json.dumps(scenario))
            command = ['ansible-playbook', str(tests / 'test.yml'), '-i', 'localhost,',
                       '-e', 'scenario_vars=scenario.yml']
            if global_check:
                command.append('--check')
            result = subprocess.run(command, capture_output=True, text=True)
            output = result.stdout + result.stderr
            if not valid:
                self.assertNotEqual(result.returncode, 0, output)
                self.assertIn('must be a YAML boolean', output)
                self.assertFalse(target.exists())
                return
            self.assertEqual(result.returncode, 0, output)
            self.assertEqual(target.exists(), not (setting is True or global_check), output)
            self.assertIn('changed=1', output)

    def test_scenario_check_mode_does_not_write(self):
        self.run_scenario(True)

    def test_false_runs_normally(self):
        self.run_scenario(False)

    def test_omitted_runs_normally(self):
        self.run_scenario()

    def test_global_check_preserved_when_scenario_false(self):
        self.run_scenario(False, global_check=True)

    def test_global_check_preserved_when_scenario_omitted(self):
        self.run_scenario(global_check=True)

    def test_invalid_setting_rejected(self):
        self.run_scenario('false', valid=False)

    def test_api_banner_and_skipped_request_for_scenario_and_cli_check(self):
        with tempfile.TemporaryDirectory(prefix='scenario-banner-') as directory:
            role = Path(directory) / 'api_client'
            shutil.copytree(ROOT / 'roles/api_client', role, ignore=shutil.ignore_patterns(
                'vault.yml', '.vault_pass', '*.log', '.mock_api.*', '__pycache__'))
            for scenario, cli_check in (('happy-path-check', False), ('happy-path', True)):
                with self.subTest(scenario=scenario):
                    command = ['ansible-playbook', str(role / 'tests/test.yml'), '-i', 'localhost,',
                               '-e', json.dumps({'scenario_vars': f'scenarios/{scenario}.yml',
                                                 'api_token': 'banner-secret-sentinel'})]
                    if cli_check:
                        command.append('--check')
                    result = subprocess.run(command, capture_output=True, text=True)
                    output = result.stdout + result.stderr
                    self.assertEqual(result.returncode, 0, output)
                    self.assertIn('API client configuration', output)
                    self.assertIn('"execution_mode": "CHECK MODE"', output)
                    self.assertIn('"check_mode": true', output)
                    self.assertIn('No API call was made', output)
                    self.assertNotIn('banner-secret-sentinel', output)


if __name__ == '__main__':
    unittest.main()
