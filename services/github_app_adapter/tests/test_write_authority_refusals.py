"""Ledger read-side refusals: every fail-closed branch has a test with a positive control."""
from __future__ import annotations
import datetime as dt
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from write_authority import active_implementation_lease, parse_trusted_events
from write_policy import WriteRefused

NOW = dt.datetime(2026, 9, 19, 12, 0, tzinfo=dt.timezone.utc)
T0 = "2026-09-19T11:00:00Z"
PUBLISHERS = {"NTinkicht"}


def body(obj):
    return "<!-- onecompany-ledger-v1 -->\n```json\n" + json.dumps(obj) + "\n```"


def make_event(type="ROLE_LEASE_ASSIGNED", event_id="evt1", payload=None, **over):
    data = {"lease_id": "lease1", "pr": 106, "work_unit": "WU-X",
            "branch": "wu-x", "role": "implementation", "start_head": "a" * 40}
    data.update(payload or {})
    obj = {"version": 2, "event_id": event_id, "type": type,
           "actor": "grok-4-6-interactive", "timestamp": T0, "payload": data}
    obj.update(over)
    return obj


def comment(text, id=1, user="NTinkicht", created=T0):
    return {"id": id, "user": {"login": user}, "created_at": created,
            "updated_at": created, "body": text}


def parse(comments):
    return parse_trusted_events(comments, PUBLISHERS)


def lease(events, **over):
    args = dict(lease_id="lease1", work_unit="WU-X", pr_number=106,
                now=NOW, ttl_seconds=14400)
    args.update(over)
    return active_implementation_lease(events, **args)


class ParseRefusalTests(unittest.TestCase):
    def refused(self, reason, comments, publishers=None):
        with self.assertRaises(WriteRefused) as ctx:
            parse_trusted_events(comments, PUBLISHERS if publishers is None else publishers)
        self.assertEqual(str(ctx.exception), reason)

    def test_positive_control_parses(self):
        events = parse([comment(body(make_event()))])
        self.assertEqual([e["id"] for e in events], ["evt1"])

    def test_empty_inputs_are_incomplete(self):
        self.refused("ledger_incomplete", [])
        self.refused("ledger_incomplete", [comment(body(make_event()))], publishers=set())

    def test_oversized_ledger_is_incomplete(self):
        many = [comment("x", id=i + 1) for i in range(501)]
        self.refused("ledger_incomplete", many)
        parse(many[:500])  # boundary is accepted

    def test_invalid_comment_shapes(self):
        self.refused("ledger_comment_invalid", ["not-a-dict"])
        self.refused("ledger_comment_invalid", [comment("x", id="1")])

    def test_ids_must_strictly_increase(self):
        self.refused("ledger_order_invalid", [comment("x", id=2), comment("y", id=2)])
        self.refused("ledger_order_invalid", [comment("x", id=3), comment("y", id=2)])
        parse([comment("x", id=2), comment("y", id=3)])

    def test_marker_without_json_block_is_refused_only_for_publishers(self):
        text = "<!-- onecompany-ledger-v1 --> no fenced json"
        self.refused("ledger_malformed_trusted_event", [comment(text)])
        self.assertEqual(parse([comment(text, user="stranger")]), [])

    def test_invalid_json_is_refused(self):
        text = "<!-- onecompany-ledger-v1 -->\n```json\n{not json}\n```"
        self.refused("ledger_malformed_trusted_event", [comment(text)])

    def test_event_schema_is_enforced(self):
        bad = [
            make_event(version=1), make_event(event_id=""), make_event(event_id=7),
            make_event(actor=3), make_event(payload=None, type=None),
            make_event(type=5),
        ]
        for obj in bad:
            with self.subTest(obj=obj):
                self.refused("ledger_event_schema_invalid", [comment(body(obj))])
        for obj in ({"version": 2, "event_id": "e", "type": "T", "actor": "a", "payload": []},):
            with self.subTest(obj=obj):
                self.refused("ledger_event_schema_invalid", [comment(body(obj))])

    def test_duplicate_event_id_is_refused(self):
        first = comment(body(make_event()), id=1)
        second = comment(body(make_event(payload={"lease_id": "lease2"})), id=2)
        self.refused("ledger_duplicate_event_id", [first, second])
        other = comment(body(make_event(event_id="evt2", payload={"lease_id": "lease2"})), id=2)
        parse([first, other])

    def test_claimed_timestamp_must_match_platform_time(self):
        far = make_event(timestamp="2026-09-19T11:05:01Z")
        self.refused("ledger_timestamp_not_platform_bound", [comment(body(far))])
        edge = make_event(timestamp="2026-09-19T11:05:00Z")
        parse([comment(body(edge))])
        parse([comment(body(make_event(timestamp=None)))])

    def test_naive_or_garbage_timestamps_are_refused(self):
        self.refused("ledger_timestamp_invalid", [comment(body(make_event()), created="2026-09-19T11:00:00")])
        self.refused("ledger_timestamp_invalid", [comment(body(make_event()), created="garbage")])
        self.refused("ledger_timestamp_invalid", [comment(body(make_event(timestamp="2026-09-19T11:00:00")))])


