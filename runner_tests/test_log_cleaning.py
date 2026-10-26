"""Keep visible evidence while removing Ansible Runner's hidden event frames."""
import base64
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


def event_frame(data, width=78):
    payload = base64.b64encode(json.dumps(data).encode()).decode()
    chunks = [payload[offset:offset + width] for offset in range(0, len(payload), width)]
    return '\x1b[K' + ''.join(f'{chunk}\x1b[{len(chunk)}D' for chunk in chunks) + '\x1b[K'


class LogCleaningTests(unittest.TestCase):
    def clean(self, text):
        result = subprocess.run(['bash', '-c',
            'source "$1/env.sh"; source "$1/lib/log.sh"; sanitize_stream',
            'bash', str(ROOT / 'roles/api_client/tests')],
            input=text, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_runner_frames_are_removed_before_ansi_controls(self):
        output = (event_frame({}) + event_frame({'uuid': 'task-id'}, width=8)
                  + '\x1b[32mok: [localhost]\x1b[0m\r\n'
                  + event_frame({}) + '\x1b[31mfatal: [localhost]: FAILED! => {"status": 404}\x1b[0m\n'
                  + event_frame({'uuid': 'recap'}) + 'PLAY RECAP\nfailed=1\n' + event_frame({}))
        self.assertEqual(self.clean(output),
                         'ok: [localhost]\nfatal: [localhost]: FAILED! => {"status": 404}\nPLAY RECAP\nfailed=1\n')

    def test_legitimate_base64_and_visible_text_are_preserved(self):
        text = 'e30=\neyJ1dWlkIjogInRhc2staWQifQ==\nAPI CLIENT SCENARIO\nCHECK MODE\nUTF-8: café\n'
        self.assertEqual(self.clean(text), text)

    def test_plain_cursor_controls_do_not_remove_visible_text(self):
        self.assertEqual(self.clean('\x1b[Khello\x1b[5D\x1b[K'), 'hello')
