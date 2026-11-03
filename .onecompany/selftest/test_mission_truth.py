"""Per-WU mission truth projection: drift, staleness, ordering, fail-closed (OC-P0-17)."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import mission_truth as mt  # noqa: E402

A, B, C = "a" * 40, "b" * 40, "c" * 40
NOW = dt.datetime(2026, 11, 3, 12, 0, tzinfo=dt.timezone.utc)
CACHED = "2026-11-03T11:00:00+00:00"
FRESH = "2026-11-03T11:55:00+00:00"


def wu(wid="WU-1", **kw):
    base = {"id": wid, "claimed_state": "MERGED", "head_sha": A, "merge_sha": B,
            "cached_at": CACHED, "priority": 1, "risk": "LOW"}
    base.update(kw)
    return base


def live(prs, at=FRESH):
    return {"observed_at": at, "prs": prs}


def row(cache, lv, max_age=900):
    return mt.project_work_units(cache, lv, NOW, max_age)["work_units"][0]


class MissionTruthTests(unittest.TestCase):
    def test_verified_merged_requires_exact_head_and_merge_sha(self):
        r = row([wu()], live({"WU-1": {"merged": True, "head_sha": A, "merge_sha": B}}))
        self.assertEqual((r["state"], r["next_action"]), ("VERIFIED_MERGED", "NONE"))

    def test_sha_mismatch_or_unmerged_is_drift(self):
        for pr in ({"merged": True, "head_sha": C, "merge_sha": B},
                   {"merged": True, "head_sha": A, "merge_sha": C},
                   {"merged": False, "head_sha": A, "merge_sha": B}):
            r = row([wu()], live({"WU-1": pr}))
            self.assertEqual(r["state"], "DRIFT")
            self.assertEqual(r["next_action"], "RECONCILE_CACHE_WITH_GITHUB")

    def test_malformed_sha_never_verifies(self):
        r = row([wu(head_sha="x")], live({"WU-1": {"merged": True, "head_sha": "x", "merge_sha": B}}))
        self.assertEqual(r["state"], "DRIFT")

    def test_missing_live_observation_is_unable_to_verify_not_success(self):
        for lv in (None, {}, live({})):
            r = row([wu()], lv)
            self.assertEqual(r["state"], "UNABLE_TO_VERIFY")
            self.assertEqual(r["next_action"], "REFRESH_LIVE_OBSERVATION")

    def test_stale_future_and_out_of_order_snapshots_never_verify(self):
        pr = {"WU-1": {"merged": True, "head_sha": A, "merge_sha": B}}
        cases = {"STALE_SNAPSHOT": "2026-11-03T09:00:00+00:00",
                 "FUTURE_SNAPSHOT": "2026-11-03T13:00:00+00:00",
                 "OUT_OF_ORDER_EVENT": "2026-11-03T10:59:00+00:00"}
        for finding, at in cases.items():
            r = row([wu()], live(pr, at), max_age=36000 if finding == "OUT_OF_ORDER_EVENT" else 900)
            self.assertEqual(r["state"], "UNABLE_TO_VERIFY", finding)
            self.assertIn(finding, r["findings"])

    def test_naive_or_invalid_timestamps_fail_closed(self):
        pr = {"WU-1": {"merged": True, "head_sha": A, "merge_sha": B}}
        for at in ("2026-11-03T11:55:00", "nope", None):
            self.assertEqual(row([wu()], live(pr, at))["state"], "UNABLE_TO_VERIFY")
        self.assertEqual(row([wu(cached_at="bad")], live(pr))["state"], "UNABLE_TO_VERIFY")

    def test_blockers_and_open_units_carry_next_action(self):
        r = row([wu(claimed_state="OPEN", blockers=["#9"])], live({}))
        self.assertEqual((r["state"], r["blockers"], r["next_action"]),
                         ("BLOCKED", ["#9"], "RESOLVE_BLOCKERS"))
        self.assertEqual(row([wu(claimed_state="OPEN")], live({}))["state"], "OPEN")

    def test_ordering_is_deterministic_by_priority_risk_id(self):
        cache = [wu("WU-C", priority=2, claimed_state="OPEN"),
                 wu("WU-B", priority=1, risk="LOW", claimed_state="OPEN"),
                 wu("WU-A", priority=1, risk="HIGH", claimed_state="OPEN")]
        out = mt.project_work_units(cache, live({}), NOW, 900)
        self.assertEqual([r["id"] for r in out["work_units"]], ["WU-A", "WU-B", "WU-C"])
        self.assertEqual(out["next_action"], "CONTINUE_WORK")

    def test_unknown_risk_defaults_to_high_and_authority_never_granted(self):
        out = mt.project_work_units([wu(claimed_state="OPEN", risk="??")], live({}), NOW, 900)
        self.assertEqual(out["work_units"][0]["risk"], "HIGH")
        self.assertIs(out["authority_granted"], False)
        self.assertIs(out["all_verified"], False)

    def test_all_verified_only_when_every_unit_verified(self):
        prs = {"WU-1": {"merged": True, "head_sha": A, "merge_sha": B}}
        self.assertTrue(mt.project_work_units([wu()], live(prs), NOW, 900)["all_verified"])
        self.assertFalse(mt.project_work_units([], live(prs), NOW, 900)["all_verified"])

    def test_invalid_inputs_rejected(self):
        for bad in (None, {}, [1], [{"id": ""}], [wu(), wu()]):
            with self.assertRaises(ValueError):
                mt.project_work_units(bad, live({}), NOW, 900)

    def test_cli_rejects_bad_input_and_prints_projection(self):
        with tempfile.TemporaryDirectory() as d:
            c, l = Path(d) / "c.json", Path(d) / "l.json"
            c.write_text(json.dumps([wu()]))
            l.write_text("{}")
            self.assertEqual(mt.main(["--cache", str(c), "--live", str(l)]), 0)
            c.write_text("not json")
            self.assertEqual(mt.main(["--cache", str(c), "--live", str(l)]), 2)


if __name__ == "__main__":
    unittest.main()
