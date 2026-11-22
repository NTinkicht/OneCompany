from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / ".onecompany" / "selftest"))
import brief_handoff_proposal as handoff
from test_brief_handoff_proposal import BASE, HEAD, draft


AUTH = "Product Brief contains authority-bearing state"


def reason(fn, *args) -> str:
    try:
        fn(*args)
    except ValueError as exc:
        return str(exc)
    return "ACCEPTED"


class ProposeReasonVectors(unittest.TestCase):
    """Each refusal must fail for its own reason, never a neighbouring one."""

    def test_positive_control_accepts_valid_draft(self):
        self.assertEqual(handoff.propose(draft(), HEAD, BASE)["authorization"], "NOT_GRANTED")

    def test_exact_reasons(self):
        # propose() runs the canonical draft validator first, so forged status,
        # approval, lease, implementer and AC claims are refused there with its
        # own reasons; the later local guards are defence in depth.
        vectors = (
            ("status", lambda d: d.update(status="APPROVED"), "unsupported Product Brief draft"),
            ("approval", lambda d: d["approval"].update(product_brief=True), AUTH),
            ("lease", lambda d: d.update(write_lease_granted=True), AUTH),
            ("implementer", lambda d: d.update(qualified_implementer_selected=True), AUTH),
            ("ac", lambda d: d.update(acceptance_criteria=["x"]), AUTH),
            ("blocker", lambda d: d.update(safety_blockers=["x"]), "DISCOVERY_SAFETY_BLOCKED"),
            ("missing", lambda d: d.update(missing_required_answers=["problem"]), "inconsistent Product Brief required answers"),
        )
        for label, mutate, expected in vectors:
            with self.subTest(label=label):
                candidate = draft()
                mutate(candidate)
                got = reason(handoff.propose, candidate, HEAD, BASE)
                self.assertEqual(got, expected)

    def test_revision_reasons(self):
        for head, base in ((HEAD[:7], BASE), (HEAD, HEAD), ("z" * 40, BASE), (HEAD, ""), (None, BASE)):
            with self.subTest(head=head, base=base):
                self.assertEqual(reason(handoff.propose, draft(), head, base), "EXACT_DISTINCT_REVISIONS_REQUIRED")


class ConsumeReasonVectors(unittest.TestCase):
    def setUp(self):
        self.base = handoff.propose(draft(), HEAD, BASE)

    def test_positive_control(self):
        out = handoff.consume_for_planning(copy.deepcopy(self.base), HEAD, BASE)
        self.assertEqual(out["authorization"], "NOT_GRANTED")
        self.assertFalse(out["provider_invocation"])
        self.assertEqual(out["requested_extra_spend"], 0)

    def test_exact_reasons(self):
        vectors = (
            ("not dict", None, "HANDOFF_PROPOSAL_REQUIRED"),
            ("schema", lambda p: p.update(schema="other"), "HANDOFF_PROPOSAL_REQUIRED"),
            ("extra field", lambda p: p.update(approved=True), "HANDOFF_PROPOSAL_FIELD_SET_INVALID"),
            ("missing field", lambda p: p.pop("next_action"), "HANDOFF_PROPOSAL_FIELD_SET_INVALID"),
            ("authorization", lambda p: p.update(authorization="GRANTED"), "HANDOFF_MUST_BE_UNAUTHORIZED"),
            ("read_only", lambda p: p.update(read_only=False), "HANDOFF_MUST_BE_UNAUTHORIZED"),
            ("state", lambda p: p.update(state="APPROVED"), "HANDOFF_STATE_INVALID"),
            ("run_key", lambda p: p.update(run_key="k"), "EXECUTION_AUTHORITY_PRESENT"),
            ("lease", lambda p: p.update(lease_id="l"), "EXECUTION_AUTHORITY_PRESENT"),
            ("wu", lambda p: p.update(canonical_work_unit="WU-X"), "EXECUTION_AUTHORITY_PRESENT"),
            ("refs", lambda p: p.update(source_refs_unverified="x"), "STALE_OR_UNVERIFIED_REVISION"),
            ("stale head", lambda p: p["source_refs_unverified"].update(head="c" * 40), "STALE_OR_UNVERIFIED_REVISION"),
            ("project path", lambda p: p["project"].update(path="remote"), "HANDOFF_CONTENT_INVALID"),
            ("project extra", lambda p: p["project"].update(approved=True), "HANDOFF_CONTENT_INVALID"),
            ("empty intent", lambda p: p["owner_intent"].update(problem=" "), "HANDOFF_CONTENT_INVALID"),
            ("constraints", lambda p: p.update(constraints=True), "HANDOFF_CONTENT_INVALID"),
            ("next action", lambda p: p.update(next_action={}), "HANDOFF_CONTENT_INVALID"),
            ("assets", lambda p: p["project"]["existing_ci"].append(True), "KNOWN_ASSETS_INVALID"),
            ("ac", lambda p: p.update(acceptance_criteria=["x"]), "AC_MUST_BE_PROPOSED_BY_TRUSTED_PLANNING"),
        )
        for label, mutate, expected in vectors:
            with self.subTest(label=label):
                poisoned = copy.deepcopy(self.base)
                if mutate is None:
                    poisoned = None
                else:
                    mutate(poisoned)
                self.assertEqual(reason(handoff.consume_for_planning, poisoned, HEAD, BASE), expected)

    def test_trusted_revision_reasons(self):
        for head, base in ((HEAD[:7], BASE), (HEAD, HEAD), (HEAD, None), ("", BASE)):
            with self.subTest(head=head, base=base):
                self.assertEqual(reason(handoff.consume_for_planning, copy.deepcopy(self.base), head, base),
                                 "STALE_OR_UNVERIFIED_REVISION")


if __name__ == "__main__":
    unittest.main()
