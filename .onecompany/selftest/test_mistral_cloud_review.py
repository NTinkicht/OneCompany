"""Fail-closed unit tests for source-only cloud Mistral exact-head advisory review."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import bootstrap
import mistral_cloud_review as target

HEAD = "b" * 40
BASE = "a" * 40
BODY = (
    "@mistral-vibe\nMISTRAL_REVIEW_V1\n"
    "pr: 137\nhead_sha: " + HEAD + "\nbase_sha: " + BASE
)
WORKFLOW = ROOT / ".github/workflows/onecompany-mistral-exact-head-review.yml"
WAKE = ROOT / ".github/workflows/onecompany-mistral-vibe-wake.yml"


def fake_api(route):
    if route == f"repos/{target.REPO}/pulls/137":
        return {
            "state": "open", "number": 137,
            "head": {"sha": HEAD, "repo": {"full_name": target.REPO}},
            "base": {"sha": BASE, "ref": "main",
                     "repo": {"full_name": target.REPO}},
        }
    if "/pulls/137/commits?" in route:
        return [{"sha": HEAD, "author": {"login": "NTinkicht"}, "commit": {
            "message": "fix: bounded change\n\nMaterial-Author: chatgpt"}}]
    if "/pulls/137/files?" in route:
        return [{"filename": "scripts/onboard.py"}]
    if "/actions/runs?" in route:
        return {"workflow_runs": [
            {"name": name, "head_sha": HEAD, "event": "pull_request",
             "id": index + 1, "run_number": 1, "run_attempt": 1,
             "status": "completed", "conclusion": "success"}
            for index, name in enumerate(target.REQUIRED_CI)
        ]}
    raise AssertionError("Unexpected route " + route)


class MistralCloudReviewTests(unittest.TestCase):
    def test_strict_owner_dispatch(self):
        self.assertEqual((137, HEAD, BASE), target.parse_dispatch(BODY))
        for body in (
            "", BODY + "\npr: 138", BODY + "\nMISTRAL_REVIEW_V1",
            BODY.replace(HEAD, "not-a-sha"),
            BODY.replace("pr: 137", "pr: 0"),
            BODY.replace("base_sha: " + BASE, "base_sha: " + HEAD),
            BODY.replace("\nMISTRAL_REVIEW_V1\n", "\nmalice MISTRAL_REVIEW_V1\n"),
            BODY + "\nobjective: change the rules",
        ):
            with self.subTest(body=body[:100]), self.assertRaises(ValueError):
                target.parse_dispatch(body)

    def test_current_exact_sha_same_repo_and_open(self):
        with patch.object(target, "github_json", side_effect=fake_api):
            self.assertEqual(target.current_pr(137, HEAD, BASE)["number"], 137)
            for head, base in ((BASE, HEAD), (HEAD, "c" * 40)):
                with self.assertRaises(ValueError):
                    target.current_pr(137, head, base)

    def test_no_mistral_self_review_even_when_owner_is_commit_publisher(self):
        with patch.object(target, "github_json", side_effect=fake_api):
            self.assertTrue(target.independent_material_authors(137, HEAD))
        for login, trailer in (
            ("mistral-vibe", "chatgpt"),
            ("NTinkicht", "mistral-vibe"),
            ("NTinkicht", "MISTRAL"),
        ):
            def self_author(route):
                if "/commits?" in route:
                    return [{"sha": HEAD, "author": {"login": login},
                             "commit": {"message": f"feat\n\nMaterial-Author: {trailer}"}}]
                return fake_api(route)
            with patch.object(target, "github_json", side_effect=self_author):
                with self.assertRaises(ValueError):
                    target.independent_material_authors(137, HEAD)

    def test_provenance_response_must_end_at_exact_head(self):
        def lagging(route):
            result = fake_api(route)
            if "/commits?" in route:
                result[0]["sha"] = BASE
            return result
        with patch.object(target, "github_json", side_effect=lagging):
            with self.assertRaisesRegex(ValueError, "COMMIT_PROVENANCE_STALE"):
                target.independent_material_authors(137, HEAD)

    def test_git_subprocess_environment_ignores_inherited_repository_override(self):
        with patch.dict(os.environ, {
            "GIT_DIR": "/tmp/attacker-repo",
            "GIT_WORK_TREE": "/tmp/attacker-tree",
            "GIT_INDEX_FILE": "/tmp/attacker-index",
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "core.worktree",
            "GIT_CONFIG_VALUE_0": "/tmp/attacker-tree",
            "ONECOMPANY_REVIEW_TEST_MARKER": "kept",
        }):
            cleaned = target.clean_git_env()
            self.assertTrue(all(not key.startswith("GIT_") for key in cleaned))
            self.assertEqual(cleaned["ONECOMPANY_REVIEW_TEST_MARKER"], "kept")

    def test_latest_failed_or_running_ci_cannot_be_hidden_by_old_green(self):
        with patch.object(target, "github_json", side_effect=fake_api):
            self.assertTrue(target.latest_ci_green(137, HEAD))
        def stale_ci(route):
            data = fake_api(route)
            if "/actions/runs?" in route:
                data["workflow_runs"].append({
                    "name": "OneCompany Validate", "head_sha": HEAD,
                    "event": "pull_request", "id": 999, "run_number": 2,
                    "run_attempt": 1, "status": "completed", "conclusion": "failure",
                })
            return data
        with patch.object(target, "github_json", side_effect=stale_ci):
            self.assertFalse(target.latest_ci_green(137, HEAD))

    def test_ledger_smoke_only_required_for_trusted_matching_pr_paths(self):
        from unittest.mock import patch as override
        self.assertIn(
            ".onecompany/ledger.json",
            target.ledger_trigger_paths(
                ROOT / ".github/workflows/onecompany-ledger-read-smoke.yml"
            ),
        )
        with override.object(target, "github_json", side_effect=fake_api):
            self.assertTrue(target.latest_ci_green(137, HEAD))
        def ledger_changed(route):
            if "/pulls/137/files?" in route:
                return [{"filename": ".onecompany/ledger.json"}]
            return fake_api(route)
        with override.object(target, "github_json", side_effect=ledger_changed):
            self.assertFalse(target.latest_ci_green(137, HEAD))
        def ledger_green(route):
            result = ledger_changed(route)
            if "/actions/runs?" in route:
                result["workflow_runs"].append({
                    "name": target.LEDGER_CHECK,
                    "head_sha": HEAD, "event": "pull_request",
                    "id": 80, "run_number": 3, "run_attempt": 1,
                    "status": "completed", "conclusion": "success",
                })
            return result
        with override.object(target, "github_json", side_effect=ledger_green):
            self.assertTrue(target.latest_ci_green(137, HEAD))
        def ledger_new_red(route):
            result = ledger_green(route)
            if "/actions/runs?" in route:
                result["workflow_runs"].append({
                    "name": target.LEDGER_CHECK,
                    "head_sha": HEAD, "event": "pull_request",
                    "id": 90, "run_number": 4, "run_attempt": 1,
                    "status": "completed", "conclusion": "failure",
                })
            return result
        with override.object(target, "github_json", side_effect=ledger_new_red):
            self.assertFalse(target.latest_ci_green(137, HEAD))

    def test_pr_file_api_fails_closed_on_missing_data(self):
        def bad_files(route):
            if "/pulls/137/files?" in route:
                return [{"unexpected_field": "unsafe"}]
            return fake_api(route)
        with patch.object(target, "github_json", side_effect=bad_files):
            with self.assertRaisesRegex(ValueError, "REVIEW_FILENAME_INVALID"):
                target.changed_pr_paths(137)
        with self.assertRaisesRegex(ValueError, "LEDGER_PATH_FILTER_UNAVAILABLE"):
            with tempfile.TemporaryDirectory() as temp:
                bad = Path(temp) / "ledger.yml"
                bad.write_text("on:\n  pull_request:\n    branches: [main]\n")
                target.ledger_trigger_paths(bad)

    def test_prepare_never_promotes_invalid_dispatch(self):
        with tempfile.TemporaryDirectory() as temp:
            outputs = Path(temp) / "output"
            with patch.dict(os.environ, {
                "GITHUB_OUTPUT": str(outputs),
                "GITHUB_REPOSITORY": target.REPO,
                "DISPATCH_BODY": BODY,
            }), patch.object(target, "github_json", side_effect=fake_api):
                target.prepare()
            self.assertIn("ready=true", outputs.read_text())
            outputs.write_text("")
            with patch.dict(os.environ, {
                "GITHUB_OUTPUT": str(outputs),
                "GITHUB_REPOSITORY": target.REPO,
                "DISPATCH_BODY": BODY.replace(HEAD, "c" * 40),
            }), patch.object(target, "github_json", side_effect=fake_api):
                target.prepare()
            self.assertIn("REVIEW_TARGET_BLOCKED", outputs.read_text())

    def test_evidence_is_exclusive_and_never_follows_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            current = Path.cwd()
            try:
                os.chdir(root)
                outputs = root / "output"
                victim = root / "victim"
                victim.write_bytes(b"preserve me")
                (root / target.DIFF_NAME).symlink_to(victim)
                def git(args, **kwargs):
                    if args[1:3] == ["rev-parse", "HEAD"]:
                        return (HEAD + "\n").encode("ascii")
                    if args[1] == "diff":
                        return b"diff --git a/x b/x\n+safe diff\n"
                    raise AssertionError(args)
                with patch.dict(os.environ, {
                    "GITHUB_OUTPUT": str(outputs),
                    "REVIEW_PR": "137", "REVIEW_SHA": HEAD,
                    "REVIEW_BASE": BASE,
                }), patch.object(target, "github_json", side_effect=fake_api), patch.object(
                    target.subprocess, "check_output", side_effect=git
                ):
                    target.evidence()
                self.assertIn("REVIEW_EVIDENCE_BLOCKED", outputs.read_text())
                self.assertEqual(victim.read_bytes(), b"preserve me")
                (root / target.DIFF_NAME).unlink()
                outputs.write_text("")
                with patch.dict(os.environ, {
                    "GITHUB_OUTPUT": str(outputs),
                    "REVIEW_PR": "137", "REVIEW_SHA": HEAD,
                    "REVIEW_BASE": BASE,
                }), patch.object(target, "github_json", side_effect=fake_api), patch.object(
                    target.subprocess, "check_output", side_effect=git
                ):
                    target.evidence()
                self.assertIn("ready=true", outputs.read_text())
                self.assertIn(b"safe diff", (root / target.DIFF_NAME).read_bytes())
            finally:
                os.chdir(current)

    def test_trusted_stage_contains_only_bounded_untrusted_data(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old = Path.cwd()
            try:
                os.chdir(root)
                trusted = root / "trusted"
                trusted.mkdir()
                (trusted / "AGENTS.md").write_text("main protected policy")
                (trusted / "CLOUD-AGENT-QUALIFICATION.md").write_text("main policy")
                (root / target.DIFF_NAME).write_text("candidate review diff")
                (root / "scripts").mkdir()
                (root / "scripts" / "demo.py").write_text("untrusted candidate source")
                def fake_git(args, **kwargs):
                    if args[1:3] == ["rev-parse", "HEAD"]:
                        return (HEAD + "\n").encode("ascii")
                    if args[1] == "diff" and "--name-only" in args:
                        return b"scripts/demo.py\0"
                    raise AssertionError(args)
                with patch.dict(os.environ, {
                    "GITHUB_OUTPUT": str(root / "out"),
                    "REVIEW_PR": "137", "REVIEW_SHA": HEAD, "REVIEW_BASE": BASE,
                }), patch.object(target, "github_json", side_effect=fake_api), patch.object(
                    target.subprocess, "check_output", side_effect=fake_git
                ):
                    target.stage_review(stage=root / "stage", trusted=trusted)
                self.assertIn("ready=true", (root / "out").read_text())
                stage = root / "stage"
                self.assertIn("main protected policy",
                              (stage / "_onecompany_trusted/AGENTS.md").read_text())
                self.assertIn("candidate review diff", (stage / "review.diff").read_text())
                self.assertIn("untrusted candidate",
                              (stage / "review_sources/scripts/demo.py").read_text())
                self.assertFalse((stage / ".git").exists())
                self.assertFalse((stage / ".vibe").exists())
                # A model must never be able to read the actual PR checkout from
                # its trusted working directory through an artifact symlink.
                (root / "scripts" / "demo.py").unlink()
                (root / "scripts" / "demo.py").symlink_to(trusted / "AGENTS.md")
                (root / "out").write_text("")
                with patch.dict(os.environ, {
                    "GITHUB_OUTPUT": str(root / "out"),
                    "REVIEW_PR": "137", "REVIEW_SHA": HEAD, "REVIEW_BASE": BASE,
                }), patch.object(target, "github_json", side_effect=fake_api), patch.object(
                    target.subprocess, "check_output", side_effect=fake_git
                ):
                    target.stage_review(stage=root / "stage-symlink", trusted=trusted)
                self.assertIn("REVIEW_STAGE_BLOCKED", (root / "out").read_text())
            finally:
                os.chdir(old)

    def test_large_source_is_a_bounded_changed_line_excerpt(self):
        """Reviewer sees numbered changed context, never unrelated huge source."""
        original = [f"line_{number} = {number}" for number in range(1, 5001)]
        original[0] = "UNRELATED_SECRET_MARKER = 1"
        original[2499] = "REVIEW_CHANGED_MARKER = 2500"
        source = ("\n".join(original) + "\n").encode("utf-8")
        self.assertGreater(len(source), target.MAX_REVIEW_STAGE_SOURCE_BYTES)

        def patch_for_one_hunk(args, **_kwargs):
            self.assertEqual(args[1:3], ["diff", "--no-ext-diff"])
            self.assertIn("--unified=0", args)
            self.assertEqual(args[-1], "scripts/large.py")
            return b"diff --git a/scripts/large.py b/scripts/large.py\n@@ -2500 +2500 @@\n"

        with patch.object(target.subprocess, "check_output", side_effect=patch_for_one_hunk):
            staged = target.bounded_review_source("scripts/large.py", source, BASE, HEAD)
        self.assertLessEqual(len(staged), target.MAX_REVIEW_STAGE_SOURCE_BYTES)
        self.assertIn(b"2500: REVIEW_CHANGED_MARKER = 2500", staged)
        self.assertIn(b"INSUFFICIENT_EVIDENCE, not PASS.", staged)
        self.assertNotIn(b"UNRELATED_SECRET_MARKER", staged)
        self.assertNotIn(b"line_5000", staged)
        self.assertIn(b"2499:", staged)

    def test_large_source_missing_changed_hunks_fails_closed(self):
        """A truncated or malformed diff cannot create a false source review."""
        source = b"line = 1\n" * 3000
        with patch.object(target.subprocess, "check_output", return_value=b""):
            with self.assertRaisesRegex(ValueError, "REVIEW_SOURCE_HUNKS_MISSING"):
                target.bounded_review_source("scripts/large.py", source, BASE, HEAD)

    def test_large_source_excerpt_still_has_hard_byte_ceiling(self):
        """Even changed-line windows do not admit an oversized staged payload."""
        source = (b"change = '" + b"A" * 13000 + b"'\n") * 2
        with patch.object(target.subprocess, "check_output",
                          return_value=b"@@ -1 +1 @@\n"):
            with self.assertRaisesRegex(ValueError, "REVIEW_SOURCE_EXCERPT_BOUND_EXCEEDED"):
                target.bounded_review_source("scripts/large.py", source, BASE, HEAD)

    def test_insufficient_evidence_uses_a_valid_standalone_marker(self):
        """A prose mention is not a terminal marker; an isolated marker is."""
        workflow = WORKFLOW.read_text(encoding="utf-8")
        pattern = r"^[[:space:]]*INSUFFICIENT_EVIDENCE[[:space:]]*$"
        self.assertIn("grep -Eqi '" + pattern + "' /tmp/onecompany-mistral-output.txt", workflow)
        for output, accepted in (
            ("INSUFFICIENT_EVIDENCE\n", True),
            ("   INSUFFICIENT_EVIDENCE   \n", True),
            ("The result is not INSUFFICIENT_EVIDENCE\n", False),
            ("CHANGES_REQUIRED because of a confirmed defect\n", False),
        ):
            with self.subTest(output=output):
                result = subprocess.run(
                    ["grep", "-Eqi", pattern], input=output, text=True,
                    capture_output=True, check=False,
                )
                self.assertEqual(result.returncode == 0, accepted)

    def test_redaction_step_creates_review_input_under_actions_guard(self):
        """Publisher must not depend on unset READY/ACTOR_EXIT shell variables."""
        workflow = WORKFLOW.read_text(encoding="utf-8")
        stage = workflow.split(
            "      - name: Prepare redacted current-head Mistral review\n", 1
        )[1].split("      # The parent publishes model PASS", 1)[0]
        self.assertIn(
            "if: steps.preflight.outputs.ready == 'true' && steps.actor.outputs.exit_code == '0'",
            stage,
        )
        self.assertNotIn("${READY:-false}", stage)
        self.assertNotIn("${ACTOR_EXIT:-1}", stage)
        script = textwrap.dedent(stage.split("        run: |\n", 1)[1])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "model-source.json"
            public = root / "redacted.json"
            token = "SYNTHETIC_REDAC_TEST_TOKEN"
            source.write_text('{"summary": "' + token + '"}', encoding="utf-8")
            script = script.replace(
                "/tmp/onecompany-mistral-output.txt", str(source)
            ).replace(
                "/tmp/onecompany-mistral-public.txt", str(public)
            )
            env = os.environ.copy()
            env["MISTRAL_API_KEY"] = token
            result = subprocess.run(
                ["bash", "-c", script], capture_output=True, text=True,
                env=env, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            actual = public.read_text(encoding="utf-8")
            self.assertIn("[REDACTED]", actual)
            self.assertNotIn(token, actual)
            self.assertEqual(result.stdout, "")

    def test_wake_bus_reports_binding_only_after_successful_platform_publication(self):
        """Grok finding: a pre-publish wake message must never claim binding PASS."""
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertEqual(workflow.count("- name: Post Mistral result"), 1)
        report = workflow.split("      - name: Post Mistral result\n", 1)[1]
        script = textwrap.dedent(report.split("        run: |\n", 1)[1])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            comment = root / "wake-report.md"
            model_output = root / "model-result.json"
            model_output.write_text('{"synthetic": "review"}', encoding="utf-8")
            script = script.replace(
                "/tmp/onecompany-mistral-comment.md", str(comment)
            ).replace(
                "/tmp/onecompany-mistral-public.txt", str(model_output)
            )
            scenarios = [
                ("success", "APPROVE", "BINDING technical PASS", False),
                ("success", "REQUEST_CHANGES", "BINDING technical FAIL", False),
                ("failure", "", "REVIEW_PUBLICATION_BLOCKED", True),
                ("skipped", "", "REVIEW_PUBLICATION_BLOCKED", True),
            ]
            for outcome, event, expected, blocked in scenarios:
                with self.subTest(outcome=outcome, event=event):
                    env = os.environ.copy()
                    env.update({
                        "READY": "true", "ACTOR_EXIT": "0",
                        "TARGET_READY": "true",
                        "EVIDENCE_READY": "true", "STAGE_READY": "true",
                        "PUBLISH_OUTCOME": outcome,
                        "PUBLISH_EVENT": event,
                        "REVIEW_PR": "220", "REVIEW_SHA": HEAD,
                        "GITHUB_SERVER_URL": "https://github.com",
                        "GITHUB_REPOSITORY": "NTinkicht/OneCompany",
                        "GITHUB_RUN_ID": "42",
                    })
                    # Replace the external GitHub operation with a shell stub.
                    result = subprocess.run(
                        ["bash", "-c", "gh() { :; }\n" + script],
                        capture_output=True, text=True, env=env, check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    report_body = comment.read_text(encoding="utf-8")
                    self.assertIn(expected, report_body)
                    self.assertIn("PR #220; exact head " + HEAD, report_body)
                    self.assertIn(
                        "https://github.com/NTinkicht/OneCompany/actions/runs/42",
                        report_body,
                    )
                    self.assertNotIn("ADVISORY review (non-binding)", report_body)
                    self.assertNotIn('{"synthetic": "review"}', report_body)
                    if not blocked:
                        self.assertIn("Validated findings are in the exact-head GitHub PR review.", report_body)
                    self.assertEqual(
                        "no binding GitHub technical PASS/FAIL recorded" in report_body,
                        blocked,
                    )

    def test_owner_wake_and_review_are_disjoint_source_only(self):
        regular = WAKE.read_text(encoding="utf-8")
        review = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("contains(github.event.comment.body, 'MISTRAL_REVIEW_V1') == false", regular)
        self.assertIn("contains(github.event.comment.body, 'MISTRAL_REVIEW_V1')", review)
        self.assertIn("github.actor == 'NTinkicht'", review)
        self.assertIn("github.event.issue.number == 130", review)
        self.assertIn("persist-credentials: false", review)
        self.assertIn("/tmp/onecompany-budget-trusted.json", review)
        self.assertIn("cp scripts/mistral_cloud_review.py /tmp/", review)
        self.assertIn("name: OneCompany Mistral Exact-Head Technical Review", review)
        self.assertIn("cp AGENTS.md /tmp/onecompany-mistral-trusted/AGENTS.md", review)
        self.assertIn("cp docs/CLOUD-AGENT-QUALIFICATION.md /tmp/onecompany-mistral-trusted/", review)
        self.assertIn("cp scripts/mistral_review_packet.py /tmp/onecompany-mistral-packet-trusted.py", review)
        self.assertIn("--stage /tmp/onecompany-mistral-review-stage", review)
        self.assertIn("--trusted /tmp/onecompany-mistral-trusted", review)
        self.assertIn("REVIEW_PACKET_BLOCKED", review)
        self.assertIn("--max-turns 2", review)
        self.assertIn("enabled_tools = [\"re:^(?!)\"]", review)
        self.assertIn("--enabled-tools 're:^(?!)'", review)
        self.assertNotIn("--enabled-tools read_file", review)
        self.assertNotIn("--enabled-tools grep", review)
        self.assertIn("REVIEW_PACKET_BLOCKED", review)
        self.assertIn("--max-tokens 64000", review)
        self.assertIn("NOT proof of exhausted subscription credits, included quota or financial budget", review)
        self.assertNotIn("--max-tokens 50000", review)
        self.assertIn("the entire permitted review context", review)
        self.assertIn("TURN_LIMIT_EXCEEDED", review)
        self.assertIn("RESULT_CONTRACT_INVALID", review)
        self.assertIn("Mistral returned a valid JSON insufficient-evidence verdict", review)
        self.assertIn("REVIEW_PACKET_BLOCKED", review)
        self.assertIn("python -I /tmp/onecompany-mistral-result-trusted.py", review)
        self.assertNotIn("output INSUFFICIENT_EVIDENCE on its own line", review)
        self.assertIn("Turn limit of [0-9]+ reached", review)
        self.assertNotIn("--max-turns 4", review)
        self.assertIn("or repeated tool turns", review)
        self.assertLessEqual(target.MAX_REVIEW_STAGE_DIFF_BYTES, 32_000)
        self.assertLessEqual(target.MAX_REVIEW_STAGE_SOURCE_BYTES, 24_000)
        self.assertLessEqual(target.MAX_REVIEW_STAGE_TOTAL_BYTES, 64_000)
        self.assertNotIn(
            "Read AGENTS.md, agents/mistral-vibe.md, docs/agent-setup/",
            review,
        )
        self.assertNotIn("read files in $GITHUB_WORKSPACE", review)
        self.assertIn("--workdir /tmp/onecompany-mistral-review-stage", review)
        self.assertIn("steps.stage.outputs.ready == 'true'", review)
        self.assertIn("cp AGENTS.md /tmp/onecompany-mistral-trusted", review)
        self.assertIn("cp .github/workflows/onecompany-ledger-read-smoke.yml", review)
        self.assertIn("ONECOMPANY_LEDGER_RULES_FILE:", review)
        self.assertNotIn('--workdir "$GITHUB_WORKSPACE"', review)
        self.assertNotIn("contents: write", review)
        self.assertIn("pull-requests: write", review)
        # Candidate PR checkout must never shadow stdlib modules while tokens
        # are in privileged trusted-parent Python heredocs.
        self.assertEqual(review.count("python -I - <<'PY'"), 4)
        self.assertNotIn("python - <<'PY'", review)
        self.assertIn("python -I /tmp/onecompany-mistral-review-trusted.py", review)
        self.assertIn("python -I -m pip install", review)
        self.assertNotIn("run: python -m pip install", review)
        self.assertIn("Publish current-head Mistral independent technical PR review as Actions bot", review)
        self.assertIn("steps.actor.outputs.exit_code == '0'", review)
        self.assertIn("guard.current_pr(number, head, base)", review)
        self.assertIn("guard.latest_ci_green(number, head)", review)
        self.assertIn("guard.independent_material_authors(number, head)", review)
        self.assertIn('-f "event=$review_event"', review)
        self.assertIn('review_event" != "APPROVE"', review)
        self.assertIn('review_event" != "REQUEST_CHANGES"', review)
        self.assertIn("parser.format_binding_review(", review)
        self.assertNotIn("-f event=COMMENT", review)
        self.assertIn('"commit_id=$REVIEW_SHA"', review)
        self.assertIn("technical PASS/FAIL", review)
        self.assertIn("**Mistral Vibe exact-head BINDING technical PASS", review)
        self.assertIn("**Mistral Vibe exact-head BINDING technical FAIL", review)
        self.assertIn("Mistral Vibe review NOT BINDING", review)
        self.assertNotIn("ADVISORY review (non-binding)", review)
        self.assertIn("PUBLISH_OUTCOME: ${{ steps.publish.outcome }}", review)
        self.assertIn("PUBLISH_EVENT: ${{ steps.publish.outputs.review_event }}", review)
        self.assertIn('echo "review_event=$review_event" >> "$GITHUB_OUTPUT"', review)
        self.assertIn("REVIEW_PUBLICATION_BLOCKED", review)
        self.assertNotIn("cat /tmp/onecompany-mistral-public.txt", review)
        self.assertNotIn("MISTRAL_API_KEY", review.split("- name: Post Mistral result", 1)[1])
        self.assertIn("Trusted run: $GITHUB_SERVER_URL/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID", review)
        self.assertLess(
            review.index("- name: Prepare redacted current-head Mistral review"),
            review.index("- name: Publish current-head Mistral independent technical PR review as Actions bot"),
        )
        self.assertLess(
            review.index("- name: Publish current-head Mistral independent technical PR review as Actions bot"),
            review.index("- name: Post Mistral result"),
        )
        self.assertNotIn("gh pr merge", review)
        import re
        active_uses = re.findall(r"(?m)^\s+uses:\s+([^\s]+)", review)
        self.assertEqual(len(active_uses), 3)
        for use in active_uses:
            self.assertRegex(use, r"^actions/[a-z0-9-]+@[0-9a-f]{40}$")
        for source_path in (
            "scripts/mistral_cloud_review.py",
            "scripts/mistral_review_result.py",
            ".github/workflows/onecompany-mistral-exact-head-review.yml",
        ):
            self.assertIn(source_path, bootstrap.SOURCE_INSTALLATION_EXCLUSIONS)
        self.assertIn(
            ".onecompany/selftest/test_mistral_cloud_review.py",
            bootstrap.SOURCE_INSTALLATION_EXCLUSIONS,
        )
        self.assertIn(
            ".onecompany/selftest/test_mistral_review_result.py",
            bootstrap.SOURCE_INSTALLATION_EXCLUSIONS,
        )
        for source_only in (
            "scripts/mistral_review_packet.py",
            ".onecompany/selftest/test_mistral_review_packet.py",
        ):
            self.assertIn(source_only, bootstrap.SOURCE_INSTALLATION_EXCLUSIONS)


if __name__ == "__main__":
    unittest.main()
