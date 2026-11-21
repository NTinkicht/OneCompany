"""Fail-closed vectors for policy_truth claim validation and exact-base history (OC-P0-10)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import policy_truth

SHA = "a" * 40
ENTRY = {"file": "config.json", "path": "/k", "key": "k", "classification": "GUIDANCE",
         "owner": "guidance-only", "evidence": []}
EVIDENCE = ".onecompany/selftest/test_policy_truth_vectors.py"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, text=True,
                          capture_output=True).stdout.strip()


class PullRequestBaseShaVectors(unittest.TestCase):
    def _env(self, tmp: str, payload, *, workspace: str | None = None, event="pull_request"):
        env = {"GITHUB_EVENT_NAME": event, "GITHUB_WORKSPACE": workspace or str(ROOT)}
        if payload is not None:
            path = Path(tmp) / "event.json"
            path.write_text(payload if isinstance(payload, str) else json.dumps(payload))
            env["GITHUB_EVENT_PATH"] = str(path)
        return mock.patch.dict(os.environ, env, clear=True)

    def test_positive_control_valid_pr_event_yields_exact_base(self):
        with tempfile.TemporaryDirectory() as tmp, self._env(tmp, {"pull_request": {"base": {"sha": SHA}}}):
            self.assertEqual(policy_truth.pull_request_base_sha(), SHA)

    def test_missing_event_path_refuses(self):
        with tempfile.TemporaryDirectory() as tmp, self._env(tmp, None):
            with self.assertRaisesRegex(RuntimeError, "missing GITHUB_EVENT_PATH"):
                policy_truth.pull_request_base_sha()

    def test_malformed_or_short_base_sha_refuses(self):
        for payload in ({"pull_request": {"base": {"sha": "abc123"}}},
                        {"pull_request": {"base": {"sha": None}}},
                        {"pull_request": {}}, "{not json", []):
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as tmp, \
                    self._env(tmp, payload):
                with self.assertRaises(RuntimeError):
                    policy_truth.pull_request_base_sha()

    def test_unreadable_event_file_refuses(self):
        with tempfile.TemporaryDirectory() as tmp, self._env(tmp, {"x": 1}):
            os.environ["GITHUB_EVENT_PATH"] = str(Path(tmp) / "absent.json")
            with self.assertRaisesRegex(RuntimeError, "cannot determine exact pull-request base"):
                policy_truth.pull_request_base_sha()

    def test_non_pr_and_foreign_workspace_skip_history_comparison(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self._env(tmp, None, event="push"):
                self.assertIsNone(policy_truth.pull_request_base_sha())
            with self._env(tmp, None, workspace=str(Path(tmp) / "elsewhere")):
                self.assertIsNone(policy_truth.pull_request_base_sha())


class LoadClaimsAtRevisionVectors(unittest.TestCase):
    def _repo(self, tmp: str, content: str | None) -> Path:
        repo = Path(tmp)
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@example.invalid")
        _git(repo, "config", "user.name", "t")
        (repo / "seed").write_text("x")
        if content is not None:
            target = repo / policy_truth.CLAIMS_PATH
            target.parent.mkdir(parents=True)
            target.write_text(content)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "c")
        return repo

    def test_positive_control_reads_claims_from_exact_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            claims = [{"file": "a.json", "path": "/k", "classification": "GUIDANCE"}]
            repo = self._repo(tmp, json.dumps({"claims": claims}))
            self.assertEqual(policy_truth.load_claims_at_revision("HEAD", root=repo), claims)

    def test_unknown_revision_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(tmp, json.dumps({"claims": []}))
            with self.assertRaisesRegex(RuntimeError, "missing or cannot read"):
                policy_truth.load_claims_at_revision(SHA, root=repo)

    def test_base_without_claims_file_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, "missing or cannot read"):
                policy_truth.load_claims_at_revision("HEAD", root=self._repo(tmp, None))

    def test_invalid_json_and_non_list_claims_refuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(tmp, "{broken")
            with self.assertRaisesRegex(RuntimeError, "invalid JSON"):
                policy_truth.load_claims_at_revision("HEAD", root=repo)
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(tmp, json.dumps({"claims": {"a": 1}}))
            with self.assertRaisesRegex(RuntimeError, "must be an array"):
                policy_truth.load_claims_at_revision("HEAD", root=repo)


class ClaimValidationVectors(unittest.TestCase):
    def _errors(self, claims, inventory=None, index=None):
        return policy_truth.validate_claims(
            inventory if inventory is not None else [ENTRY], claims,
            root=ROOT, source_index=index if index is not None else {})

    def test_positive_control_valid_guidance_claim_passes(self):
        self.assertEqual(self._errors([{"file": "config.json", "path": "/k",
                                        "classification": "GUIDANCE"}]), [])

    def test_duplicate_claim_identity_is_rejected(self):
        claim = {"file": "config.json", "path": "/k", "classification": "GUIDANCE"}
        self.assertTrue(any("duplicates policy-claim identity" in e
                            for e in self._errors([claim, dict(claim)])))

    def test_invalid_classification_is_rejected(self):
        errors = self._errors([{"file": "config.json", "path": "/k", "classification": "TRUSTED"}])
        self.assertTrue(any("invalid classification" in e for e in errors), errors)

    def test_claim_matching_no_policy_key_is_rejected(self):
        errors = self._errors([{"file": "config.json", "path": "/ghost", "classification": "GUIDANCE"}])
        self.assertTrue(any("matches no current policy key" in e for e in errors), errors)

    def test_removed_requires_rationale_and_provenance(self):
        base = {"file": "config.json", "path": "/gone", "classification": "REMOVED"}
        errors = self._errors([base])
        self.assertTrue(any("requires removal_rationale" in e for e in errors), errors)
        self.assertTrue(any("requires removal_provenance" in e for e in errors), errors)
        ok = dict(base, removal_rationale="retired", removal_provenance="PR #1")
        self.assertEqual(self._errors([ok]), [])

    def test_removed_claim_for_still_present_key_is_rejected(self):
        claim = {"file": "config.json", "path": "/k", "classification": "REMOVED",
                 "removal_rationale": "r", "removal_provenance": "p"}
        errors = self._errors([claim])
        self.assertTrue(any("still matches" in e for e in errors), errors)

    def test_enforced_claim_with_missing_test_file_is_rejected(self):
        entry = dict(ENTRY, classification="ENFORCED", owner="validate.py", evidence=["validate.py"])
        claim = {"file": "config.json", "path": "/k", "classification": "ENFORCED",
                 "tests": ["does/not/exist.py"]}
        errors = self._errors([claim], [entry])
        self.assertTrue(any("test evidence does not exist" in e for e in errors), errors)
        claim["tests"] = [EVIDENCE]
        self.assertEqual(self._errors([claim], [entry]), [])


class ClassificationVectors(unittest.TestCase):
    def test_render_only_modules_cannot_make_a_key_enforced(self):
        for module in sorted(policy_truth.NON_ENFORCING_MODULES):
            self.assertEqual(policy_truth.classify_key("k", {module}), "GUIDANCE", module)
        self.assertEqual(policy_truth.classify_key("k", {"status.py", "validate.py"}), "ENFORCED")
        self.assertEqual(policy_truth.classify_key("k", set()), "GUIDANCE")

    def test_invalid_policy_json_is_reported_not_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "config.json").write_text("{broken")
            inventory = policy_truth.generate_inventory(Path(tmp), source_index={})
        self.assertEqual([e["key"] for e in inventory], ["<invalid-json>"])
        self.assertEqual(inventory[0]["classification"], "REMOVED")


if __name__ == "__main__":
    unittest.main()
