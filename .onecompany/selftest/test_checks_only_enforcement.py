from __future__ import annotations

import base64
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import github_controls as controls


STRICT_CODEOWNERS = base64.b64encode(
    b"/.github/ @NTinkicht\n"
).decode("ascii")


REPO_ID = 4242

STRICT_SPECS = [{
    "name": "validate",
    "app_slug": "github-actions",
    "workflow_path": ".github/workflows/onecompany-validate.yml",
}]


class ChecksOnlyEnforcementTests(unittest.TestCase):
    """Require technical checks without manufacturing individual review gates."""

    def api(self, path: str):
        """Return representative branch-level and ruleset GitHub metadata."""
        if "/contents/.github/CODEOWNERS?" in path:
            return (
                0,
                {"encoding": "base64", "content": base64.b64encode(
                    b"/scripts/ @NTinkicht\n"
                ).decode("ascii")},
                "",
            )
        if "/codeowners/errors?" in path:
            return 0, {"errors": []}, ""
        if path.endswith("/protection"):
            return 1, None, "no classic protection"
        if path.endswith("/rulesets") or "/rulesets?" in path:
            return 0, [{"id": 1, "enforcement": "active"}], ""
        if path.endswith("/rulesets/1"):
            return 0, {
                "id": 1, "name": "checks-only",
                "enforcement": "active",
                "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"]}},
                "bypass_actors": [],
                "rules": [{
                    "type": "required_status_checks",
                    "parameters": {"required_status_checks": [
                        {"context": "validate"},
                    ]},
                }],
            }, ""
        raise AssertionError(path)

    def test_checks_only_does_not_enforce_independent_review(self):
        """Pass non-bypassable technical checks without a Code Owner rule."""
        with (
            patch.object(controls, "gh_api", side_effect=self.api),
            patch.object(
                controls, "_codeowners_coverage", return_value=(True, []),
            ),
        ):
            result = controls.inspect_enforcement(
                "example/app", "main", {"validate"},
            )
        self.assertTrue(result["codeowners_valid"])
        self.assertFalse(result["code_owner_review_enforced"])
        self.assertEqual(result["missing_required_checks"], [])
        self.assertFalse(result["review_gate_enforced"])
        self.assertFalse(result["enforcement_ok"])

    def test_pinned_review_app_status_check_enforces_independence(self):
        """Permit an independently vetted app, not a candidate-controlled name."""
        original = self.api
        def pinned_api(path):
            """Require the exact review App for the non-bypassable ruleset."""
            code, payload, error = original(path)
            if path.endswith("/rulesets/1"):
                payload["rules"][0]["parameters"]["required_status_checks"].append({
                    "context": controls.REVIEW_GATE_CONTEXT,
                    "integration_id": 117,
                })
            return code, payload, error
        with (
            patch.object(controls, "gh_api", side_effect=pinned_api),
            patch.object(controls, "_codeowners_coverage", return_value=(True, [])),
            patch.object(controls, "REVIEW_GATE_APP_ID", 117),
        ):
            result = controls.inspect_enforcement(
                "example/app", "main", {"validate"},
            )
        self.assertTrue(result["review_gate_enforced"])
        self.assertTrue(result["enforcement_ok"])

    def test_wrong_review_app_cannot_fake_attestation(self):
        """Reject status context published by the wrong GitHub integration."""
        original = self.api
        def foreign_api(path):
            """Return a same-named status check from an unauthorized app."""
            code, payload, error = original(path)
            if path.endswith("/rulesets/1"):
                payload["rules"][0]["parameters"]["required_status_checks"].append({
                    "context": controls.REVIEW_GATE_CONTEXT,
                    "integration_id": 999,
                })
            return code, payload, error
        with (
            patch.object(controls, "gh_api", side_effect=foreign_api),
            patch.object(controls, "_codeowners_coverage", return_value=(True, [])),
            patch.object(controls, "REVIEW_GATE_APP_ID", 117),
        ):
            result = controls.inspect_enforcement(
                "example/app", "main", {"validate"},
            )
        self.assertFalse(result["review_gate_enforced"])
        self.assertFalse(result["enforcement_ok"])

    def test_non_bypassable_classic_pinned_review_app(self):
        """Classic protection counts only a source-pinned, non-bypassable gate."""
        original = self.api
        expected = {
            "enforce_admins": {"enabled": True},
            "required_pull_request_reviews": {
                "bypass_pull_request_allowances": {
                    "users": [], "teams": [], "apps": [],
                },
                "require_code_owner_reviews": False,
            },
            "required_status_checks": {
                "contexts": ["validate"],
                "checks": [
                    {"context": controls.REVIEW_GATE_CONTEXT, "app_id": 117},
                ],
            },
        }
        def check(payload):
            def api(path):
                if path.endswith("/protection"):
                    return 0, payload, ""
                return original(path)
            with (
                patch.object(controls, "gh_api", side_effect=api),
                patch.object(controls, "_codeowners_coverage", return_value=(True, [])),
                patch.object(controls, "REVIEW_GATE_APP_ID", 117),
            ):
                return controls.inspect_enforcement(
                    "example/app", "main", {"validate"},
                )
        result = check(expected)
        self.assertTrue(result["review_gate_enforced"])
        self.assertTrue(result["enforcement_ok"])
        wrong = dict(expected)
        wrong["required_status_checks"] = {
            "contexts": ["validate", controls.REVIEW_GATE_CONTEXT],
            "checks": [{"context": controls.REVIEW_GATE_CONTEXT, "app_id": 999}],
        }
        self.assertFalse(check(wrong)["review_gate_enforced"])
        bypassable = dict(expected)
        bypassable["enforce_admins"] = {"enabled": False}
        self.assertFalse(check(bypassable)["review_gate_enforced"])

    def test_strict_merge_platform_ruleset_passes_only_with_publisher_and_fresh_review(self):
        def strict_api(path):
            if path == "apps/github-actions":
                return 0, {"id": 15368, "slug": "github-actions"}, ""
            if path == "repos/example/app":
                return 0, {"id": REPO_ID, "full_name": "example/app"}, ""
            if "/contents/.github/CODEOWNERS?ref=" in path:
                return 0, {"encoding": "base64", "content": STRICT_CODEOWNERS}, ""
            if path.endswith("/protection"):
                return 1, None, "no classic protection"
            if path.endswith("/rulesets") or "/rulesets?" in path:
                return 0, [{"id": 7, "enforcement": "active"}], ""
            if path.endswith("/rulesets/7"):
                return 0, {
                    "id": 7,
                    "enforcement": "active",
                    "target": "branch",
                    "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
                    "bypass_actors": [],
                    "rules": [
                        {
                            "type": "pull_request",
                            "parameters": {
                                "required_approving_review_count": 1,
                                "dismiss_stale_reviews_on_push": True,
                                "require_last_push_approval": True,
                                "required_review_thread_resolution": True,
                                "require_code_owner_review": True,
                            },
                        },
                        {"type": "deletion"},
                        {"type": "non_fast_forward"},
                    {
                        "type": "workflows",
                        "parameters": {
                            "workflows": [
                                {
                                    "path": ".github/workflows/onecompany-validate.yml",
                                    "repository_id": REPO_ID,
                                    "ref": "main",
                                },
                                {
                                    "path": controls.REVIEW_AUTH_WORKFLOW_PATH,
                                    "repository_id": REPO_ID,
                                    "ref": "main",
                                },
                            ],
                        },
                    },
                        {
                            "type": "required_status_checks",
                            "parameters": {
                                "strict_required_status_checks_policy": True,
                                "required_status_checks": [{
                                    "context": "validate",
                                    "integration_id": 15368,
                                }],
                            },
                        },
                    ],
                }, ""
            raise AssertionError(path)

        with patch.object(controls, "gh_api", side_effect=strict_api):
            self.assertTrue(
                controls.strict_merge_platform_enforcement(
                    "example/app", "main", STRICT_SPECS
                )
            )

    def test_strict_merge_platform_ruleset_rejects_bypass_stale_or_wrong_publisher(self):
        def make_api(*, bypass=False, strict=True, fresh=True, app_id=15368):
            def api(path):
                if path == "apps/github-actions":
                    return 0, {"id": 15368, "slug": "github-actions"}, ""
                if path == "repos/example/app":
                    return 0, {"id": REPO_ID, "full_name": "example/app"}, ""
                if "/contents/.github/CODEOWNERS?ref=" in path:
                    return 0, {"encoding": "base64", "content": STRICT_CODEOWNERS}, ""
                if path.endswith("/protection"):
                    return 1, None, "no classic protection"
                if path.endswith("/rulesets") or "/rulesets?" in path:
                    return 0, [{"id": 8, "enforcement": "active"}], ""
                if path.endswith("/rulesets/8"):
                    return 0, {
                        "id": 8,
                        "enforcement": "active",
                        "target": "branch",
                        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
                        "bypass_actors": ([{"actor_id": 1}] if bypass else []),
                        "rules": [
                            {
                                "type": "pull_request",
                                "parameters": {
                                    "required_approving_review_count": 1,
                                    "dismiss_stale_reviews_on_push": fresh,
                                    "require_last_push_approval": fresh,
                                    "required_review_thread_resolution": fresh,
                                    "require_code_owner_review": fresh,
                                },
                            },
                            {"type": "deletion"},
                            {"type": "non_fast_forward"},
                            {
                                "type": "workflows",
                                "parameters": {
                                    "workflows": [
                                        {
                                            "path": ".github/workflows/onecompany-validate.yml",
                                            "repository_id": REPO_ID,
                                            "ref": "main",
                                        },
                                        {
                                            "path": controls.REVIEW_AUTH_WORKFLOW_PATH,
                                            "repository_id": REPO_ID,
                                            "ref": "main",
                                        },
                                    ],
                                },
                            },
                            {
                                "type": "required_status_checks",
                                "parameters": {
                                    "strict_required_status_checks_policy": strict,
                                    "required_status_checks": [{
                                        "context": "validate",
                                        "integration_id": app_id,
                                    }],
                                },
                            },
                        ],
                    }, ""
                raise AssertionError(path)
            return api

        cases = (
            {"bypass": True},
            {"strict": False},
            {"fresh": False},
            {"app_id": 999},
        )
        for kwargs in cases:
            with self.subTest(**kwargs):
                with patch.object(controls, "gh_api", side_effect=make_api(**kwargs)):
                    self.assertFalse(
                        controls.strict_merge_platform_enforcement(
                            "example/app", "main", STRICT_SPECS
                        )
                    )

    def test_strict_merge_platform_aggregates_non_bypassable_rulesets(self):
        details = {
            11: {
                "id": 11,
                "enforcement": "active",
                "target": "branch",
                "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
                "bypass_actors": [],
                "rules": [{
                    "type": "pull_request",
                    "parameters": {
                        "required_approving_review_count": 1,
                        "dismiss_stale_reviews_on_push": True,
                        "require_last_push_approval": True,
                        "required_review_thread_resolution": True,
                        "require_code_owner_review": True,
                    },
                }],
            },
            12: {
                "id": 12,
                "enforcement": "active",
                "target": "branch",
                "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
                "bypass_actors": [],
                "rules": [
                    {"type": "deletion"},
                    {"type": "non_fast_forward"},
                    {
                        "type": "workflows",
                        "parameters": {
                            "workflows": [
                                {
                                    "path": ".github/workflows/onecompany-validate.yml",
                                    "repository_id": REPO_ID,
                                    "ref": "main",
                                },
                                {
                                    "path": controls.REVIEW_AUTH_WORKFLOW_PATH,
                                    "repository_id": REPO_ID,
                                    "ref": "main",
                                },
                            ],
                        },
                    },
                    {
                        "type": "required_status_checks",
                        "parameters": {
                            "strict_required_status_checks_policy": True,
                            "required_status_checks": [{
                                "context": "validate",
                                "integration_id": 15368,
                            }],
                        },
                    },
                ],
            },
        }

        def api(path):
            if path == "apps/github-actions":
                return 0, {"id": 15368, "slug": "github-actions"}, ""
            if path == "repos/example/app":
                return 0, {"id": REPO_ID, "full_name": "example/app"}, ""
            if "/contents/.github/CODEOWNERS?ref=" in path:
                return 0, {"encoding": "base64", "content": STRICT_CODEOWNERS}, ""
            if path.endswith("/protection"):
                return 1, None, "no classic protection"
            if path.endswith("/rulesets") or "/rulesets?" in path:
                return 0, [
                    {"id": 11, "enforcement": "active"},
                    {"id": 12, "enforcement": "active"},
                ], ""
            for ruleset_id, detail in details.items():
                if path.endswith(f"/rulesets/{ruleset_id}"):
                    return 0, detail, ""
            raise AssertionError(path)

        with patch.object(controls, "gh_api", side_effect=api):
            self.assertTrue(
                controls.strict_merge_platform_enforcement(
                    "example/app", "main", STRICT_SPECS
                )
            )

    def test_missing_required_check_is_a_blocker_even_without_review_gate(self):
        """Keep exact-head status checks mechanically required."""
        with (
            patch.object(controls, "gh_api", side_effect=self.api),
            patch.object(
                controls, "_codeowners_coverage", return_value=(True, []),
            ),
        ):
            result = controls.inspect_enforcement(
                "example/app", "main", {"validate", "security-scan"},
            )
        self.assertFalse(result["enforcement_ok"])
        self.assertEqual(result["missing_required_checks"], ["security-scan"])


if __name__ == "__main__":
    unittest.main()
