import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import docs_check  # noqa: E402


class DocsCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / "docs").mkdir()
        (self.tmp / "onecompany.py").write_text('COMMANDS = {\n    "alpha": ["a.py"],\n    "beta-check": ["b.py"],\n}\n')
        for rel in docs_check.REQUIRED:
            (self.tmp / rel).write_text("# page\n")
        self.readme = self.tmp / "README.md"
        self.readme.write_text("run `python onecompany.py alpha` and `python onecompany.py beta-check`\n")

    def run_cli(self, *extra):
        return subprocess.run([sys.executable, str(ROOT / "scripts" / "docs_check.py"), "--root", str(self.tmp), *extra],
                              capture_output=True, text=True)

    def test_clean_tree_passes(self):
        r = self.run_cli()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_undocumented_command_fails(self):
        self.readme.write_text("only `python onecompany.py alpha`; beta-check is mentioned bare\n")
        r = self.run_cli("--json")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(json.loads(r.stdout)["undocumented_commands"], ["beta-check"])

    def test_command_prefix_does_not_count(self):
        self.readme.write_text("`python onecompany.py alpha` `python onecompany.py beta-check-extra`\n")
        self.assertEqual(json.loads(self.run_cli("--json").stdout)["undocumented_commands"], ["beta-check"])

    def test_missing_required_doc_fails(self):
        (self.tmp / "docs" / "FAQ.md").unlink()
        r = self.run_cli("--json")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(json.loads(r.stdout)["required_missing"], ["docs/FAQ.md"])

    def test_broken_link_fails_but_external_and_anchor_pass(self):
        self.readme.write_text(self.readme.read_text() + "[x](docs/GONE.md) [y](https://example.com/a) [z](#top) [ok](docs/FAQ.md#q)\n")
        out = json.loads(self.run_cli("--json").stdout)
        self.assertEqual(out["broken_links"], ["README.md -> docs/GONE.md"])

    def test_link_escaping_repository_fails(self):
        outside = self.tmp.parent / "outside-docs-check.md"
        outside.write_text("x")
        self.addCleanup(outside.unlink)
        self.readme.write_text(self.readme.read_text() + f"[e](../{outside.name})\n")
        out = json.loads(self.run_cli("--json").stdout)
        self.assertEqual(len(out["broken_links"]), 1)
        self.assertIn("escapes repository", out["broken_links"][0])

    def test_unverifiable_inputs_exit_2(self):
        (self.tmp / "onecompany.py").write_text("print('no registry')\n")
        self.assertEqual(self.run_cli().returncode, 2)
        self.assertEqual(subprocess.run([sys.executable, str(ROOT / "scripts" / "docs_check.py"), "--root", str(self.tmp / "nope")],
                                        capture_output=True, text=True).returncode, 2)

    def test_check_does_not_write(self):
        before = sorted(p.name for p in self.tmp.rglob("*"))
        self.run_cli()
        self.assertEqual(before, sorted(p.name for p in self.tmp.rglob("*")))

    @unittest.skipUnless((ROOT / "docs" / "MASTER-EVOLUTION-ROADMAP-2026.md").is_file(), "source checkout only; bootstrapped targets carry their own docs")
    def test_repository_docs_are_complete(self):
        r = subprocess.run([sys.executable, str(ROOT / "onecompany.py"), "docs-check"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
