"""Fail-closed tests for .github/ntk-reviewer/review.py (no network, no model)."""
from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
REVIEWER = ROOT / ".github/ntk-reviewer/review.py"
if not REVIEWER.is_file():
    # Host-only tool: bootstrapped product copies of the selftests do not ship it.
    raise unittest.SkipTest("ntk-reviewer is not installed in this checkout")
SPEC = importlib.util.spec_from_file_location("ntk_review", REVIEWER)
R = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(R)

HEAD = "a" * 40
NEW_HEAD = "b" * 40
LOGIN = "ntk-reviewer[bot]"
PASS = json.dumps({"verdict": "PASS", "summary": "Looks correct.", "findings": []})


class FakeGitHub:
    def __init__(self, *, files=("src/app.py",), ci="success", annotations=(), reviews=(),
                 comments=(), head_after=HEAD, diff="diff --git a/src/app.py b/src/app.py\n+x\n",
                 changed_files=None, rules=None):
        self.files = [{"filename": f} for f in files]
        self.ci, self.annotations = ci, list(annotations)
        self.reviews, self.comments = list(reviews), list(comments)
        self.head_after, self.diff = head_after, diff
        self.changed_files = len(files) if changed_files is None else changed_files
        self.rules = rules if rules is not None else [{"type": "required_status_checks", "parameters": {
            "required_status_checks": [{"context": "validate", "integration_id": 15368}]}}]
        self.posted, self.patched = [], []
        self.pr_reads = 0

    def pr(self, sha=HEAD):
        return {"number": 7, "state": "open", "draft": False, "title": "Add thing", "body": "Body",
                "head": {"sha": sha, "repo": {"full_name": "NTinkicht/Tabibi"}},
                "base": {"ref": "main"}, "changed_files": self.changed_files}

    def get(self, path):
        if path.endswith("/rules/branches/main"):
            return self.rules
        if path.endswith("/status"):
            return {"statuses": []}
        if "/annotations" in path:
            return self.annotations
        if path.endswith("/pulls/7"):
            self.pr_reads += 1
            return self.pr(HEAD if self.pr_reads == 1 else self.head_after)
        raise AssertionError(path)

    def get_diff(self, path):
        return self.diff

    def pages(self, path, key=None, limit=10):
        if "/check-runs" in path:
            if self.ci == "missing":
                return []
            status = "in_progress" if self.ci == "pending" else "completed"
            return [{"id": 1, "name": "validate", "status": status, "conclusion": self.ci,
                     "app": {"id": 15368}}]
        if path.endswith("/reviews"):
            return self.reviews
        if path.endswith("/comments"):
            return self.comments
        if path.endswith("/files"):
            return self.files
        if "/pulls?state=open" in path:
            return [self.pr()]
        raise AssertionError(path)

    def post(self, path, body):
        self.posted.append((path, body))
        return {"id": 99}

    def patch(self, path, body):
        self.patched.append((path, body))
        return {}


class Model:
    def __init__(self, *outputs):
        self.outputs, self.prompts = list(outputs), []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        out = self.outputs.pop(0)
        return out if isinstance(out, tuple) else (out, None, None)


def run(gh, model, mode="approve", now=1_000_000.0):
    return R.review_pr(gh, "Tabibi", gh.pr(), login=LOGIN, mode=mode, run_model=model,
                       calls=[0], now=now, run_url="https://x/run/1")


def reviews_posted(gh):
    return [b for p, b in gh.posted if p.endswith("/reviews")]


def status_of(gh):
    bodies = [b["body"] for p, b in gh.posted + gh.patched if "comments" in p]
    return json.loads(R.STATUS_MARK.search(bodies[-1]).group(1)) if bodies else None


