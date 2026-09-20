"""Regression tests for read-only three-target A4/L2 pilot intake."""
from __future__ import annotations

import ast
import base64
import textwrap
import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import a4_pr_producer as producer
import p123_pilot_intake as intake
from test_a4_first_pr_producer import BASE, installation

REPOS = ("owner-a/scratch-a", "owner-b/scratch-b", "owner-c/scratch-c")
WU = ("WU-A", "WU-B", "WU-C")
ACTOR = "fixture-bot"


def manifest():
    def entry(i):
        return {
            "repository": REPOS[i], "base_sha": BASE,
            "wu": WU[i], "actor": ACTOR, "disposable": True,
        }
    return {
        "a4_pilots": [entry(0), entry(1)],
        "l2_pilot": {**entry(2), "pr_number": 7},
    }


class ReadOnlyPilotApi:
    def __init__(self, repository, l2=False):
        self.repository = repository
        self.base = BASE
        self.private = False
        self.visibility = "public"
        self.branch_sha = "b" * 40
        self.calls = []
        self.missing = None
        self.drift = None
        self.docs = {
            key: value for key, value in installation(
                repository, WU[REPOS.index(repository)],
            ).items() if key in intake.CONTROL
        }
        self.docs["config"]["project"]["disposable_pilot"] = True
        if l2:
            self.docs["queue"]["work_units"][0]["pr"] = 7
            self.docs["readiness"]["actors"][0][
                "verified_capabilities"
            ].append("ci_remediation")
            self.docs["actors"]["actors"][0]["capabilities"].append(
                "ci_remediation"
            )
            self.docs["dispatch"]["actors"][0]["mechanisms"].append({
                "id": "github-actions-l2-fixture-repair",
                "kind": "github_action", "configured": True,
                "unattended": True, "capabilities": ["ci_remediation"],
            })
            self.docs["ledger"] = {"enabled": True, "issue_number": 45}

    def call(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if method != "GET" or payload is not None:
            raise AssertionError("pilot intake must not mutate")
        if path == "/":
            return {
                "full_name": self.repository, "private": self.private,
                "visibility": self.visibility, "default_branch": "main",
            }
        if path == "/git/ref/heads/main":
            return {"object": {"sha": self.base}}
        if path == "/git/ref/heads/onecompany-a4-wu-c":
            return {"object": {"sha": self.branch_sha}}
        if path.startswith("/contents/"):
            name, ref = path[len("/contents/"):].split("?ref=", 1)
            if ref != BASE or self.missing == name:
                raise producer.Refused("file_absent")
            if name.startswith(".onecompany/") and name.endswith(".json"):
                content = json.dumps(self.docs[name.split("/")[-1][:-5]])
                return {
                    "type": "file", "encoding": "base64",
                    "content": base64.b64encode(content.encode()).decode(),
                    "sha": "b" * 40,
                }
            blobs = {**intake.BASE_FILES, **intake.L2_FILES}
            if name not in blobs:
                raise AssertionError(name)
            return {
                "type": "file",
                "sha": "0" * 40 if self.drift == name else blobs[name],
            }
        if path.startswith("/pulls?"):
            return []
        if path == "/pulls/7":
            return {
                "number": 7, "state": "open",
                "head": {
                    "ref": producer.branch_for("WU-C"),
                    "sha": "b" * 40,
                    "repo": {"full_name": self.repository},
                },
                "base": {
                    "ref": "main", "sha": BASE,
                    "repo": {"full_name": self.repository},
                },
            }
        raise AssertionError(path)


class PilotIntakeTests(unittest.TestCase):
    def setup_targets(self):
        return {
            repo: ReadOnlyPilotApi(repo, l2=(i == 2))
            for i, repo in enumerate(REPOS)
        }

    def test_reviewed_source_and_workflow_pins_are_real_git_blobs(self):
        actual = intake.source_pins()
        self.assertEqual(
            actual["scripts/l2_fixture_repair.py"],
            intake.REPAIR_SCRIPT_BLOB,
        )
        self.assertEqual(
            actual[".onecompany/templates/workflows/onecompany-l2-fixture-validation.yml.disabled"],
            intake.CI_BLOB,
        )

    def test_l2_validation_embedded_python_compiles(self):
        # Live Actions failure 35507892719 was a SyntaxError, not fixture repair.
        path = ROOT / ".onecompany/templates/workflows/onecompany-l2-fixture-validation.yml.disabled"
        workflow = path.read_text(encoding="utf-8")
        start = "          python - <<'PY'\n"
        self.assertEqual(workflow.count(start), 1)
        snippet = workflow.split(start, 1)[1].split("\n          PY", 1)[0]
        ast.parse(textwrap.dedent(snippet), filename=str(path))
        self.assertIn("L2_FIXTURE_INTENTIONAL_FAILURE:fixture_ci_repair_not_complete", snippet)

    def test_stale_worker_pin_fails_even_when_synthetic_api_says_ready(self):
        with patch.object(intake, "REPAIR_SCRIPT_BLOB", "0" * 40):
            with self.assertRaisesRegex(
                producer.Refused,
                "source_pin_drift:scripts/l2_fixture_repair.py",
            ):
                intake.audit(manifest(), "reader", lambda name, token: None)

    def test_three_distinct_public_targets_source_preflight_only(self):
        apis = self.setup_targets()
        result = intake.audit(
            manifest(), "reader", lambda name, token: apis[name],
        )
        self.assertEqual(
            result["status"],
            "THREE_PILOT_INSTALLATIONS_PRECHECKED_NOT_QUALIFIED",
        )
        self.assertEqual(len(result["pilots"]), 3)
        self.assertTrue(all(
            not x["owner_authorization_verified"]
            and not x["live_run_qualified"] for x in result["pilots"]
        ))
        self.assertFalse(result["p1_verified"])
        self.assertFalse(result["p3_verified"])
        for api in apis.values():
            self.assertTrue(api.calls)
            self.assertTrue(all(m == "GET" and v is None
                                for m, _, v in api.calls))

    def test_owner_pair_and_three_repo_isolation(self):
        for change, reason in (
            ({"repository": "owner-a/other"}, "a4_owners_must_be_distinct"),
            ({"repository": REPOS[2]}, "pilot_repositories_must_be_distinct"),
        ):
            case = manifest()
            case["a4_pilots"][1].update(change)
            with self.assertRaisesRegex(producer.Refused, reason):
                intake._manifest(case)

    def test_manifest_claim_cannot_override_live_project_pilot_policy(self):
        api = self.setup_targets()[REPOS[0]]
        api.docs["config"]["project"].pop("disposable_pilot")
        case = manifest()["a4_pilots"][0]
        with self.assertRaisesRegex(
            producer.Refused, "target_disposable_pilot_policy_missing",
        ):
            intake.inspect(api, case, l2=False)
        self.assertFalse(any(m != "GET" for m, _, _ in api.calls))

    def test_manifest_cannot_smuggle_token_or_fake_live_evidence(self):
        for extra in ("token", "live_qualified", "owner_approved",
                      "gh_pat", "run_id"):
            case = manifest()
            case["a4_pilots"][0][extra] = "attacker"
            with self.assertRaisesRegex(
                producer.Refused, "pilot_manifest_keys_invalid",
            ):
                intake._manifest(case)
        case = manifest()
        case["l2_pilot"]["disposable"] = False
        with self.assertRaises(producer.Refused):
            intake._manifest(case)

    def test_p3_requires_positive_prebound_existing_pr(self):
        for value in (None, True, 0, -1, "7"):
            case = manifest()
            case["l2_pilot"]["pr_number"] = value
            with self.subTest(value=value):
                with self.assertRaisesRegex(
                    producer.Refused, "l2_existing_canonical_pr_number_required",
                ):
                    intake._manifest(case)

    def test_reject_private_or_wrong_visibility_before_runner_or_reads(self):
        for field, value in (
            ("private", True), ("visibility", "private"),
        ):
            with self.subTest(field=field):
                api = self.setup_targets()[REPOS[0]]
                setattr(api, field, value)
                with self.assertRaisesRegex(
                    producer.Refused, "target_not_verified_public_repository",
                ):
                    intake.inspect(api, manifest()["a4_pilots"][0], l2=False)
                self.assertEqual(len(api.calls), 1)

    def test_refuse_changed_base_and_untrusted_installed_code(self):
        for change in ("base", "script", "workflow", "missing"):
            with self.subTest(change=change):
                api = self.setup_targets()[REPOS[0]]
                if change == "base":
                    api.base = "f" * 40
                elif change == "script":
                    api.drift = "scripts/a4_pr_producer.py"
                elif change == "workflow":
                    api.drift = intake.TRUSTED_CI_WORKFLOW_PATH
                else:
                    api.missing = "scripts/a4_pr_producer.py"
                with self.assertRaises(producer.Refused):
                    intake.inspect(
                        api, manifest()["a4_pilots"][0], l2=False,
                    )
                self.assertFalse(
                    any(method != "GET" for method, _, _ in api.calls)
                )

    def test_reject_stop_and_unknown_cost_not_hardcode_ready(self):
        for change in ("stop", "overage", "l1", "unverified"):
            with self.subTest(change=change):
                api = self.setup_targets()[REPOS[0]]
                if change == "stop":
                    api.docs["config"]["safety"]["emergency_stop"] = True
                elif change == "overage":
                    api.docs["budget"]["ai"]["allow_overage"] = True
                elif change == "l1":
                    api.docs["config"]["autonomy"]["level"] = "L1"
                else:
                    api.docs["readiness"]["actors"][0]["unattended"][
                        "verified"
                    ] = False
                with self.assertRaises(producer.Refused):
                    intake.inspect(
                        api, manifest()["a4_pilots"][0], l2=False,
                    )

    def test_l2_requires_ledger_and_real_route(self):
        for which in ("ledger", "queue", "route", "pr",
                      "ref", "foreign_pr_repo"):
            with self.subTest(which=which):
                api = self.setup_targets()[REPOS[2]]
                if which == "ledger":
                    api.docs["ledger"]["enabled"] = False
                elif which == "queue":
                    api.docs["queue"]["work_units"][0]["pr"] = None
                elif which == "route":
                    api.docs["dispatch"]["actors"][0][
                        "mechanisms"
                    ].pop()
                elif which == "ref":
                    api.branch_sha = "c" * 40
                else:
                    original = api.call
                    def wrong(method, path, payload=None):
                        value = original(method, path, payload)
                        if path == "/pulls/7":
                            if which == "pr":
                                value["state"] = "closed"
                            else:
                                value["head"]["repo"] = None
                        return value
                    api.call = wrong
                with self.assertRaises(producer.Refused):
                    intake.inspect(
                        api, manifest()["l2_pilot"], l2=True,
                    )

    def test_audit_reports_bounded_why_blocked_without_remote_body(self):
        apis = self.setup_targets()
        apis[REPOS[1]].docs["budget"]["ai"]["allow_overage"] = True
        with self.assertRaisesRegex(
            producer.Refused,
            "pilot_preflight_blocked:a4:owner-b/scratch-b:"
            "zero_extra_spend_preflight_failed",
        ):
            intake.audit(manifest(), "reader", lambda name, token: apis[name])
        self.assertTrue(all(
            method == "GET" for api in apis.values()
            for method, _, _ in api.calls
        ))

    def test_replay_does_not_create_or_claim_pilot_success(self):
        apis = self.setup_targets()
        result1 = intake.audit(
            manifest(), "reader", lambda name, token: apis[name],
        )
        result2 = intake.audit(
            manifest(), "reader", lambda name, token: apis[name],
        )
        self.assertEqual(result1, result2)
        self.assertFalse(any(x["live_run_qualified"]
                             for x in result2["pilots"]))


if __name__ == "__main__":
    unittest.main()
