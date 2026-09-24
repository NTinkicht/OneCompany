"""Fail-closed structural contract for Mistral's source-only advisory reviewer."""
import json
import subprocess
import tempfile
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from mistral_review_result import MAX_BYTES, parse_result, format_comment

HEAD = "a" * 40
BASE = "b" * 40


class MistralReviewResultTests(unittest.TestCase):
    def payload(self):
        return {
            "version": 1, "repo": "NTinkicht/OneCompany", "pr": 201,
            "head_sha": HEAD, "base_sha": BASE,
            "verdict": "NO_BLOCKING_FINDINGS",
            "summary": "No supported actionable defect in examined diff.",
            "findings": [],
        }

    def parse(self, payload):
        return parse_result(json.dumps(payload).encode("utf-8"), pr=201, head=HEAD, base=BASE)

    def test_accepts_valid_bounded_review_and_renders_advisory_comment(self):
        value = self.parse(self.payload())
        text = format_comment(value, run_url="https://github.com/example/run/1")
        self.assertIn(HEAD, text)
        self.assertIn("NON-GATING", text)
        self.assertIn("github-actions[bot]", text)
        self.assertIn("NO_BLOCKING_FINDINGS", text)

    def test_model_prose_is_rendered_inert(self):
        p = self.payload()
        p["summary"] = "@team **bold** <img src=x>"
        p["verdict"] = "CHANGES_REQUIRED"
        p["findings"] = [{"severity": "MEDIUM", "path": "scripts/example.py", "line": 7,
                          "description": "Ping @owner and [click](https://example.invalid) <b>x</b>."}]
        text = format_comment(self.parse(p), run_url="https://github.com/example/run/1")
        self.assertNotIn("@team", text)
        self.assertNotIn("@owner", text)
        self.assertNotIn("**bold**", text)
        self.assertNotIn("<img", text)
        self.assertNotIn("<b>", text)
        self.assertIn("&#64;team", text)
        self.assertIn("&#64;owner", text)
        self.assertIn("&lt;img", text)

    def test_contractions_stay_readable_while_prose_stays_inert(self):
        p = self.payload()
        p["summary"] = "The guard doesn't recheck the base; @team *should* see it."
        p["verdict"] = "CHANGES_REQUIRED"
        p["findings"] = [{"severity": "MEDIUM", "path": "scripts/example.py", "line": 7,
                          "description": "It isn't bounded; ping @owner [here](https://example.invalid)."}]
        text = format_comment(self.parse(p), run_url="https://github.com/example/run/1")
        self.assertIn("doesn't", text)
        self.assertIn("isn't", text)
        self.assertNotIn("&#x27;", text)
        self.assertNotIn("&#35;x27;", text)
        self.assertNotIn("@team", text)
        self.assertNotIn("@owner", text)
        self.assertNotIn("*should*", text)
        self.assertNotIn("[here]", text)
        self.assertIn("&#64;team", text)
        self.assertIn("&#64;owner", text)

    def test_rejects_stale_foreign_or_malformed_results(self):
        for field, bad in (
            ("version", True), ("version", 2), ("repo", "other/repo"), ("pr", 202),
            ("pr", True), ("head_sha", BASE), ("base_sha", HEAD), ("summary", ""),
            ("summary", "bad\nline"), ("summary", "x" * 1801), ("verdict", "APPROVED"),
            ("verdict", "MERGE_NOW"), ("verdict", []), ("verdict", {}),
            ("findings", {}), ("findings", [{}]), ("findings", [{}] * 13),
        ):
            with self.subTest(field=field, bad=str(bad)[:25]):
                p = self.payload(); p[field] = bad
                with self.assertRaises(ValueError): self.parse(p)

    def test_rejects_extra_missing_and_duplicate_keys(self):
        p = self.payload(); p["authority"] = "MERGE"
        with self.assertRaises(ValueError): self.parse(p)
        p = self.payload(); del p["findings"]
        with self.assertRaises(ValueError): self.parse(p)
        raw = json.dumps(self.payload()).replace('"version": 1', '"version": 1, "version": 1').encode("utf-8")
        with self.assertRaises(ValueError): parse_result(raw, pr=201, head=HEAD, base=BASE)

    def test_rejects_oversized_non_json_and_infinite(self):
        for data in (b"", b"not JSON", b"{" + b"x" * MAX_BYTES, b"{}" + b" " * MAX_BYTES,
                     json.dumps(self.payload()).replace('"version": 1', '"version": NaN').encode("utf-8")):
            with self.subTest(size=len(data)), self.assertRaises(ValueError):
                parse_result(data, pr=201, head=HEAD, base=BASE)

    def test_rejects_forged_authority_and_inconsistent_severity(self):
        sample = {"severity": "MAJOR", "path": "scripts/example.py", "line": 7,
                  "description": "Concrete wrong branch."}
        p = self.payload(); p["findings"] = [sample]
        with self.assertRaises(ValueError): self.parse(p)
        p["verdict"] = "CHANGES_REQUIRED"
        self.assertEqual(len(self.parse(p)["findings"]), 1)
        for name, bad in (("severity", "APPROVED"), ("path", "../private"), ("path", ".git/config"),
                          ("path", "/etc/passwd"), ("line", True), ("line", 0),
                          ("description", ""), ("description", "a\ncontrol")):
            with self.subTest(name=name):
                q = self.payload(); q["verdict"] = "CHANGES_REQUIRED"; q["findings"] = [{**sample, name: bad}]
                with self.assertRaises(ValueError): self.parse(q)

    def test_change_request_without_findings_is_rejected(self):
        p = self.payload(); p["verdict"] = "CHANGES_REQUIRED"
        with self.assertRaisesRegex(ValueError, "WITHOUT_FINDINGS"): self.parse(p)

    def test_isolated_cli_classifies_json_review_and_insufficient(self):
        script = SCRIPTS / "mistral_review_result.py"
        with tempfile.TemporaryDirectory() as temp:
            result = Path(temp) / "review.json"
            for verdict, expected in (
                ("NO_BLOCKING_FINDINGS", 0),
                ("INSUFFICIENT_EVIDENCE", 71),
                ("APPROVE", 72),
            ):
                with self.subTest(verdict=verdict):
                    p = self.payload()
                    p["verdict"] = verdict
                    result.write_text(json.dumps(p), encoding="utf-8")
                    run = subprocess.run(
                        [sys.executable, "-I", str(script),
                         "201", HEAD, BASE, str(result)],
                        capture_output=True, text=True, check=False,
                    )
                    self.assertEqual(run.returncode, expected, run.stderr)
                    self.assertEqual(run.stdout, "")

    def test_incomplete_review_cannot_publish(self):
        p = self.payload(); p["verdict"] = "INSUFFICIENT_EVIDENCE"
        with self.assertRaisesRegex(ValueError, "INSUFFICIENT"): self.parse(p)


if __name__ == "__main__":
    unittest.main()
