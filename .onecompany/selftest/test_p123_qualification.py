"""P1/P3 deterministic disposable-pilot and read-only live proof regression tests."""
from __future__ import annotations

import base64
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
import l2_fixture_repair as repair
import p123_qualify as campaign
from test_a4_first_pr_producer import (
    BASE, CLAIM, REPO, WU, FakeGitHub, installation,
)

SECOND = "1" * 40
ACTOR = "fixture-bot"


def approved():
    config = installation()
    config["readiness"]["actors"][0]["verified_capabilities"].append(
        "ci_remediation"
    )
    config["actors"]["actors"][0]["capabilities"].append("ci_remediation")
    config["dispatch"]["actors"][0]["mechanisms"].append({
        "id": "github-actions-l2-fixture-repair",
        "kind": "github_action", "configured": True,
        "unattended": True, "capabilities": ["ci_remediation"],
    })
    return config


class RepairGitHub(FakeGitHub):
    def __init__(self):
        super().__init__(REPO)
        self.failed_run = {
            "event": "workflow_dispatch", "head_sha": CLAIM,
            "conclusion": "failure", "path": repair.CI_PATH,
            "repository": {"full_name": REPO},
        }
        self.writes = 0
        self.lose_patch_response = False

    def call(self, method, path, payload=None):
        if method == "GET" and path.startswith(
            "/contents/" + repair.CI_PATH + "?ref="
        ):
            return {"type": "file", "sha": repair.CI_BLOB}
        if method == "GET" and path == "/actions/runs/42":
            return self.failed_run
        if method == "GET" and path == "/git/commits/" + CLAIM:
            return {"tree": {"sha": "e" * 40},
                    "parents": [{"sha": BASE}]}
        if method == "GET" and path == "/git/commits/" + SECOND:
            return {"parents": [{"sha": CLAIM}]}
        if method == "POST" and path == "/git/commits" and CLAIM in self.parents:
            self.parents[SECOND] = payload["parents"][0]
            self.files[SECOND] = self.blob_body
            return {"sha": SECOND}
        if method == "PATCH" and path == (
            "/git/refs/heads/" + producer.branch_for(WU)
        ):
            self.writes += 1
            self.refs[producer.branch_for(WU)] = payload["sha"]
            self.prs[0]["head"]["sha"] = payload["sha"]
            if self.lose_patch_response:
                raise producer.ApiFailure(503)
            return {"object": {"sha": payload["sha"]}}
        return super().call(method, path, payload)


