"""OC-P0-08 (#341): reviewer independence and outage/exhausted/zero-spend routing matrix.

Every case drives ``router.main()`` with injected control documents and coordination
view, so it pins the real CLI decision rather than a helper in isolation.
"""
from __future__ import annotations

import json
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import router  # noqa: E402

REVIEW = ["code_review"]
IMPLEMENTATION = ["implementation"]


def actor(actor_id: str, capabilities: list[str], cost_class: str = "INCLUDED_SUBSCRIPTION", **extra) -> dict:
    return {
        "id": actor_id,
        "enabled": True,
        "configured": True,
        "capabilities": capabilities,
        "cost_class": cost_class,
        "may_independently_gate_own_material_authorship": False,
        **extra,
    }


def readiness(actor_id: str, capabilities: list[str], **extra) -> dict:
    record = {
        "actor_id": actor_id,
        "setup_state": "ready",
        "verified_capabilities": capabilities,
        "temporarily_unavailable_capabilities": [],
        "repository_access": {"read": True, "write": True, "review": True, "merge": False},
    }
    record.update(extra)
    return record


def documents(actors: list[dict], records: list[dict], capabilities: list[str]) -> dict:
    return {
        "actors.json": {"actors": actors},
        "readiness.json": {"actors": records},
        "routing.json": {
            "preference_by_capability": {
                capability: [item["id"] for item in actors] for capability in capabilities
            }
        },
        "dispatch.json": {
            "actors": [
                {
                    "actor_id": item["id"],
                    "mechanisms": [
                        {
                            "id": "interactive",
                            "configured": True,
                            "unattended": False,
                            "capabilities": capabilities,
                        }
                    ],
                }
                for item in actors
            ]
        },
        "budget.json": {
            "cost_classes": {
                "allowed": ["INCLUDED_SUBSCRIPTION", "FREE_ALLOWANCE", "HUMAN"],
                "conditionally_allowed": ["METERED_ALLOWED"],
                "forbidden": ["UNKNOWN_COST"],
            }
        },
    }


def lease(lease_id: str, actor_id: str) -> dict:
    return {"id": lease_id, "role": "implementation", "actor": actor_id, "work_unit": f"WU-{lease_id}"}