class ParserTests(unittest.TestCase):
    def test_plain_fenced_and_prefixed_json(self):
        for text in (PASS, f"```json\n{PASS}\n```", f"Here is my review:\n{PASS}"):
            self.assertEqual(R.parse(text, set())["verdict"], "PASS")

    def test_rejections_are_format_errors(self):
        for text, code in (("", "EMPTY_OUTPUT"), ("no json", "NO_JSON_OBJECT"), ("{bad", "JSON_INVALID"),
                           ('{"verdict": "LGTM"}', "VERDICT_INVALID"), ("[1]", "NO_JSON_OBJECT"),
                           ('{"verdict":"PASS","findings":"x"}', "FINDINGS_INVALID"),
                           ("{" + " " * 40_000 + "}", "OUTPUT_TOO_LARGE")):
            with self.assertRaises(R.FormatError) as ctx:
                R.parse(text, set())
            self.assertEqual(str(ctx.exception), code)

    def test_pass_with_blocking_or_unknown_severity_is_downgraded(self):
        for sev in ("MEDIUM", "CRITICAL", "weird", None):
            out = R.parse(json.dumps({"verdict": "PASS", "summary": "s", "findings": [
                {"severity": sev, "path": "a.py", "line": 3, "description": "d"}]}), {"a.py"})
            self.assertEqual(out["verdict"], "CHANGES_REQUIRED")
            self.assertTrue(out["downgraded"])

    def test_low_findings_keep_pass(self):
        out = R.parse(json.dumps({"verdict": "PASS", "summary": "s", "findings": [
            {"severity": "low", "path": "./a.py", "line": 0, "description": "nit"}]}), {"a.py"})
        self.assertEqual((out["verdict"], out["findings"][0]["path"], out["findings"][0]["line"]),
                         ("PASS", "a.py", None))

    def test_blocking_finding_beyond_twenty_still_counts(self):
        items = [{"severity": "LOW", "description": "n"}] * 20 + [{"severity": "HIGH", "description": "x"}]
        out = R.parse(json.dumps({"verdict": "PASS", "summary": "s", "findings": items}), set())
        self.assertEqual((out["verdict"], out["omitted"]), ("CHANGES_REQUIRED", 1))

    def test_model_text_is_neutralised(self):
        out = R.parse(json.dumps({"verdict": "PASS", "summary": "line1\nline2 @owner <!-- ntk-review v1 head="
                                  + HEAD + " mode=approve -->", "findings": []}), set())
        self.assertNotIn("\n", out["summary"])
        self.assertNotIn("<!--", out["summary"])
        self.assertNotIn("@owner", out["summary"])
        self.assertLessEqual(len(R.parse(json.dumps({"verdict": "PASS", "summary": "x" * 5000}), set())
                                 ["summary"]), 1200)

    def test_finding_without_description_rejected(self):
        with self.assertRaises(R.FormatError):
            R.parse(json.dumps({"verdict": "CHANGES_REQUIRED", "findings": [{"severity": "HIGH"}]}), set())


class PolicyTests(unittest.TestCase):
    def test_floor_paths(self):
        for p in (".github/workflows/ci.yml", ".github/ntk-reviewer/review.py", "CODEOWNERS",
                  ".onecompany/config.json"):
            self.assertTrue(R.is_floor(p), p)
        for p in ("src/.github.py", "scripts/x.py", "docs/github.md"):
            self.assertFalse(R.is_floor(p), p)

    def test_event_choice_never_approves_floor_or_shadow(self):
        self.assertEqual(R.choose_event("approve", "PASS", False), "APPROVE")
        self.assertEqual(R.choose_event("approve", "PASS", True), "COMMENT")
        self.assertEqual(R.choose_event("approve", "CHANGES_REQUIRED", True), "REQUEST_CHANGES")
        self.assertEqual(R.choose_event("comment", "PASS", False), "COMMENT")
        self.assertEqual(R.choose_event("anything", "PASS", False), "COMMENT")


