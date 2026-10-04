#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from wu_stream_inventory import (
    ConflictingStreamObservationError,
    DuplicateCanonicalStreamError,
    IncompleteInventoryError,
    Stream,
    canonical_stream,
)


class WorkUnitStreamInventoryTests(unittest.TestCase):
    def test_empty_complete_snapshot_is_an_observation_not_start_authorization(self) -> None:
        self.assertIsNone(canonical_stream([], repository="NTinkicht/OneCompany", wu_id="WU-1", snapshot_complete=True))

    def test_incomplete_or_unavailable_snapshot_fails_closed(self) -> None:
        with self.assertRaisesRegex(IncompleteInventoryError, "INVENTORY_INCOMPLETE"):
            canonical_stream([], repository="NTinkicht/OneCompany", wu_id="WU-1", snapshot_complete=False)

    def test_one_stream_is_canonical(self) -> None:
        stream = Stream("WU-1", "NTinkicht/OneCompany", "wu/1", 301, "a" * 40)
        self.assertIs(canonical_stream([stream], repository=stream.repository, wu_id=stream.wu_id, snapshot_complete=True), stream)

    def test_repository_identity_is_case_insensitive(self) -> None:
        stream = Stream("WU-1", "ntinkicht/onecompany", "wu/1", 301, "a" * 40)
        self.assertEqual(canonical_stream([stream], repository="NTinkicht/OneCompany", wu_id="WU-1", snapshot_complete=True), stream)

    def test_replayed_identical_observation_collapses_by_pr_identity(self) -> None:
        stream = Stream("WU-1", "NTinkicht/OneCompany", "wu/1", 301, "a" * 40)
        replay = Stream("WU-1", "ntinkicht/onecompany", "wu/1", 301, "a" * 40)
        self.assertEqual(canonical_stream([stream, replay, stream], repository=stream.repository, wu_id=stream.wu_id, snapshot_complete=True), stream)

    def test_conflicting_observations_for_same_pr_fail_closed(self) -> None:
        streams = [Stream("WU-1", "NTinkicht/OneCompany", "wu/1", 301, "a" * 40), Stream("WU-1", "NTinkicht/OneCompany", "wu/1", 301, "b" * 40)]
        with self.assertRaisesRegex(ConflictingStreamObservationError, "CANONICAL_STREAM_OBSERVATION_CONFLICT"):
            canonical_stream(streams, repository="NTinkicht/OneCompany", wu_id="WU-1", snapshot_complete=True)

    def test_conflicting_wu_observations_fail_before_requested_wu_filter(self) -> None:
        streams = [Stream("WU-1", "NTinkicht/OneCompany", "wu/1", 301, "a" * 40), Stream("WU-2", "ntinkicht/onecompany", "wu/1", 301, "a" * 40)]
        with self.assertRaisesRegex(ConflictingStreamObservationError, "CANONICAL_STREAM_OBSERVATION_CONFLICT"):
            canonical_stream(streams, repository="NTinkicht/OneCompany", wu_id="WU-1", snapshot_complete=True)

    def test_conflict_payload_is_stable_for_reversed_observation_order(self) -> None:
        first = Stream("WU-1", "NTinkicht/OneCompany", "wu/a", 301, "a" * 40)
        second = Stream("WU-1", "ntinkicht/onecompany", "wu/b", 301, "b" * 40)
        messages: list[str] = []
        for streams in ([first, second], [second, first]):
            with self.assertRaises(ConflictingStreamObservationError) as caught:
                canonical_stream(list(streams), repository="NTinkicht/OneCompany", wu_id="WU-1", snapshot_complete=True)
            messages.append(str(caught.exception))
        self.assertEqual(messages[0], messages[1])

    def test_branch_reuse_across_work_units_fails_before_wu_filter(self) -> None:
        streams = [
            Stream("WU-1", "NTinkicht/OneCompany", "wu/shared", 301, "a" * 40),
            Stream("WU-2", "ntinkicht/onecompany", "wu/shared", 302, "b" * 40),
        ]
        with self.assertRaisesRegex(ConflictingStreamObservationError, "CANONICAL_BRANCH_WU_CONFLICT"):
            canonical_stream(streams, repository="NTinkicht/OneCompany", wu_id="WU-1", snapshot_complete=True)

    def test_multiple_distinct_pr_streams_fail_closed(self) -> None:
        streams = [Stream("WU-1", "NTinkicht/OneCompany", "wu/1-a", 301, "a" * 40), Stream("WU-1", "NTinkicht/OneCompany", "wu/1-b", 302, "b" * 40)]
        with self.assertRaisesRegex(DuplicateCanonicalStreamError, "DUPLICATE_CANONICAL_STREAMS"):
            canonical_stream(streams, repository="NTinkicht/OneCompany", wu_id="WU-1", snapshot_complete=True)


if __name__ == "__main__":
    unittest.main()