class LeaseRefusalTests(unittest.TestCase):
    def events(self, *specs):
        return parse([comment(body({**obj, "timestamp": created}), id=i + 1, created=created)
                      for i, (obj, created) in enumerate(specs)])

    def refused(self, reason, events, **over):
        with self.assertRaises(WriteRefused) as ctx:
            lease(events, **over)
        self.assertEqual(str(ctx.exception), reason)

    def test_positive_control_is_active(self):
        self.assertEqual(lease(self.events((make_event(), T0)))["id"], "lease1")

    def test_ttl_must_be_a_bounded_integer(self):
        events = self.events((make_event(), T0))
        for ttl in (0, -1, 14401, True, "14400", None, 1.5):
            with self.subTest(ttl=ttl):
                self.refused("ledger_ttl_unverified", events, ttl_seconds=ttl)
        self.assertEqual(lease(events, ttl_seconds=14400)["id"], "lease1")

    def test_reused_or_empty_lease_ids_conflict(self):
        dup = self.events((make_event(), T0), (make_event(event_id="e2"), T0))
        self.refused("ledger_lease_conflict", dup)
        released = self.events(
            (make_event(), T0),
            (make_event("ROLE_LEASE_RELEASED", "e2", {"lease_id": "lease1"}), T0),
            (make_event(event_id="e3"), T0))
        self.refused("ledger_lease_conflict", released)
        self.refused("ledger_lease_conflict", self.events((make_event(payload={"lease_id": ""}), T0)))

    def test_transfer_requires_known_active_source_and_fresh_target(self):
        move = {"old_lease_id": "lease1", "new_lease_id": "lease2"}
        ok = self.events((make_event(), T0), (make_event("ROLE_LEASE_TRANSFERRED", "e2", move), T0))
        self.assertEqual(lease(ok, lease_id="lease2")["id"], "lease2")
        self.refused("active_canonical_lease_not_unique", ok)  # old lease is gone
        unknown = self.events((make_event(), T0), (make_event(
            "ROLE_LEASE_TRANSFERRED", "e2", {"old_lease_id": "nope", "new_lease_id": "lease2"}), T0))
        self.refused("ledger_transfer_ambiguous", unknown)
        reuse = self.events((make_event(), T0), (make_event(
            "ROLE_LEASE_TRANSFERRED", "e2", {"old_lease_id": "lease1", "new_lease_id": "lease1"}), T0))
        self.refused("ledger_transfer_ambiguous", reuse)
        empty = self.events((make_event(), T0), (make_event(
            "ROLE_LEASE_TRANSFERRED", "e2", {"old_lease_id": "lease1", "new_lease_id": ""}), T0))
        self.refused("ledger_transfer_ambiguous", empty)

    def test_expired_source_cannot_be_transferred(self):
        move = {"old_lease_id": "lease1", "new_lease_id": "lease2"}
        late = self.events((make_event(), T0), (
            make_event("ROLE_LEASE_TRANSFERRED", "e2", move), "2026-09-19T15:00:00Z"))
        self.refused("ledger_transfer_source_expired", late, ttl_seconds=14400,
                     now=NOW + dt.timedelta(hours=5))
        early = self.events((make_event(), T0), (
            make_event("ROLE_LEASE_TRANSFERRED", "e2", move), "2026-09-19T14:59:59Z"))
        self.assertEqual(lease(early, lease_id="lease2", now=dt.datetime(
            2026, 9, 19, 15, 0, tzinfo=dt.timezone.utc))["id"], "lease2")

    def test_merged_work_unit_is_refused_but_other_units_are_not(self):
        other = self.events((make_event(), T0), (make_event("MERGED", "e2", {"work_unit": "WU-OTHER"}), T0))
        self.assertEqual(lease(other)["id"], "lease1")
        merged = self.events((make_event(), T0), (make_event("MERGED", "e2", {"work_unit": "WU-X"}), T0))
        self.refused("work_unit_already_merged", merged)

    def test_reaped_lease_loses_authority_and_other_renewals_are_ignored(self):
        reaped = self.events((make_event(), T0), (make_event(
            "ROLE_LEASE_REAPED", "e2", {"lease_id": "lease1"}), T0))
        self.refused("active_canonical_lease_not_unique", reaped)
        other = self.events((make_event(), T0), (make_event(
            "ROLE_LEASE_RENEWED", "e2", {"lease_id": "elsewhere"}), T0))
        self.assertEqual(lease(other)["id"], "lease1")

    def test_competing_lease_for_same_work_unit_is_not_unique(self):
        both = self.events((make_event(), T0), (make_event(
            event_id="e2", payload={"lease_id": "lease2", "pr": 999}), T0))
        self.refused("active_canonical_lease_not_unique", both)
        # same PR number under a different work unit also collides
        by_pr = self.events((make_event(), T0), (make_event(
            event_id="e2", payload={"lease_id": "lease2", "work_unit": "WU-Y"}), T0))
        self.refused("active_canonical_lease_not_unique", by_pr)

    def test_wrong_lease_id_is_not_unique(self):
        self.refused("active_canonical_lease_not_unique",
                     self.events((make_event(), T0)), lease_id="forged")

    def test_expiry_boundary(self):
        events = self.events((make_event(), T0))
        self.refused("active_lease_expired", events, now=NOW + dt.timedelta(hours=3))
        self.assertEqual(lease(events, now=NOW + dt.timedelta(hours=2, minutes=59))["id"], "lease1")


if __name__ == "__main__":
    unittest.main()