class FlowTests(unittest.TestCase):
    def test_green_pass_approves_exact_head(self):
        gh, model = FakeGitHub(), Model(PASS)
        self.assertEqual(run(gh, model), "POSTED APPROVE PASS")
        (review,) = reviews_posted(gh)
        self.assertEqual((review["commit_id"], review["event"]), (HEAD, "APPROVE"))
        self.assertIn(f"head={HEAD} mode=approve", review["body"])

    def test_shadow_mode_only_comments(self):
        gh = FakeGitHub()
        run(gh, Model(PASS), mode="comment")
        self.assertEqual(reviews_posted(gh)[0]["event"], "COMMENT")

    def test_changes_required_requests_changes(self):
        gh = FakeGitHub()
        out = json.dumps({"verdict": "CHANGES_REQUIRED", "summary": "s",
                          "findings": [{"severity": "HIGH", "path": "src/app.py", "line": 1, "description": "bug"}]})
        run(gh, Model(out))
        self.assertEqual(reviews_posted(gh)[0]["event"], "REQUEST_CHANGES")

    def test_control_plane_pass_is_comment_only(self):
        gh = FakeGitHub(files=("src/app.py", ".github/workflows/ci.yml"))
        self.assertEqual(run(gh, Model(PASS)), "POSTED COMMENT PASS")
        self.assertIn("never approves", reviews_posted(gh)[0]["body"])

    def test_incomplete_file_list_never_approves(self):
        gh = FakeGitHub(changed_files=2)
        self.assertEqual(run(gh, Model(PASS)), "POSTED COMMENT PASS")

    def test_pending_or_missing_ci_waits_without_model_call(self):
        for ci in ("pending", "missing"):
            gh, model = FakeGitHub(ci=ci), Model()
            self.assertTrue(run(gh, model).startswith("WAIT ci"))
            self.assertEqual((model.prompts, gh.posted), ([], []))

    def test_red_ci_is_code_error_without_model_call(self):
        gh, model = FakeGitHub(ci="failure"), Model()
        self.assertTrue(run(gh, model).startswith("CODE_ERROR"))
        self.assertEqual(model.prompts, [])
        self.assertEqual(status_of(gh)["class"], "CODE_ERROR")

    def test_billing_annotation_is_ci_infra_error(self):
        gh = FakeGitHub(ci="failure", annotations=[{"message": "The job was not started because recent "
                                                    "account payments have failed or your spending limit"}])
        self.assertTrue(run(gh, Model()).startswith("CI_INFRA_ERROR"))

    def test_already_reviewed_head_is_done(self):
        prior = {"user": {"login": LOGIN}, "commit_id": HEAD,
                 "body": f"x <!-- ntk-review v1 head={HEAD} mode=approve verdict=PASS floor=0 -->"}
        gh, model = FakeGitHub(reviews=[prior]), Model()
        self.assertTrue(run(gh, model).startswith("DONE"))
        self.assertEqual(model.prompts, [])

    def test_stale_or_foreign_review_is_not_reused(self):
        stale = {"user": {"login": LOGIN}, "commit_id": NEW_HEAD,
                 "body": f"<!-- ntk-review v1 head={NEW_HEAD} mode=approve verdict=PASS floor=0 -->"}
        forged = {"user": {"login": "someone"}, "commit_id": HEAD,
                  "body": f"<!-- ntk-review v1 head={HEAD} mode=approve verdict=PASS floor=0 -->"}
        shadow = {"user": {"login": LOGIN}, "commit_id": HEAD,
                  "body": f"<!-- ntk-review v1 head={HEAD} mode=comment verdict=PASS floor=0 -->"}
        gh = FakeGitHub(reviews=[stale, forged, shadow])
        self.assertEqual(run(gh, Model(PASS)), "POSTED APPROVE PASS")

    def test_head_moved_before_posting_posts_nothing(self):
        gh = FakeGitHub(head_after=NEW_HEAD)
        self.assertEqual(run(gh, Model(PASS)), "SKIP head moved before posting")
        self.assertEqual(reviews_posted(gh), [])

    def test_oversize_diff_is_code_error_without_model_call(self):
        gh, model = FakeGitHub(diff="+" * (R.MAX_DIFF_BYTES + 1)), Model()
        self.assertTrue(run(gh, model).startswith("CODE_ERROR CHANGE_TOO_LARGE"))
        self.assertEqual(model.prompts, [])

    def test_no_required_checks_is_configuration_error(self):
        with self.assertRaises(R.Stop):
            run(FakeGitHub(rules=[]), Model())

    def test_capacity_errors_are_bounded_with_backoff(self):
        comments, now = [], 1_000_000.0
        for expected_calls, at in ((1, now), (1, now + 60), (2, now + 3700), (2, now + 3800),
                                   (3, now + 3700 + 14500), (3, now + 10**6)):
            gh = FakeGitHub(comments=comments)
            model = Model(("", "REVIEW_CAPACITY_ERROR", "RATE_LIMITED"))
            run(gh, model, now=at)
            if model.prompts:
                body = (gh.posted + gh.patched)[-1][1]["body"]
                comments = [{"id": 5, "user": {"login": LOGIN}, "body": body}]
            total = status_of(gh)["counts"]["REVIEW_CAPACITY_ERROR"] if model.prompts else None
            if model.prompts:
                self.assertEqual(total, expected_calls)
        self.assertEqual(json.loads(R.STATUS_MARK.search(comments[0]["body"]).group(1))
                         ["counts"]["REVIEW_CAPACITY_ERROR"], 3)

    def test_format_error_gets_one_repair_then_stops(self):
        gh = FakeGitHub()
        run(gh, Model("not json"))
        body = gh.posted[-1][1]["body"]
        comments = [{"id": 5, "user": {"login": LOGIN}, "body": body}]
        gh2, model2 = FakeGitHub(comments=comments), Model("still not json")
        run(gh2, model2)
        self.assertIn("rejected by the parser (NO_JSON_OBJECT)", model2.prompts[0])
        comments = [{"id": 5, "user": {"login": LOGIN}, "body": gh2.patched[-1][1]["body"]}]
        gh3, model3 = FakeGitHub(comments=comments), Model()
        self.assertTrue(run(gh3, model3).startswith("STOPPED REVIEW_FORMAT_ERROR"))
        self.assertEqual(model3.prompts, [])

    def test_new_head_resets_budget(self):
        status = {"head": NEW_HEAD, "counts": {"REVIEW_FORMAT_ERROR": 2}}
        body = f"x <!-- ntk-review-status v1 {json.dumps(status)} -->"
        gh = FakeGitHub(comments=[{"id": 5, "user": {"login": LOGIN}, "body": body}])
        self.assertEqual(run(gh, Model(PASS)), "POSTED APPROVE PASS")

    def test_status_comment_from_other_user_is_ignored(self):
        status = {"head": HEAD, "counts": {"REVIEW_FORMAT_ERROR": 2}}
        body = f"<!-- ntk-review-status v1 {json.dumps(status)} -->"
        gh = FakeGitHub(comments=[{"id": 5, "user": {"login": "ntk-ai"}, "body": body}])
        self.assertEqual(run(gh, Model(PASS)), "POSTED APPROVE PASS")

    def test_draft_and_fork_skipped(self):
        gh = FakeGitHub()
        self.assertEqual(R.review_pr(gh, "Tabibi", dict(gh.pr(), draft=True), login=LOGIN, mode="approve",
                                     run_model=Model(), calls=[0], now=0, run_url=""), "SKIP draft")
        fork = dict(gh.pr(), head={"sha": HEAD, "repo": {"full_name": "evil/Tabibi"}})
        self.assertEqual(R.review_pr(gh, "Tabibi", fork, login=LOGIN, mode="approve",
                                     run_model=Model(), calls=[0], now=0, run_url=""), "SKIP fork")

    def test_run_cap_defers(self):
        gh = FakeGitHub()
        out = R.review_pr(gh, "Tabibi", gh.pr(), login=LOGIN, mode="approve", run_model=Model(),
                          calls=[R.MAX_MODEL_CALLS_PER_RUN], now=0, run_url="")
        self.assertEqual(out, "DEFERRED run cap")


