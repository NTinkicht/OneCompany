from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
from argparse import Namespace
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import execution as execution_cli
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
    """Regression tests for bounded execution integrity and governance."""

    def context(self, **budget):
        """Build a deterministic test execution context."""
        return RunContext.new(
            "WU-EC-1",
            "Implement bounded execution",
            {
                "AC1": "state persists",
                "AC2": "completion is evidence driven",
            },
            ResourceBudget(**budget),
            run_id="run-1",
        )

    def test_generation_fence_rejects_late_worker(self):
        """Reject an old generation after objective revision."""
        context = self.context()
        stale = context.key
        new_key = ObjectiveTracker.edit(
            context,
            context.key,
            objective="Revised objective",
        )
        self.assertEqual(new_key.generation, 2)
        with self.assertRaises(StaleGenerationError):
            TaskBoard.upsert(
                context,
                stale,
                TaskItem("T1", "late mutation"),
            )

    def test_cli_requires_and_enforces_caller_run_key(self):
        """Require public CLI callers to supply the exact run identity."""
        parser = execution_cli.build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(
                [
                    "task-add",
                    "--wu",
                    "WU-EC-1",
                    "--task-id",
                    "T1",
                    "--description",
                    "work",
                ]
            )

        with tempfile.TemporaryDirectory() as directory:
            store = ExecutionStore(Path(directory))
            context = self.context()
            store.persist_event(context, "created")
            ObjectiveTracker.edit(
                context,
                context.key,
                objective="generation two",
            )
            store.persist_event(context, "revised")
            args = Namespace(
                runtime_root=directory,
                wu=context.key.wu_id,
                run_id=context.key.run_id,
                generation=1,
                task_id="late",
                description="stale worker",
                status=TaskStatus.PENDING.value,
            )
            with self.assertRaises(StaleGenerationError):
                execution_cli.cmd_task_add(args)

    def test_evidence_driven_completion(self):
        """Complete only when tasks and authoritative AC evidence are met."""
        context = self.context()
        TaskBoard.upsert(
            context,
            context.key,
            TaskItem("T1", "implementation"),
        )
        TaskBoard.set_status(
            context, context.key, "T1", TaskStatus.DONE
        )
        EvidenceRegistry.add(
            context,
            context.key,
            EvidenceItem(
                "E1", "test", "test:state", ["AC1"], True
            ),
        )
        EvidenceRegistry.add(
            context,
            context.key,
            EvidenceItem("E2", "ci", "run:2", ["AC2"], True),
        )
        preflight = CompletionGate.record_worker_claim(
            context, context.key, "done"
        )
        self.assertEqual(
            preflight.verdict, CompletionVerdict.MET
        )
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
        """Do not treat a worker completion statement as proof."""
        context = self.context()
        EvidenceRegistry.add(
            context,
            context.key,
            EvidenceItem(
                "E1",
                "claim",
                "worker:says-done",
                ["AC1", "AC2"],
                False,
            ),
        )
        preflight = CompletionGate.record_worker_claim(
            context, context.key, "done"
        )
        self.assertEqual(
            preflight.verdict, CompletionVerdict.CONTINUE
        )
        with self.assertRaises(InvalidTransitionError):
            CompletionGate.apply_evaluator_verdict(
                context,
                context.key,
                CompletionVerdict.MET,
                confidence=1,
                notes="unsupported",
                cited_evidence=["E1"],
            )

    def test_complete_run_is_terminal_for_transitions_and_tasks(self):
        """Prevent completed executions from reopening or mutating tasks."""
        context = self.context()
        TaskBoard.upsert(
            context, context.key, TaskItem("T1", "done task")
        )
        context.status = RunStatus.COMPLETE
        with self.assertRaises(InvalidTransitionError):
            TransitionEngine.transition(
                context,
                context.key,
                "block",
                now=1,
                payload={"reason": "late"},
            )
        with self.assertRaises(InvalidTransitionError):
            TransitionEngine.transition(
                context,
                context.key,
                "budget_limit",
                now=1,
            )
        with self.assertRaises(InvalidTransitionError):
            TaskBoard.set_status(
                context,
                context.key,
                "T1",
                TaskStatus.DONE,
            )

    def test_stall_detection_uses_substantive_fingerprint(self):
        """Trip stall detection only after repeated unchanged facts."""
        context = self.context(max_unchanged_cycles=2)
        fingerprint = ProgressSentinel.fingerprint(
            head_sha="abc",
            unmet_acceptance_criteria=["AC1"],
            test_state={"unit": "failing"},
        )
        self.assertFalse(
            ProgressSentinel.observe(
                context, context.key, fingerprint
            )
        )
        self.assertFalse(
            ProgressSentinel.observe(
                context, context.key, fingerprint
            )
        )
        self.assertTrue(
            ProgressSentinel.observe(
                context, context.key, fingerprint
            )
        )
        decision = ExecutionSupervisor.assess(context)
        self.assertEqual(
            decision.action, "RECONCILE_OR_FAILOVER"
        )
        self.assertTrue(decision.requires_new_generation)

    def test_material_progress_resets_stall_and_error_counters(self):
        """Reset stall/error counters after substantive progress."""
        context = self.context(max_unchanged_cycles=3)
        context.consecutive_errors = 2
        first = ProgressSentinel.fingerprint(
            head_sha="a",
            unmet_acceptance_criteria=["AC1"],
        )
        second = ProgressSentinel.fingerprint(
            head_sha="b", unmet_acceptance_criteria=[]
        )
        ProgressSentinel.observe(context, context.key, first)
        ProgressSentinel.observe(context, context.key, first)
        ProgressSentinel.observe(context, context.key, second)
        self.assertEqual(context.unchanged_cycles, 0)
        self.assertEqual(context.consecutive_errors, 0)

    def test_resource_guard_enforces_non_runnable_state(self):
        """Persist guard exhaustion and block later evidence/completion."""
        context = self.context(max_assistant_tokens=10)
        self.assertTrue(
            ResourceGuard.record_usage(
                context,
                context.key,
                assistant_tokens=9,
            ).allowed
        )
        decision = ResourceGuard.record_usage(
            context, context.key, assistant_tokens=1
        )
        self.assertFalse(decision.allowed)
        ResourceGuard.enforce(
            context, context.key, decision
        )
        self.assertEqual(
            context.status, RunStatus.BUDGET_LIMITED
        )
        self.assertEqual(
            decision.reason, "assistant_token_budget_exhausted"
        )
        self.assertEqual(
            ExecutionSupervisor.assess(context).action,
            "PAUSE_BUDGET",
        )
        with self.assertRaises(InvalidTransitionError):
            EvidenceRegistry.add(
                context,
                context.key,
                EvidenceItem(
                    "E1", "test", "late", ["AC1"], True
                ),
            )
        with self.assertRaises(InvalidTransitionError):
            CompletionGate.record_worker_claim(
                context, context.key, "late done"
            )

    def test_transition_engine_does_not_mutate_input(self):
        """Keep the deterministic transition engine copy-based."""
        context = self.context()
        result = TransitionEngine.transition(
            context, context.key, "pause", now=123
        )
        self.assertEqual(context.status, RunStatus.ACTIVE)
        self.assertEqual(
            result.context.status, RunStatus.PAUSED
        )
        self.assertEqual(result.context.updated_at, 123)

    def test_store_roundtrip_and_hash_chained_journal(self):
        """Persist state and verify a monotonic hash-chained journal."""
        context = self.context()
        with tempfile.TemporaryDirectory() as directory:
            store = ExecutionStore(Path(directory))
            store.persist_event(
                context, "created", {"source": "test"}
            )
            TaskBoard.upsert(
                context,
                context.key,
                TaskItem("T1", "work"),
            )
            store.persist_event(
                context, "task_updated", {"task": "T1"}
            )
            loaded = store.load(context.key.wu_id)
            self.assertEqual(loaded.key, context.key)
            records = ExecutionJournal.verify(
                store.journal_path(context.key.wu_id)
            )
            self.assertEqual(len(records), 2)
            self.assertEqual(
                records[1]["previous_hash"],
                records[0]["record_hash"],
            )

    def test_journal_appends_are_serialized(self):
        """Serialize concurrent sequence/hash assignment per work unit."""
        context = self.context()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "WU-EC-1.events.jsonl"

            def append(index: int) -> None:
                ExecutionJournal.append(
                    path,
                    event_type=f"event-{index}",
                    context=context,
                    details={"index": index},
                )

            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(append, range(20)))
            records = ExecutionJournal.verify(path)
            self.assertEqual(
                [record["sequence"] for record in records],
                list(range(1, 21)),
            )
            self.assertEqual(
                len(
                    {
                        record["operation_id"]
                        for record in records
                    }
                ),
                20,
            )

    def test_store_recovers_failed_journal_append(self):
        """Recover a state write interrupted before journal commit."""
        context = self.context()
        with tempfile.TemporaryDirectory() as directory:
            store = ExecutionStore(Path(directory))
            original = ExecutionJournal.append

            with patch.object(
                ExecutionJournal,
                "append",
                side_effect=OSError("simulated append failure"),
            ):
                with self.assertRaises(OSError):
                    store.persist_event(context, "created")
            self.assertTrue(
                store.pending_path(context.key.wu_id).exists()
            )

            with patch.object(
                ExecutionJournal,
                "append",
                wraps=original,
            ):
                loaded = store.load(context.key.wu_id)
            self.assertEqual(loaded.key, context.key)
            self.assertFalse(
                store.pending_path(context.key.wu_id).exists()
            )
            records = ExecutionJournal.verify(
                store.journal_path(context.key.wu_id)
            )
            self.assertEqual(len(records), 1)
            self.assertEqual(
                records[0]["event_type"], "created"
            )

    def test_load_rejects_state_without_matching_journal(self):
        """Reject unjournaled state when no recovery marker exists."""
        context = self.context()
        with tempfile.TemporaryDirectory() as directory:
            store = ExecutionStore(Path(directory))
            store.persist_event(context, "created")
            state_path = store.state_path(context.key.wu_id)
            tampered = json.loads(
                state_path.read_text(encoding="utf-8")
            )
            tampered["objective"] = "unjournaled mutation"
            state_path.write_text(
                json.dumps(tampered) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(JournalIntegrityError):
                store.load(context.key.wu_id)

    def test_concurrent_read_modify_write_preserves_both_updates(self):
        """Hold the per-WU lock across each full read-modify-write cycle."""
        context = self.context()
        with tempfile.TemporaryDirectory() as directory:
            store = ExecutionStore(Path(directory))
            store.persist_event(context, "created")
            started = threading.Event()

            def mutate(task_id: str, delay: float) -> None:
                with store.lock(context.key.wu_id):
                    loaded = store.load(
                        context.key.wu_id,
                        lock_held=True,
                    )
                    started.set()
                    time.sleep(delay)
                    TaskBoard.upsert(
                        loaded,
                        loaded.key,
                        TaskItem(task_id, task_id),
                    )
                    store.persist_event(
                        loaded,
                        "task_updated",
                        {"task": task_id},
                        lock_held=True,
                    )

            first = threading.Thread(
                target=mutate, args=("T1", 0.05)
            )
            second = threading.Thread(
                target=mutate, args=("T2", 0.0)
            )
            first.start()
            started.wait(timeout=2)
            second.start()
            first.join(timeout=3)
            second.join(timeout=3)
            self.assertFalse(first.is_alive())
            self.assertFalse(second.is_alive())
            loaded = store.load(context.key.wu_id)
            self.assertEqual(
                set(loaded.tasks), {"T1", "T2"}
            )

    def test_journal_tampering_fails_closed(self):
        """Reject modified journal details that no longer match hashes."""
        context = self.context()
        with tempfile.TemporaryDirectory() as directory:
            store = ExecutionStore(Path(directory))
            store.persist_event(context, "created")
            path = store.journal_path(context.key.wu_id)
            record = json.loads(
                path.read_text(encoding="utf-8")
            )
            record["details"] = {"tampered": True}
            path.write_text(
                json.dumps(record) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(JournalIntegrityError):
                ExecutionJournal.verify(path)

    def test_worker_profile_ranking_matches_complexity(self):
        """Prefer a capable heavy profile for heavy implementation work."""
        profiles = [
            WorkerProfile.from_dict(
                {
                    "actor_id": "small",
                    "roles": ["implementation"],
                    "tiers": {"implementation": "light"},
                    "preferred_complexity": ["light"],
                    "cost_class": "FREE_ALLOWANCE",
                }
            ),
            WorkerProfile.from_dict(
                {
                    "actor_id": "strong",
                    "roles": ["implementation"],
                    "tiers": {"implementation": "heavy"},
                    "preferred_complexity": ["heavy"],
                    "cost_class": "INCLUDED_SUBSCRIPTION",
                }
            ),
        ]
        ranked = rank_worker_profiles(
            profiles,
            role="implementation",
            complexity=WorkerTier.HEAVY,
            allowed_cost_classes={
                "FREE_ALLOWANCE",
                "INCLUDED_SUBSCRIPTION",
            },
        )
        self.assertEqual(
            [item.actor_id for item in ranked],
            ["strong", "small"],
        )

    def test_external_runtime_adapter_uses_json_stdin_and_no_shell(self):
        """Pass the fenced RunKey to a shell-free external runtime."""
        with tempfile.TemporaryDirectory() as directory:
            worker = Path(directory) / "worker.py"
            worker.write_text(
                "import json,sys\n"
                "d=json.load(sys.stdin)\n"
                "print(json.dumps({'role':d['role'],"
                "'g':d['run_key']['generation']}))\n",
                encoding="utf-8",
            )
            adapter: AgentRuntimeAdapter = CommandRuntimeAdapter(
                [sys.executable, str(worker)]
            )
            result = adapter.execute(
                RuntimeRequest(
                    RunKey("WU-1", "r", 2),
                    "objective",
                    "review",
                    {"x": 1},
                ),
                timeout_seconds=5,
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual(
                json.loads(result.stdout),
                {"role": "review", "g": 2},
            )

    def test_decision_evidence_dead_end_lessons_are_bounded(self):
        """Retain only the newest bounded execution lessons."""
        context = self.context()
        for index in range(25):
            EvidenceRegistry.add_lesson(
                context,
                context.key,
                "decision",
                f"d{index}",
            )
        self.assertEqual(len(context.lessons), 20)
        self.assertEqual(context.lessons[0].text, "d5")


if __name__ == "__main__":
    unittest.main()
