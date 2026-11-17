"""Exact-reason refusal tests for the adapter read_source/read_document gates (OC-P0-10).

Offline: no network, keys or paid provider. Each case asserts the specific
refusal reason, and the positive controls prove the guards are not vacuous.
"""
from __future__ import annotations
import base64
import sys
import unittest
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE))
sys.path.insert(0, str(SERVICE / "tests"))

from github_app import AdapterRefused
from test_adapter import FakeClient, settings

SHA = "a" * 40


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


class ContentClient(FakeClient):
    """FakeClient whose /contents/ answer is controlled by the test."""
    contents = None

    def _call(self, method, path, token, payload=None):
        if "/contents/" in path:
            self.calls.append((method, path, payload))
            return self.contents
        return super()._call(method, path, token, payload)


def client_with(contents):
    client = ContentClient(settings())
    client.contents = contents
    return client


def file_of(raw: bytes, **extra):
    data = {"type": "file", "encoding": "base64", "content": b64(raw)}
    data.update(extra)
    return data


class TestReadSourceRefusals(unittest.TestCase):
    P = "scripts/lease.py"

    def refused(self, contents, reason, **kw):
        client = client_with(contents)
        with self.assertRaises(AdapterRefused) as ctx:
            client.read_source(self.P, SHA, kw.get("s", 1), kw.get("e", 5))
        self.assertEqual(str(ctx.exception), reason)

    def test_positive_control(self):
        result = client_with(file_of(b"a\nb\nc\n")).read_source(self.P, SHA, 2, 3)
        self.assertEqual(result["content"], "b\nc")
        self.assertTrue(result["read_only"])

    def test_line_range_boundaries(self):
        client = client_with(file_of(b"x\n"))
        for start, end in [(0, 1), (-1, 1), (5, 4), (1, 161), (True, 2),
                           (1, True), ("1", 2), (1, 2.0)]:
            with self.subTest(start=start, end=end):
                with self.assertRaises(AdapterRefused) as ctx:
                    client.read_source(self.P, SHA, start, end)
                self.assertEqual(str(ctx.exception), "source_line_range_invalid")
        self.assertEqual(client.calls, [])  # refused before any GitHub call
        client.read_source(self.P, SHA, 1, 160)  # widest allowed span

    def test_non_string_sha_and_path_are_refused_before_network(self):
        client = client_with(file_of(b"x"))
        with self.assertRaises(AdapterRefused) as ctx:
            client.read_source(self.P, None, 1, 2)
        self.assertEqual(str(ctx.exception), "exact_commit_sha_required")
        with self.assertRaises(AdapterRefused) as ctx:
            client.read_source(None, SHA, 1, 2)
        self.assertEqual(str(ctx.exception), "source_path_not_allowlisted")
        self.assertEqual(client.calls, [])

    def test_non_file_results_are_refused(self):
        for contents in ({"type": "dir"}, {"type": "symlink"}, [], None, "x"):
            with self.subTest(contents=contents):
                self.refused(contents, "source_not_file")

    def test_bad_encoding_and_content_are_refused(self):
        for contents in (
            {"type": "file", "encoding": "none", "content": b64(b"x")},
            {"type": "file", "encoding": "base64", "content": 5},
            {"type": "file", "encoding": "base64"},
            {"type": "file", "encoding": "base64", "content": "!!notbase64!!"},
            file_of(b"\xff\xfe\x00bad"),
        ):
            with self.subTest(contents=contents):
                self.refused(contents, "source_content_unavailable")

    def test_size_limits(self):
        self.refused(file_of(b"x" * 96_001), "source_exceeds_limit")
        # file under the byte cap, but 160 lines of 200 bytes exceed excerpt cap
        wide = ("y" * 200 + "\n") * 160
        self.refused(file_of(wide.encode()), "source_excerpt_exceeds_limit", e=160)
        # a single line at the excerpt cap (30_000 bytes) is still served
        ok = client_with(file_of(b"x" * 30_000)).read_source(self.P, SHA, 1, 1)
        self.assertEqual(ok["total_lines"], 1)
        self.refused(file_of(b"x" * 30_001), "source_excerpt_exceeds_limit", e=1)


class TestReadDocumentRefusals(unittest.TestCase):
    D = "docs/START.md"

    def refused(self, client, reason, path=None, ref=SHA):
        with self.assertRaises(AdapterRefused) as ctx:
            client.read_document(path or self.D, ref)
        self.assertEqual(str(ctx.exception), reason)

    def test_positive_control(self):
        out = client_with(file_of(b"# ok\n")).read_document(self.D, SHA)
        self.assertEqual(out["content"], "# ok\n")

    def test_stale_ref_refused_before_content_fetch(self):
        client = client_with(file_of(b"x"))
        self.refused(client, "approved_main_head_sha_required", ref="b" * 40)
        self.assertFalse(any("/contents/" in c[1] for c in client.calls))

    def test_non_file_and_bad_content_refused(self):
        self.refused(client_with({"type": "dir"}), "document_not_file")
        for contents in (
            {"type": "file", "encoding": "utf-8", "content": "x"},
            {"type": "file", "encoding": "base64"},
            {"type": "file", "encoding": "base64", "content": "@@@"},
            file_of(b"\xff\xfe"),
        ):
            with self.subTest(contents=contents):
                self.refused(client_with(contents), "document_content_unavailable")

    def test_size_limit(self):
        self.refused(client_with(file_of(b"x" * 30_001)), "document_exceeds_limit")
        client_with(file_of(b"x" * 30_000)).read_document(self.D, SHA)

    def test_long_or_odd_paths_refused_before_network(self):
        client = client_with(file_of(b"x"))
        for path in ("docs/" + "a" * 200 + ".md", "docs//x.md", "docs/../x.md"):
            with self.subTest(path=path[:30]):
                with self.assertRaises(AdapterRefused) as ctx:
                    client.read_document(path, SHA)
                self.assertEqual(str(ctx.exception), "document_path_not_allowlisted")
        self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()
