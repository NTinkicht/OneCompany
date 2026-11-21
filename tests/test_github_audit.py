"""OC-P0-06 (#582): the live GitHub merge-control audit fails closed."""
import contextlib
import io
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import github_audit  # noqa: E402

GOOD_ENFORCEMENT = {
    "codeowners_exists": True,
    "codeowners_valid": True,
    "classic": {"configured": True, "required_checks": ["ci"], "code_owner_review": False},
    "rulesets": [],
    "missing_required_checks": [],
    "review_gate_enforced": True,
    "enforcement_ok": True,
}
CONFIG = {"project": {"repository": "o/r", "default_branch": "main"}}
IDENTITY = {"principals": [{"login": "alice", "authorities": ["root"]}]}


def run_audit(*, enforcement=None, metadata=None, config=None, identity=None,
              actions=None, gh=True, auth=0, users=None):
    enf = dict(GOOD_ENFORCEMENT, **(enforcement or {}))
    meta = {"private": True, "archived": False, "default_branch": "main"}
    if metadata is not False:
        meta.update(metadata or {})
    else:
        meta = False
    cfg = CONFIG if config is None else config
    ident = IDENTITY if identity is None else identity
    act = {"default_workflow_permissions": "read"} if actions is None else actions
    users = users or {"alice": {"type": "User"}}

    def fake_api(path):
        if path == "repos/o/r":
            return (0, meta, "") if meta is not False else (1, None, "boom")
        if path.startswith("users/"):
            u = users.get(path.split("/", 1)[1])
            return (0, u, "") if u else (1, None, "not found")
        if path.endswith("actions/permissions/workflow"):
            return (0, act, "") if act else (1, None, "denied")
        raise AssertionError(path)

    def fake_load(path):
        return ident if Path(path).name == "identity.json" else cfg

    out = io.StringIO()
    with mock.patch.object(github_audit, "gh_api", fake_api), \
            mock.patch.object(github_audit, "inspect_enforcement", return_value=enf), \
            mock.patch.object(github_audit, "command_exists", return_value=gh), \
            mock.patch.object(github_audit, "required_check_names", return_value=["ci"]), \
            mock.patch.object(github_audit, "load_json", fake_load), \
            mock.patch.object(github_audit, "run", return_value=subprocess.CompletedProcess([], auth)), \
            contextlib.redirect_stdout(out):
        code = github_audit.main()
    return code, out.getvalue()


class GithubAuditTests(unittest.TestCase):
    def assertRefused(self, text, **kw):
        code, out = run_audit(**kw)
        self.assertEqual(code, 1, out)
        self.assertIn(text, out)
        self.assertIn("FAILED", out)

    def test_positive_control_passes(self):
        code, out = run_audit()
        self.assertEqual(code, 0, out)
        self.assertIn("audit PASS", out)
        self.assertNotIn("ERROR", out)

    def test_missing_gh_or_auth_exits_2(self):
        self.assertEqual(run_audit(gh=False)[0], 2)
        self.assertEqual(run_audit(auth=1)[0], 2)

    def test_unconfigured_repository_exits_2(self):
        for cfg in ({"project": {}}, {"project": {"repository": "noslash"}}):
            code, out = run_audit(config=cfg)
            self.assertEqual(code, 2, out)
            self.assertIn("set config.project.repository", out)

    def test_unreadable_metadata_exits_2(self):
        code, out = run_audit(metadata=False)
        self.assertEqual(code, 2, out)

    def test_archived_repository_refused(self):
        self.assertRefused("repository is archived", metadata={"archived": True})

    def test_default_branch_drift_refused(self):
        self.assertRefused("differs from GitHub default branch", metadata={"default_branch": "trunk"})

    def test_identity_without_root_refused(self):
        self.assertRefused(
            "no principal with root authority",
            identity={"principals": [{"login": "alice", "authorities": []}]},
        )

    def test_root_principal_must_be_concrete_user(self):
        self.assertRefused("not a concrete User", users={"alice": {"type": "Bot"}})

    def test_unresolvable_principal_refused(self):
        self.assertRefused("does not resolve through GitHub", users={"bob": {"type": "User"}})

    def test_empty_principals_refused(self):
        self.assertRefused("no platform principals", identity={"principals": []})

    def test_missing_codeowners_refused(self):
        self.assertRefused(
            ".github/CODEOWNERS is missing",
            enforcement={"codeowners_exists": False, "codeowners_valid": False},
        )

    def test_uncovered_protected_paths_refused(self):
        self.assertRefused(
            "does not cover protected paths: .github/**",
            enforcement={"codeowners_valid": False,
                         "codeowners_missing_protected_paths": [".github/**"]},
        )

    def test_unestablished_codeowners_validity_refused(self):
        self.assertRefused("validity could not be established", enforcement={"codeowners_valid": False})

    def test_missing_required_check_refused(self):
        self.assertRefused(
            "not enforced on main: lint",
            enforcement={"missing_required_checks": ["lint"], "enforcement_ok": False},
        )

    def test_missing_review_gate_refused(self):
        self.assertRefused(
            "no pinned independent-review GitHub App check",
            enforcement={"review_gate_enforced": False, "enforcement_ok": False},
        )

    def test_no_protection_or_ruleset_refused(self):
        self.assertRefused(
            "no enforceable default-branch protection/ruleset",
            enforcement={"classic": {"configured": False}, "rulesets": [], "enforcement_ok": False},
        )

    def test_ruleset_alone_satisfies_protection(self):
        code, out = run_audit(enforcement={
            "classic": {"configured": False},
            "rulesets": [{"name": "main-rs", "required_checks": ["ci"]}],
        })
        self.assertEqual(code, 0, out)
        self.assertIn("ruleset main-rs", out)

    def test_enforcement_not_ok_refused(self):
        self.assertRefused("do not currently enforce", enforcement={"enforcement_ok": False})

    def test_write_token_default_is_warning_only(self):
        code, out = run_audit(actions={"default_workflow_permissions": "write"})
        self.assertEqual(code, 0, out)
        self.assertIn("WARN: Actions GITHUB_TOKEN defaults to write", out)

    def test_unreadable_actions_permissions_is_warning_only(self):
        code, out = run_audit(actions={})
        self.assertEqual(code, 0, out)
        self.assertIn("could not be read", out)


if __name__ == "__main__":
    unittest.main()
