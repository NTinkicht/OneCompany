"""Trust boundary regression for bounded external reviewer refusal telemetry."""
from __future__ import annotations

import contextlib
import importlib.util
import io
from pathlib import Path
from unittest import TestCase, mock

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / ".github" / "mistral_external_review_impl.py"
spec = importlib.util.spec_from_file_location("l5_review_denial_telemetry", MODULE_PATH)
assert spec is not None and spec.loader is not None
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


class SafeExternalReviewBuildTelemetryTests(TestCase):
    def _run(self, exception: Exception) -> tuple[str, dict]:
        printed = io.StringIO()
        outputs: list[dict] = []

        def capture(**fields):
            outputs.append(fields)

        # Fail before network, git checkout or untrusted evidence handling.
        # Test only the trusted failure-reporting boundary.
        with (
            mock.patch.dict(review.os.environ, {
                "TARGET_REPO": "NTinkicht/veritas-atlas",
                "TARGET_PR": "64",
                "TARGET_HEAD": "a" * 40,
                "TARGET_BASE": "b" * 40,
                "TARGET_DIR": str(ROOT),
            }),
            mock.patch.object(review, "current_pr", side_effect=exception),
            mock.patch.object(review, "output", side_effect=capture),
            contextlib.redirect_stdout(printed),
        ):
            review.build_prompt()
        self.assertEqual(len(outputs), 1)
        self.assertEqual(outputs[0]["ready"], "false")
        return printed.getvalue(), outputs[0]

    def test_allowlisted_denial_emits_only_trusted_code(self):
        log, result = self._run(ValueError("EXTERNAL_REVIEW_DIFF_BOUND_BLOCKED"))
        self.assertEqual(result["status"], "EXTERNAL_REVIEW_DIFF_BOUND_BLOCKED")
        self.assertEqual(log, "EXTERNAL_REVIEW_BUILD_DENIED=EXTERNAL_REVIEW_DIFF_BOUND_BLOCKED\n")

    def test_arbitrary_exception_text_is_not_logged_or_published(self):
        secret_canary = "PRIVATE_SENTINEL_NOT_FOR_LOGS_123"
        log, result = self._run(RuntimeError(secret_canary))
        self.assertEqual(result["status"], "EXTERNAL_REVIEW_EVIDENCE_BLOCKED")
        self.assertEqual(log, "EXTERNAL_REVIEW_BUILD_DENIED=EXTERNAL_REVIEW_EVIDENCE_BLOCKED\n")
        self.assertNotIn(secret_canary, log + str(result))

    def test_unrecognized_valueerror_is_redacted(self):
        log, result = self._run(ValueError("untrusted path /tmp/test-token"))
        self.assertEqual(result["status"], "EXTERNAL_REVIEW_EVIDENCE_BLOCKED")
        self.assertNotIn("untrusted path", log)
