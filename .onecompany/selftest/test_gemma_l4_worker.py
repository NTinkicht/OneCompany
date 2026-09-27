import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import gemma_l4_worker as w


class FakeResponse:
    def __init__(self, body):
        self.body = body
    def __enter__(self):
        return self
    def __exit__(self, *_args):
        return False
    def read(self, _limit):
        return self.body


class GemmaL4WorkerTests(unittest.TestCase):
    def test_sensitive_paths_fail_closed(self):
        self.assertFalse(w.safe_path(".env"))
        self.assertFalse(w.safe_path("ops/secrets/token.txt"))
        self.assertFalse(w.safe_path("auth.json"))
        self.assertTrue(w.safe_path("src/service.py"))

    def test_nonzero_cost_fails_closed(self):
        body = json.dumps({
            "usage": {"cost": 0.01},
            "choices": [{"message": {"content": "ok"}}],
        }).encode()
        with patch.object(w.guard, "check_budget"), patch.object(w.guard, "check_model"):
            with self.assertRaisesRegex(ValueError, "NONZERO_OR_UNKNOWN_INFERENCE_COST"):
                w.request_gemma(
                    "test-key",
                    "task",
                    {"head_sha": "a" * 40, "base_sha": "b" * 40},
                    opener=lambda *_a, **_k: FakeResponse(body),
                )

    def test_request_uses_qualified_free_model_and_repository_evidence(self):
        seen = []
        body = json.dumps({
            "usage": {"cost": 0},
            "choices": [{"message": {"content": "grounded advisory"}}],
        }).encode()
        def opener(request, timeout):
            seen.append((request, timeout))
            return FakeResponse(body)
        context = {
            "head_sha": "a" * 40,
            "base_sha": "b" * 40,
            "changed_files": ["src/example.py"],
            "diff": "+example",
            "repository_files": [],
            "omitted_files": [],
        }
        with patch.object(w.guard, "check_budget"), patch.object(w.guard, "check_model"):
            result = w.request_gemma("test-key", "inspect src/example.py", context, opener=opener)
        self.assertEqual(result, "grounded advisory")
        request, timeout = seen[0]
        self.assertEqual(timeout, 120)
        payload = json.loads(request.data)
        self.assertEqual(payload["model"], w.guard.FREE_MODEL)
        self.assertEqual(payload["usage"], {"include": True})
        user = json.loads(payload["messages"][1]["content"])
        self.assertEqual(user["repository_evidence"]["head_sha"], "a" * 40)
        self.assertEqual(user["repository_evidence"]["changed_files"], ["src/example.py"])

    def test_secret_like_diff_is_rejected(self):
        with patch.object(w, "git") as git:
            git.side_effect = [
                "a" * 40 + "\n",
                "b" * 40 + "\n",
                "src/example.py\n",
                "+API_KEY=supersecretvalue123\n",
            ]
            with self.assertRaisesRegex(ValueError, "SECRET_LIKE_DIFF_CONTENT_BLOCKED"):
                w.build_context("inspect example", "origin/main")

    def test_file_bound_and_read_errors_are_recorded(self):
        with patch.object(w, "git") as git, patch.object(Path, "read_bytes") as read_bytes:
            tracked = "\n".join(f"src/file{i}.py" for i in range(12)) + "\n"
            git.side_effect = [
                "a" * 40 + "\n",
                "b" * 40 + "\n",
                "",
                "",
                tracked,
            ]
            read_bytes.side_effect = OSError("unreadable")
            context = w.build_context("inspect files", "origin/main")
            self.assertTrue(
                any(item.get("reason") == "read_error" for item in context["omitted_files"])
            )


if __name__ == "__main__":
    unittest.main()