class RouterIndependenceMatrixTests(unittest.TestCase):
    def route(self, docs: dict, view: dict, argv: list[str]) -> tuple[int, dict]:
        output = StringIO()
        with (
            mock.patch.object(router, "load_json", side_effect=lambda path: docs[Path(path).name]),
            mock.patch.object(router, "coordination_view", return_value=view),
            mock.patch.object(router, "implementation_availability", return_value=(1, [])),
            mock.patch.object(sys, "argv", ["router.py", *argv]),
            redirect_stdout(output),
        ):
            rc = router.main()
        return rc, json.loads(output.getvalue())

    def rejected(self, payload: dict) -> dict[str, list[str]]:
        return {item["actor"]: item["reasons"] for item in payload["rejected"]}

    def test_review_route_excludes_material_author_without_the_explicit_flag(self):
        docs = documents(
            [actor("author", REVIEW), actor("reviewer", REVIEW)],
            [readiness("author", REVIEW), readiness("reviewer", REVIEW)],
            REVIEW,
        )
        view = {"active_leases": [lease("l1", "author")], "material_authors": ["author"]}

        rc, payload = self.route(docs, view, ["--capability", "code_review"])

        self.assertEqual(rc, 0)
        self.assertTrue(payload["independent_gate"])
        self.assertEqual(payload["proposed_actor"], "reviewer")
        self.assertEqual(payload["material_authors_excluded"], ["author"])
        self.assertIn("material_author_conflict", self.rejected(payload)["author"])

    def test_security_review_route_is_an_independent_gate_too(self):
        caps = ["security_review"]
        docs = documents([actor("author", caps)], [readiness("author", caps)], caps)
        view = {"active_leases": [lease("l1", "author")], "material_authors": ["author"]}

        rc, payload = self.route(docs, view, ["--capability", "security_review"])

        self.assertEqual(rc, 2)
        self.assertEqual(payload["status"], "BLOCKED_NO_ELIGIBLE_ROUTE")
        self.assertIsNone(payload["proposed_actor"])
        self.assertIn("material_author_conflict", self.rejected(payload)["author"])

    def test_review_route_rejects_self_gating_policy_actor_without_the_flag(self):
        docs = documents(
            [
                actor("self-gater", REVIEW, may_independently_gate_own_material_authorship=True),
                actor("reviewer", REVIEW),
            ],
            [readiness("self-gater", REVIEW), readiness("reviewer", REVIEW)],
            REVIEW,
        )
        rc, payload = self.route(docs, {"active_leases": [], "material_authors": []}, ["--capability", "code_review"])

        self.assertEqual(rc, 0)
        self.assertEqual(payload["proposed_actor"], "reviewer")
        self.assertIn("self_gate_policy_conflict", self.rejected(payload)["self-gater"])

    def test_review_route_refuses_ambiguous_streams_without_pr(self):
        docs = documents([actor("reviewer", REVIEW)], [readiness("reviewer", REVIEW)], REVIEW)
        view = {
            "active_leases": [lease("l1", "a"), lease("l2", "b")],
            "material_authors": ["a", "b"],
        }

        rc, payload = self.route(docs, view, ["--capability", "code_review"])

        self.assertEqual(rc, 2)
        self.assertEqual(payload["status"], "BLOCKED_AMBIGUOUS_REVIEW_STREAM")
        self.assertEqual(payload["eligible"], [])

    def test_review_route_uses_the_pr_stream_authors(self):
        docs = documents(
            [actor("a", REVIEW), actor("b", REVIEW)],
            [readiness("a", REVIEW), readiness("b", REVIEW)],
            REVIEW,
        )
        view = {"active_leases": [lease("l1", "a"), lease("l2", "b")], "material_authors": ["b"]}

        rc, payload = self.route(docs, view, ["--capability", "code_review", "--pr", "7"])

        self.assertEqual(rc, 0)
        self.assertEqual(payload["proposed_actor"], "a")
        self.assertEqual(payload["material_authors_excluded"], ["b"])

    def test_implementation_route_is_not_an_independent_gate(self):
        docs = documents([actor("author", IMPLEMENTATION)], [readiness("author", IMPLEMENTATION)], IMPLEMENTATION)
        view = {"active_leases": [lease("l1", "author")], "material_authors": ["author"]}

        rc, payload = self.route(docs, view, ["--capability", "implementation"])

        self.assertEqual(rc, 0)
        self.assertFalse(payload["independent_gate"])
        self.assertEqual(payload["proposed_actor"], "author")
        self.assertEqual(payload["material_authors_excluded"], [])

    def test_outage_exhausted_and_spend_matrix_falls_back_only_to_included_ready_actor(self):
        docs = documents(
            [
                actor("outage", REVIEW),
                actor("exhausted", REVIEW),
                actor("unverified", REVIEW),
                actor("no-review-scope", REVIEW),
                actor("metered", REVIEW, cost_class="METERED_ALLOWED"),
                actor("unknown-cost", REVIEW, cost_class="UNKNOWN_COST"),
                actor("fallback", REVIEW),
            ],
            [
                readiness("outage", REVIEW, temporarily_unavailable_capabilities=REVIEW),
                readiness("exhausted", REVIEW, setup_state="blocked"),
                readiness("unverified", []),
                readiness(
                    "no-review-scope",
                    REVIEW,
                    repository_access={"read": True, "write": True, "review": False, "merge": False},
                ),
                readiness("metered", REVIEW),
                readiness("unknown-cost", REVIEW),
                readiness("fallback", REVIEW),
            ],
            REVIEW,
        )

        rc, payload = self.route(docs, {"active_leases": [], "material_authors": []}, ["--capability", "code_review"])

        self.assertEqual(rc, 0)
        self.assertEqual(payload["proposed_actor"], "fallback")
        self.assertEqual([item["actor"] for item in payload["eligible"]], ["fallback"])
        self.assertEqual(
            self.rejected(payload),
            {
                "outage": ["temporarily_unavailable:code_review"],
                "exhausted": ["setup_state:blocked"],
                "unverified": ["unverified_capabilities:code_review"],
                "no-review-scope": ["review_publish_not_verified"],
                "metered": ["forbidden_by_budget"],
                "unknown-cost": ["forbidden_by_budget"],
            },
        )

    def test_all_routes_rejected_blocks_with_no_proposal(self):
        docs = documents(
            [actor("outage", REVIEW), actor("metered", REVIEW, cost_class="METERED_ALLOWED")],
            [
                readiness("outage", REVIEW, temporarily_unavailable_capabilities=REVIEW),
                readiness("metered", REVIEW),
            ],
            REVIEW,
        )

        rc, payload = self.route(docs, {"active_leases": [], "material_authors": []}, ["--capability", "code_review"])

        self.assertEqual(rc, 2)
        self.assertEqual(payload["status"], "BLOCKED_NO_ELIGIBLE_ROUTE")
        self.assertIsNone(payload["proposed_actor"])
        self.assertEqual(payload["eligible"], [])


if __name__ == "__main__":
    unittest.main()
