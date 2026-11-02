import itertools
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import team_wizard as tw  # noqa: E402

ALL = "claude,chatgpt,codex,copilot,gemini,mistral,grok"
ACTORS = {a["id"]: a for a in tw.load("actors.json")["actors"]}


def plan(declared: str):
    return tw.build_plan(tw.parse_declared(declared, ACTORS))


def roles(p):
    return {row["role"]: row["actor"] for row in p["assignments"]}


class TeamWizardTests(unittest.TestCase):
    def test_deterministic_byte_identical(self):
        first = subprocess.run([sys.executable, str(ROOT / "onecompany.py"), "team", "--declare", ALL, "--json"],
                               capture_output=True, text=True, check=True).stdout
        second = subprocess.run([sys.executable, str(ROOT / "onecompany.py"), "team", "--declare", "grok,mistral,gemini,copilot,codex,chatgpt,claude", "--json"],
                                capture_output=True, text=True, check=True).stdout
        self.assertEqual(first, second)

    def test_every_role_covered_and_unqualified(self):
        p = plan(ALL)
        self.assertEqual([r["role"] for r in p["assignments"]], [r["id"] for r in tw.load("roles.json")["roles"]])
        for row in p["assignments"]:
            self.assertEqual(row["status"], "UNQUALIFIED")
            self.assertIn("qualify-worker", row["qualification"])
            self.assertTrue((ROOT / "docs" / "agent-setup" / row["qualification"].rsplit("/", 1)[1]).is_file())
        self.assertEqual(p["authorization"], "NOT_GRANTED")
        self.assertEqual(p["additional_spend"], 0)

    def test_rejections(self):
        for bad in ("", " ", "claude,,codex", "claude,claude", "copilot,github-copilot", "nobody", "human-owner"):
            with self.assertRaises(ValueError, msg=bad):
                tw.parse_declared(bad, ACTORS)

    def test_property_reviewers_never_authors_for_every_subset(self):
        names = ["claude", "chatgpt", "codex", "copilot", "gemini", "mistral", "grok"]
        for size in range(1, len(names) + 1):
            for subset in itertools.combinations(names, size):
                r = roles(plan(",".join(subset)))
                authors = {r["implementer"], r["ci_remediator"]}
                for reviewer in ("independent_reviewer", "security_reviewer"):
                    self.assertNotIn(r[reviewer], authors, subset)

    def test_single_llm_gets_human_reviewer_and_warning(self):
        p = plan("claude")
        r = roles(p)
        self.assertEqual(r["implementer"], "claude")
        for role in ("independent_reviewer", "security_reviewer", "merge_executor"):
            self.assertEqual(r[role], "human-owner")
        self.assertTrue(p["warnings"])

    def test_human_author_never_reviews_own_work(self):
        for declared in ("mistral", "gemini", "mistral,grok"):
            r = roles(plan(declared))
            if r["implementer"] == "human-owner":
                for reviewer in ("independent_reviewer", "security_reviewer"):
                    self.assertEqual(r[reviewer], tw.BLOCKED, declared)
        r = roles(plan("mistral"))
        self.assertEqual(r["implementer"], "human-owner")
        self.assertEqual(r["independent_reviewer"], tw.BLOCKED)

    def test_only_included_subscription_considered(self):
        p = plan("gemini")
        r = roles(p)
        self.assertNotIn("gemini-cli", r.values())
        self.assertEqual(r["implementer"], "human-owner")
        self.assertEqual(r["independent_reviewer"], tw.BLOCKED)
        self.assertEqual(r["security_reviewer"], tw.BLOCKED)
        self.assertEqual(p["excluded"][0]["actor"], "gemini-cli")
        p = plan("claude,gemini")
        self.assertNotIn("gemini-cli", roles(p).values())
        self.assertTrue(p["warnings"])

    def test_save_to_is_exclusive_and_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "team.json"
            cmd = [sys.executable, str(ROOT / "scripts" / "team_wizard.py"), "--declare", ALL, "--save-to", str(target)]
            self.assertEqual(subprocess.run(cmd, capture_output=True).returncode, 0)
            self.assertEqual(os.stat(target).st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(target.read_text())["authorization"], "NOT_GRANTED")
            before = target.read_bytes()
            self.assertEqual(subprocess.run(cmd, capture_output=True).returncode, 2)
            self.assertEqual(target.read_bytes(), before)

    def test_does_not_modify_config(self):
        files = [ROOT / ".onecompany" / n for n in ("actors.json", "readiness.json", "routing.json")]
        before = [f.read_bytes() for f in files]
        plan(ALL)
        self.assertEqual(before, [f.read_bytes() for f in files])

    def test_refuses_when_budget_allows_spend(self):
        original = tw.load
        def fake(name):
            data = original(name)
            if name == "budget.json":
                data["ai"]["allow_paid_fallback"] = True
            return data
        tw.load = fake
        try:
            with self.assertRaises(ValueError):
                plan("claude,codex")
        finally:
            tw.load = original


if __name__ == "__main__":
    unittest.main()