class RuntimeTests(unittest.TestCase):
    def tree(self, stop=False, cap=0):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        (root / ".onecompany").mkdir()
        (root / ".onecompany/config.json").write_text(json.dumps({"safety": {"emergency_stop": stop}}))
        (root / ".onecompany/budget.json").write_text(json.dumps({"ai": {
            "additional_monthly_spend_cap": cap, "allow_paid_fallback": False, "allow_overage": False,
            "allow_auto_topup": False, "allow_new_paid_vendor": False}}))
        self.addCleanup(tmp.cleanup)
        return root

    def env(self, **extra):
        base = {"PAYG_DISABLED_CONFIRMED": "true", "REVIEWER_LOGIN": LOGIN, "REVIEWER_REPOS": "Tabibi"}
        base.update(extra)
        return patch.dict(os.environ, base, clear=False)

    def test_emergency_stop_makes_no_calls(self):
        gh, model = FakeGitHub(), Model()
        with self.env():
            self.assertEqual(R.main(self.tree(stop=True), gh=gh, run_model=model, now=0), 0)
        self.assertEqual((gh.posted, model.prompts), ([], []))

    def test_spend_policy_and_payg_flag_required(self):
        with self.env():
            self.assertEqual(R.main(self.tree(cap=5), gh=FakeGitHub(), run_model=Model(), now=0), 1)
        with self.env(PAYG_DISABLED_CONFIRMED="false"):
            self.assertEqual(R.main(self.tree(), gh=FakeGitHub(), run_model=Model(), now=0), 1)

    def test_invalid_mode_falls_back_to_shadow(self):
        gh = FakeGitHub()
        with self.env(REVIEWER_MODE="APPROVE_ALL"):
            self.assertEqual(R.main(self.tree(), gh=gh, run_model=Model(PASS), now=0), 0)
        self.assertEqual(reviews_posted(gh)[0]["event"], "COMMENT")

    def test_only_filter_validated(self):
        with self.env(REVIEW_ONLY="Tabibi#7; rm -rf /"):
            self.assertEqual(R.main(self.tree(), gh=FakeGitHub(), run_model=Model(), now=0), 1)
        gh = FakeGitHub()
        with self.env(REVIEW_ONLY="Tabibi#8", REVIEWER_MODE="approve"):
            R.main(self.tree(), gh=gh, run_model=Model(), now=0)
        self.assertEqual(gh.posted, [])

    def test_global_stop_ends_run(self):
        def boom(prompt):
            raise R.Stop("CONFIGURATION_ERROR: Mistral rejected the credential", global_=True)
        gh = FakeGitHub()
        with self.env(REVIEWER_REPOS="Tabibi,Tabibi", REVIEWER_MODE="approve"):
            self.assertEqual(R.main(self.tree(), gh=gh, run_model=boom, now=0), 1)
        self.assertEqual(reviews_posted(gh), [])


if __name__ == "__main__":
    unittest.main()
