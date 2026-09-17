#!/usr/bin/env python3
"""Manage bounded OneCompany execution sessions below the WU lease boundary."""
from __future__ import annotations

import argparse
import json
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from execution_core import (
    CompletionGate,
    CompletionVerdict,
    EvidenceItem,
    EvidenceRegistry,
    ExecutionJournal,
    ExecutionStore,
    ExecutionSupervisor,
    ObjectiveTracker,
    ProgressSentinel,
    ResourceBudget,
    ResourceGuard,
    RunContext,
    RunKey,
    RunStatus,
    TaskBoard,
    TaskItem,
    TaskStatus,
    TransitionEngine,
    WorkerProfile,
    WorkerTier,
    rank_worker_profiles,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME = ROOT / ".onecompany" / "runtime" / "execution"
PROFILE_PATH = ROOT / ".onecompany" / "execution-profiles.json"
BUDGET_PATH = ROOT / ".onecompany" / "budget.json"


def emit(value: object) -> None:
    """Print one deterministic JSON response."""
    print(json.dumps(value, indent=2, sort_keys=True, default=str))


def criterion(value: str) -> tuple[str, str]:
    """Parse an ID=description acceptance criterion."""
    if "=" not in value:
        raise argparse.ArgumentTypeError(
            "acceptance criterion must be ID=description"
        )
    key, text = value.split("=", 1)
    if not key.strip() or not text.strip():
        raise argparse.ArgumentTypeError(
            "acceptance criterion must contain non-empty ID and description"
        )
    return key.strip(), text.strip()


def store_for(args: argparse.Namespace) -> ExecutionStore:
    """Build an execution store from CLI arguments."""
    return ExecutionStore(Path(args.runtime_root).resolve())


def caller_key(args: argparse.Namespace) -> RunKey:
    """Construct the exact caller-supplied execution identity."""
    return RunKey(args.wu, args.run_id, args.generation)


@contextmanager
def locked_context(
    args: argparse.Namespace,
) -> Iterator[tuple[ExecutionStore, RunContext, RunKey]]:
    """Lock, load, and fence one mutable work-unit execution context."""
    store = store_for(args)
    supplied_key = caller_key(args)
    with store.lock(args.wu):
        context = store.load(args.wu, lock_held=True)
        context.assert_key(supplied_key)
        yield store, context, supplied_key



def cmd_create(args: argparse.Namespace) -> int:
    """Create generation one while serializing the existence check."""
    context = RunContext.new(
        args.wu,
        args.objective,
        dict(args.acceptance_criterion),
        ResourceBudget(
            args.max_tokens,
            args.max_active_seconds,
            args.max_errors,
            args.max_unchanged,
        ),
        run_id=args.run_id,
    )
    store = store_for(args)
    with store.lock(args.wu):
        store.recover_pending(args.wu, lock_held=True)
        if store.state_path(args.wu).exists() and not args.replace:
            raise FileExistsError(
                f"execution state already exists for {args.wu}"
            )
        store.persist_event(
            context,
            "execution_created",
            {
                "acceptance_criteria": sorted(
                    context.acceptance_criteria
                )
            },
            lock_held=True,
        )
    emit(context.to_dict())
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    """Show the current journal-matched execution state."""
    store = store_for(args)
    context = store.load(args.wu)
    emit(context.to_dict())
    return 0


def cmd_edit(args: argparse.Namespace) -> int:
    """Revise the objective using the caller's exact RunKey."""
    with locked_context(args) as (
        store,
        context,
        supplied_key,
    ):
        criteria = (
            dict(args.acceptance_criterion)
            if args.acceptance_criterion
            else None
        )
        old_generation = context.key.generation
        ObjectiveTracker.edit(
            context,
            supplied_key,
            objective=args.objective,
            acceptance_criteria=criteria,
        )
        store.persist_event(
            context,
            "objective_revised",
            {
                "previous_generation": old_generation,
                "new_generation": context.key.generation,
            },
            lock_held=True,
        )
    emit(context.to_dict())
    return 0


def cmd_task_add(args: argparse.Namespace) -> int:
    """Add or replace a tactical task under exact generation fencing."""
    with locked_context(args) as (
        store,
        context,
        supplied_key,
    ):
        TaskBoard.upsert(
            context,
            supplied_key,
            TaskItem(
                args.task_id,
                args.description,
                TaskStatus(args.status),
            ),
        )
        store.persist_event(
            context,
            "task_updated",
            {"task_id": args.task_id, "status": args.status},
            lock_held=True,
        )
    emit(context.to_dict())
    return 0


def cmd_task_status(args: argparse.Namespace) -> int:
    """Change a task status under exact generation fencing."""
    with locked_context(args) as (
        store,
        context,
        supplied_key,
    ):
        status = TaskStatus(args.status)
        TaskBoard.set_status(
            context,
            supplied_key,
            args.task_id,
            status,
            blocker=args.blocker,
        )
        store.persist_event(
            context,
            "task_status_changed",
            {
                "task_id": args.task_id,
                "status": status.value,
                "blocker": args.blocker,
            },
            lock_held=True,
        )
    emit(context.to_dict())
    return 0


def cmd_evidence(args: argparse.Namespace) -> int:
    """Record bounded evidence while execution remains runnable."""
    with locked_context(args) as (
        store,
        context,
        supplied_key,
    ):
        item = EvidenceItem(
            args.evidence_id,
            args.kind,
            args.reference,
            [
                item.strip()
                for item in args.acceptance_criteria.split(",")
                if item.strip()
            ],
            args.authoritative,
        )
        EvidenceRegistry.add(context, supplied_key, item)
        store.persist_event(
            context,
            "evidence_recorded",
            {
                "evidence_id": item.id,
                "authoritative": item.authoritative,
            },
            lock_held=True,
        )
    emit(context.to_dict())
    return 0


def cmd_lesson(args: argparse.Namespace) -> int:
    """Record one bounded execution lesson."""
    with locked_context(args) as (
        store,
        context,
        supplied_key,
    ):
        EvidenceRegistry.add_lesson(
            context, supplied_key, args.kind, args.text
        )
        store.persist_event(
            context,
            "lesson_recorded",
            {"kind": args.kind},
            lock_held=True,
        )
    emit(context.to_dict())
    return 0


def cmd_usage(args: argparse.Namespace) -> int:
    """Record usage and persist a non-runnable state if a guard trips."""
    with locked_context(args) as (
        store,
        context,
        supplied_key,
    ):
        decision = ResourceGuard.record_usage(
           context,
            supplied_key,
            assistant_tokens=args.assistant_tokens,
            active_seconds=args.active_seconds,
        )
        ResourceGuard.enforce(context, supplied_key, decision)
        store.persist_event(
            context,
            "usage_recorded",
            {
                "assistant_tokens": args.assistant_tokens,
                "active_seconds": args.active_seconds,
                "guard_allowed": decision.allowed,
                "guard_reason": decision.reason,
                "status": context.status.value,
            },
            lock_held=True,
        )
    emit(
        {
            "guard": decision.__dict__,
            "context": context.to_dict(),
        }
    )
    return 0 if decision.allowed else 3


def cmd_error(args: argparse.Namespace) -> int:
    """Record an execution error and persist any tripped guard."""
    with locked_context(args) as (
        store,
        context,
        supplied_key,
    ):
        decision = ResourceGuard.record_error(
            context, supplied_key
        )
        ResourceGuard.enforce(context, supplied_key, decision)
        store.persist_event(
            context,
            "execution_error",
            {
                "reason": args.reason,
                "guard_allowed": decision.allowed,
                "guard_reason": decision.reason,
                "status": context.status.value,
            },
            lock_held=True,
        )
    emit(
        {
            "guard": decision.__dict__,
            "context": context.to_dict(),
        }
    )
    return 0 if decision.allowed else 3


def cmd_progress(args: argparse.Namespace) -> int:
    """Record substantive progress and persist stall-state enforcement."""
    with locked_context(args) as (
        store,
        context,
        supplied_key,
    ):
        tests: dict[str, str] = {}
        for item in args.test or []:
            if "=" not in item:
                raise ValueError(
                    "--test values must be NAME=STATE"
                )
            key, value = item.split("=", 1)
            tests[key] = value
        fingerprint = ProgressSentinel.fingerprint(
            head_sha=args.head,
            unmet_acceptance_criteria=args.unmet_ac or [],
            test_state=tests,
            blockers=args.blocker or [],
            evidence_ids=args.evidence_id or [],
            material_changes=args.material_change or [],
        )
        stalled = ProgressSentinel.observe(
            context, supplied_key, fingerprint
        )
        decision = ResourceGuard.check(context)
        ResourceGuard.enforce(context, supplied_key, decision)
        store.persist_event(
            context,
            "progress_observed",
            {
                "fingerprint": fingerprint,
                "stalled": stalled,
                "guard_allowed": decision.allowed,
                "guard_reason": decision.reason,
                "status": context.status.value,
            },
            lock_held=True,
        )
    emit(
        {
            "fingerprint": fingerprint,
            "stalled": stalled,
            "unchanged_cycles": context.unchanged_cycles,
            "status": context.status.value,
        }
    )
    return 3 if not decision.allowed else 0


def cmd_claim(args: argparse.Namespace) -> int:
    """Record a completion claim only for the exact active generation."""
    with locked_context(args) as (
        store,
        context,
        supplied_key,
    ):
        assessment = CompletionGate.record_worker_claim(
            context, supplied_key, args.claim
        )
        store.persist_event(
            context,
            "completion_claimed",
            {"preflight_verdict": assessment.verdict.value},
            lock_held=True,
        )
    emit(
        {
            "assessment": assessment.__dict__,
            "context": context.to_dict(),
        }
    )
    return (
        0
        if assessment.verdict == CompletionVerdict.MET
        else 3
    )


def cmd_evaluate(args: argparse.Namespace) -> int:
    """Apply an evaluator verdict to the exact pending generation."""
    with locked_context(args) as (
        store,
        context,
        supplied_key,
    ):
        verdict = CompletionVerdict(args.verdict)
        CompletionGate.apply_evaluator_verdict(
            context,
            supplied_key,
            verdict,
            confidence=args.confidence,
            notes=args.notes,
            cited_evidence=args.cited_evidence or [],
        )
        store.persist_event(
            context,
            "completion_evaluated",
            {
                "verdict": verdict.value,
                "confidence": args.confidence,
            },
            lock_held=True,
        )
    emit(context.to_dict())
    return 0 if verdict == CompletionVerdict.MET else 3


def cmd_transition(args: argparse.Namespace) -> int:
    """Apply one deterministic lifecycle transition."""
    with locked_context(args) as (
        store,
        context,
        supplied_key,
    ):
        result = TransitionEngine.transition(
            context,
            supplied_key,
            args.command,
            now=args.now,
            payload={"reason": args.reason}
            if args.reason
            else {},
        )
        store.persist_event(
            result.context,
            "transition:" + result.event_type,
            result.details,
            lock_held=True,
        )
    emit(result.context.to_dict())
    return 0


def cmd_supervise(args: argparse.Namespace) -> int:
    """Assess supervision and persist guard enforcement if needed."""
    with locked_context(args) as (
        store,
        context,
        supplied_key,
    ):
        guard = ResourceGuard.check(context)
        changed = False
        if not guard.allowed and context.status in {
            RunStatus.ACTIVE,
            RunStatus.COMPLETION_PENDING,
        }:
            ResourceGuard.enforce(
                context, supplied_key, guard
            )
            changed = True
        if changed:
            store.persist_event(
                context,
                "guard_enforced",
                {
                    "guard_reason": guard.reason,
                    "status": context.status.value,
                },
                lock_held=True,
            )
        decision = ExecutionSupervisor.assess(context)
    emit(decision.__dict__)
    return (
        0
        if decision.action
        in {
            "CONTINUE",
            "NO_ACTION",
            "RUN_COMPLETION_EVALUATOR",
        }
        else 3
    )


def cmd_journal(args: argparse.Namespace) -> int:
    """Verify the recovered journal under the per-WU lock."""
    store = store_for(args)
    with store.lock(args.wu):
        store.recover_pending(args.wu, lock_held=True)
        records = ExecutionJournal.verify(
            store.journal_path(args.wu)
        )
    emit(
        {
            "valid": True,
            "events": len(records),
            "last_hash": records[-1]["record_hash"]
            if records
            else None,
        }
    )
    return 0


def cmd_profile_rank(args: argparse.Namespace) -> int:
    """Rank advisory worker profiles after existing hard eligibility."""
    profile_doc = json.loads(
        PROFILE_PATH.read_text(encoding="utf-8")
    )
    budget_doc = json.loads(
        BUDGET_PATH.read_text(encoding="utf-8")
    )
    profiles = [
        WorkerProfile.from_dict(item)
        for item in profile_doc.get("profiles", [])
    ]
    ranked = rank_worker_profiles(
        profiles,
        role=args.role,
        complexity=WorkerTier(args.complexity),
        allowed_cost_classes=set(
            budget_doc.get("cost_classes", {}).get(
                "allowed", []
            )
        ),
    )
    emit(
        {
            "role": args.role,
            "complexity": args.complexity,
            "eligible_ranked": [
                item.actor_id for item in ranked
            ],
        }
    )
    return 0 if ranked else 3


def add_run_key_arguments(
    parser: argparse.ArgumentParser,
) -> None:
    """Require exact caller identity for existing-state mutations."""
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--generation", type=int, required=True)


def build_parser() -> argparse.ArgumentParser:
    """Build the bounded execution CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runtime-root",
        default=str(DEFAULT_RUNTIME),
        help="unversioned execution-state directory",
    )
    sub = parser.add_subparsers(
        dest="subcommand", required=True
    )

    create = sub.add_parser("create")
    create.add_argument("--wu", required=True)
    create.add_argument("--objective", required=True)
    create.add_argument(
        "--acceptance-criterion",
        action="append",
        type=criterion,
        required=True,
    )
    create.add_argument("--run-id")
    create.add_argument("--max-tokens", type=int)
    create.add_argument("--max-active-seconds", type=float)
    create.add_argument("--max-errors", type=int, default=3)
    create.add_argument("--max-unchanged", type=int, default=3)
    create.add_argument("--replace", action="store_true")
    create.set_defaults(func=cmd_create)

    show = sub.add_parser("show")
    show.add_argument("--wu", required=True)
    show.set_defaults(func=cmd_show)

    edit = sub.add_parser("edit")
    edit.add_argument("--wu", required=True)
    add_run_key_arguments(edit)
    edit.add_argument("--objective")
    edit.add_argument(
        "--acceptance-criterion",
        action="append",
        type=criterion,
    )
    edit.set_defaults(func=cmd_edit)

    task_add = sub.add_parser("task-add")
    task_add.add_argument("--wu", required=True)
    add_run_key_arguments(task_add)
    task_add.add_argument("--task-id", required=True)
    task_add.add_argument("--description", required=True)
    task_add.add_argument(
        "--status",
        choices=[item.value for item in TaskStatus],
        default=TaskStatus.PENDING.value,
    )
    task_add.set_defaults(func=cmd_task_add)

    task_status = sub.add_parser("task-status")
    task_status.add_argument("--wu", required=True)
    add_run_key_arguments(task_status)
    task_status.add_argument("--task-id", required=True)
    task_status.add_argument(
        "--status",
        required=True,
        choices=[item.value for item in TaskStatus],
    )
    task_status.add_argument("--blocker")
    task_status.set_defaults(func=cmd_task_status)

    evidence = sub.add_parser("evidence-add")
    evidence.add_argument("--wu", required=True)
    add_run_key_arguments(evidence)
    evidence.add_argument("--evidence-id", required=True)
    evidence.add_argument("--kind", required=True)
    evidence.add_argument("--reference", required=True)
    evidence.add_argument(
        "--acceptance-criteria", required=True
    )
    evidence.add_argument(
        "--authoritative", action="store_true"
    )
    evidence.set_defaults(func=cmd_evidence)

    lesson = sub.add_parser("lesson-add")
    lesson.add_argument("--wu", required=True)
    add_run_key_arguments(lesson)
    lesson.add_argument(
        "--kind",
        choices=["decision", "evidence", "dead_end"],
        required=True,
    )
    lesson.add_argument("--text", required=True)
    lesson.set_defaults(func=cmd_lesson)

    usage = sub.add_parser("usage")
    usage.add_argument("--wu", required=True)
    add_run_key_arguments(usage)
    usage.add_argument(
        "--assistant-tokens", type=int, default=0
    )
    usage.add_argument(
        "--active-seconds", type=float, default=0
    )
    usage.set_defaults(func=cmd_usage)

    error = sub.add_parser("error")
    error.add_argument("--wu", required=True)
    add_run_key_arguments(error)
    error.add_argument("--reason", required=True)
    error.set_defaults(func=cmd_error)

    progress = sub.add_parser("progress")
    progress.add_argument("--wu", required=True)
    add_run_key_arguments(progress)
    progress.add_argument("--head")
    progress.add_argument("--unmet-ac", action="append")
    progress.add_argument("--test", action="append")
    progress.add_argument("--blocker", action="append")
    progress.add_argument("--evidence-id", action="append")
    progress.add_argument(
        "--material-change", action="append"
    )
    progress.set_defaults(func=cmd_progress)

    claim = sub.add_parser("claim")
    claim.add_argument("--wu", required=True)
    add_run_key_arguments(claim)
    claim.add_argument("--claim", required=True)
    claim.set_defaults(func=cmd_claim)

    evaluate = sub.add_parser("evaluate")
    evaluate.add_argument("--wu", required=True)
    add_run_key_arguments(evaluate)
    evaluate.add_argument(
        "--verdict",
        required=True,
        choices=[item.value for item in CompletionVerdict],
    )
    evaluate.add_argument(
        "--confidence", type=float, required=True
    )
    evaluate.add_argument("--notes", required=True)
    evaluate.add_argument(
        "--cited-evidence", action="append"
    )
    evaluate.set_defaults(func=cmd_evaluate)

    transition = sub.add_parser("transition")
    transition.add_argument("--wu", required=True)
    add_run_key_arguments(transition)
    transition.add_argument(
        "--command",
        required=True,
        choices=[
            "pause",
            "resume",
            "block",
            "unblock",
            "budget_limit",
            "rotate_generation",
        ],
    )
    transition.add_argument("--reason")
    transition.add_argument(
        "--now", type=float, required=True
    )
    transition.set_defaults(func=cmd_transition)

    supervise = sub.add_parser("supervise")
    supervise.add_argument("--wu", required=True)
    add_run_key_arguments(supervise)
    supervise.set_defaults(func=cmd_supervise)

    journal = sub.add_parser("journal-verify")
    journal.add_argument("--wu", required=True)
    journal.set_defaults(func=cmd_journal)

    rank = sub.add_parser("profile-rank")
    rank.add_argument("--role", required=True)
    rank.add_argument(
        "--complexity",
        required=True,
        choices=[item.value for item in WorkerTier],
    )
    rank.set_defaults(func=cmd_profile_rank)
    return parser


def main() -> int:
    """Run the execution CLI and fail closed on invalid mutations."""
    args = build_parser().parse_args()
    try:
        return args.func(args)
    except (
        FileNotFoundError,
        FileExistsError,
        KeyError,
        ValueError,
        RuntimeError,
    ) as exc:
        emit({"status": "BLOCKED", "error": str(exc)})
        return 2


if __name__ == "__main__":
    sys.exit(main())
