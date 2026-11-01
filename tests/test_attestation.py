"""Google's login type cannot be verified by Center, so the user attests once in an interactive terminal."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / 'backend'))
from center_runtime import Center


class AttestationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.center = Center(Path(self.tmp.name) / 'state')
        self.phrase = Center.ATTEST_PHRASE.format(provider='GOOGLE')

    def login_check(self):
        listing = SimpleNamespace(returncode=0, stdout=b'gemini-3.8-flash-low\tGemini', stderr=b'')
        with patch('center_runtime.cli_command', return_value=['agy']), patch.object(subprocess, 'run', return_value=listing):
            return self.center._check_live_login('google')

    def test_google_is_never_launched_without_an_attestation(self):
        with self.assertRaisesRegex(ValueError, 'subscription_auth_unverified.*attested'):
            self.login_check()

    def test_an_agent_without_a_terminal_cannot_attest(self):
        with patch('sys.stdin.isatty', return_value=False), self.assertRaisesRegex(ValueError, 'interactive terminal'):
            self.center.attest_provider('google', 'Google AI Pro', typed=self.phrase)
        self.assertIsNone(self.center.attestation('google'))

    def test_a_wrong_confirmation_phrase_records_nothing(self):
        with patch('sys.stdin.isatty', return_value=True), self.assertRaisesRegex(ValueError, 'did not match'):
            self.center.attest_provider('google', 'Google AI Pro', typed='yes')
        self.assertIsNone(self.center.attestation('google'))

    def test_an_interactive_confirmation_unlocks_google_and_is_visible_in_status(self):
        with patch('sys.stdin.isatty', return_value=True):
            record = self.center.attest_provider('google', 'Google AI Pro', typed=self.phrase)
        self.assertEqual(record['attested_by'], 'user_interactive_terminal')
        self.assertIsNone(self.login_check())
        self.assertEqual(self.center.provider_status()['google']['attestation']['plan'], 'Google AI Pro')
        self.assertIsNone(self.center.provider_status()['codex']['attestation'])

    def test_only_google_needs_an_attestation_and_a_plan_name_is_required(self):
        with patch('sys.stdin.isatty', return_value=True):
            with self.assertRaises(ValueError):
                self.center.attest_provider('codex', 'ChatGPT Plus', typed='x')
            with self.assertRaises(ValueError):
                self.center.attest_provider('google', '   ', typed=self.phrase)


if __name__ == '__main__':
    unittest.main()
