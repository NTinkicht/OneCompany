"""Regression coverage for the 256 KB exact-head Mistral review packet limit."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "onecompany-mistral-exact-head-review.yml"


class MistralReview256KWorkflowTests(unittest.TestCase):
    def test_runtime_review_limits_are_raised_to_256k(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn('"MAX_DIFF_BYTES = 100_000": "MAX_DIFF_BYTES = 256_000"', text)
        self.assertIn('"MAX_REVIEW_STAGE_DIFF_BYTES = 32_000": "MAX_REVIEW_STAGE_DIFF_BYTES = 256_000"', text)
        self.assertIn('"MAX_REVIEW_STAGE_TOTAL_BYTES = 48_000": "MAX_REVIEW_STAGE_TOTAL_BYTES = 320_000"', text)
        self.assertIn('"MAX_INLINE_BYTES = 50_000": "MAX_INLINE_BYTES = 320_000"', text)
        self.assertIn('"MAX_INPUT_BYTES = 64_000": "MAX_INPUT_BYTES = 256_000"', text)


if __name__ == "__main__":
    unittest.main()
