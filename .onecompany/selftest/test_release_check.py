import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import release_check as rc  # noqa: E402

FILES = ("onecompany.py", ".onecompany/config.json", *rc.DOCS)


class ReleaseCheckTests(unittest.TestCase):
    def fixture(self) -> Path:
        """A minimal copy of exactly the inputs the check reads, so one mutation = one finding."""
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        for name in FILES:
            target = tmp / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(ROOT / name, target)
        for ref in rc.DOC_PATH.findall("".join((ROOT / d).read_text(encoding="utf-8") for d in rc.DOCS)):
            target = tmp / ref
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("x", encoding="utf-8")
        return tmp

    def edit(self, root: Path, name: str, old: str, new: str) -> None:
        path = root / name
        text = path.read_text(encoding="utf-8")
        self.assertIn(old, text)
        path.write_text(text.replace(old, new, 1), encoding="utf-8")

    def test_current_repository_is_ready_and_read_only(self):
        self.assertEqual(rc.check(ROOT), [])
        result = subprocess.run([sys.executable, str(ROOT / "onecompany.py"), "release-check", "--json"],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"findings": [], "ready": True})

    def test_unknown_command_in_checklist(self):
        root = self.fixture()
        self.edit(root, "docs/RELEASE-CHECKLIST.md", "python onecompany.py doctor", "python onecompany.py no-such-drill")
        self.assertEqual(rc.check(root), ["UNKNOWN_COMMAND:docs/RELEASE-CHECKLIST.md:no-such-drill"])

    def test_a_valid_prefix_with_an_invalid_suffix_is_not_accepted(self):
        for typo in ("doctor_typo", "doctor.py", "doctor-x"):
            root = self.fixture()
            self.edit(root, "docs/RELEASE-CHECKLIST.md", "python onecompany.py doctor", f"python onecompany.py {typo}")
            self.assertEqual(rc.check(root), [f"UNKNOWN_COMMAND:docs/RELEASE-CHECKLIST.md:{typo}"], typo)

    def test_unknown_command_in_runbook(self):
        root = self.fixture()
        path = root / "docs/INCIDENT-RUNBOOK.md"
        path.write_text(path.read_text(encoding="utf-8") + "\nRun `python onecompany.py panic-button`.\n", encoding="utf-8")
        self.assertEqual(rc.check(root), ["UNKNOWN_COMMAND:docs/INCIDENT-RUNBOOK.md:panic-button"])

    def test_emergency_stop_must_be_a_boolean(self):
        for bad in ('"false"', "0", "null"):
            root = self.fixture()
            config = root / ".onecompany/config.json"
            data = json.loads(config.read_text(encoding="utf-8"))
            data["safety"]["emergency_stop"] = json.loads(bad)
            config.write_text(json.dumps(data), encoding="utf-8")
            self.assertEqual(rc.check(root), ["EMERGENCY_STOP_NOT_BOOLEAN"], bad)
        root = self.fixture()
        config = root / ".onecompany/config.json"
        data = json.loads(config.read_text(encoding="utf-8"))
        del data["safety"]["emergency_stop"]
        config.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(rc.check(root), ["EMERGENCY_STOP_NOT_BOOLEAN"])

    def test_required_sections(self):
        root = self.fixture()
        self.edit(root, "docs/RELEASE-CHECKLIST.md", "## Trusted control plane", "## Renamed")
        self.assertEqual(rc.check(root), ["SECTION_MISSING:docs/RELEASE-CHECKLIST.md:Trusted control plane"])
        root = self.fixture()
        self.edit(root, "docs/INCIDENT-RUNBOOK.md", "## 6. Restore autonomy gradually", "## 6. Hurry")
        self.assertEqual(rc.check(root), ["SECTION_MISSING:docs/INCIDENT-RUNBOOK.md:6. Restore autonomy gradually"])

    def test_missing_doc_and_missing_referenced_path(self):
        root = self.fixture()
        (root / "docs/INCIDENT-RUNBOOK.md").unlink()
        self.assertEqual(rc.check(root), ["DOC_MISSING:docs/INCIDENT-RUNBOOK.md"])
        root = self.fixture()
        path = root / "docs/RELEASE-CHECKLIST.md"
        path.write_text(path.read_text(encoding="utf-8") + "\nSee `docs/NOT-THERE.md`.\n", encoding="utf-8")
        self.assertEqual(rc.check(root), ["REFERENCED_PATH_MISSING:docs/RELEASE-CHECKLIST.md:docs/NOT-THERE.md"])

    def test_references_escaping_the_repository_are_rejected_without_probing(self):
        root = self.fixture()
        path = root / "docs/RELEASE-CHECKLIST.md"
        path.write_text(path.read_text(encoding="utf-8") + "\nSee `docs/../../etc/passwd.md`.\n", encoding="utf-8")
        self.assertEqual(rc.check(root), ["REFERENCED_PATH_OUTSIDE_REPO:docs/RELEASE-CHECKLIST.md:docs/../../etc/passwd.md"])

    def test_unreadable_registry_fails_closed_and_output_is_deterministic(self):
        root = self.fixture()
        (root / "onecompany.py").write_text("COMMANDS = compute()\n", encoding="utf-8")
        self.assertEqual(rc.check(root), ["COMMAND_REGISTRY_UNREADABLE"])
        self.assertEqual(rc.check(root), rc.check(root))

    def test_check_never_writes(self):
        root = self.fixture()
        before = sorted((p.relative_to(root).as_posix(), p.stat().st_mtime_ns) for p in root.rglob("*") if p.is_file())
        rc.check(root)
        after = sorted((p.relative_to(root).as_posix(), p.stat().st_mtime_ns) for p in root.rglob("*") if p.is_file())
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
