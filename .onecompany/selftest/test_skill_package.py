import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "onecompany" / "SKILL.md"
DOCS = [SKILL, ROOT / "docs" / "INSTALL-SKILL.md", ROOT / "docs" / "agent-setup" / "onecompany-skill.md"]


def _commands(text):
    return set(re.findall(r"onecompany\.py\s+([a-z][a-z-]*)", text))


class SkillPackageTests(unittest.TestCase):
    def test_frontmatter(self):
        text = SKILL.read_text(encoding="utf-8")
        m = re.match(r"---\nname: (onecompany)\ndescription: (.+)\n---\n", text)
        self.assertIsNotNone(m)
        self.assertLessEqual(len(m.group(2)), 1024)

    def test_every_referenced_command_exists(self):
        help_text = subprocess.run(
            [sys.executable, str(ROOT / "onecompany.py"), "--help"],
            capture_output=True, text=True, cwd=ROOT, timeout=60).stdout
        listed = set(re.findall(r"^\s{2}([a-z][a-z-]*)\b", help_text, re.M))
        for doc in DOCS:
            cmds = _commands(doc.read_text(encoding="utf-8"))
            if doc.name != "INSTALL-SKILL.md":
                self.assertTrue(cmds, doc)
            for c in cmds:
                self.assertIn(c, listed, f"{doc.name}: {c}")

    def test_safety_rules_present_and_no_forbidden_behaviour(self):
        text = SKILL.read_text(encoding="utf-8")
        for needle in ("Never approve on the user's behalf", "Never ask for, store or print tokens",
                       "L1 default", "Never propose a paid service", "--owner-ack"):
            self.assertIn(needle, text)
        # The skill must never run approval itself or raise autonomy.
        for line in text.splitlines():
            if "approve-brief" in line:
                self.assertIn("Only the user", line)
        self.assertNotRegex(text, r"--approve-wu")
        self.assertNotRegex(text, r"(?i)autonomy[^\n]*\bL[2-9]\b")
        self.assertNotRegex(text, r"(?i)(api[_-]?key|token)\s*[=:]\s*\S")

    def test_install_doc_is_short(self):
        steps = [l for l in (ROOT / "docs" / "INSTALL-SKILL.md").read_text().splitlines()
                 if re.match(r"\d+\. ", l)]
        self.assertLessEqual(len(steps), 10)


if __name__ == "__main__":
    unittest.main()
