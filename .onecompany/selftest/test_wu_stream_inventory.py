#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from wu_stream_inventory import DuplicateCanonicalStreamError, Stream, canonical_stream, may_start_new_stream


class WorkUnitStreamInventoryTests(unittest.TestCase):
    def test_zero_streams_allows_start(self) -> None:
        self.assertTrue(may_start_new_stream([], repository="NTinkicht/OneCompany", wu_id="WU-1"))

    def test_one_stream_is_canonical(self) -> None:
        stream = Stream("WU-1", "NTinkicht/OneCompany", "wu/1", 301, "a" * 40)
        self.assertIs(canonical_stream([stream], repository=stream.repository, wu_id=stream.wu_id), stream)
        self.assertFalse(may_start_new_stream([stream], repository=stream.repository, wu_id=stream.wu_id))

    def test_duplicate_streams_fail_closed(self) -> None:
        streams = [
            Stream("WU-1", "NTinkicht/OneCompany", "wu/1-a", 301, "a" * 40),
            Stream("WU-1", "NTinkicht/OneCompany", "wu/1-b", 302, "b" * 40),
        ]
        with self.assertRaisesRegex(DuplicateCanonicalStreamError, "DUPLICATE_CANONICAL_STREAMS"):
            canonical_stream(streams, repository="NTinkicht/OneCompany", wu_id="WU-1")


if __name__ == "__main__":
    unittest.main()
