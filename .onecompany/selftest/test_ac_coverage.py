import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import ac_coverage as ac  # noqa: E402

CATALOG = {"acceptance_criteria": [
    {"id": "AC-001", "status": "approved", "negative_or_failure_case": False},
    {"id": "AC-002", "status": "approved", "negative_or_failure_case": True},
    {"id": "AC-003", "status": "proposed", "negative_or_failure_case": True},
]}


class AcCoverageTests(unittest.TestCase):
    def fixture(self, catalog=CATALOG, tests=None) -> Path:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / ".onecompany" / "selftest").mkdir(parents=True)
        (tmp / "tests").mkdir()
        text = catalog if isinstance(catalog, str) else json.dumps(catalog)
        (tmp / ".onecompany" / "requirements-catalog.json").write_text(text, encoding="utf-8")
        for name, body in (tests or {}).items():
            (tmp / name).write_text(body, encoding="utf-8")
        return tmp

    def test_declared_and_uncovered(self):
        root = self.fixture(tests={"tests/test_a.py": "# covers: AC-001\n"})
        result = ac.report(root)
        self.assertEqual(result["uncovered"], ["AC-002"])
        self.assertEqual(result["uncovered_negative"], ["AC-002"])
        self.assertEqual(result["declarations"], {"AC-001": ["tests/test_a.py"]})
        self.assertEqual((result["approved"], result["covered"]), (2, 1))

    def test_non_approved_not_counted_uncovered(self):
        result = ac.report(self.fixture())
        self.assertNotIn("AC-003", result["uncovered"])

    def test_unknown_reference_reported(self):
        root = self.fixture(tests={".onecompany/selftest/test_b.py": "# covers: AC-001, AC-099\n"})
        result = ac.report(root)
        self.assertEqual(result["unknown"], ["AC-099"])
        self.assertEqual(result["declarations"]["AC-001"], [".onecompany/selftest/test_b.py"])

    def test_ignored_forms(self):
        body = 'x = "# covers: AC-001"\nprint("covers: AC-002")\n# covers: AC-2\n# covers: AC-001 trailing\n'
        root = self.fixture(tests={"tests/test_c.py": body, "tests/helper.py": "# covers: AC-001\n"})
        result = ac.report(root)
        self.assertEqual(result["uncovered"], ["AC-001", "AC-002"])
        self.assertEqual(result["unknown"], [])

    def test_symlinked_test_ignored(self):
        root = self.fixture()
        outside = root / "outside.txt"
        outside.write_text("# covers: AC-001\n", encoding="utf-8")
        (root / "tests" / "test_link.py").symlink_to(outside)
        self.assertIn("AC-001", ac.report(root)["uncovered"])

    def test_malformed_catalog_fails_closed(self):
        for bad in ("{", json.dumps({"acceptance_criteria": []}),
                    json.dumps({"acceptance_criteria": [{"id": "AC-001"}, {"id": "AC-001"}]}),
                    json.dumps({"acceptance_criteria": ["AC-001"]})):
            with self.assertRaises(ValueError):
                ac.report(self.fixture(catalog=bad))

    def test_missing_or_invalid_status_fails_closed(self):
        for item in ({"id": "AC-001"}, {"id": "AC-001", "status": "bogus"}, {"id": "AC-001", "status": None}):
            with self.assertRaises(ValueError):
                ac.report(self.fixture(catalog={"acceptance_criteria": [item]}))

    def test_string_content_is_not_an_annotation(self):
        body = 'DOC = """\n# covers: AC-001\n# covers: AC-099\n"""\n\n# covers: AC-002\n'
        result = ac.report(self.fixture(tests={"tests/test_d.py": body}))
        self.assertEqual(result["uncovered"], ["AC-001"])
        self.assertEqual(result["unknown"], [])
        self.assertEqual(result["declarations"], {"AC-002": ["tests/test_d.py"]})

    def test_deterministic(self):
        root = self.fixture(tests={"tests/test_a.py": "# covers: AC-002\n", "tests/test_z.py": "# covers: AC-002\n"})
        self.assertEqual(ac.report(root), ac.report(root))
        self.assertEqual(ac.report(root)["declarations"]["AC-002"], ["tests/test_a.py", "tests/test_z.py"])

    def test_cli_matches_library_for_this_checkout(self):
        """Target checkouts may carry an empty catalog; the CLI must then fail closed (exit 2)."""
        base = [sys.executable, str(ROOT / "onecompany.py"), "ac-coverage"]
        plain = subprocess.run([*base, "--json"], capture_output=True, text=True, check=False)
        try:
            expected = ac.report(ROOT)
        except ValueError:
            self.assertEqual(plain.returncode, 2)
            self.assertEqual(plain.stdout, "")
            return
        self.assertEqual(plain.returncode, 0, plain.stderr)
        data = json.loads(plain.stdout)
        self.assertEqual(data, expected)
        strict = subprocess.run([*base, "--strict"], capture_output=True, text=True, check=False)
        self.assertEqual(strict.returncode, 1 if expected["uncovered"] or expected["unknown"] else 0)


if __name__ == "__main__":
    unittest.main()
