from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class IndependentInstallationsTests(unittest.TestCase):
    def test_two_unrelated_installs_do_not_share_owner_queue_or_runtime_state(self) -> None:
        with tempfile.TemporaryDirectory(prefix="onecompany-multi-project-") as tmp:
            targets: list[Path] = []
            identities = [
                ("alpha-client", "example/alpha-client", "Alpha App", "alpha-owner"),
                ("beta-client", "example/beta-client", "Beta App", "beta-owner"),
            ]
            for folder, repo, name, owner in identities:
                target = Path(tmp) / folder
                target.mkdir()
                result = subprocess.run(
                    [
                        sys.executable,
                        str(ROOT / "onecompany.py"),
                        "bootstrap",
                        "--target", str(target),
                        "--repository", repo,
                        "--project-name", name,
                        "--default-branch", "main",
                        "--code-owner", f"@{owner}",
                        "--reviewer-code-owner", f"@{owner}-reviewer",
                        "--root-principal", owner,
                    ],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                config = json.loads((target / ".onecompany/config.json").read_text())
                self.assertEqual(config["project"]["repository"], repo)
                self.assertEqual(config["project"]["name"], name)
                identity = json.loads((target / ".onecompany/identity.json").read_text())
                root = [p for p in identity["principals"] if "root" in p.get("authorities", [])]
                self.assertEqual(len(root), 1)
                self.assertEqual(root[0]["login"], owner)
                codeowners = (target / ".github/CODEOWNERS").read_text()
                for line in codeowners.splitlines():
                    if line.startswith("/"):
                        self.assertEqual(
                            line.split()[1:],
                            [f"@{owner}", f"@{owner}-reviewer"],
                            "source owners must never leak into a new target",
                        )
                self.assertFalse((target / "source-evidence").exists())
                self.assertFalse((target / "evidence").exists())
                self.assertFalse(json.loads((target / ".onecompany/ledger.json").read_text())["enabled"])
                self.assertFalse(json.loads((target / ".onecompany/supervision.json").read_text())["enabled"])
                self.assertEqual(json.loads((target / ".onecompany/queue.json").read_text())["work_units"], [])
                targets.append(target)

            first_queue = targets[0] / ".onecompany/queue.json"
            queue = json.loads(first_queue.read_text())
            queue["work_units"].append({"id": "ALPHA-ONLY"})
            first_queue.write_text(json.dumps(queue) + "\n")
            second_queue = json.loads((targets[1] / ".onecompany/queue.json").read_text())
            self.assertEqual(second_queue["work_units"], [])
            second_config = json.loads((targets[1] / ".onecompany/config.json").read_text())
            self.assertEqual(second_config["project"]["repository"], identities[1][1])


if __name__ == "__main__":
    unittest.main()
