"""Offline canary contract: never spend, run model code, or fake provider evidence."""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import gemma_free_probe as g

CODE = "def clamp(value, low, high):\n    if low > high: raise ValueError('bounds')\n    return max(low, min(value, high))\n"
TESTS = "import unittest\nclass TestClamp(unittest.TestCase):\n    def test_low(self): self.assertEqual(clamp(-1, 0, 5), 0)\n"


class FakeResponse:
    """Bounded response stub with the urllib context-manager contract."""

    def __init__(self, value):
        self._stream = io.BytesIO(value)

    def __enter__(self):
        return self._stream

    def __exit__(self, *_args):
        self._stream.close()


def free_response(content=None, *, cost=0):
    """Encode a minimal zero-cost hosted completion for offline assertions."""
    if content is None:
        content = json.dumps({"code": CODE, "tests": TESTS})
    return json.dumps({
        "choices": [{"message": {"content": content}}],
        "usage": {"cost": cost},
    }).encode()


class GemmaFreeProbeTests(unittest.TestCase):
    """Guard the budget, model identity, network, and untrusted output."""

    def test_exact_model_allowlist(self):
        for model in ("google/gemma-4-26b-a4b-it", "openrouter/free",
                      "google/gemma-4-31b-it:free", "auto", ""):
            with self.subTest(model=model), self.assertRaisesRegex(
                ValueError, "PAID_OR_UNVERIFIED_MODEL_BLOCKED"
            ):
                g.check_model(model)

    def test_budget_rejects_paid_fallback_overage_unknown_cost(self):
        original = json.loads((ROOT / ".onecompany/budget.json").read_text())
        g.check_budget(ROOT / ".onecompany/budget.json")
        for key, value in (
            ("allow_paid_fallback", True), ("allow_overage", True),
            ("allow_auto_topup", True), ("allow_new_paid_vendor", True),
            ("additional_monthly_spend_cap", 1),
            ("unknown_cost_behavior", "allow"),
        ):
            trial = json.loads(json.dumps(original))
            trial["ai"][key] = value
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "budget.json"
                path.write_text(json.dumps(trial))
                with self.subTest(key=key), self.assertRaisesRegex(
                    ValueError, "ZERO_ADDITIONAL_SPEND_POLICY_BLOCKED"
                ):
                    g.check_budget(path)

    def test_no_key_blocks_before_network(self):
        def no_network(*_args, **_kwargs):
            raise AssertionError("Network contacted without key")
        with self.assertRaisesRegex(ValueError, "OPENROUTER_API_KEY_MISSING"):
            g.probe("", opener=no_network)

    def test_free_request_contains_synthetic_task_no_repo_source(self):
        seen = []
        def fake_open(request, timeout):
            seen.append((request, timeout))
            return FakeResponse(free_response())
        result = g.probe("PRIVATE_TOKEN_TEST", opener=fake_open)
        self.assertEqual(result["status"], "SYNTHETIC_PROPOSAL_RECEIVED")
        self.assertFalse(result["model_code_executed"])
        self.assertFalse(result["repo_code_transmitted"])
        self.assertFalse(result["model_authored_repo_commit"])
        self.assertFalse(result["independent_review_qualified"])
        self.assertEqual(len(seen), 1)
        request, timeout = seen[0]
        self.assertEqual(timeout, 30)
        self.assertEqual(request.full_url, g.API)
        payload = json.loads(request.data)
        self.assertEqual(payload["model"], g.FREE_MODEL)
        self.assertEqual(payload["stream"], False)
        self.assertEqual(payload["max_tokens"], 750)
        self.assertEqual(len(payload["messages"]), 2)
        self.assertIn("synthetic example", payload["messages"][1]["content"])
        self.assertNotIn("PRIVATE_TOKEN_TEST", request.data.decode())

    def test_http_quota_is_an_explicit_block_without_body_leak(self):
        def rate_limit(*_args, **_kwargs):
            raise urllib.error.HTTPError(
                g.API, 429, "PRIVATE_RESPONSE_BODY", {}, io.BytesIO(b"PRIVATE")
            )
        with self.assertRaisesRegex(ValueError, "^OPENROUTER_HTTP_429$"):
            g.probe("PRIVATE_TOKEN_TEST", opener=rate_limit)

    def test_provider_cost_and_malformed_outputs_fail_closed(self):
        samples = [
            (free_response(cost=0.1), "NONZERO_OR_UNKNOWN_INFERENCE_COST"),
            (free_response(cost="unknown"), "NONZERO_OR_UNKNOWN_INFERENCE_COST"),
            (free_response('{"code": "a=1", "code": "a=2", "tests": "b=1"}'),
             "DUPLICATE_MODEL_OUTPUT_KEY"),
            (free_response('{"code": "syntax error", "tests": "b=1"}'),
             "invalid syntax"),
            (free_response('{"code": "a=1", "tests": "b=1", "verdict": "PASS"}'),
             "MODEL_OUTPUT_FIELDS_INVALID"),
        ]
        for data, expected in samples:
            with self.subTest(expected=expected), self.assertRaisesRegex(
                (ValueError, SyntaxError), expected
            ):
                g.probe("PRIVATE_TOKEN_TEST",
                        opener=lambda *_a, data=data, **_k: FakeResponse(data))

    def test_offline_cli_does_not_require_key_or_contact_network(self):
        out = io.StringIO()
        with patch.object(sys, "argv", ["gemma_free_probe.py"]), patch.dict(
            "os.environ", {"OPENROUTER_API_KEY": ""}, clear=False
        ), patch.object(g.urllib.request, "urlopen",
                       side_effect=AssertionError("No network")):
            with contextlib.redirect_stdout(out):
                code = g.main()
        self.assertEqual(code, 0)
        result = json.loads(out.getvalue())
        out.close()
        self.assertEqual(result["status"], "PREFLIGHT_OK_NO_NETWORK")


if __name__ == "__main__":
    unittest.main()
