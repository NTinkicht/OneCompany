"""Regression coverage for malformed optional-provider configuration."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from execution_core import RunKey
from harness_contract import HarnessIntent, TrustedHarnessSnapshot, assess_intent

HEAD = "a" * 40
BASE = "b" * 40
KEY = RunKey("WU-P1-FOUNDATIONS-001", "provider-config", 4)


class HarnessProviderConfigurationTests(unittest.TestCase):
    def test_non_mapping_provider_configuration_fails_closed(self):
        intent = HarnessIntent(
            key=KEY,
            project="example/private-project",
            actor="verified-bot",
            capability="implementation",
            head=HEAD,
            base=BASE,
            tools=frozenset({"read_file", "run_tests"}),
        )
        trusted = TrustedHarnessSnapshot(
            key=KEY,
            project="example/private-project",
            head=HEAD,
            base=BASE,
            lease_actor="verified-bot",
            lease_capability="implementation",
            lease_active=True,
            permitted_tools=frozenset({"read_file", "run_tests"}),
            actor_verified=True,
            actor_cost_class="INCLUDED_SUBSCRIPTION",
            stop_active=False,
            extra_spend_cap=0,
        )
        for malformed in ([], (), "native", 1, True):
            with self.subTest(malformed=repr(malformed)):
                verdict = assess_intent(
                    intent,
                    trusted,
                    provider_configuration=malformed,  # type: ignore[arg-type]
                )
                self.assertFalse(verdict.permitted)
                self.assertEqual(verdict.code, "INVALID_PROVIDER_CONFIGURATION")


if __name__ == "__main__":
    unittest.main()
