#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import mistral_external_review as review


class ExternalReviewScalarLiteralTests(unittest.TestCase):
    def _diff(self, value: str) -> str:
        return (
            "diff --git a/.github/workflows/example.yml b/.github/workflows/example.yml\n"
            "--- a/.github/workflows/example.yml\n"
            "+++ b/.github/workflows/example.yml\n"
            "@@ -1 +1 @@\n"
            f"+          persist-credentials: {value}\n"
        )

    def test_non_secret_primitive_scalars_are_allowed(self) -> None:
        for value in ("false", "true", "null", "0", "1", "-1", "3.5"):
            with self.subTest(value=value):
                review.validate_diff([".github/workflows/example.yml"], self._diff(value))

    def test_literal_secret_string_remains_blocked(self) -> None:
        diff = (
            "diff --git a/config.yml b/config.yml\n"
            "--- a/config.yml\n"
            "+++ b/config.yml\n"
            "@@ -1 +1 @@\n"
            "+password: supersecretvalue123456789\n"
        )
        with self.assertRaisesRegex(ValueError, "EXTERNAL_REVIEW_SECRET_CONTENT_BLOCKED"):
            review.validate_diff(["config.yml"], diff)


if __name__ == "__main__":
    unittest.main()
