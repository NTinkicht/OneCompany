#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import mistral_review_packet as packet


class MistralResultContractRegressionTests(unittest.TestCase):
    def _emitted_prompt(self) -> str:
        head = "a" * 40
        base = "b" * 40
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stage = root / "stage"
            trusted = root / "trusted"
            source_root = stage / "review_sources"
            source_root.mkdir(parents=True)
            trusted.mkdir()
            (stage / "review-target.txt").write_text(
                f"repo=NTinkicht/OneCompany\npr=123\nbase={base}\nhead={head}\n",
                encoding="utf-8",
            )
            (stage / "review.diff").write_text(
                "diff --git a/example.py b/example.py\n"
                "--- a/example.py\n+++ b/example.py\n@@ -1 +1 @@\n-old\n+new\n",
                encoding="utf-8",
            )
            (source_root / "example.py").write_text("new\n", encoding="utf-8")
            (trusted / "AGENTS.md").write_text("trusted policy\n", encoding="utf-8")
            return packet.build_packet(stage, trusted, 123, head, base)

    def test_prompt_contains_exact_json_skeleton_and_no_markdown_escape_hatch(self) -> None:
        prompt = self._emitted_prompt()
        self.assertIn('Return exactly ONE compact UTF-8 JSON object and nothing else.', prompt)
        self.assertIn('"version":1', prompt)
        self.assertIn('"verdict":"NO_BLOCKING_FINDINGS"', prompt)
        self.assertIn('"findings":[]', prompt)
        self.assertIn('Do not use markdown', prompt)
        self.assertIn('INSUFFICIENT_EVIDENCE', prompt)

    def test_contract_requires_all_exact_top_level_keys(self) -> None:
        prompt = self._emitted_prompt()
        for key in (
            '"version"', '"repo"', '"pr"', '"head_sha"', '"base_sha"',
            '"verdict"', '"summary"', '"findings"',
        ):
            with self.subTest(key=key):
                self.assertIn(key, prompt)
        self.assertIn('Emit every key exactly once and no additional keys.', prompt)


if __name__ == "__main__":
    unittest.main()
