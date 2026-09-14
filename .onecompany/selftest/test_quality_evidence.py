from __future__ import annotations

import ast
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import quality_evidence


class QualityEvidenceTests(unittest.TestCase):
    def test_product_source_filter_excludes_measurement_and_simulation_helpers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scripts = root / "scripts"
            scripts.mkdir()
            good = scripts / "worker.py"
            good.write_text("x = 1\n", encoding="utf-8")
            measurement = scripts / "quality_evidence.py"
            measurement.write_text("x = 1\n", encoding="utf-8")
            simulation = scripts / "simulate_demo.py"
            simulation.write_text("x = 1\n", encoding="utf-8")
            entry = root / "onecompany.py"
            entry.write_text("x = 1\n", encoding="utf-8")

            self.assertTrue(quality_evidence._is_product_source(good, root))
            self.assertTrue(quality_evidence._is_product_source(entry, root))
            self.assertFalse(quality_evidence._is_product_source(measurement, root))
            self.assertFalse(quality_evidence._is_product_source(simulation, root))

    def test_static_model_finds_lines_and_conditional_branch_edges(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scripts = root / "scripts"
            scripts.mkdir()
            sample = scripts / "sample.py"
            sample.write_text(
                "def choose(value):\n"
                "    if value:\n"
                "        return 1\n"
                "    return 0\n",
                encoding="utf-8",
            )
            lines, branches = quality_evidence._static_model(root)
            self.assertIn(("scripts/sample.py", 1), lines)
            self.assertIn(("scripts/sample.py", 2), lines)
            self.assertGreaterEqual(len(branches), 2)

    def test_single_mutator_flips_comparison(self):
        tree = ast.parse("def f(a, b):\n    return a == b\n")
        mutator = quality_evidence._SingleMutator(0)
        mutated = mutator.visit(tree)
        self.assertTrue(mutator.applied)
        compare = next(node for node in ast.walk(mutated) if isinstance(node, ast.Compare))
        self.assertIsInstance(compare.ops[0], ast.NotEq)

    def test_single_mutator_flips_boolean_operator(self):
        tree = ast.parse("def f(a, b):\n    return a and b\n")
        mutator = quality_evidence._SingleMutator(0)
        mutated = mutator.visit(tree)
        self.assertTrue(mutator.applied)
        boolean = next(node for node in ast.walk(mutated) if isinstance(node, ast.BoolOp))
        self.assertIsInstance(boolean.op, ast.Or)

    def test_bounded_mutation_candidates_round_robin_across_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = root / "a.py"
            b = root / "b.py"
            a.write_text("def f(x):\n    return x == 1 or x == 2\n", encoding="utf-8")
            b.write_text("def g(x):\n    return x != 3 and x != 4\n", encoding="utf-8")
            values = quality_evidence._bounded_mutation_candidates([a, b], 4)
            self.assertEqual(
                [path.name for path, _ in values], ["a.py", "b.py", "a.py", "b.py"]
            )

    def test_changed_line_parser_uses_added_hunks_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scripts = root / "scripts"
            scripts.mkdir()
            sample = scripts / "worker.py"
            sample.write_text("a = 1\nb = 2\nc = 3\nd = 4\n", encoding="utf-8")
            diff = (
                "diff --git a/scripts/worker.py b/scripts/worker.py\n"
                "--- a/scripts/worker.py\n"
                "+++ b/scripts/worker.py\n"
                "@@ -1,0 +2,2 @@\n"
                "+b = 2\n"
                "+c = 3\n"
            )
            with patch.object(quality_evidence, "_git_diff", return_value=diff):
                changed = quality_evidence._changed_lines(root, "a" * 40, "b" * 40)
            self.assertEqual(
                changed, {("scripts/worker.py", 2), ("scripts/worker.py", 3)}
            )

    def test_coverage_parent_only_aggregates_isolated_worker_observations(self):
        worker_payload = {
            "tests_successful": True,
            "tests_run": 1,
            "failures": 0,
            "errors": 0,
            "executed_lines": [["scripts/sample.py", 1]],
            "observed_edges": [],
            "test_output_tail": "ok",
        }
        completed = subprocess.CompletedProcess(
            args=["python"],
            returncode=0,
            stdout=quality_evidence.WORKER_MARKER + json.dumps(worker_payload) + "\n",
            stderr="",
        )
        with (
            patch.object(
                quality_evidence,
                "_static_model",
                return_value=({("scripts/sample.py", 1)}, set()),
            ),
            patch.object(quality_evidence.subprocess, "run", return_value=completed) as run,
            patch.object(
                quality_evidence,
                "_discover_suite",
                side_effect=AssertionError("candidate tests imported in trusted parent"),
            ),
        ):
            coverage, details = quality_evidence._coverage_measurement(ROOT)
        self.assertEqual(coverage["line"], 100.0)
        self.assertTrue(details["worker_process_isolated"])
        run.assert_called_once()

    def test_family_statuses_come_from_real_command_exit_codes(self):
        def fake_run(command, cwd, timeout=180):
            failed = "hardening-audit" in command
            return {
                "command": command,
                "returncode": 1 if failed else 0,
                "duration_seconds": 0.01,
                "stdout_tail": "",
                "stderr_tail": "",
            }

        with patch.object(quality_evidence, "_run", side_effect=fake_run):
            statuses, details = quality_evidence._family_results(ROOT)
        self.assertEqual(statuses["security"], "fail")
        self.assertEqual(statuses["static"], "pass")
        self.assertEqual(statuses["unit"], "pass")
        self.assertTrue(details["security"])

    def test_output_schema_contains_exact_head_and_base(self):
        with (
            patch.object(
                quality_evidence,
                "_coverage_measurement",
                return_value=({"line": 90.0, "branch": 85.0}, {"executed_lines": []}),
            ),
            patch.object(
                quality_evidence,
                "_changed_line_coverage",
                return_value=(
                    100.0,
                    {"changed_executable_lines": 0, "covered_changed_lines": 0},
                ),
            ),
            patch.object(
                quality_evidence,
                "_mutation_score",
                return_value=(
                    75.0,
                    {
                        "generated": 4,
                        "killed": 3,
                        "survived": 1,
                        "bounded_max": 30,
                        "survivors": [],
                    },
                ),
            ),
            patch.object(
                quality_evidence,
                "_family_results",
                return_value=({"static": "pass", "unit": "pass"}, {}),
            ),
        ):
            value = quality_evidence.produce(ROOT, "a" * 40, "b" * 40, 30)
        self.assertEqual(value["schema"], "onecompany-quality-evidence-v1")
        self.assertEqual(value["candidate_sha"], "a" * 40)
        self.assertEqual(value["base_sha"], "b" * 40)
        self.assertEqual(value["coverage"]["mutation"], 75.0)
        self.assertEqual(value["test_families"]["mutation"], "pass")


if __name__ == "__main__":
    unittest.main()
