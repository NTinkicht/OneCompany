#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import mistral_review_packet as packet


class MistralResultContractRegressionTests(unittest.TestCase):
    def test_prompt_contains_exact_json_skeleton_and_no_markdown_escape_hatch(self) -> None:
        instructions = packet.INSTRUCTIONS
        self.assertIn('Return exactly ONE compact UTF-8 JSON object and nothing else.', instructions)
        self.assertIn('"version":1', instructions)
        self.assertIn('"verdict":"NO_BLOCKING_FINDINGS"', instructions)
        self.assertIn('"findings":[]', instructions)
        self.assertIn('Do not use markdown', instructions)
        self.assertIn('INSUFFICIENT_EVIDENCE', instructions)

    def test_contract_requires_all_exact_top_level_keys(self) -> None:
        instructions = packet.INSTRUCTIONS
        for key in (
            '"version"', '"repo"', '"pr"', '"head_sha"', '"base_sha"',
            '"verdict"', '"summary"', '"findings"',
        ):
            with self.subTest(key=key):
                self.assertIn(key, instructions)
        self.assertIn('Emit every key exactly once and no additional keys.', instructions)


if __name__ == "__main__":
    unittest.main()
