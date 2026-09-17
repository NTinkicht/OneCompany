#!/usr/bin/env python3
"""Dependency-free bounded execution primitives below OneCompany's WU lease boundary."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


class ExecutionError(RuntimeError):
    pass


class StaleGenerationError(ExecutionError):
    pass


class InvalidTransitionError(ExecutionError):
    pass


class JournalIntegrityError(ExecutionError):
    pass


class RuntimeAdapterError(ExecutionError):
    pass


class RunStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    BLOCKED = "blocked"
    BUDGET_LIMITED = "budget_limited"
    COMPLETION_PENDING = "completion_pending"
    COMPLETE = "complete"


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    BLOCKED = "blocked"


class CompletionVerdict(str, Enum):
    CONTINUE = "continue"
    MET = "met"
    IMPOSSIBLE = "impossible"
    UNAVAILABLE = "unavailable"


class WorkerTier(str, Enum):
    LIGHT = "light"
    STANDARD = "standard"
    HEAVY = "heavy"


@dataclass(frozen=True)
class RunKey:
    wu_id: str
    run_id: str
    generation: int

    def validate(self) -> None:
        if not self.wu_id.strip() or not self.run_id.strip():
            raise ValueError("wu_id and run_id are required")
        if self.generation < 1:
            raise ValueError("generation must be >= 1")


@dataclass
class ResourceBudget:
    max_assistant_tokens: int | None = None
    max_active_seconds: float | None = None
    max_consecutive_errors: int = 3
    max_unchanged_cycles: int = 3

    def __post_init__(self) -> None:
        if self.max_consecutive_errors < 1 or self.max_unchanged_cycles < 1:
            raise ValueError("error and unchanged-cycle limits must be >= 1")
        if self.max_assistant_tokens is not None and self.max_assistant_tokens < 1:
            raise ValueError("max_assistant_tokens must be positive")
        if self.max_active_seconds is not None and self.max_active_seconds <= 0:
            raise ValueError("max_active_seconds must be positive")


@dataclass
class TaskItem:
    id: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    blocker: str | None = None


@dataclass
class EvidenceItem:
    id: str
    kind: str
    reference: str
    acceptance_criteria: list[str] = field(default_factory=list)
    authoritative: bool = False
    observed_at: float = field(default_factory=time.time)


@dataclass
class LessonItem:
    kind: str
    text: str
    created_at: float = field(default_factory=time.time)


@dataclass
class RunContext:
    key: RunKey
    objective: str
    acceptance_criteria: dict[str, str]
    budget: ResourceBudget = field(default_factory=ResourceBudget)
    status: RunStatus = RunStatus.ACTIVE
    blocked_reason: str | None = None
    tasks: dict[str, TaskItem] = field(default_factory=dict)
    evidence: dict[str, EvidenceItem] = field(default_factory=dict)
    lessons: list[LessonItem] = field(default_factory=list)
    assistant_tokens: int = 0
    active_seconds: float = 0.0
    consecutive_errors: int = 0
    unchanged_cycles: int = 0
    last_progress_fingerprint: str | None = None
    completion_confidence: float = 0.0
    completion_claim: str | None = None
    completion_verdict: CompletionVerdict | None = None
    evaluator_notes: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self.key.validate()
        if not self.objective.strip() or not self.acceptance_criteria:
            raise ValueError("objective and acceptance criteria are required")
        if any(not str(k).strip() or not str(v).strip() for k, v in self.acceptance_criteria.items()):
            raise ValueError("acceptance criteria require non-empty ids and descriptions")

    @classmethod
    def new(cls, wu_id: str, objective: str, acceptance_criteria: Mapping[str, str], budget: ResourceBudget | None = None, *, run_id: str | None = None) -> "RunContext":
        return cls(RunKey(wu_id, run_id or uuid.uuid4().hex, 1), objective, dict(acceptance_criteria), budget or ResourceBudget())

    def assert_key(self, supplied: RunKey) -> None:
        supplied.validate()
        if supplied != self.key:
            raise StaleGenerationError(
                f"stale execution key: expected {self.key.wu_id}/{self.key.run_id}/g{self.key.generation}, got {supplied.wu_id}/{supplied.run_id}/g{supplied.generation}"
            )

    def rotate_generation(self) -> RunKey:
        if self.status == RunStatus.COMPLETE:
            raise InvalidTransitionError("cannot rotate generation for a complete run")
        self.key = RunKey(self.key.wu_id, self.key.run_id, self.key.generation + 1)
        self.consecutive_errors = 0
        self.unchanged_cycles = 0
        self.last_progress_fingerprint = None
        self.updated_at = time.time()
        return self.key

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        data["completion_verdict"] = self.completion_verdict.value if self.completion_verdict else None
        data["tasks"] = {key: {**asdict(item), "status": item.status.value} for key, item in self.tasks.items()}
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RunContext":
        tasks = {
            key: TaskItem(item["id"], item["description"], TaskStatus(item.get("status", "pending")), item.get("blocker"))
            for key, item in data.get("tasks", {}).items()
        }
        evidence = {key: EvidenceItem(**item) for key, item in data.get("evidence", {}).items()}
        verdict = data.get("completion_verdict")
        return cls(
            key=RunKey(**data["key"]),
            objective=data["objective"],
            acceptance_criteria=dict(data["acceptance_criteria"]),
            budget=ResourceBudget(**data.get("budget", {})),
            status=RunStatus(data.get("status", "active")),
            blocked_reason=data.get("blocked_reason"),
            tasks=tasks,
            evidence=evidence,
            lessons=[LessonItem(**item) for item in data.get("lessons", [])],
            assistant_tokens=int(data.get("assistant_tokens", 0)),
            active_seconds=float(data.get("active_seconds", 0)),
            consecutive_errors=int(data.get("consecutive_errors", 0)),
            unchanged_cycles=int(data.get("unchanged_cycles", 0)),
            last_progress_fingerprint=data.get("last_progress_fingerprint"),
            completion_confidence=float(data.get("completion_confidence", 0)),
            completion_claim=data.get("completion_claim"),
            completion_verdict=CompletionVerdict(verdict) if verdict else None,
            evaluator_notes=data.get("evaluator_notes"),
            created_at=float(data.get("created_at", time.time())),
            updated_at=float(data.get("updated_at", time.time())),
        )


class ObjectiveTracker:
    @staticmethod
    def edit(context: RunContext, supplied_key: RunKey, *, objective: str | None = None, acceptance_criteria: Mapping[str, str] | None = None) -> RunKey:
        context.assert_key(supplied_key)
        if context.status == RunStatus.COMPLETE:
            raise InvalidTransitionError("cannot edit a complete objective")
        if objective is not None:
            if not objective.strip():
                raise ValueError("objective cannot be empty")
            context.objective = objective
        if acceptance_criteria is not None:
            if not acceptance_criteria:
                raise ValueError("acceptance criteria cannot be empty")
            context.acceptance_criteria = dict(acceptance_criteria)
        return context.rotate_generation()


class TaskBoard:
    @staticmethod
    def upsert(context: RunContext, supplied_key: RunKey, item: TaskItem) -> None:
        context.assert_key(supplied_key)
        if context.status not in {RunStatus.ACTIVE, RunStatus.COMPLETION_PENDING}:
            raise InvalidTransitionError(f"cannot mutate tasks while run is {context.status.value}")
        if not item.id.strip() or not item.description.strip():
            raise ValueError("task id and description are required")
        context.tasks[item.id] = copy.deepcopy(item)
        context.updated_at = time.time()

    @staticmethod
    def set_status(context: RunContext, supplied_key: RunKey, task_id: str, status: TaskStatus, blocker: str | None = None) -> None:
        context.assert_key(supplied_key)
        item = context.tasks.get(task_id)
        if item is None:
            raise KeyError(task_id)
        item.status = status
        item.blocker = blocker if status == TaskStatus.BLOCKED else None
        context.updated_at = time.time()


class EvidenceRegistry:
    @staticmethod
    def add(context: RunContext, supplied_key: RunKey, item: EvidenceItem) -> None:
        context.assert_key(supplied_key)
        if not item.id.strip() or not item.kind.strip() or not item.reference.strip():
            raise ValueError("evidence id, kind, and reference are required")
        unknown = sorted(set(item.acceptance_criteria) - set(context.acceptance_criteria))
        if unknown:
            raise ValueError("evidence references unknown acceptance criteria: " + ",".join(unknown))
        context.evidence[item.id] = copy.deepcopy(item)
        context.updated_at = time.time()

    @staticmethod
    def add_lesson(context: RunContext, supplied_key: RunKey, kind: str, text: str) -> None:
        context.assert_key(supplied_key)
        normalized = kind.strip().lower()
        if normalized not in {"decision", "evidence", "dead_end"}:
            raise ValueError("lesson kind must be decision, evidence, or dead_end")
        if not text.strip():
            raise ValueError("lesson text is required")
        context.lessons.append(LessonItem(normalized, text.strip()))
        context.lessons = context.lessons[-20:]
        context.updated_at = time.time()


class ProgressSentinel:
    @staticmethod
    def fingerprint(*, head_sha: str | None, unmet_acceptance_criteria: Iterable[str], test_state: Mapping[str, str] | None = None, blockers: Iterable[str] = (), evidence_ids: Iterable[str] = (), material_changes: Iterable[str] = ()) -> str:
        payload = {
            "head_sha": head_sha or "",
            "unmet_acceptance_criteria": sorted(set(unmet_acceptance_criteria)),
            "test_state": dict(sorted((test_state or {}).items())),
            "blockers": sorted(set(blockers)),
            "evidence_ids": sorted(set(evidence_ids)),
            "material_changes": sorted(set(material_changes)),
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    @staticmethod
    def observe(context: RunContext, supplied_key: RunKey, fingerprint: str) -> bool:
        context.assert_key(supplied_key)
        if context.last_progress_fingerprint is None:
            context.unchanged_cycles = 0
        elif context.last_progress_fingerprint == fingerprint:
            context.unchanged_cycles += 1
        else:
            context.unchanged_cycles = 0
            context.consecutive_errors = 0
        context.last_progress_fingerprint = fingerprint
        context.updated_at = time.time()
        return context.unchanged_cycles >= context.budget.max_unchanged_cycles


@dataclass(frozen=True)
class GuardDecision:
    allowed: bool
    reason: str | None = None


class ResourceGuard:
    @staticmethod
    def record_usage(context: RunContext, supplied_key: RunKey, *, assistant_tokens: int = 0, active_seconds: float = 0) -> GuardDecision:
        context.assert_key(supplied_key)
        if assistant_tokens < 0 or active_seconds < 0:
            raise ValueError("usage increments cannot be negative")
        context.assistant_tokens += assistant_tokens
        context.active_seconds += active_seconds
        context.updated_at = time.time()
        return ResourceGuard.check(context)

    @staticmethod
    def record_error(context: RunContext, supplied_key: RunKey) -> GuardDecision:
        context.assert_key(supplied_key)
        context.consecutive_errors += 1
        context.updated_at = time.time()
        return ResourceGuard.check(context)

    @staticmethod
    def check(context: RunContext) -> GuardDecision:
        if context.budget.max_assistant_tokens is not None and context.assistant_tokens >= context.budget.max_assistant_tokens:
            return GuardDecision(False, "assistant_token_budget_exhausted")
        if context.budget.max_active_seconds is not None and context.active_seconds >= context.budget.max_active_seconds:
            return GuardDecision(False, "active_time_budget_exhausted")
        if context.consecutive_errors >= context.budget.max_consecutive_errors:
            return GuardDecision(False, "consecutive_error_limit_reached")
        if context.unchanged_cycles >= context.budget.max_unchanged_cycles:
            return GuardDecision(False, "unchanged_progress_limit_reached")
        return GuardDecision(True)


@dataclass(frozen=True)
class CompletionAssessment:
    verdict: CompletionVerdict
    confidence: float
    unmet_acceptance_criteria: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    cited_evidence: tuple[str, ...] = ()


class CompletionGate:
    @staticmethod
    def assess(context: RunContext) -> CompletionAssessment:
        blockers = [item.id for item in context.tasks.values() if item.status == TaskStatus.BLOCKED]
        unfinished = [item.id for item in context.tasks.values() if item.status != TaskStatus.DONE]
        coverage = {ac_id: [] for ac_id in context.acceptance_criteria}
        for evidence in context.evidence.values():
            if evidence.authoritative:
                for ac_id in evidence.acceptance_criteria:
                    if ac_id in coverage:
                        coverage[ac_id].append(evidence.id)
        unmet = sorted(ac_id for ac_id, refs in coverage.items() if not refs)
        reasons = []
        if blockers:
            reasons.append("blocked_tasks:" + ",".join(sorted(blockers)))
        if unfinished:
            reasons.append("unfinished_tasks:" + ",".join(sorted(unfinished)))
        if unmet:
            reasons.append("acceptance_criteria_without_authoritative_evidence:" + ",".join(unmet))
        if context.status == RunStatus.BLOCKED:
            reasons.append("run_blocked")
        cited = tuple(sorted({ref for refs in coverage.values() for ref in refs}))
        if reasons:
            return CompletionAssessment(CompletionVerdict.CONTINUE, 0.0, tuple(unmet), tuple(reasons), cited)
        return CompletionAssessment(CompletionVerdict.MET, 1.0, cited_evidence=cited)

    @staticmethod
    def record_worker_claim(context: RunContext, supplied_key: RunKey, claim: str) -> CompletionAssessment:
        context.assert_key(supplied_key)
        if context.status != RunStatus.ACTIVE:
            raise InvalidTransitionError("completion can only be claimed from active execution")
        if not claim.strip():
            raise ValueError("completion claim is required")
        context.completion_claim = claim.strip()
        context.status = RunStatus.COMPLETION_PENDING
        context.updated_at = time.time()
        return CompletionGate.assess(context)

    @staticmethod
    def apply_evaluator_verdict(context: RunContext, supplied_key: RunKey, verdict: CompletionVerdict, *, confidence: float, notes: str, cited_evidence: Sequence[str] = ()) -> None:
        context.assert_key(supplied_key)
        if context.status != RunStatus.COMPLETION_PENDING:
            raise InvalidTransitionError("external evaluation requires completion_pending state")
        if not 0 <= confidence <= 1:
            raise ValueError("confidence must be within [0, 1]")
        unknown = sorted(set(cited_evidence) - set(context.evidence))
        if unknown:
            raise ValueError("evaluator cited unknown evidence: " + ",".join(unknown))
        if verdict == CompletionVerdict.MET and CompletionGate.assess(context).verdict != CompletionVerdict.MET:
            raise InvalidTransitionError("evaluator cannot override missing deterministic completion evidence")
        context.completion_verdict = verdict
        context.completion_confidence = confidence
        context.evaluator_notes = notes
        if verdict == CompletionVerdict.MET:
            context.status = RunStatus.COMPLETE
        elif verdict == CompletionVerdict.IMPOSSIBLE:
            context.status = RunStatus.BLOCKED
            context.blocked_reason = notes or "completion_evaluator_declared_impossible"
        elif verdict == CompletionVerdict.UNAVAILABLE:
            context.status = RunStatus.PAUSED
        else:
            context.status = RunStatus.ACTIVE
        context.updated_at = time.time()


@dataclass(frozen=True)
class TransitionResult:
    context: RunContext
    event_type: str
    details: dict[str, Any]


class TransitionEngine:
    @staticmethod
    def transition(current: RunContext, supplied_key: RunKey, command: str, *, now: float, payload: Mapping[str, Any] | None = None) -> TransitionResult:
        next_context = copy.deepcopy(current)
        next_context.assert_key(supplied_key)
        payload = dict(payload or {})
        if command == "pause":
            if next_context.status not in {RunStatus.ACTIVE, RunStatus.COMPLETION_PENDING}:
                raise InvalidTransitionError("pause requires active or completion_pending state")
            next_context.status = RunStatus.PAUSED
        elif command == "resume":
            if next_context.status not in {RunStatus.PAUSED, RunStatus.BUDGET_LIMITED}:
                raise InvalidTransitionError("resume requires paused or budget_limited state")
            if not ResourceGuard.check(next_context).allowed:
                raise InvalidTransitionError("cannot resume while resource guard is tripped")
            next_context.status = RunStatus.ACTIVE
        elif command == "block":
            reason = str(payload.get("reason", "")).strip()
            if not reason:
                raise ValueError("block requires reason")
            next_context.status = RunStatus.BLOCKED
            next_context.blocked_reason = reason
        elif command == "unblock":
            if next_context.status != RunStatus.BLOCKED:
                raise InvalidTransitionError("unblock requires blocked state")
            next_context.status = RunStatus.ACTIVE
            next_context.blocked_reason = None
        elif command == "budget_limit":
            next_context.status = RunStatus.BUDGET_LIMITED
            next_context.blocked_reason = str(payload.get("reason") or "execution_budget_limited")
        elif command == "rotate_generation":
            next_context.rotate_generation()
        else:
            raise InvalidTransitionError(f"unknown execution transition: {command}")
        next_context.updated_at = now
        return TransitionResult(next_context, command, payload)


@dataclass(frozen=True)
class JournalRecord:
    sequence: int
    event_type: str
    run_key: dict[str, Any]
    details: dict[str, Any]
    previous_hash: str
    state_hash: str
    recorded_at: float
    record_hash: str


class ExecutionJournal:
    GENESIS_HASH = "0" * 64

    @staticmethod
    def canonical_hash(value: Any) -> str:
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()

    @classmethod
    def read(cls, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        records = []
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise JournalIntegrityError(f"invalid JSON at journal line {line_number}") from exc
        return records

    @classmethod
    def verify(cls, path: Path) -> list[dict[str, Any]]:
        records = cls.read(path)
        previous = cls.GENESIS_HASH
        for expected_sequence, record in enumerate(records, 1):
            if record.get("sequence") != expected_sequence or record.get("previous_hash") != previous:
                raise JournalIntegrityError("journal sequence or hash chain is broken")
            supplied_hash = record.get("record_hash")
            body = {key: value for key, value in record.items() if key != "record_hash"}
            if supplied_hash != cls.canonical_hash(body):
                raise JournalIntegrityError("journal record hash mismatch")
            previous = supplied_hash
        return records

    @classmethod
    def append(cls, path: Path, *, event_type: str, context: RunContext, details: Mapping[str, Any] | None = None, recorded_at: float | None = None) -> JournalRecord:
        records = cls.verify(path)
        body = {
            "sequence": len(records) + 1,
            "event_type": event_type,
            "run_key": asdict(context.key),
            "details": dict(details or {}),
            "previous_hash": records[-1]["record_hash"] if records else cls.GENESIS_HASH,
            "state_hash": cls.canonical_hash(context.to_dict()),
            "recorded_at": recorded_at if recorded_at is not None else time.time(),
        }
        record = {**body, "record_hash": cls.canonical_hash(body)}
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return JournalRecord(**record)


class ExecutionStore:
    def __init__(self, root: Path):
        self.root = root

    @staticmethod
    def safe_name(wu_id: str) -> str:
        normalized = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in wu_id)
        if not normalized or normalized in {".", ".."}:
            raise ValueError("invalid work-unit id")
        return normalized

    def state_path(self, wu_id: str) -> Path:
        return self.root / (self.safe_name(wu_id) + ".json")

    def journal_path(self, wu_id: str) -> Path:
        return self.root / (self.safe_name(wu_id) + ".events.jsonl")

    def save(self, context: RunContext) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        destination = self.state_path(context.key.wu_id)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.root, delete=False) as handle:
            json.dump(context.to_dict(), handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        os.replace(temporary, destination)

    def load(self, wu_id: str) -> RunContext:
        with self.state_path(wu_id).open("r", encoding="utf-8") as handle:
            return RunContext.from_dict(json.load(handle))

    def persist_event(self, context: RunContext, event_type: str, details: Mapping[str, Any] | None = None) -> None:
        self.save(context)
        ExecutionJournal.append(self.journal_path(context.key.wu_id), event_type=event_type, context=context, details=details)


@dataclass(frozen=True)
class WorkerProfile:
    actor_id: str
    roles: tuple[str, ...]
    tiers: dict[str, WorkerTier]
    preferred_complexity: tuple[WorkerTier, ...]
    cost_class: str
    context_strength: str = "standard"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "WorkerProfile":
        return cls(
            actor_id=str(data["actor_id"]),
            roles=tuple(str(item) for item in data.get("roles", [])),
            tiers={key: WorkerTier(value) for key, value in data.get("tiers", {}).items()},
            preferred_complexity=tuple(WorkerTier(item) for item in data.get("preferred_complexity", [])),
            cost_class=str(data.get("cost_class", "UNKNOWN_COST")),
            context_strength=str(data.get("context_strength", "standard")),
        )


_TIER_SCORE = {WorkerTier.LIGHT: 0, WorkerTier.STANDARD: 1, WorkerTier.HEAVY: 2}


def rank_worker_profiles(profiles: Sequence[WorkerProfile], *, role: str, complexity: WorkerTier, allowed_cost_classes: set[str]) -> list[WorkerProfile]:
    eligible = [profile for profile in profiles if role in profile.roles and profile.cost_class in allowed_cost_classes]

    def score(profile: WorkerProfile) -> tuple[int, int, int, str]:
        preferred_penalty = 0 if complexity in profile.preferred_complexity else 1
        declared_tier = profile.tiers.get(role, WorkerTier.STANDARD)
        underpowered = 1 if _TIER_SCORE[declared_tier] < _TIER_SCORE[complexity] else 0
        return (underpowered, preferred_penalty, abs(_TIER_SCORE[declared_tier] - _TIER_SCORE[complexity]), profile.actor_id)

    return sorted(eligible, key=score)


@dataclass(frozen=True)
class RuntimeRequest:
    run_key: RunKey
    objective: str
    role: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class RuntimeResult:
    returncode: int
    stdout: str
    stderr: str
    elapsed_seconds: float


class AgentRuntimeAdapter:
    def execute(self, request: RuntimeRequest, *, timeout_seconds: float) -> RuntimeResult:
        raise NotImplementedError


class CommandRuntimeAdapter(AgentRuntimeAdapter):
    def __init__(self, argv: Sequence[str], *, cwd: Path | None = None, env_allowlist: Sequence[str] = ()):
        if not argv or not all(str(item).strip() for item in argv):
            raise ValueError("adapter argv must contain non-empty entries")
        self.argv = tuple(str(item) for item in argv)
        self.cwd = cwd
        self.env_allowlist = tuple(env_allowlist)

    def execute(self, request: RuntimeRequest, *, timeout_seconds: float) -> RuntimeResult:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        request.run_key.validate()
        envelope = {"run_key": asdict(request.run_key), "objective": request.objective, "role": request.role, "payload": request.payload}
        env = {key: os.environ[key] for key in self.env_allowlist if key in os.environ}
        env.setdefault("PATH", os.environ.get("PATH", ""))
        started = time.monotonic()
        try:
            proc = subprocess.run(list(self.argv), input=json.dumps(envelope), text=True, capture_output=True, cwd=str(self.cwd) if self.cwd else None, env=env, timeout=timeout_seconds, check=False, shell=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeAdapterError(str(exc)) from exc
        return RuntimeResult(proc.returncode, proc.stdout, proc.stderr, time.monotonic() - started)


@dataclass(frozen=True)
class SupervisorDecision:
    action: str
    reason: str
    requires_new_generation: bool = False


class ExecutionSupervisor:
    @staticmethod
    def assess(context: RunContext) -> SupervisorDecision:
        if context.status == RunStatus.COMPLETE:
            return SupervisorDecision("NO_ACTION", "execution_complete")
        if context.status == RunStatus.BLOCKED:
            return SupervisorDecision("ESCALATE_BLOCKER", context.blocked_reason or "run_blocked")
        if context.status == RunStatus.COMPLETION_PENDING:
            assessment = CompletionGate.assess(context)
            if assessment.verdict == CompletionVerdict.MET:
                return SupervisorDecision("RUN_COMPLETION_EVALUATOR", "deterministic_completion_preflight_met")
            return SupervisorDecision("RESUME_EXECUTION", ";".join(assessment.reasons))
        guard = ResourceGuard.check(context)
        if not guard.allowed:
            if guard.reason in {"assistant_token_budget_exhausted", "active_time_budget_exhausted"}:
                return SupervisorDecision("PAUSE_BUDGET", guard.reason)
            if guard.reason == "unchanged_progress_limit_reached":
                return SupervisorDecision("RECONCILE_OR_FAILOVER", guard.reason, True)
            return SupervisorDecision("REMEDIATE_OR_FAILOVER", guard.reason or "guard_blocked", True)
        if context.status == RunStatus.BUDGET_LIMITED:
            return SupervisorDecision("NO_ACTION", "budget_limited")
        if context.status == RunStatus.PAUSED:
            return SupervisorDecision("NO_ACTION", "execution_paused")
        return SupervisorDecision("CONTINUE", "execution_within_bounds")
