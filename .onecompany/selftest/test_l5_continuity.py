import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "l5_continuity", ROOT / "scripts" / "l5_continuity.py"
)
l5 = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(l5)


class L5ContinuityTests(unittest.TestCase):
    def test_only_same_repo_main_prs_count_toward_quota(self):
        pulls = [
            {
                "number": 5,
                "base": {"ref": "main"},
                "head": {"repo": {"full_name": "NTinkicht/OneCompany"}},
            },
            {
                "number": 6,
                "base": {"ref": "main"},
                "head": {"repo": {"full_name": "someone/fork"}},
            },
            {
                "number": 7,
                "base": {"ref": "release"},
                "head": {"repo": {"full_name": "NTinkicht/OneCompany"}},
            },
        ]
        self.assertEqual(
            l5.active_internal_prs("NTinkicht/OneCompany", "main", pulls), [5]
        )

    def test_human_only_ready_issue_is_never_selected(self):
        issues = [
            {
                "number": 4,
                "state": "open",
                "labels": [{"name": "l5-ready"}],
            },
            {
                "number": 2,
                "state": "open",
                "labels": [{"name": "l4-ready"}, {"name": "human-only"}],
            },
        ]
        selected = l5.eligible_issues(
            issues, {"l5-ready", "l4-ready"}, {"human-only"}
        )
        self.assertEqual([row["number"] for row in selected], [4])

    def test_unreviewed_mutation_mode_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "UNREVIEWED_MUTATION_MODE"):
            l5.plan(
                {
                    "mutation_mode": "AUTO_CREATE",
                    "repositories": [
                        {
                            "repository": "NTinkicht/OneCompany",
                            "target_open_prs": 2,
                        }
                    ],
                }
            )


if __name__ == "__main__":
    unittest.main()
