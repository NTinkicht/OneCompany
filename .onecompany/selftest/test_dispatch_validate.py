"""Exact-reason fail-closed coverage for scripts/dispatch_validate.py (OC-P0-08)."""
import contextlib
import copy
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import dispatch_validate  # noqa: E402

ACTORS = {"actors": [{"id": "a1", "capabilities": ["write", "review"]}]}
READY = {"actors": [{"actor_id": "a1", "unattended": {"configured": True, "verified": True}}]}
DISPATCH = {
    "policy": {
        "routing_does_not_equal_execution": True,
        "no_dispatch_without_verified_capability": True,
        "unattended_supervisor_requires_unattended_dispatch": True,
        "dispatch_never_creates_authority": True,
        "missing_execution_path_behavior": "CAPACITY_BLOCKED",
    },
    "actors": [
        {
            "actor_id": "a1",
            "mechanisms": [
                {"id": "m1", "capabilities": ["write"], "configured": True, "evidence": "ev", "unattended": True}
            ],
        }
    ],
}


def run(actors=ACTORS, readiness=READY, dispatch=DISPATCH):
    docs = {
        "actors.json": copy.deepcopy(actors),
        "readiness.json": copy.deepcopy(readiness),
        "dispatch.json": copy.deepcopy(dispatch),
    }
    out = io.StringIO()
    with patch.object(dispatch_validate, "load_json", side_effect=lambda p: docs[Path(p).name]):
        with contextlib.redirect_stdout(out):
            code = dispatch_validate.main()
    return code, out.getvalue().splitlines()


class DispatchValidateTests(unittest.TestCase):
    def assertRefused(self, code, lines, error):
        self.assertEqual(code, 1)
        self.assertIn(f"ERROR: {error}", lines)

    def test_positive_control_passes(self):
        code, lines = run()
        self.assertEqual(code, 0)
        self.assertEqual(lines, ["OneCompany dispatch validation PASS (0 warning(s))."])

    def test_each_policy_flag_must_be_true(self):
        for key in (
            "routing_does_not_equal_execution",
            "no_dispatch_without_verified_capability",
            "unattended_supervisor_requires_unattended_dispatch",
            "dispatch_never_creates_authority",
        ):
            for bad in (False, "true", None):
                doc = copy.deepcopy(DISPATCH)
                doc["policy"][key] = bad
                code, lines = run(dispatch=doc)
                self.assertRefused(code, lines, f"dispatch.policy.{key} must be true")
        doc = copy.deepcopy(DISPATCH)
        del doc["policy"]["dispatch_never_creates_authority"]
        code, lines = run(dispatch=doc)
        self.assertRefused(code, lines, "dispatch.policy.dispatch_never_creates_authority must be true")

    def test_missing_execution_path_must_be_capacity_blocked(self):
        doc = copy.deepcopy(DISPATCH)
        doc["policy"]["missing_execution_path_behavior"] = "PROCEED"
        code, lines = run(dispatch=doc)
        self.assertRefused(code, lines, "dispatch.policy.missing_execution_path_behavior must be CAPACITY_BLOCKED")

    def test_actor_without_id_is_refused(self):
        doc = copy.deepcopy(DISPATCH)
        doc["actors"].append({"mechanisms": []})
        code, lines = run(dispatch=doc)
        self.assertRefused(code, lines, "dispatch actor missing actor_id")

    def test_duplicate_actor_is_refused(self):
        doc = copy.deepcopy(DISPATCH)
        doc["actors"].append(copy.deepcopy(doc["actors"][0]))
        code, lines = run(dispatch=doc)
        self.assertRefused(code, lines, "duplicate dispatch actor: a1")

    def test_unknown_actor_is_refused(self):
        doc = copy.deepcopy(DISPATCH)
        doc["actors"].append({"actor_id": "ghost", "mechanisms": []})
        code, lines = run(dispatch=doc)
        self.assertRefused(code, lines, "dispatch references unknown actor: ghost")

    def test_mechanism_without_id_is_refused(self):
        doc = copy.deepcopy(DISPATCH)
        doc["actors"][0]["mechanisms"].append({"capabilities": []})
        code, lines = run(dispatch=doc)
        self.assertRefused(code, lines, "dispatch a1 has mechanism without id")

    def test_duplicate_mechanism_id_is_refused(self):
        doc = copy.deepcopy(DISPATCH)
        doc["actors"][0]["mechanisms"].append({"id": "m1", "capabilities": []})
        code, lines = run(dispatch=doc)
        self.assertRefused(code, lines, "dispatch a1 duplicate mechanism id: m1")

    def test_undeclared_capability_is_refused(self):
        doc = copy.deepcopy(DISPATCH)
        doc["actors"][0]["mechanisms"][0]["capabilities"] = ["write", "merge", "deploy"]
        code, lines = run(dispatch=doc)
        self.assertRefused(
            code, lines, "dispatch a1/m1 exposes undeclared capabilities: ['deploy', 'merge']"
        )

    def test_declared_capability_subset_is_allowed(self):
        doc = copy.deepcopy(DISPATCH)
        doc["actors"][0]["mechanisms"][0]["capabilities"] = ["review", "write"]
        code, _ = run(dispatch=doc)
        self.assertEqual(code, 0)

    def test_configured_unattended_requires_verified_readiness(self):
        expected = "configured unattended dispatch a1/m1 requires readiness unattended configured+verified"
        cases = {
            "not verified": {"configured": True, "verified": False},
            "not configured": {"configured": False, "verified": True},
            "truthy but not True": {"configured": True, "verified": "yes"},
            "empty": {},
        }
        for name, unattended in cases.items():
            with self.subTest(name):
                ready = {"actors": [{"actor_id": "a1", "unattended": unattended}]}
                code, lines = run(readiness=ready)
                self.assertRefused(code, lines, expected)

    def test_configured_unattended_with_actor_absent_from_readiness_is_refused(self):
        code, lines = run(readiness={"actors": []})
        self.assertRefused(
            code, lines, "configured unattended dispatch a1/m1 requires readiness unattended configured+verified"
        )

    def test_unconfigured_or_attended_mechanism_needs_no_readiness(self):
        for edit in ({"configured": False}, {"unattended": False}):
            with self.subTest(edit=edit):
                doc = copy.deepcopy(DISPATCH)
                doc["actors"][0]["mechanisms"][0].update(edit)
                code, _ = run(dispatch=doc, readiness={"actors": []})
                self.assertEqual(code, 0)

    def test_actor_without_dispatch_record_is_refused(self):
        actors = {"actors": ACTORS["actors"] + [{"id": "a2", "capabilities": []}]}
        code, lines = run(actors=actors)
        self.assertRefused(code, lines, "actors missing dispatch records: ['a2']")

    def test_configured_mechanism_without_evidence_only_warns(self):
        doc = copy.deepcopy(DISPATCH)
        del doc["actors"][0]["mechanisms"][0]["evidence"]
        code, lines = run(dispatch=doc)
        self.assertEqual(code, 0)
        self.assertEqual(lines[0], "WARN: configured dispatch a1/m1 has no evidence reference")
        self.assertEqual(lines[-1], "OneCompany dispatch validation PASS (1 warning(s)).")


if __name__ == "__main__":
    unittest.main()
