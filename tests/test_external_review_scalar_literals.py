#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import mistral_external_review as review


class ExternalReviewScalarLiteralTests(unittest.TestCase):
    def _diff(self, key: str, value: str) -> str:
        return (
            "diff --git a/.github/workflows/example.yml b/.github/workflows/example.yml\n"
            "--- a/.github/workflows/example.yml\n"
            "+++ b/.github/workflows/example.yml\n"
            "@@ -1 +1 @@\n"
            f"+          {key}: {value}\n"
        )

    def test_non_secret_primitive_scalars_are_allowed_for_persist_credentials(self) -> None:
        for value in ("false", "true", "null", "0", "1", "-1", "3.5"):
            with self.subTest(value=value):
                review.validate_diff(
                    [".github/workflows/example.yml"],
                    self._diff("persist-credentials", value),
                )

    def test_numeric_literal_has_a_hard_bound(self) -> None:
        maximum = "1" * review.MAX_SAFE_NUMERIC_LITERAL_CHARS
        review.validate_diff(
            [".github/workflows/example.yml"],
            self._diff("persist-credentials", maximum),
        )
        oversized = "1" * (review.MAX_SAFE_NUMERIC_LITERAL_CHARS + 1)
        with self.assertRaisesRegex(ValueError, "EXTERNAL_REVIEW_SECRET_CONTENT_BLOCKED"):
            review.validate_diff(
                [".github/workflows/example.yml"],
                self._diff("persist-credentials", oversized),
            )

    def test_quoted_primitive_remains_a_string_and_is_blocked(self) -> None:
        with self.assertRaisesRegex(ValueError, "EXTERNAL_REVIEW_SECRET_CONTENT_BLOCKED"):
            review.validate_diff(
                [".github/workflows/example.yml"],
                self._diff("persist-credentials", '"false"'),
            )

    def test_other_sensitive_keys_do_not_gain_primitive_exemption(self) -> None:
        with self.assertRaisesRegex(ValueError, "EXTERNAL_REVIEW_SECRET_CONTENT_BLOCKED"):
            review.validate_diff(["config.yml"], self._diff("password", "false"))

    def test_literal_secret_strings_remain_blocked(self) -> None:
        for key in ("password", "persist-credentials"):
            with self.subTest(key=key):
                with self.assertRaisesRegex(ValueError, "EXTERNAL_REVIEW_SECRET_CONTENT_BLOCKED"):
                    review.validate_diff(
                        ["config.yml"],
                        self._diff(key, "supersecretvalue123456789"),
                    )


if __name__ == "__main__":
    unittest.main()
