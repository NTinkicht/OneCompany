"""OC-P0-02 negative vectors for the WU / requirement / AC / portfolio traceability graph.

Each test copies the real control-plane documents into a temporary directory,
applies exactly one mutation and asserts the specific validator error, so the
rejections required by PRODUCT.md OC-P0-02 (unknown references, cycles,
duplicate WU) cannot silently regress.
"""
import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import planning_validate  # noqa: E402
import queue_validate  # noqa: E402

DOCUMENTS = (
    "planning.json", "portfolio.json", "requirements-catalog.json", "risk-register.json",
    "queue.json", "requirements.json", "risk.json",
)


class GraphFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.control = Path(self._tmp.name)
        for name in DOCUMENTS:
            shutil.copy(ROOT / ".onecompany" / name, self.control / name)
        for module in (planning_validate, queue_validate):
            patcher = mock.patch.object(module, "CONTROL", self.control)
            patcher.start()
            self.addCleanup(patcher.stop)

    def edit(self, name, mutate):
        path = self.control / name
        data = json.loads(path.read_text(encoding="utf-8"))
        mutate(data)
        path.write_text(json.dumps(data), encoding="utf-8")

    def work_unit(self, data, wu_id):
        return next(item for item in data["work_units"] if item["id"] == wu_id)

    def requirement(self, data, req_id):
        return next(item for item in data["requirements"] if item["id"] == req_id)

    def planning_errors(self):
        errors, _warnings = planning_validate.validate_documents()
        return errors

    def queue_result(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = queue_validate.main()
        return code, out.getvalue()


class BaselineTests(GraphFixture):
    def test_unmodified_control_plane_passes_both_validators(self):
        self.assertEqual(self.planning_errors(), [])
        code, output = self.queue_result()
        self.assertEqual(code, 0, output)


class QueueGraphVectors(GraphFixture):
    def assertQueueRejects(self, expected):
        code, output = self.queue_result()
        self.assertEqual(code, 1, output)
        self.assertIn(f"ERROR: {expected}", output)

    def test_duplicate_work_unit_id_is_rejected(self):
        def mutate(data):
            clone = dict(self.work_unit(data, "WU-PFC-001"))
            clone["status"] = "CANCELLED"
            data["work_units"].append(clone)
        self.edit("queue.json", mutate)
        self.assertQueueRejects("duplicate work unit id: WU-PFC-001")

    def test_unknown_dependency_is_rejected(self):
        self.edit("queue.json", lambda d: self.work_unit(d, "WU-MISTRAL-RECOVERY-001")["dependencies"].append("WU-GHOST-001"))
        self.assertQueueRejects("WU-MISTRAL-RECOVERY-001: missing dependency WU-GHOST-001")

    def test_self_dependency_is_rejected(self):
        self.edit("queue.json", lambda d: self.work_unit(d, "WU-PFC-001")["dependencies"].append("WU-PFC-001"))
        self.assertQueueRejects("WU-PFC-001: self-dependency is forbidden")

    def test_dependency_cycle_is_rejected(self):
        self.edit("queue.json", lambda d: self.work_unit(d, "WU-PFC-001")["dependencies"].append("WU-MISTRAL-RECOVERY-001"))
        self.assertQueueRejects("dependency cycle: WU-PFC-001 -> WU-MISTRAL-RECOVERY-001 -> WU-PFC-001")


class PlanningGraphVectors(GraphFixture):
    def assertPlanningRejects(self, expected):
        self.assertIn(expected, self.planning_errors())

    def test_unknown_requirement_id_on_active_work_is_rejected(self):
        self.edit("queue.json", lambda d: self.work_unit(d, "WU-PFC-001")["requirement_ids"].append("FR-999"))
        self.assertPlanningRejects("WU-PFC-001: unknown requirement_id FR-999")

    def test_unknown_planning_ref_on_active_work_is_rejected(self):
        self.edit("queue.json", lambda d: self.work_unit(d, "WU-PFC-001")["planning_refs"].append("EPIC-999"))
        self.assertPlanningRejects("WU-PFC-001: unknown planning_ref EPIC-999")

    def test_requirement_referencing_unknown_acceptance_criterion_is_rejected(self):
        self.edit("requirements-catalog.json", lambda d: self.requirement(d, "FR-002")["acceptance_criteria"].append("AC-999"))
        self.assertPlanningRejects("FR-002: references unknown acceptance criterion AC-999")

    def test_requirement_referencing_unknown_risk_is_rejected(self):
        self.edit("requirements-catalog.json", lambda d: self.requirement(d, "FR-002")["risk_ids"].append("RISK-999"))
        self.assertPlanningRejects("FR-002: references unknown planning risk RISK-999")

    def test_requirement_depending_on_unknown_requirement_is_rejected(self):
        self.edit("requirements-catalog.json", lambda d: self.requirement(d, "FR-002").update(depends_on=["FR-999"]))
        self.assertPlanningRejects("FR-002: depends_on unknown requirement FR-999")

    def test_requirement_self_dependency_is_rejected_once(self):
        self.edit("requirements-catalog.json", lambda d: self.requirement(d, "FR-002").update(depends_on=["FR-002"]))
        errors = self.planning_errors()
        self.assertIn("FR-002: self dependency is forbidden", errors)
        self.assertFalse([e for e in errors if e.startswith("requirement dependency cycle")], errors)

    def test_requirement_dependency_cycle_is_rejected(self):
        def mutate(data):
            self.requirement(data, "FR-001")["depends_on"] = ["FR-002"]
            self.requirement(data, "FR-002")["depends_on"] = ["FR-003"]
            self.requirement(data, "FR-003")["depends_on"] = ["FR-001"]
        self.edit("requirements-catalog.json", mutate)
        self.assertPlanningRejects("requirement dependency cycle: FR-001 -> FR-002 -> FR-003 -> FR-001")

    def test_acyclic_requirement_dependencies_are_accepted(self):
        def mutate(data):
            self.requirement(data, "FR-001")["depends_on"] = ["FR-002", "FR-003"]
            self.requirement(data, "FR-002")["depends_on"] = ["FR-003"]
        self.edit("requirements-catalog.json", mutate)
        self.assertEqual(self.planning_errors(), [])

    def test_duplicate_requirement_id_is_rejected(self):
        self.edit("requirements-catalog.json", lambda d: d["requirements"].append(dict(self.requirement(d, "FR-003"))))
        self.assertPlanningRejects("duplicate requirement id: FR-003")

    def test_duplicate_acceptance_criterion_id_is_rejected(self):
        self.edit("requirements-catalog.json", lambda d: d["acceptance_criteria"].append(dict(d["acceptance_criteria"][0])))
        self.assertPlanningRejects("duplicate acceptance criterion id: AC-001")

    def test_portfolio_hierarchy_cycle_is_rejected(self):
        self.edit("portfolio.json", lambda d: d["links"].append({"source": "CAP-001", "target": "OBJ-001", "relationship": "contains", "rationale": "cycle"}))
        self.assertPlanningRejects("portfolio hierarchy cycle: CAP-001 -> OBJ-001 -> EPIC-001 -> CAP-001")

    def test_portfolio_link_to_unknown_target_is_rejected(self):
        self.edit("portfolio.json", lambda d: d["links"].append({"source": "EPIC-001", "target": "FEAT-999", "relationship": "contains", "rationale": "ghost"}))
        self.assertPlanningRejects("portfolio link has unknown target 'FEAT-999'")



class CycleDetectionDepthTests(unittest.TestCase):
    """Deep but valid catalogs must validate; Python's recursion limit is no excuse to fail."""

    DEPTH = 5000

    def chain(self):
        return {f"FR-{i:05d}": [f"FR-{i + 1:05d}"] if i + 1 < self.DEPTH else [] for i in range(self.DEPTH)}

    def test_deep_acyclic_chain_is_accepted(self):
        self.assertGreater(self.DEPTH, sys.getrecursionlimit())
        self.assertEqual(planning_validate._cycle_errors(self.chain(), "requirement dependency"), [])

    def test_deep_cycle_is_reported_once_with_full_path(self):
        graph = self.chain()
        graph[f"FR-{self.DEPTH - 1:05d}"] = ["FR-00000"]
        errors = planning_validate._cycle_errors(graph, "requirement dependency")
        self.assertEqual(len(errors), 1, errors[:1])
        self.assertTrue(errors[0].startswith("requirement dependency cycle: FR-00000 -> FR-00001 -> "))
        self.assertTrue(errors[0].endswith(f"-> FR-{self.DEPTH - 1:05d} -> FR-00000"))

    def test_shared_descendant_is_not_a_cycle(self):
        graph = {"A": ["B", "C"], "B": ["D"], "C": ["D"], "D": []}
        self.assertEqual(planning_validate._cycle_errors(graph, "x"), [])

if __name__ == "__main__":
    unittest.main()