class SamePRRepairTests(unittest.TestCase):
    def setup_pilot(self):
        api = RepairGitHub()
        options = approved()
        first = producer.produce(api, **options)
        self.assertEqual(first["head"], CLAIM)
        # A separate P3 pre-bound project baseline, not A4's pre-PR queue.
        options["queue"]["work_units"][0]["pr"] = 1
        return api, options

    def invoke(self, api, options):
        with patch.object(repair, "_native_lease", return_value="lease-test"):
            return repair.repair(
                api, **options, number=1, initial=CLAIM,
                failed_run_id=42,
            )

    def test_one_repair_then_idempotent_replay_same_pr(self):
        api, options = self.setup_pilot()
        result = self.invoke(api, options)
        self.assertEqual(result["status"], "L2_REPAIR_COMMITTED")
        self.assertEqual(result["repaired"], SECOND)
        again = self.invoke(api, options)
        self.assertEqual(again["status"], "L2_REPAIR_RECONCILED")
        self.assertTrue(again["already_applied"])
        self.assertEqual(api.created_prs, 1)
        self.assertEqual(api.created_refs, 1)
        self.assertEqual(api.writes, 1)
        self.assertEqual(api.parents[SECOND], CLAIM)
        self.assertEqual(
            api.files[SECOND],
            producer.fixture_body(REPO, WU, ACTOR, BASE)
            + repair.REPAIR_LINE,
        )

    def test_native_lease_absence_refuses_before_git_mutation(self):
        api, options = self.setup_pilot()
        with patch.object(
            repair, "_native_lease",
            side_effect=producer.Refused("durable_canonical_implementation_lease_missing"),
        ):
            with self.assertRaisesRegex(
                producer.Refused, "durable_canonical_implementation_lease_missing"
            ):
                repair.repair(
                    api, **options, number=1, initial=CLAIM, failed_run_id=42,
                )
        self.assertEqual(api.writes, 0)

    def test_pre_pr_queue_does_not_count_as_p3_binding(self):
        api, options = self.setup_pilot()
        options["queue"]["work_units"][0]["pr"] = None
        with self.assertRaisesRegex(
            producer.Refused, "p3_canonical_pr_queue_binding_required"
        ):
            self.invoke(api, options)
        self.assertEqual(api.writes, 0)

    def test_uncertain_ref_update_never_retries_or_rewrites(self):
        api, options = self.setup_pilot()
        api.lose_patch_response = True
        with self.assertRaisesRegex(
            producer.Refused, "repair_ref_indeterminate_reconcile_no_retry"
        ):
            self.invoke(api, options)
        self.assertEqual(api.writes, 1)
        self.assertEqual(api.created_prs, 1)
        api.lose_patch_response = False
        self.assertTrue(self.invoke(api, options)["already_applied"])
        self.assertEqual(api.writes, 1)

    def test_no_successful_ci_is_pretended_failed(self):
        api, options = self.setup_pilot()
        api.failed_run["conclusion"] = "success"
        with self.assertRaisesRegex(
            producer.Refused, "failed_ci_not_exact_initial_head"
        ):
            self.invoke(api, options)
        self.assertEqual(api.writes, 0)

    def test_wrong_source_workflow_refuses(self):
        api, options = self.setup_pilot()
        class Drift(RepairGitHub):
            pass
        api.call_origin = api.call
        def wrong(method, path, payload=None):
            if method == "GET" and path.startswith(
                "/contents/" + repair.CI_PATH
            ):
                return {"type": "file", "sha": "0" * 40}
            return api.call_origin(method, path, payload)
        api.call = wrong
        with self.assertRaisesRegex(
            producer.Refused, "reviewed_l2_validation_workflow_drift"
        ):
            self.invoke(api, options)
        self.assertEqual(api.writes, 0)

    def test_foreign_or_dirty_pr_refuses_before_git_objects(self):
        for alteration in ("foreign", "head", "base"):
            with self.subTest(alteration=alteration):
                api, options = self.setup_pilot()
                if alteration == "foreign":
                    api.prs[0]["head"]["repo"] = None
                elif alteration == "head":
                    api.prs[0]["head"]["sha"] = "f" * 40
                else:
                    api.prs[0]["base"]["sha"] = "f" * 40
                with self.assertRaises(producer.Refused):
                    self.invoke(api, options)
                self.assertEqual(api.writes, 0)

    def test_negative_policy_capability_scope_and_public_runner(self):
        for alteration in ("stop", "ci", "route", "private", "scope"):
            with self.subTest(alteration=alteration):
                api, options = self.setup_pilot()
                options = copy.deepcopy(options)
                if alteration == "stop":
                    options["config"]["safety"]["emergency_stop"] = True
                elif alteration == "ci":
                    options["readiness"]["actors"][0][
                        "verified_capabilities"
                    ].remove("ci_remediation")
                elif alteration == "route":
                    options["dispatch"]["actors"][0][
                        "mechanisms"
                    ].pop()
                elif alteration == "private":
                    api.private = True
                else:
                    options["queue"]["work_units"][0][
                        "write_scope"
                    ] = ["docs/**"]
                with self.assertRaises(producer.Refused):
                    self.invoke(api, options)
                self.assertEqual(api.writes, 0)


