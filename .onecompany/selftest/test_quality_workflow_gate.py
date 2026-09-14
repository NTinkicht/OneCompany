from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "onecompany-validate.yml"


class QualityWorkflowGateTests(unittest.TestCase):
    def test_post_bootstrap_workflow_fails_closed_for_missing_trusted_producers(self):
        text = WORKFLOW.read_text(encoding="utf-8")

        self.assertNotIn("ready=false", text)
        self.assertIn(
            'if ! git cat-file -e "$BASE_SHA:scripts/quality_evidence.py"',
            text,
        )
        self.assertIn(
            "Reviewed base is missing scripts/quality_evidence.py; "
            "post-bootstrap evidence cannot be produced.",
            text,
        )
        self.assertIn(
            'if git cat-file -e "$BASE_SHA:scripts/quality_evidence_v3.py"',
            text,
        )
        self.assertIn(
            "Reviewed base is missing scripts/quality_evidence_v3.py; "
            "candidate-code fallback is forbidden.",
            text,
        )
        self.assertNotIn(
            'git show "$CANDIDATE_SHA:scripts/quality_evidence.py"',
            text,
        )

    def test_exact_base_path_checks_reject_deleted_or_moved_producer(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.email", "quality-gate@example.invalid"],
                cwd=repo,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Quality Gate Test"],
                cwd=repo,
                check=True,
            )
            scripts = repo / "scripts"
            scripts.mkdir()
            (scripts / "quality_evidence.py").write_text("# trusted v2\n", encoding="utf-8")
            (scripts / "quality_evidence_v3.py").write_text("# trusted v3\n", encoding="utf-8")
            subprocess.run(["git", "add", "scripts"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=repo, check=True)
            base_sha = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()

            def exists_at(sha: str, path: str) -> bool:
                return (
                    subprocess.run(
                        ["git", "cat-file", "-e", f"{sha}:{path}"],
                        cwd=repo,
                        check=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    ).returncode
                    == 0
                )

            self.assertTrue(exists_at(base_sha, "scripts/quality_evidence.py"))
            self.assertTrue(exists_at(base_sha, "scripts/quality_evidence_v3.py"))

            (scripts / "quality_evidence.py").unlink()
            subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "delete v2"], cwd=repo, check=True)
            deleted_sha = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            self.assertFalse(exists_at(deleted_sha, "scripts/quality_evidence.py"))

            (scripts / "quality_evidence_v3.py").rename(
                scripts / "quality_evidence_v3_moved.py"
            )
            subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "move v3"], cwd=repo, check=True)
            moved_sha = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            self.assertFalse(exists_at(moved_sha, "scripts/quality_evidence_v3.py"))


if __name__ == "__main__":
    unittest.main()
