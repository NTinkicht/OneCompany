from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from execution_core import (
    AgentRuntimeAdapter,
    CommandRuntimeAdapter,
    CompletionGate,
    CompletionVerdict,
    EvidenceItem,
    EvidenceRegistry,
    ExecutionJournal,
    ExecutionStore,
    ExecutionSupervisor,
    InvalidTransitionError,
    JournalIntegrityError,
    ObjectiveTracker,
    ProgressSentinel,
    ResourceBudget,
    ResourceGuard,
    RunContext,
    RunKey,
    RunStatus,
    RuntimeRequest,
    StaleGenerationError,
    TaskBoard,
    TaskItem,
    TaskStatus,
    TransitionEngine,
    WorkerProfile,
    WorkerTier,
    rank_worker_profiles,
)


class ExecutionCoreTests(unittest.TestCase):
    def context(self, **budget):
        return RunContext.new(
            "WU-EC-1",
            "Implement bounded execution",
            {"AC1": "state persists", "AC2": "completion is evidence driven"},
            ResourceBudget(**budget),
            run_id="run-1",
        )

    def test_generation_fence_rejects_late_worker(self):
        context = self.context()
        stale = context.key
        new_key = ObjectiveTracker.edit(context, context.key, objective="Revised objective")
        self.assertEqual(new_key.generation, 2)
        with self.assertRaises(StaleGenerationError):
            TaskBoard.upsert(context, stale, TaskItem("T1", "late mutation"))

    def test_evidence_driven_completion(self):
        context = self.context()
        TaskBoard.upsert(context, context.key, TaskItem("T1", "implementation"))
        TaskBoard.set_status(context, context.key, "T1", TaskStatus.DONE)
        EvidenceRegistry.add(context, context.key, EvidenceItem("E1", "test", "test:state", ["AC1"], True))
        EvidenceRegistry.add(context, context.key, EvidenceItem("E2", "ci", "run:2", ["AC2"], True))
        preflight = CompletionGate.record_worker_claim(context, context.key, "done")
        self.assertEqual(preflight.verdict, CompletionVerdict.MET)
        CompletionGate.apply_evaluator_verdict(
            context,
            context.key,
            CompletionVerdict.MET,
            confidence=0.98,
            notes="verified",
            cited_evidence=["E1", "E2"],
        )
        self.assertEqual(context.status, RunStatus.COMPLETE)

    def test_worker_claim_is_not_authoritative_evidence(self):
        context = self.context()
        EvidenceRegistry.add(context, context.key, EvidenceItem("E1", "claim", "worker:says-done", ["AC1", "AC2"], False))
        preflight = CompletionGate.record_worker_claim(context, context.key, "done")
        self.assertEqual(preflight.verdict, CompletionVerdict.CONTINUE)
        with self.assertRaises(InvalidTransitionError):
            CompletionGate.apply_evaluator_verdict(
                context,
                context.key,
                CompletionVerdict.MET,
                confidence=1,
                notes="unsupported",
                cited_evidence=["E1"],
            )

    def test_stall_detection_uses_substantive_fingerprint(self):
        context = self.context(max_unchanged_cycles=2)
        fingerprint = ProgressSentinel.fingerprint(
            head_sha="abc",
            unmet_acceptance_criteria=["AC1"],
            test_state={"unit": "failing"},
        )
        self.assertFalse(ProgressSentinel.observe(context, context.key, fingerprint))
        self.assertFalse(ProgressSentinel.observe(context, context.key, fingerprint))
        self.assertTrue(ProgressSentinel.observe(context, context.key, fingerprint))
        decision = ExecutionSupervisor.assess(context)
        self.assertEqual(decision.action, "RECONCILE_OR_FAILOVER")
        self.assertTrue(decision.requires_new_generation)

    def test_material_progress_resets_stall_and_error_counters(self):
        context = self.context(max_unchanged_cycles=3)
        context.consecutive_errors = 2
        first = ProgressSentinel.fingerprint(head_sha="a", unmet_acceptance_criteria=["AC1"])
        second = ProgressSentinel.fingerprint(head_sha="b", unmet_acceptance_criteria=[])
        ProgressSentinel.observe(context, context.key, first)
        ProgressSentinel.observe(context, context.key, first)
        ProgressSentinel.observe(context, context.key, second)
        self.assertEqual(context.unchanged_cycles, 0)
        self.assertEqual(context.consecutive_errors, 0)

    def test_resource_guard_enforces_token_budget(self):
        context = self.context(max_assistant_tokens=10)
        self.assertTrue(ResourceGuard.record_usage(context, context.key, assistant_tokens=9).allowed)
        decision = ResourceGuard.record_usage(context, context.key, assistant_tokens=1)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "assistant_token_budget_exhausted")
        self.assertEqual(ExecutionSupervisor.assess(context).action, "PAUSE_BUDGET")

    def test_transition_engine_does_not_mutate_input(self):
        context = self.context()
        result = TransitionEngine.transition(context, context.key, "pause", now=123)
        self.assertEqual(context.status, RunStatus.ACTIVE)
        self.assertEqual(result.context.status, RunStatus.PAUSED)
        self.assertEqual(result.context.updated_at, 123)

    def test_store_roundtrip_and_hash_chained_journal(self):
        context = self.context()
        with tempfile.TemporaryDirectory() as directory:
            store = ExecutionStore(Path(directory))
            store.persist_event(context, "created", {"source": "test"})
            TaskBoard.upsert(context, context.key, TaskItem("T1", "work"))
            store.persist_event(context, "task_updated", {"task": "T1"})
            loaded = store.load(context.key.wu_id)
            self.assertEqual(loaded.key, context.key)
            records = ExecutionJournal.verify(store.journal_path(context.key.wu_id))
            self.assertEqual(len(records), 2)
            self.assertEqual(records[1]["previous_hash"], records[0]["record_hash"])

    def test_journal_tampering_fails_closed(self):
        context = self.context()
        with tempfile.TemporaryDirectory() as directory:
            store = ExecutionStore(Path(directory))
            store.persist_event(context, "created")
            path = store.journal_path(context.key.wu_id)
            record = json.loads(path.read_text(encoding="utf-8"))
            record["details"] = {"tampered": True}
            path.write_text(json.dumps(record) + "\n", encoding="utf-8")
            with self.assertRaises(JournalIntegrityError):
                ExecutionJournal.verify(path)

    def test_worker_profile_ranking_matches_complexity(self):
        profiles = [
            WorkerProfile.from_dict({
                "actor_id": "small",
                "roles": ["implementation"],
                "tiers": {"implementation": "light"},
                "preferred_complexity": ["light"],
                "cost_class": "FREE_ALLOWANCE",
            }),
            WorkerProfile.from_dict({
                "actor_id": "strong",
                "roles": ["implementation"],
                "tiers": {"implementation": "heavy"},
                "preferred_complexity": ["heavy"],
                "cost_class": "INCLUDED_SUBSCRIPTION",
            }),
        ]
        ranked = rank_worker_profiles(
            profiles,
            role="implementation",
            complexity=WorkerTier.HEAVY,
            allowed_cost_classes={"FREE_ALLOWANCE", "INCLUDED_SUBSCRIPTION"},
        )
        self.assertEqual([item.actor_id for item in ranked], ["strong", "small"])

    def test_external_runtime_adapter_uses_json_stdin_and_no_shell(self):
        with tempfile.TemporaryDirectory() as directory:
            worker = Path(directory) / "worker.py"
            worker.write_text(
                "import json,sys\n"
                "d=json.load(sys.stdin)\n"
                "print(json.dumps({'role':d['role'],'g':d['run_key']['generation']}))\n",
                encoding="utf-8",
            )
            adapter: AgentRuntimeAdapter = CommandRuntimeAdapter([sys.executable, str(worker)])
            result = adapter.execute(
                RuntimeRequest(RunKey("WU-1", "r", 2), "objective", "review", {"x": 1}),
                timeout_seconds=5,
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual(json.loads(result.stdout), {"role": "review", "g": 2})

    def test_decision_evidence_dead_end_lessons_are_bounded(self):
        context = self.context()
        for index in range(25):
            EvidenceRegistry.add_lesson(context, context.key, "decision", f"d{index}")
        self.assertEqual(len(context.lessons), 20)
        self.assertEqual(context.lessons[0].text, "d5")


if __name__ == "__main__":
    unittest.main()