class EvidenceGitHub:
    """Minimal read-only provider-shaped exact-head L2 evidence."""
    def __init__(self, repo, _token):
        self.repository = repo
        self.calls = []
        self.initial = CLAIM
        self.repaired = SECOND
        self.base = BASE
        self.pr = 7
        self.merged = "7" * 40
        self.review_id = 23
        self.review_login = "independent-reviewer[bot]"
        self.author_login = "github-actions[bot]"
        self.ci = repair.CI_BLOB
        self.l2 = {
            "repository": repo, "wu": WU, "actor": ACTOR,
            "pr_number": self.pr, "base_sha": BASE,
            "initial_head": CLAIM, "repaired_head": SECOND,
            "failed_run_id": 80, "passed_run_id": 81,
            "review_id": self.review_id,
        }
        self.ledger = {
            "version": 2, "type": "MERGED", "event_id": "evt-1",
            "actor": "human-owner", "payload": {
                "work_unit": WU, "pr": 7,
                "approved_head": SECOND, "approved_base": BASE,
                "merge_sha": self.merged,
            },
        }

    def call(self, method, path, payload=None):
        self.calls.append((method, path))
        if method != "GET":
            raise AssertionError("campaign must be read-only")
        if path == "/":
            return {"full_name": self.repository, "visibility": "public",
                    "private": False, "default_branch": "main"}
        if path == "/pulls/7":
            return {
                "number": 7, "state": "closed", "merged_at": "2026-09-20T00:00:00Z",
                "merge_commit_sha": self.merged,
                "head": {"sha": SECOND, "ref": producer.branch_for(WU),
                         "repo": {"full_name": self.repository}},
                "base": {"sha": BASE, "ref": "main",
                         "repo": {"full_name": self.repository}},
            }
        if path == f"/compare/{BASE}...{SECOND}":
            return {
                "status": "ahead",
                "files": [{"filename": producer.fixture_path(WU),
                           "status": "added"}],
                "commits": [{"sha": CLAIM}, {"sha": SECOND}],
            }
        if path == "/git/commits/" + SECOND:
            return {"parents": [{"sha": CLAIM}]}
        if path.startswith("/contents/"):
            ref = path.split("?ref=", 1)[1]
            if path.startswith("/contents/" + repair.CI_PATH):
                body, sha = "reviewed workflow", self.ci
            elif path.startswith("/contents/.onecompany/ledger.json"):
                body, sha = json.dumps({
                    "enabled": True, "issue_number": 41,
                    "trusted_publisher_logins": ["owner"],
                }), "f" * 40
            else:
                body = producer.fixture_body(self.repository, WU, ACTOR, BASE)
                if ref == SECOND:
                    body += repair.REPAIR_LINE
                sha = "f" * 40
            return {"type": "file", "sha": sha, "encoding": "base64",
                    "content": base64.b64encode(body.encode()).decode()}
        if path == "/actions/runs/80/jobs?per_page=100":
            return {"jobs": [{
                "id": 800, "name": "validate-fixture",
                "conclusion": "failure",
                "steps": [{
                    "name": "Validate one bounded repaired fixture",
                    "conclusion": "failure",
                }],
            }]}
        if path in ("/actions/runs/80", "/actions/runs/81"):
            first = path.endswith("80")
            return {
                "path": repair.CI_PATH, "event": "workflow_dispatch",
                "status": "completed",
                "conclusion": "failure" if first else "success",
                "head_sha": CLAIM if first else SECOND,
                "repository": {"full_name": self.repository},
            }
        if path.endswith("/check-runs?per_page=100"):
            first = CLAIM in path
            run = 80 if first else 81
            return {"check_runs": [{
                "name": "validate-fixture",
                "head_sha": CLAIM if first else SECOND,
                "status": "completed",
                "conclusion": "failure" if first else "success",
                "app": {"slug": "github-actions"},
                "details_url": (
                    f"https://github.com/{self.repository}"
                    f"/actions/runs/{run}/job/3"
                ),
            }]}
        if path == "/pulls/7/reviews?per_page=100":
            return [{"id": self.review_id, "commit_id": SECOND,
                     "state": "APPROVED",
                     "user": {"login": self.review_login}}]
        if path.startswith("/commits/"):
            return {"author": {"login": self.author_login}}
        if path == "/issues/41/comments?per_page=100&page=1":
            return [{"id": 100, "user": {"login": "owner"},
                     "body": (campaign.MARKER + "\n```json\n"
                              + json.dumps(self.ledger) + "\n```"),
                     "created_at": "2026-09-20T00:00:00Z",
                     "updated_at": "2026-09-20T00:00:00Z"}]
        raise AssertionError(path)


