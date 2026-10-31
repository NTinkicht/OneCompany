"""OC-P0-01 (#383): raw GitHub branch rules -> the report's required checks, fail closed."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # shared #379/#381 fixtures

from github_pr_observation import pr_observation  # noqa: E402
from github_required_check_observation import (  # noqa: E402
    InvalidPayload,
    required_check_observation,
)
from github_work_observation import work_observation  # noqa: E402
from live_reconciliation_report import build_report, load_snapshot  # noqa: E402
from test_github_pr_observation import NOW, gh_run, inputs, pull  # noqa: E402
from test_github_work_observation import args, document, ref  # noqa: E402

ACTIONS = 15368
OTHER_APP = 9001
SLUGS = {ACTIONS: "github-actions", OTHER_APP: "other-ci"}


def rule(*checks, kind="required_status_checks", ruleset=1):
    return {"type": kind, "ruleset_source_type": "Repository",
            "ruleset_source": "NTinkicht/OneCompany", "ruleset_id": ruleset,
            "parameters": {"strict_required_status_checks_policy": True,
                           "do_not_enforce_on_create": False,
                           "required_status_checks": list(checks)}}


def check(context, integration=ACTIONS):
    return {"context": context, "integration_id": integration}


def other_rule(kind):
    return {"type": kind, "ruleset_source_type": "Repository",
            "ruleset_source": "NTinkicht/OneCompany", "ruleset_id": 1}


def rules():
    return [[other_rule("deletion"), rule(check("validate")),
             {"type": "pull_request", "parameters": {"required_approving_review_count": 1}}],
            [rule(check("lint"), check("validate"), ruleset=2), other_rule("non_fast_forward")]]


def observe(pages=None, complete=True, slugs=None):
    return required_check_observation(rules() if pages is None else pages,
                                      rules_complete=complete,
                                      app_slugs=SLUGS if slugs is None else slugs)


def report(required, pr_inputs=None):
    record = pr_observation(pull(), **(pr_inputs or inputs()))
    data = document(work_observation(ref(), **args()), record)
    data["required_checks"] = required
    return build_report(data, NOW)


class MappingTests(unittest.TestCase):
    def test_maps_exact_fields_deterministically(self):
        required = observe()
        self.assertEqual([{"name": "lint", "app": "github-actions"},
                          {"name": "validate", "app": "github-actions"}], required)
        self.assertEqual(required, observe())

    def test_other_rule_types_are_ignored(self):
        self.assertEqual([], observe([[other_rule("deletion"), other_rule("code_coverage")]]))

    def test_end_to_end_report_is_consistent(self):
        record = pr_observation(pull(), **inputs())
        data = document(work_observation(ref(), **args()), record)
        data["required_checks"] = observe()
        load_snapshot(data)
        self.assertEqual("CONSISTENT", build_report(data, NOW)["status"])

    def test_findings_still_reach_the_report(self):
        only_validate = dict(inputs(), check_run_pages=[
            {"total_count": 1, "check_runs": [gh_run(11, "validate")]}])
        foreign = dict(inputs(), check_run_pages=[
            {"total_count": 3, "check_runs": [gh_run(11, "validate"), gh_run(12, "lint"),
                                              gh_run(13, "lint", slug="other-ci")]}])
        cases = {
            "required check missing on the head": (
                observe(), only_validate, [[9, "lint", "MISSING_REQUIRED_CHECK"]]),
            "no required_status_checks rule": (
                observe([[other_rule("deletion")]]), inputs(), [[9, "", "NO_REQUIRED_CHECKS"]]),
            "required check posted by another app": (
                observe(), foreign, [[9, "lint", "FOREIGN_APP_CHECK"]]),
            "requirement bound to another app": (
                observe([[rule(check("validate"), check("lint", OTHER_APP))]]), inputs(),
                [[9, "lint", "FOREIGN_APP_CHECK"], [9, "lint", "MISSING_REQUIRED_CHECK"]]),
        }
        for label, (required, pr_inputs, expected) in cases.items():
            with self.subTest(label):
                result = report(required, pr_inputs)
                self.assertEqual("INCONSISTENT", result["status"])
                self.assertEqual(expected, result["findings"]["required_checks"])

    def test_refuses_malformed_incomplete_or_unbound_rules(self):
        def single(*checks):
            return [[rule(*checks)]]

        bad_params = rule(check("validate"))
        bad_params["parameters"]["required_status_checks"] = {"context": "validate"}
        cases = {
            "rules not paged to the end": (rules(), False, SLUGS),
            "truthy completeness": (rules(), 1, SLUGS),
            "pages not a list": ({"rules": []}, True, SLUGS),
            "page not a list": ([{"type": "deletion"}], True, SLUGS),
            "rule without a type": ([[{"parameters": {}}]], True, SLUGS),
            "rule not an object": ([["required_status_checks"]], True, SLUGS),
            "required rule without parameters": (
                [[other_rule("required_status_checks")]], True, SLUGS),
            "required checks not a list": ([[bad_params]], True, SLUGS),
            "any app may post the context": (single({"context": "validate"}), True, SLUGS),
            "null integration id": (single(check("validate", None)), True, SLUGS),
            "boolean integration id": (single(check("validate", True)), True, SLUGS),
            "zero integration id": (single(check("validate", 0)), True, SLUGS),
            "string integration id": (single(check("validate", "15368")), True, SLUGS),
            "unmapped integration id": (single(check("validate", 42)), True, SLUGS),
            "empty context": (single(check("")), True, SLUGS),
            "missing context": (single({"integration_id": ACTIONS}), True, SLUGS),
            "check not an object": (single("validate"), True, SLUGS),
            "same context, two apps": (
                [[rule(check("lint"))], [rule(check("lint", OTHER_APP), ruleset=2)]], True, SLUGS),
            "app_slugs not a dict": (rules(), True, [(ACTIONS, "github-actions")]),
            "app_slugs boolean key": (rules(), True, {True: "github-actions"}),
            "app_slugs empty slug": (rules(), True, {ACTIONS: ""}),
        }
        for label, (pages, complete, slugs) in cases.items():
            with self.subTest(label):
                with self.assertRaises(InvalidPayload):
                    required_check_observation(copy.deepcopy(pages), rules_complete=complete,
                                               app_slugs=slugs)

    def test_error_names_path_not_value(self):
        secret = "ghp_" + "x" * 36
        with self.assertRaises(InvalidPayload) as caught:
            observe([[rule(check("validate", secret))]])
        self.assertNotIn(secret, str(caught.exception))
        self.assertEqual("invalid rules[0].parameters.required_status_checks[0].integration_id",
                         str(caught.exception))
        with self.assertRaises(InvalidPayload) as caught:
            observe([[rule({"context": secret})]])
        self.assertNotIn(secret, str(caught.exception))
        self.assertEqual(
            "unbound app rules[0].parameters.required_status_checks[0].integration_id",
            str(caught.exception))


if __name__ == "__main__":
    unittest.main()
