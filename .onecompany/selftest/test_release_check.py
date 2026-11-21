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
    BASE = "d" * 40

    def good(self) -> dict:
        return {
            "release_version": "1.4.0", "environment": "staging", "head_sha": self.HEAD,
            "base_sha": self.BASE,
            "ci": {"conclusion": "success", "head_sha": self.HEAD, "base_sha": self.BASE, "observed_at": "2026-11-14T11:30:00Z"},
            "review": {"state": "APPROVED", "head_sha": self.HEAD, "base_sha": self.BASE, "reviewer": "ntk-reviewer[bot]", "authors": ["claude"], "observed_at": "2026-11-14T11:30:00Z"},
            "provider": {"status": "up", "observed_at": "2026-11-14T11:30:00Z"},
            "rollback_drill": {"passed": True, "previous_version": "1.3.0", "restored_version": "1.3.0", "head_sha": self.HEAD, "base_sha": self.BASE,
                               "observed_at": "2026-11-14T11:30:00Z"},
            "stop_drill": {"passed": True, "writes_after_stop": 0, "head_sha": self.HEAD, "base_sha": self.BASE, "observed_at": "2026-11-14T11:30:00Z"},
            "backup": {"verified": True, "head_sha": self.HEAD, "base_sha": self.BASE, "restore_tested": True, "observed_at": "2026-11-14T11:30:00Z",
                       "digest": "e" * 64, "restored_digest": "e" * 64},
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
            "HEAD_SHA_INVALID": lambda d: [d.update(head_sha="abc"), d["ci"].update(head_sha="abc"), d["review"].update(head_sha="abc"), [d[k].update(head_sha="abc") for k in ("rollback_drill", "stop_drill", "backup")]],
            "RELEASE_VERSION_MISSING": lambda d: d.update(release_version=" "),
            "ENVIRONMENT_NOT_STAGING_OR_TEST": lambda d: d.update(environment="production"),
            "CI_NOT_GREEN": lambda d: d["ci"].update(conclusion="failure"),
            "CI_HEAD_MISMATCH": lambda d: d["ci"].update(head_sha="b" * 40),
            "CI_BASE_MISMATCH": lambda d: d["ci"].update(base_sha="c" * 40),
            "REVIEWER_NOT_INDEPENDENT": lambda d: d["review"].update(reviewer="Claude"),
            "DRILL_HEAD_MISMATCH": lambda d: d["backup"].update(head_sha="b" * 40),
            "DRILL_BASE_MISMATCH": lambda d: d["backup"].update(base_sha="c" * 40),
            "ROLLBACK_NOT_RESTORED_TO_PREVIOUS": lambda d: d["rollback_drill"].update(restored_version="1.2.0"),
            "ROLLBACK_NOOP": lambda d: d["rollback_drill"].update(previous_version=" 1.4.0", restored_version="1.4.0"),
            "REVIEW_NOT_APPROVED": lambda d: d["review"].update(state="CHANGES_REQUESTED"),
            "REVIEW_HEAD_MISMATCH": lambda d: d["review"].update(head_sha="b" * 40),
            "REVIEW_BASE_MISMATCH": lambda d: d["review"].update(base_sha="c" * 40),
            "PROVIDER_NOT_HEALTHY": lambda d: d["provider"].update(status="down"),
            "ROLLBACK_DRILL_NOT_PASSED": lambda d: d["rollback_drill"].update(passed="true"),
            "ROLLBACK_PREVIOUS_VERSION_MISSING": lambda d: d["rollback_drill"].pop("previous_version"),
            "STOP_DRILL_NOT_PASSED": lambda d: d["stop_drill"].update(passed=False),
            "BACKUP_NOT_VERIFIED": lambda d: d["backup"].update(verified=1),
            "BACKUP_RESTORE_NOT_PROVEN": lambda d: d["backup"].update(restore_tested=1),
            "BACKUP_DIGEST_MISMATCH": lambda d: d["backup"].update(restored_digest="f" * 64),
            "EMERGENCY_STOP_ACTIVE": lambda d: d.update(emergency_stop_active=True),
            "EVIDENCE_STALE": lambda d: d.update(observed_at="2026-11-14T10:00:00Z"),
            "EVIDENCE_FROM_FUTURE": lambda d: d.update(observed_at="2026-11-14T13:00:00Z"),
            "EVIDENCE_TIME_INVALID": lambda d: d.update(max_age_seconds=True),
        }
        for code, mutate in cases.items():
            self.assertEqual(self.findings(mutate), [code], code)

    def test_evidence_cannot_declare_an_unbounded_freshness_window(self):
        limit = rc.MAX_EVIDENCE_AGE_SECONDS
        self.assertEqual(self.findings(lambda d: d.update(max_age_seconds=limit)), [])  # positive control
        self.assertEqual(self.findings(lambda d: d.update(max_age_seconds=limit + 1)), ["EVIDENCE_MAX_AGE_EXCESSIVE"])

        def ancient(d):
            d.update(max_age_seconds=10 * 365 * 86400, observed_at="2025-11-14T12:00:00Z")
            for k in ("rollback_drill", "stop_drill", "backup"):
                d[k]["observed_at"] = "2025-11-14T12:00:00Z"
        self.assertEqual(self.findings(ancient), ["EVIDENCE_MAX_AGE_EXCESSIVE"])

    def test_stop_drill_must_prove_no_writes_after_the_stop(self):
        code = ["STOP_DRILL_NOT_EFFECTIVE"]
        self.assertEqual(self.findings(lambda d: d["stop_drill"].update(writes_after_stop=0)), [])  # positive control
        self.assertEqual(self.findings(lambda d: d["stop_drill"].pop("writes_after_stop")), code)
        for bad in (True, False, -1, 1, 7, "0", 0.0, None):
            self.assertEqual(self.findings(lambda d, v=bad: d["stop_drill"].update(writes_after_stop=v)), code, repr(bad))
        # A drill that claims to have passed while writers kept writing is still refused.
        self.assertEqual(self.findings(lambda d: d["stop_drill"].update(passed=True, writes_after_stop=3)), code)
        self.assertEqual(self.findings(lambda d: d["stop_drill"].update(passed=False)), ["STOP_DRILL_NOT_PASSED"])

    def test_rollback_must_restore_the_named_previous_version(self):
        code = ["ROLLBACK_NOT_RESTORED_TO_PREVIOUS"]
        self.assertEqual(self.findings(lambda d: d["rollback_drill"].pop("restored_version")), code)
        self.assertEqual(self.findings(lambda d: d["rollback_drill"].update(restored_version=130)), code)
        self.assertEqual(self.findings(lambda d: d["rollback_drill"].update(restored_version=" ")), code)
        self.assertEqual(self.findings(lambda d: d["rollback_drill"].update(restored_version=" 1.3.0 ")), [])

    def test_backup_restore_must_be_proven_with_matching_digests(self):
        code = ["BACKUP_DIGEST_MISMATCH"]
        self.assertEqual(self.findings(lambda d: d["backup"].pop("restore_tested")), ["BACKUP_RESTORE_NOT_PROVEN"])
        self.assertEqual(self.findings(lambda d: d["backup"].pop("digest")), code)
        self.assertEqual(self.findings(lambda d: d["backup"].pop("restored_digest")), code)
        self.assertEqual(self.findings(lambda d: d["backup"].update(digest=None, restored_digest=None)), code)
        self.assertEqual(self.findings(lambda d: d["backup"].update(digest="E" * 64, restored_digest="E" * 64)), code)
        self.assertEqual(self.findings(lambda d: d["backup"].update(digest="e" * 63, restored_digest="e" * 63)), code)
        self.assertEqual(self.findings(lambda d: d.pop("backup")), sorted(
            ["BACKUP_NOT_VERIFIED", "BACKUP_RESTORE_NOT_PROVEN", "BACKUP_DIGEST_MISMATCH", "DRILL_HEAD_MISMATCH",
             "DRILL_TIME_INVALID"]))

    def test_independence_and_drill_binding_fail_closed(self):
        only = lambda code, mutate: self.assertEqual(self.findings(mutate), [code])  # noqa: E731
        only("REVIEWER_NOT_INDEPENDENT", lambda d: d["review"].pop("reviewer"))
        only("REVIEWER_NOT_INDEPENDENT", lambda d: d["review"].update(authors=[]))
        only("REVIEWER_NOT_INDEPENDENT", lambda d: d["review"].update(authors=["claude", 7]))
        only("REVIEWER_NOT_INDEPENDENT", lambda d: d["review"].update(authors="claude"))
        only("CI_BASE_MISMATCH", lambda d: d.pop("base_sha"))
        for drill in ("rollback_drill", "stop_drill"):
            only("DRILL_HEAD_MISMATCH", lambda d, k=drill: d[k].pop("head_sha"))

    def test_each_drill_must_be_bound_to_the_evidence_base(self):
        # Positive control: the good fixture's drills carry the evidence base and pass.
        self.assertEqual(self.findings(), [])
        for drill in ("rollback_drill", "stop_drill", "backup"):
            for mutate in (lambda d, k=drill: d[k].update(base_sha="c" * 40), lambda d, k=drill: d[k].pop("base_sha"),
                           lambda d, k=drill: d[k].update(base_sha=7), lambda d, k=drill: d[k].update(base_sha=None)):
                self.assertEqual(self.findings(mutate), ["DRILL_BASE_MISMATCH"])
        # Matching CI and review bases cannot launder a drill run against another base.
        self.assertEqual(self.findings(lambda d: d["stop_drill"].update(base_sha="b" * 40)), ["DRILL_BASE_MISMATCH"])
        # An invalid evidence base is reported once, as CI_BASE_MISMATCH, not also per drill.
        self.assertEqual(self.findings(lambda d: d.pop("base_sha")), ["CI_BASE_MISMATCH"])

    def test_review_must_be_bound_to_the_evidence_base(self):
        # Positive control: the good fixture carries a matching review base and passes.
        self.assertEqual(self.findings(), [])
        for mutate in (lambda d: d["review"].update(base_sha="c" * 40), lambda d: d["review"].pop("base_sha"),
                       lambda d: d["review"].update(base_sha=7), lambda d: d["review"].update(base_sha=None)):
            self.assertEqual(self.findings(mutate), ["REVIEW_BASE_MISMATCH"])
        # A matching CI base cannot launder a review given against another base.
        self.assertEqual(self.findings(lambda d: d["review"].update(base_sha="b" * 40)), ["REVIEW_BASE_MISMATCH"])

    def test_each_drill_must_be_individually_fresh(self):
        # Evidence refreshed at the top level cannot launder an old or unstamped drill.
        for drill in ("rollback_drill", "stop_drill", "backup"):
            self.assertEqual(self.findings(lambda d, k=drill: d[k].update(observed_at="2026-11-14T10:00:00Z")),
                             ["DRILL_STALE"], drill)
            self.assertEqual(self.findings(lambda d, k=drill: d[k].pop("observed_at")), ["DRILL_TIME_INVALID"], drill)
            self.assertEqual(self.findings(lambda d, k=drill: d[k].update(observed_at="2026-11-14T11:30:00")),
                             ["DRILL_TIME_INVALID"], drill)
            self.assertEqual(self.findings(lambda d, k=drill: d[k].update(observed_at="2026-11-14T13:00:00Z")),
                             ["DRILL_TIME_INVALID"], drill)
            self.assertEqual(self.findings(lambda d, k=drill: d[k].update(observed_at=12345)),
                             ["DRILL_TIME_INVALID"], drill)

    def test_ci_review_and_provider_signals_must_each_be_fresh(self):
        # A refreshed top-level stamp cannot launder an old or unstamped CI/review/provider signal.
        for section in ("ci", "review", "provider"):
            self.assertEqual(self.findings(lambda d, k=section: d[k].update(observed_at="2026-11-14T10:00:00Z")),
                             ["SIGNAL_STALE"], section)
            self.assertEqual(self.findings(lambda d, k=section: d[k].pop("observed_at")), ["SIGNAL_TIME_INVALID"], section)
            for bad in ("2026-11-14T11:30:00", "2026-11-14T13:00:00Z", 12345, None):
                self.assertEqual(self.findings(lambda d, k=section, b=bad: d[k].update(observed_at=b)),
                                 ["SIGNAL_TIME_INVALID"], (section, bad))

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

    def test_moved_head_or_base_makes_evidence_stale(self):
        other = "b" * 40
        run = lambda **kw: rc.check_evidence(self.good(), self.NOW, False, **kw)  # noqa: E731
        self.assertEqual(run(), [])
        self.assertEqual(run(expected_head=self.HEAD, expected_base=self.BASE), [])
        self.assertEqual(run(expected_head=other), ["EVIDENCE_HEAD_STALE"])
        self.assertEqual(run(expected_base=other), ["EVIDENCE_BASE_STALE"])
        self.assertEqual(run(expected_head="abc"), ["EXPECTED_HEAD_INVALID"])
        self.assertEqual(run(expected_base=""), ["EXPECTED_BASE_INVALID"])
        self.assertEqual(run(expected_head=self.HEAD.upper()), ["EXPECTED_HEAD_INVALID"])

    def test_cli_expected_head_and_base(self):
        other = "b" * 40
        self.assertEqual(self.run_cli(self.good(), "--expected-head", self.HEAD, "--expected-base", self.BASE)[0], 0)
        self.assertEqual(self.run_cli(self.good(), "--expected-head", other),
                         (1, {"findings": ["EVIDENCE_HEAD_STALE"], "ready": False}))
        self.assertEqual(self.run_cli(self.good(), "--expected-base", other)[1]["findings"], ["EVIDENCE_BASE_STALE"])
        self.assertEqual(self.run_cli(self.good(), "--expected-head", "")[1]["findings"], ["EXPECTED_HEAD_INVALID"])

    def test_duplicate_keys_are_refused_even_when_the_last_value_is_green(self):
        good = json.dumps(self.good())
        top = good[:-1] + ', "environment": "staging"}'
        nested = json.dumps(self.good()).replace('"conclusion": "success"', '"conclusion": "failure", "conclusion": "success"')
        self.assertNotEqual(nested, good)
        for label, text in (("top", top), ("nested", nested)):
            with self.subTest(label):
                self.assertEqual(json.loads(text)["ci"]["conclusion"], "success")  # plain json would accept it
                self.assertEqual(self.run_cli(text), (1, {"findings": ["EVIDENCE_DUPLICATE_KEY"], "ready": False}))
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        path = tmp / "dup.json"
        path.write_text(nested, encoding="utf-8")
        self.assertEqual(rc._load_evidence(path), (None, "EVIDENCE_DUPLICATE_KEY"))
        path.write_text("{not json", encoding="utf-8")
        self.assertEqual(rc._load_evidence(path), (None, "EVIDENCE_MALFORMED"))
        self.assertEqual(self.run_cli(self.good())[0], 0)

    def test_cli_refuses_explicitly_empty_options(self):
        run = lambda *a: subprocess.run([sys.executable, str(ROOT / "onecompany.py"), "release-check", "--json", *a],  # noqa: E731
                                        capture_output=True, text=True, check=False)
        empty = run("--evidence", "")
        self.assertEqual((empty.returncode, json.loads(empty.stdout)["findings"]), (1, ["EVIDENCE_UNREADABLE"]))
        self.assertEqual(run().returncode, 0)
        self.assertEqual(self.run_cli(self.good(), "--now", "")[1]["findings"], ["NOW_INVALID"])

    def test_cli_refuses_a_symlinked_evidence_file(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        real = tmp / "real.json"
        real.write_text(json.dumps(self.good()), encoding="utf-8")
        link = tmp / "link.json"
        link.symlink_to(real)
        data, problem = rc._load_evidence(link)
        self.assertEqual((data, problem), (None, "EVIDENCE_UNREADABLE"))
