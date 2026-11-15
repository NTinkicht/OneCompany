import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def project(n, **over):
    p = {"id": f"p{n}", "repo": f"o/r{n}", "queue_id": f"q{n}", "budget_id": f"b{n}",
         "policy_id": f"pol{n}", "credential_ref": f"c{n}"}
    p.update(over)
    return p


def base(**over):
    r = {"revision": "1" * 40, "projects": [project(1), project(2)],
         "leases": [{"id": "l1", "project": "p1", "repo": "o/r1"}],
         "approvals": [{"id": "a1", "project": "p1", "scope_project": "p1"}],
         "accesses": [{"id": "x1", "project": "p1", "target_project": "p1", "kind": "data"}]}
    r.update(over)
    return r


class PortfolioCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def run_cli(self, report, *extra, raw=None):
        path = self.tmp / "r.json"
        path.write_text(raw if raw is not None else json.dumps(report), encoding="utf-8")
        return subprocess.run([sys.executable, str(ROOT / "scripts" / "portfolio_check.py"), str(path), *extra],
                              capture_output=True, text=True)

    def assert_fails(self, report, token):
        r = self.run_cli(report)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn(token, r.stdout)

    def assert_unverifiable(self, report=None, raw=None):
        r = self.run_cli(report, raw=raw)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("UNABLE TO VERIFY", r.stderr)

    def test_clean_report_passes(self):
        r = self.run_cli(base())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_json_output_is_deterministic(self):
        self.assertEqual(self.run_cli(base(), "--json").stdout, self.run_cli(base(), "--json").stdout)

    def test_single_project_fails(self):
        self.assert_fails(base(projects=[project(1)]), "SINGLE_PROJECT")

    def test_duplicate_repo_fails_case_insensitively(self):
        self.assert_fails(base(projects=[project(1), project(2, repo="O/R1")]), "DUPLICATE_REPO o/r1")

    def test_shared_resources_fail(self):
        for field, token in (("queue_id", "SHARED_QUEUE q1"), ("budget_id", "SHARED_BUDGET b1"),
                             ("policy_id", "SHARED_POLICY pol1"), ("credential_ref", "SHARED_CREDENTIAL c1")):
            self.assert_fails(base(projects=[project(1), project(2, **{field: project(1)[field]})]), token)

    def test_shared_resources_fail_despite_case_or_whitespace(self):
        for field, token in (("queue_id", "SHARED_QUEUE q1"), ("budget_id", "SHARED_BUDGET b1"),
                             ("policy_id", "SHARED_POLICY pol1"), ("credential_ref", "SHARED_CREDENTIAL c1")):
            for variant in (project(1)[field].upper(), f"  {project(1)[field]} "):
                self.assert_fails(base(projects=[project(1), project(2, **{field: variant})]), token)

    def test_duplicate_repo_fails_despite_git_suffix(self):
        self.assert_fails(base(projects=[project(1), project(2, repo="O/R1.git")]), "DUPLICATE_REPO o/r1")

    def test_lease_repo_alias_is_not_cross_target(self):
        r = self.run_cli(base(leases=[{"id": "l1", "project": "p1", "repo": "O/R1.git"}]))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_lease_for_other_repo_fails(self):
        self.assert_fails(base(leases=[{"id": "l1", "project": "p1", "repo": "o/r2"}]), "LEASE_CROSS_TARGET l1")

    def test_cross_project_approval_fails(self):
        self.assert_fails(base(approvals=[{"id": "a1", "project": "p1", "scope_project": "p2"}]),
                          "APPROVAL_CROSS_TARGET a1")

    def test_cross_project_access_fails_for_every_kind(self):
        for kind in ("data", "credential", "lease", "approval"):
            self.assert_fails(base(accesses=[{"id": "x1", "project": "p1", "target_project": "p2", "kind": kind}]),
                              f"CROSS_TARGET_ACCESS x1 p1 reaches {kind} of p2")

    def test_shared_preview_fails_despite_case_whitespace_or_slash(self):
        a = "https://p1.example.com/app"
        for variant in (a, a.upper(), f"  {a} ", a + "/"):
            self.assert_fails(base(projects=[project(1, preview_url=a), project(2, preview_url=variant)]),
                              f"SHARED_PREVIEW {a} shared by p1,p2")

    def test_shared_preview_fails_despite_default_port(self):
        for a, b in (("https://h/app", "https://h:443/app"), ("http://h/app", "http://H:80/app/"),
                     ("https://h:8443/app", "https://h:8443/app")):
            self.assert_fails(base(projects=[project(1, preview_url=a), project(2, preview_url=b)]), "SHARED_PREVIEW")

    def test_non_default_port_is_distinct(self):
        r = self.run_cli(base(projects=[project(1, preview_url="https://h/app"),
                                        project(2, preview_url="https://h:8443/app")]))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_distinct_or_absent_previews_pass(self):
        for projects in ([project(1, preview_url="https://a.example.com"), project(2, preview_url="https://b.example.com")],
                         [project(1, preview_url="https://a.example.com"), project(2)],
                         [project(1), project(2)]):
            r = self.run_cli(base(projects=projects))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_malformed_preview_is_unverifiable(self):
        for bad in ("", "  ", "ftp://x.example.com", "not a url", "https://a b", "https:///", "https://?", "https://#x", "https://:443/", "https://h:99999/", "https://h:abc/", "https://u:p@h.example.com/", "https://u@h.example.com/", 1, None, [], {}):
            self.assert_unverifiable(base(projects=[project(1), project(2, preview_url=bad)]))

    def test_malformed_input_is_unverifiable(self):
        self.assert_unverifiable(raw="not json")
        self.assert_unverifiable(raw="[]")
        self.assert_unverifiable(base(revision="abc"))
        for key in ("projects", "leases", "approvals", "accesses"):
            r = base()
            del r[key]
            self.assert_unverifiable(r)
        self.assert_unverifiable(base(projects=[project(1), project(1)]))
        self.assert_unverifiable(base(projects=[project(1), project(2, repo="nope")]))
        self.assert_unverifiable(base(projects=[project(1), project(2, queue_id="")]))
        self.assert_unverifiable(base(leases=[{"id": "l1", "project": "zz", "repo": "o/r1"}]))
        self.assert_unverifiable(base(approvals=[{"id": "a1", "project": "p1", "scope_project": "zz"}]))
        self.assert_unverifiable(base(accesses=[{"id": "x1", "project": "p1", "target_project": "p1", "kind": "x"}]))
        for bad in ({}, [], 1, None):
            self.assert_unverifiable(base(leases=[{"id": "l1", "project": bad, "repo": "o/r1"}]))
            self.assert_unverifiable(base(approvals=[{"id": "a1", "project": bad, "scope_project": "p1"}]))
            self.assert_unverifiable(base(approvals=[{"id": "a1", "project": "p1", "scope_project": bad}]))
            self.assert_unverifiable(base(accesses=[{"id": "x1", "project": bad, "target_project": "p1", "kind": "data"}]))
            self.assert_unverifiable(base(accesses=[{"id": "x1", "project": "p1", "target_project": bad, "kind": "data"}]))
            self.assert_unverifiable(base(accesses=[{"id": "x1", "project": "p1", "target_project": "p1", "kind": bad}]))

    def test_registered_in_cli(self):
        r = subprocess.run([sys.executable, str(ROOT / "onecompany.py"), "portfolio-check", "--help"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("portfolio", r.stdout.lower())


if __name__ == "__main__":
    unittest.main()
