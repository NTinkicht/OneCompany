"""OC-P0-01 / OC-P0-05 / OC-P0-06 (#377): fail-closed review-conversation evidence."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from review_thread_reconciliation import (  # noqa: E402
    ReviewThreadObservation as T,
    review_thread_findings,
)


class ReviewThreadFindingsTests(unittest.TestCase):
    def test_complete_resolved_list_has_no_findings(self):
        self.assertEqual((), review_thread_findings((), True))
        self.assertEqual((), review_thread_findings(
            (T("a", True, False), T("b", True, True)), True))

    def test_unresolved_threads_including_outdated_are_reported(self):
        self.assertEqual(
            (("a", "UNRESOLVED_REVIEW_THREAD"), ("b", "UNRESOLVED_REVIEW_THREAD")),
            review_thread_findings((T("b", False, True), T("c", True, False),
                                    T("a", False, False)), True))

    def test_incomplete_list_is_never_proof(self):
        for complete in (False, None, 1, "true"):
            with self.subTest(complete=complete):
                self.assertIn(("", "REVIEW_THREADS_INCOMPLETE"),
                              review_thread_findings((T("a", True, False),), complete))

    def test_malformed_threads_fail_closed(self):
        cases = [
            (T("", True, False), ("", "INVALID_REVIEW_THREAD")),
            (T(" a", True, False), ("", "INVALID_REVIEW_THREAD")),
            (T(None, True, False), ("", "INVALID_REVIEW_THREAD")),
            (T("a", 1, False), ("a", "INVALID_REVIEW_THREAD")),
            (T("a", "true", False), ("a", "INVALID_REVIEW_THREAD")),
            (T("a", True, None), ("a", "INVALID_REVIEW_THREAD")),
            ({"id": "a", "is_resolved": True, "is_outdated": False}, ("", "INVALID_REVIEW_THREAD")),
        ]
        for thread, finding in cases:
            with self.subTest(thread=thread):
                self.assertEqual((finding,), review_thread_findings((thread,), True))
        self.assertEqual((("", "INVALID_REVIEW_THREAD"),),
                         review_thread_findings([T("a", True, False)], True))

    def test_duplicate_thread_ids_are_reported_once_and_sorted(self):
        self.assertEqual(
            (("a", "DUPLICATE_REVIEW_THREAD"), ("a", "UNRESOLVED_REVIEW_THREAD")),
            review_thread_findings((T("a", True, False), T("a", False, False),
                                    T("a", True, False)), True))


if __name__ == "__main__":
    unittest.main()