class L2LiveWitnessTests(unittest.TestCase):
    def setup_witness(self):
        api = EvidenceGitHub("owner/l2-test", "unused")
        return api, copy.deepcopy(api.l2)

    def verify(self, api, entry):
        # Unit fixtures mock ONLY native platform bindings. The real verifier
        # must resolve these from base-trusted identity and canonical ledger.
        with (
            patch.object(campaign, "_job_log",
                         return_value="fixture_ci_repair_not_complete"),
            patch.object(campaign, "_native_review", return_value={
                "login": api.review_login, "actor_id": "independent-reviewer",
            }),
            patch.object(campaign, "_native_merged_event", return_value=None),
        ):
            return campaign.verify_l2(
                entry, "read-only", factory=lambda repo, token: api
            )

    def test_exact_head_ci_repair_review_merge_and_ledger(self):
        api, entry = self.setup_witness()
        result = self.verify(api, entry)
        self.assertEqual(result["status"], "L2_LIVE_SAME_PR_FLOW_OBSERVED")
        self.assertEqual(result["repaired_head"], SECOND)
        self.assertTrue(all(m == "GET" for m, _ in api.calls))

    def test_wrong_check_run_head_refuses(self):
        api, entry = self.setup_witness()
        original = api.call
        def bad(method, path, payload=None):
            result = original(method, path, payload)
            if path == "/actions/runs/81":
                result["head_sha"] = CLAIM
            return result
        api.call = bad
        with self.assertRaisesRegex(
            producer.Refused, "pilot_run_wrong_identity_or_conclusion"
        ):
            self.verify(api, entry)

    def test_failed_ci_without_target_fixture_failure_refuses(self):
        api, entry = self.setup_witness()
        original = api.call
        def bad(method, path, payload=None):
            result = original(method, path, payload)
            if path == "/actions/runs/80/jobs?per_page=100":
                result["jobs"][0]["steps"][0]["conclusion"] = "success"
            return result
        api.call = bad
        with self.assertRaisesRegex(
            producer.Refused, "l2_intentional_fixture_failure_not_proven"
        ):
            self.verify(api, entry)

    def test_review_self_author_refuses(self):
        api, entry = self.setup_witness()
        api.review_login = api.author_login
        with self.assertRaisesRegex(
            producer.Refused, "self_review_not_independent"
        ):
            self.verify(api, entry)

    def test_missing_durable_merge_refuses(self):
        api, entry = self.setup_witness()
        api.ledger["payload"]["approved_head"] = CLAIM
        with self.assertRaisesRegex(
            producer.Refused, "durable_exact_head_merge_event_missing"
        ):
            self.verify(api, entry)

    def test_second_pr_or_second_path_refuses(self):
        api, entry = self.setup_witness()
        original = api.call
        def bad(method, path, payload=None):
            result = original(method, path, payload)
            if path == f"/compare/{BASE}...{SECOND}":
                result["files"].append({
                    "filename": "services/secret.py", "status": "modified",
                })
            return result
        api.call = bad
        with self.assertRaisesRegex(
            producer.Refused, "l2_not_one_repair_on_one_fixture_pr"
        ):
            self.verify(api, entry)

    def test_false_bot_attribution_never_promotes_app_capability(self):
        api = EvidenceGitHub("NTinkicht/OneCompany", "unused")
        api.author_login = "onecompany-grok-worker[bot]"
        result = campaign.verify_worker_attribution(
            {"repository": "NTinkicht/OneCompany",
             "pr_number": 7, "head_sha": SECOND},
            "read-only", factory=lambda repo, token: api,
        )
        self.assertFalse(result["authenticated_app_write_verified"])
        self.assertFalse(result["independent_reviewer_verified"])


if __name__ == "__main__":
    unittest.main()
