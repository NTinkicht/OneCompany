"""Exercise two isolated, named-only-by-fixture OneCompany installations."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class ProjectIsolationTests(unittest.TestCase):
    def test_two_projects_never_share_authority_or_runtime_state(self):
        with tempfile.TemporaryDirectory(prefix="onecompany-isolation-") as temp:
            targets = []
            for slug, owner in (("alpha", "alpha-owner"), ("beta", "beta-owner")):
                target = Path(temp) / slug
                target.mkdir()
                result = subprocess.run(
                    [
                        sys.executable, str(ROOT / "onecompany.py"), "bootstrap",
                        "--target", str(target),
                        "--repository", f"example/{slug}",
                        "--project-name", f"Example {slug}",
                        "--code-owner", f"@{owner}",
                        "--root-principal", owner,
                    ],
                    cwd=ROOT, capture_output=True, text=True, check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                config = json.loads((target / ".onecompany/config.json").read_text())
                self.assertEqual(config["project"]["repository"], f"example/{slug}")
                identity = json.loads((target / ".onecompany/identity.json").read_text())
                roots = [p for p in identity["principals"] if "root" in p.get("authorities", [])]
                self.assertEqual([p["login"] for p in roots], [owner])
                owners = (target / ".github/CODEOWNERS").read_text().splitlines()
                self.assertTrue(all(row.split()[1:] == [f"@{owner}"]
                                    for row in owners if row.startswith("/")))
                self.assertFalse((target / "source-evidence").exists())
                self.assertFalse((target / "evidence").exists())
                self.assertFalse(json.loads((target / ".onecompany/ledger.json").read_text())["enabled"])
                self.assertFalse(json.loads((target / ".onecompany/supervision.json").read_text())["enabled"])
                self.assertEqual(json.loads((target / ".onecompany/queue.json").read_text())["work_units"], [])
                targets.append(target)

            first_queue = targets[0] / ".onecompany/queue.json"
            first = json.loads(first_queue.read_text())
            first["work_units"].append({"id": "EXAMPLE-ALPHA-ONLY"})
            first_queue.write_text(json.dumps(first) + "\n")
            second = json.loads((targets[1] / ".onecompany/queue.json").read_text())
            self.assertEqual(second["work_units"], [])
            self.assertEqual(json.loads((targets[1] / ".onecompany/config.json").read_text())
                             ["project"]["repository"], "example/beta")


if __name__ == "__main__":
    unittest.main()
