"""Offline tests: Settings.from_environment is sealed and fail-closed (OC-P0-10)."""
from __future__ import annotations
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services" / "github_app_adapter"))

from settings import Settings

SECRET = "s" * 32


def build(env: dict) -> Settings:
    with mock.patch.dict(os.environ, env, clear=True):
        return Settings.from_environment()


class TestSettingsEnvironment(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        key = Path(self._tmp.name) / "app.pem"
        key.write_text("test-only" * 40)
        self.key = key

    def ready_env(self, **overrides) -> dict:
        env = {
            "ONECOMPANY_ADAPTER_ENABLED": "true",
            "ONECOMPANY_CONNECTOR_BEARER": SECRET,
            "GITHUB_APP_ID": "123",
            "GITHUB_APP_INSTALLATION_ID": "456",
            "GITHUB_APP_PRIVATE_KEY_FILE": str(self.key),
            "ONECOMPANY_APPROVED_REPOSITORY": "NTinkicht/OneCompany",
            "ONECOMPANY_PUBLIC_HOST": "adapter.example.com",
        }
        env.update(overrides)
        return env

    def test_fully_configured_environment_is_ready(self):
        s = build(self.ready_env())
        self.assertTrue(s.auth_ready())
        self.assertTrue(s.github_ready())
        self.assertTrue(s.host_valid())
        self.assertEqual((s.app_id, s.installation_id), (123, 456))

    def test_empty_environment_is_sealed(self):
        s = build({})
        self.assertFalse(s.enabled)
        self.assertFalse(s.auth_ready())
        self.assertFalse(s.github_ready())
        self.assertFalse(s.host_valid())
        self.assertEqual((s.app_id, s.installation_id), (0, 0))

    def test_only_exact_lowercase_true_activates(self):
        for value in ("True", "TRUE", "1", "yes", " true", "true ", ""):
            with self.subTest(value=value):
                s = build(self.ready_env(ONECOMPANY_ADAPTER_ENABLED=value))
                self.assertFalse(s.enabled)
                self.assertFalse(s.auth_ready())
                self.assertFalse(s.github_ready())

    def test_secret_length_floor_and_whitespace_refused(self):
        self.assertFalse(build(self.ready_env(ONECOMPANY_CONNECTOR_BEARER="s" * 31)).auth_ready())
        self.assertFalse(build(self.ready_env(ONECOMPANY_CONNECTOR_BEARER=" " * 40)).auth_ready())
        self.assertFalse(build(self.ready_env(ONECOMPANY_CONNECTOR_BEARER="")).auth_ready())
        self.assertTrue(build(self.ready_env(ONECOMPANY_CONNECTOR_BEARER="s" * 32)).auth_ready())

    def test_malformed_or_negative_ids_parse_to_zero_and_stay_sealed(self):
        for value in ("abc", "-5", "", "1.5", "0"):
            with self.subTest(value=value):
                s = build(self.ready_env(GITHUB_APP_ID=value))
                self.assertEqual(s.app_id, 0)
                self.assertTrue(s.auth_ready())
                self.assertFalse(s.github_ready())
        s = build(self.ready_env(GITHUB_APP_INSTALLATION_ID="-9"))
        self.assertEqual(s.installation_id, 0)
        self.assertTrue(s.github_ready())

    def test_repository_must_be_single_owner_name_without_traversal(self):
        for repo in ("", "OneCompany", "a/b/c", "../x", "a/..", "a b/c", "a/b;c", "https://x/y"):
            with self.subTest(repo=repo):
                self.assertFalse(
                    build(self.ready_env(ONECOMPANY_APPROVED_REPOSITORY=repo)).github_ready())

    def test_missing_or_tiny_private_key_refuses(self):
        missing = Path(self._tmp.name) / "absent.pem"
        self.assertFalse(build(self.ready_env(GITHUB_APP_PRIVATE_KEY_FILE=str(missing))).github_ready())
        tiny = Path(self._tmp.name) / "tiny.pem"
        tiny.write_text("x" * 100)
        self.assertFalse(build(self.ready_env(GITHUB_APP_PRIVATE_KEY_FILE=str(tiny))).github_ready())
        self.assertFalse(build(self.ready_env(GITHUB_APP_PRIVATE_KEY_FILE=self._tmp.name)).github_ready())

    def test_host_is_lowercased_and_must_be_a_bare_hostname(self):
        self.assertEqual(build(self.ready_env(ONECOMPANY_PUBLIC_HOST="Adapter.Example.COM")).public_host,
                         "adapter.example.com")
        self.assertTrue(build(self.ready_env(ONECOMPANY_PUBLIC_HOST="Adapter.Example.COM")).host_valid())
        for host in ("", "a..b", "https://a.b", "a.b/path", "a b", "a.b:443", "a_b.c"):
            with self.subTest(host=host):
                self.assertFalse(build(self.ready_env(ONECOMPANY_PUBLIC_HOST=host)).host_valid())


if __name__ == "__main__":
    unittest.main()
