#!/usr/bin/env python3
"""Provider-neutral *admission plan* below OneCompany's canonical WU lease.

This is not a new orchestrator, an execution entrypoint or a lease verifier.
A trusted parent must derive snapshots from the live ledger/current GitHub
state; never accept model- or PR-supplied snapshots as authorization.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

from execution_core import RunKey

SHA = re.compile(r"[0-9a-f]{40}\Z")
SEAMS = frozenset({
    "native", "memory", "context", "model_endpoint", "runtime_capability",
    "workspace", "ui_assurance", "telemetry", "skill", "deployment",
})
FORBIDDEN_TOOLS = frozenset({
    "grant_lease", "review_own_code", "approve_pr", "merge_pr",
    "change_budget", "change_credentials", "deploy_production",
})
COST_CLASSES = frozenset({"HUMAN", "INCLUDED_SUBSCRIPTION", "FREE_ALLOWANCE", "LOCAL"})


@dataclass(frozen=True)
class HarnessIntent:
    """Untrusted candidate invocation request, never a policy grant."""
    key: RunKey
    project: str
    actor: str
    capability: str
    head: str
    base: str
    tools: frozenset[str]
    provider_seam: str = "native"
    requested_extra_spend: int = 0


@dataclass(frozen=True)
class TrustedHarnessSnapshot:
    """Values the caller must resolve from trusted, current platform evidence.

    Creating this dataclass does NOT establish ledger trust on its own.
    """
    key: RunKey
    project: str
    head: str
    base: str
    lease_actor: str
    lease_capability: str
    lease_active: bool
    permitted_tools: frozenset[str]
    actor_verified: bool
    actor_cost_class: str
    stop_active: bool
    extra_spend_cap: int
    provider_available: bool = True


@dataclass(frozen=True)
class HarnessAdmission:
    """Pure, side-effect-free decision; never substitutes for GitHub/lease gate."""
    permitted: bool
    code: str
    reason: str


def deny(code: str) -> HarnessAdmission:
    """Return a stable non-leaking refusal."""
    return HarnessAdmission(False, code, code.lower().replace("_", " "))


def assess_intent(intent: HarnessIntent, snapshot: TrustedHarnessSnapshot, *, provider_configuration: Mapping[str, bool] | None = None) -> HarnessAdmission:
    """Refuse stale or overprivileged requests without invoking a provider."""
    try:
        intent.key.validate()
        snapshot.key.validate()
    except (ValueError, TypeError, AttributeError):
        return deny("INVALID_RUN_KEY")
    # Trusted flags cross the admission boundary. Type annotations are not
    # runtime enforcement: reject non-bools before any truthiness decision.
    if any(type(value) is not bool for value in (
        snapshot.stop_active,
        snapshot.lease_active,
        snapshot.actor_verified,
        snapshot.provider_available,
    )):
        return deny("INVALID_TRUSTED_SNAPSHOT")
    if snapshot.stop_active:
        return deny("EMERGENCY_STOP")
    if not snapshot.lease_active:
        return deny("LEASE_NOT_ACTIVE")
    if intent.key != snapshot.key:
        return deny("STALE_GENERATION")
    if not intent.project or intent.project != snapshot.project:
        return deny("WRONG_PROJECT")
    if not intent.actor or intent.actor != snapshot.lease_actor:
        return deny("WRONG_ACTOR")
    if not intent.capability or intent.capability != snapshot.lease_capability:
        return deny("CAPABILITY_NOT_LEASED")
    if not SHA.fullmatch(intent.head or "") or not SHA.fullmatch(intent.base or ""):
        return deny("INVALID_REVISION")
    if intent.head == intent.base:
        return deny("NONDISTINCT_REVISIONS")
    if intent.head != snapshot.head or intent.base != snapshot.base:
        return deny("STALE_REVISION")
    if not snapshot.actor_verified:
        return deny("ACTOR_NOT_VERIFIED")
    if snapshot.actor_cost_class not in COST_CLASSES:
        return deny("COST_CLASS_BLOCKED")
    if (type(intent.requested_extra_spend) is not int or type(snapshot.extra_spend_cap) is not int or intent.requested_extra_spend != 0 or snapshot.extra_spend_cap != 0):
        return deny("EXTRA_SPEND_BLOCKED")
    if not isinstance(intent.tools, frozenset) or not isinstance(snapshot.permitted_tools, frozenset):
        return deny("INVALID_TOOL_SCOPE")
    if not intent.tools or not intent.tools.issubset(snapshot.permitted_tools):
        return deny("TOOL_SCOPE_BLOCKED")
    if intent.tools & FORBIDDEN_TOOLS:
        return deny("GOVERNANCE_TOOL_BLOCKED")
    if intent.provider_seam not in SEAMS:
        return deny("UNKNOWN_PROVIDER_SEAM")
    if not snapshot.provider_available:
        return deny("PROVIDER_UNAVAILABLE")
    if provider_configuration is None:
        configured: Mapping[str, bool] = {"native": True}
    elif not isinstance(provider_configuration, Mapping):
        return deny("INVALID_PROVIDER_CONFIGURATION")
    else:
        configured = provider_configuration
    if configured.get(intent.provider_seam) is not True:
        return deny("PROVIDER_NOT_CONFIGURED")
    return HarnessAdmission(True, "ADMITTED_FOR_TRUSTED_PARENT", "candidate matches current supplied snapshot; parent must still enforce real lease, permissions and budget at execution time")
