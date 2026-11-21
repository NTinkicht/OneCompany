import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COPIED = (".github", ".onecompany", "scripts", "patterns", "overlays")
ARGS = ["--code-owner", "@example/reviewers", "--root-principal", "example-admin"]


def snapshot(base: Path) -> dict:
    return {
        str(p.relative_to(base)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(base.rglob("*"))
        if p.is_file() and not {".git", "__pycache__"} & set(p.relative_to(base).parts)
    }


SOURCE = json.loads((ROOT / ".onecompany/config.json").read_text())["project"]["repository"] == "NTinkicht/OneCompany"


@unittest.skipUnless(SOURCE, "init is only valid on an untouched template copy; bootstrapped targets skip")
class InitProjectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="onecompany-init-test-")
        self.addCleanup(self.tmp.cleanup)
        self.target = Path(self.tmp.name) / "copy"
        self.target.mkdir()
        for name in COPIED:
            shutil.copytree(ROOT / name, self.target / name, ignore=shutil.ignore_patterns("__pycache__"))

    def init(self, *extra):
        return subprocess.run(
            [sys.executable, "scripts/init_project.py", *extra],
            cwd=self.target, text=True, capture_output=True, check=False,
        )

    def assert_refused_untouched(self, result, reason):
        before = self.before
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("REFUSED", result.stdout)
        self.assertIn(reason, result.stdout)
        self.assertEqual(snapshot(self.target), before)

    def refuse(self, args, reason):
        self.before = snapshot(self.target)
        self.assert_refused_untouched(self.init(*args), reason)

    def test_positive_control_initializes_to_l1(self):
        result = self.init("--repository", "example/copy", *ARGS)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        config = json.loads((self.target / ".onecompany/config.json").read_text())
        self.assertEqual(config["project"]["repository"], "example/copy")
        self.assertEqual(config["autonomy"]["level"], "L1")
        self.assertNotIn("@NTinkicht", (self.target / ".github/CODEOWNERS").read_text())

    def test_source_repository_target_refused(self):
        self.refuse(["--repository", "NTinkicht/OneCompany", *ARGS], "must differ")

    def test_malformed_repository_refused(self):
        self.refuse(["--repository", "not-a-repo", *ARGS], "cannot infer target repository")

    def test_missing_codeowners_refused_without_writes(self):
        (self.target / ".github/CODEOWNERS").unlink()
        self.refuse(["--repository", "example/copy", *ARGS], "CODEOWNERS")

    def test_no_root_principal_refused_without_partial_writes(self):
        path = self.target / ".onecompany/identity.json"
        identity = json.loads(path.read_text())
        for p in identity["principals"]:
            p["authorities"] = [a for a in p["authorities"] if a != "root"]
        path.write_text(json.dumps(identity, indent=2))
        self.refuse(["--repository", "example/copy", *ARGS], "exactly one root principal")

    def test_root_not_human_owner_refused_without_partial_writes(self):
        path = self.target / ".onecompany/identity.json"
        identity = json.loads(path.read_text())
        for p in identity["principals"]:
            if "root" in p["authorities"]:
                p["actor_id"] = "codex"
        path.write_text(json.dumps(identity, indent=2))
        self.refuse(["--repository", "example/copy", *ARGS], "human-owner")

    def test_already_initialized_refused(self):
        self.assertEqual(self.init("--repository", "example/copy", *ARGS).returncode, 0)
        self.refuse(["--repository", "example/other", *ARGS], "already identifies")


if __name__ == "__main__":
    unittest.main()
