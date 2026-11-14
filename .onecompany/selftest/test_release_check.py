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


class ReleaseEvidenceTests(unittest.TestCase):
    NOW = rc._timestamp("2026-11-14T12:00:00Z")
    HEAD = "a" * 40

    def good(self) -> dict:
        return {
            "release_version": "1.4.0", "environment": "staging", "head_sha": self.HEAD,
            "ci": {"conclusion": "success", "head_sha": self.HEAD},
            "review": {"state": "APPROVED", "head_sha": self.HEAD},
            "provider": {"status": "up"},
            "rollback_drill": {"passed": True, "previous_version": "1.3.0"},
            "stop_drill": {"passed": True}, "backup": {"verified": True},
            "emergency_stop_active": False,
            "observed_at": "2026-11-14T11:30:00Z", "max_age_seconds": 3600,
        }

    def findings(self, mutate=None, stop_flag=False) -> list[str]:
        data = self.good()
        if mutate:
            mutate(data)
        return rc.check_evidence(data, self.NOW, stop_flag)

    def test_good_evidence_passes(self):
        self.assertEqual(self.findings(), [])

    def test_each_rule_refuses_for_exactly_its_reason(self):
        cases = {
            "HEAD_SHA_INVALID": lambda d: [d.update(head_sha="abc"), d["ci"].update(head_sha="abc"), d["review"].update(head_sha="abc")],
            "RELEASE_VERSION_MISSING": lambda d: d.update(release_version=" "),
            "ENVIRONMENT_NOT_STAGING_OR_TEST": lambda d: d.update(environment="production"),
            "CI_NOT_GREEN": lambda d: d["ci"].update(conclusion="failure"),
            "CI_HEAD_MISMATCH": lambda d: d["ci"].update(head_sha="b" * 40),
            "REVIEW_NOT_APPROVED": lambda d: d["review"].update(state="CHANGES_REQUESTED"),
            "REVIEW_HEAD_MISMATCH": lambda d: d["review"].update(head_sha="b" * 40),
            "PROVIDER_NOT_HEALTHY": lambda d: d["provider"].update(status="down"),
            "ROLLBACK_DRILL_NOT_PASSED": lambda d: d["rollback_drill"].update(passed="true"),
            "ROLLBACK_PREVIOUS_VERSION_MISSING": lambda d: d["rollback_drill"].pop("previous_version"),
            "STOP_DRILL_NOT_PASSED": lambda d: d["stop_drill"].update(passed=False),
            "BACKUP_NOT_VERIFIED": lambda d: d["backup"].update(verified=1),
            "EMERGENCY_STOP_ACTIVE": lambda d: d.update(emergency_stop_active=True),
            "EVIDENCE_STALE": lambda d: d.update(observed_at="2026-11-14T10:00:00Z"),
            "EVIDENCE_FROM_FUTURE": lambda d: d.update(observed_at="2026-11-14T13:00:00Z"),
            "EVIDENCE_TIME_INVALID": lambda d: d.update(max_age_seconds=True),
        }
        for code, mutate in cases.items():
            self.assertEqual(self.findings(mutate), [code], code)

    def test_repository_stop_flag_refuses_even_if_evidence_claims_clear(self):
        self.assertEqual(self.findings(stop_flag=True), ["EMERGENCY_STOP_ACTIVE"])

    def test_missing_sections_and_naive_time_fail_closed(self):
        self.assertIn("CI_NOT_GREEN", rc.check_evidence({}, self.NOW))
        self.assertEqual(self.findings(lambda d: d.update(observed_at="2026-11-14T11:30:00")), ["EVIDENCE_TIME_INVALID"])
        self.assertIn("PROVIDER_NOT_HEALTHY", self.findings(lambda d: d.update(provider="up")))

    def run_cli(self, content, *extra):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        path = tmp / "evidence.json"
        if content is not None:
            path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
        result = subprocess.run([sys.executable, str(ROOT / "onecompany.py"), "release-check", "--json",
                                 "--evidence", str(path), "--now", "2026-11-14T12:00:00Z", *extra],
                                capture_output=True, text=True, check=False)
        return result.returncode, json.loads(result.stdout)

    def test_cli_accepts_good_evidence_and_refuses_bad_input(self):
        self.assertEqual(self.run_cli(self.good()), (0, {"findings": [], "ready": True}))
        bad = self.good()
        bad["ci"]["conclusion"] = "failure"
        self.assertEqual(self.run_cli(bad), (1, {"findings": ["CI_NOT_GREEN"], "ready": False}))
        self.assertEqual(self.run_cli("{not json")[1]["findings"], ["EVIDENCE_MALFORMED"])
        self.assertEqual(self.run_cli("[]")[1]["findings"], ["EVIDENCE_NOT_OBJECT"])
        self.assertEqual(self.run_cli(None)[1]["findings"], ["EVIDENCE_UNREADABLE"])
        self.assertEqual(self.run_cli("x" * (rc.EVIDENCE_MAX_BYTES + 1))[1]["findings"], ["EVIDENCE_TOO_LARGE"])
        self.assertEqual(self.run_cli(self.good(), "--now", "garbage")[1]["findings"], ["NOW_INVALID"])

    def test_cli_refuses_a_symlinked_evidence_file(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        real = tmp / "real.json"
        real.write_text(json.dumps(self.good()), encoding="utf-8")
        link = tmp / "link.json"
        link.symlink_to(real)
        data, problem = rc._load_evidence(link)
        self.assertEqual((data, problem), (None, "EVIDENCE_UNREADABLE"))
