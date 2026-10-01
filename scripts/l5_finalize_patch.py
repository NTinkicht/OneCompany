#!/usr/bin/env python3
"""One-shot final hardening patch for the L5 hostile-controller candidate."""
from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"missing patch anchor in {path}: {old[:120]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


# Keep every L5 authorization/write-boundary change inside hostile CI.
Path(".github/workflows/l5-hostile-controller-ci.yml").write_text(
    """name: L5 Hostile Controller Candidate CI

on:
  pull_request:
    paths:
      - 'scripts/l5_*.py'
      - 'tests/test_l5_*.py'
      - 'docs/L5-STATE-MACHINE-V1.md'
      - 'docs/L5-INTENT-RESTRAINT-V1.1.md'
      - '.github/workflows/l5-hostile-controller-ci.yml'

permissions:
  contents: read

concurrency:
  group: l5-hostile-controller-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: true

jobs:
  hostile-controller:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
        with:
          persist-credentials: false
      - uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97
        with:
          python-version: '3.12'
      - name: Kernel selftest
        run: python scripts/l5_kernel.py
      - name: Claude L5 unit, ledger, runner, and intent tests
        run: python -m unittest discover -s tests -p "test_l5_*.py"
      - name: S1-S30 hostile interleavings
        run: python scripts/l5_hostile_sim.py
      - name: S31-S40 intent and restraint hostile traces
        run: python scripts/l5_intent_hostile_sim.py
""",
    encoding="utf-8",
)

# Let the recovery planner authorize update_branch while refs remain exact/current.
replace_once(
    "scripts/l5_state_machine.py",
    '''    if _required_bool(evidence, "head_current") is not True or _required_bool(evidence, "base_current") is not True:
        result.update(state="IMPLEMENTING", next_action="RECONCILE_HEAD_BASE"); return result

    if merged:
''',
    '''    if _required_bool(evidence, "head_current") is not True or _required_bool(evidence, "base_current") is not True:
        result.update(state="IMPLEMENTING", next_action="RECONCILE_HEAD_BASE"); return result

    behind_base = evidence.get("behind_base", False)
    if type(behind_base) is not bool:
        raise ValueError("L5_STATE_BEHIND_BASE_UNKNOWN")
    if not merged and behind_base:
        result.update(state="IMPLEMENTING", next_action="RECONCILE_HEAD_BASE"); return result

    if merged:
''',
)

# Make lease release state explicit and make MERGE_LOCKED exit a store-level invariant.
replace_once(
    "scripts/l5_kernel.py",
    '''    version: int
    intent: Intent | None = None
''',
    '''    version: int
    intent: Intent | None = None
    state: str = "ACTIVE"
''',
)
replace_once(
    "scripts/l5_kernel.py",
    '''        human_clear: bool = False,
    ) -> bool: ...
''',
    '''        human_clear: bool = False,
        post_merge_verified: bool = False,
    ) -> bool: ...
''',
)
replace_once(
    "scripts/l5_kernel.py",
    '''        human_clear: bool = False,
    ) -> bool:
        """CAS repo mode while enforcing human-only exits."""
''',
    '''        human_clear: bool = False,
        post_merge_verified: bool = False,
    ) -> bool:
        """CAS repo mode while enforcing protected exits."""
''',
)
replace_once(
    "scripts/l5_kernel.py",
    '''        if old_mode in HUMAN_CLEAR_ONLY and old_mode != mode and not human_clear:
            return False
        self.modes[repo_id] = (mode, 1 if cur is None else cur[1] + 1)
''',
    '''        if old_mode in HUMAN_CLEAR_ONLY and old_mode != mode and not human_clear:
            return False
        if old_mode == RepoMode.MERGE_LOCKED and old_mode != mode and not post_merge_verified:
            return False
        self.modes[repo_id] = (mode, 1 if cur is None else cur[1] + 1)
''',
)
replace_once(
    "scripts/l5_kernel.py",
    '''    if ttl <= 0 or now_srv >= lease.expires_at:
        return None
    cur = store.read(lease.key)
    if cur != lease or cur.holder != lease.holder or cur.epoch != lease.epoch:
        return None
    nxt = replace(lease, expires_at=now_srv + ttl, version=lease.version + 1)
''',
    '''    if ttl <= 0 or now_srv >= lease.expires_at or lease.state != "ACTIVE":
        return None
    new_expires_at = now_srv + ttl
    if new_expires_at <= lease.expires_at:
        return None
    cur = store.read(lease.key)
    if cur != lease or cur.holder != lease.holder or cur.epoch != lease.epoch or cur.state != "ACTIVE":
        return None
    nxt = replace(lease, expires_at=new_expires_at, version=lease.version + 1)
''',
)
replace_once(
    "scripts/l5_kernel.py",
    '''    if operation not in DANGEROUS | HARMLESS or now_srv >= lease.expires_at:
        return None
''',
    '''    if operation not in DANGEROUS | HARMLESS or now_srv >= lease.expires_at or lease.state != "ACTIVE":
        return None
''',
)
replace_once(
    "scripts/l5_kernel.py",
    '''def release(store: CASStore, lease: Lease, *, now_srv: float) -> Lease | None:
    """Expire only the exact current lease after any intent is terminal."""
    cur = store.read(lease.key)
    if cur != lease:
        return None
    if cur.intent is not None and cur.intent.state == "PENDING":
        return None
    nxt = replace(cur, expires_at=now_srv, version=cur.version + 1)
    return nxt if store.cas(cur.key, cur.version, nxt) else None
''',
    '''def verify_intent(store: CASStore, lease: Lease) -> Lease | None:
    """Durably mark a completed main-changing intent as post-merge verified."""
    cur = store.read(lease.key)
    if cur != lease or cur.intent is None or cur.intent.state != "DONE":
        return None
    nxt = replace(cur, intent=replace(cur.intent, state="VERIFIED"), version=cur.version + 1)
    return nxt if store.cas(cur.key, cur.version, nxt) else None


def release(store: CASStore, lease: Lease, *, now_srv: float) -> Lease | None:
    """Release only the exact current lease after any intent is terminal."""
    cur = store.read(lease.key)
    if cur != lease or cur.state != "ACTIVE":
        return None
    if cur.intent is not None and cur.intent.state == "PENDING":
        return None
    nxt = replace(cur, expires_at=now_srv, version=cur.version + 1, state="RELEASED")
    return nxt if store.cas(cur.key, cur.version, nxt) else None
''',
)
replace_once(
    "scripts/l5_kernel.py",
    '''    if cur != lease:
        return False, "LEASE_LOST"
    if now_srv + max_write_latency + skew_margin >= cur.expires_at:
''',
    '''    if cur != lease:
        return False, "LEASE_LOST"
    if cur.state != "ACTIVE":
        return False, "LEASE_RELEASED"
    if now_srv + max_write_latency + skew_margin >= cur.expires_at:
''',
)

replace_once(
    "scripts/l5_ledger.py",
    'if row.get("state") not in {"PENDING", "DONE", "ABORTED"}:',
    'if row.get("state") not in {"PENDING", "DONE", "ABORTED", "VERIFIED"}:',
)
replace_once(
    "scripts/l5_ledger.py",
    '''    new_mode: RepoMode,
    human_clear: bool = False,
) -> dict[str, Any]:
    """CAS repository mode while enforcing human-only exits."""
''',
    '''    new_mode: RepoMode,
    human_clear: bool = False,
    post_merge_verified: bool = False,
) -> dict[str, Any]:
    """CAS repository mode while enforcing protected exits."""
''',
)
replace_once(
    "scripts/l5_ledger.py",
    '''    if old in HUMAN_CLEAR_ONLY and old != new_mode and not human_clear:
        raise LedgerConflict("HUMAN_CLEAR_REQUIRED")
    out["mode"] = new_mode.value
''',
    '''    if old in HUMAN_CLEAR_ONLY and old != new_mode and not human_clear:
        raise LedgerConflict("HUMAN_CLEAR_REQUIRED")
    if old == RepoMode.MERGE_LOCKED and old != new_mode and not post_merge_verified:
        raise LedgerConflict("POST_MERGE_VERIFICATION_REQUIRED")
    out["mode"] = new_mode.value
''',
)
replace_once(
    "scripts/l5_ledger.py",
    '''    if cur.get("state") == "ACTIVE" and row.get("state") == "RELEASED":
        intent = row.get("intent")
        if isinstance(intent, Mapping) and intent.get("state") == "PENDING":
            raise LedgerConflict("PENDING_INTENT_RELEASE")
''',
    '''    if isinstance(cur_intent, Mapping) and cur_intent.get("state") == "DONE" and same_owner_epoch:
        if not isinstance(next_intent, Mapping):
            raise LedgerConflict("DONE_INTENT_LOST")
        for field in ("op_id", "idem_key", "operation", "expected_head", "expected_base", "epoch"):
            if next_intent.get(field) != cur_intent.get(field):
                raise LedgerConflict("DONE_INTENT_MUTATED")
        if next_intent.get("state") not in {"DONE", "VERIFIED"}:
            raise LedgerInvalid("DONE_INTENT_TRANSITION")

    if cur.get("state") == "RELEASED" and same_owner_epoch and row.get("state") != "RELEASED":
        raise LedgerConflict("RELEASED_LEASE_REACTIVATION")

    if cur.get("state") == "ACTIVE" and row.get("state") == "RELEASED":
        intent = row.get("intent")
        if isinstance(intent, Mapping) and intent.get("state") == "PENDING":
            raise LedgerConflict("PENDING_INTENT_RELEASE")
''',
)

replace_once(
    "scripts/l5_ledger_store.py",
    '''            version=row["version"],
            intent=cls._intent_from_record(row.get("intent")),
        )
''',
    '''            version=row["version"],
            intent=cls._intent_from_record(row.get("intent")),
            state=row["state"],
        )
''',
)
replace_once(
    "scripts/l5_ledger_store.py",
    '''        """Serialize a lease, preserving released tombstones monotonically."""
        state = "ACTIVE"
        if current is not None:
            same_epoch = (
                lease.epoch == current.get("epoch")
                and lease.holder == current.get("holder")
            )
            terminal = lease.intent is None or lease.intent.state != "PENDING"
            if (
                same_epoch
                and current.get("state") == "ACTIVE"
                and terminal
                and lease.expires_at < float(current.get("expires_at", lease.expires_at))
            ):
                state = "RELEASED"
            elif current.get("state") == "RELEASED" and lease.epoch == current.get("epoch"):
                state = "RELEASED"

        return {
''',
    '''        """Serialize a lease with an explicit ACTIVE/RELEASED state."""
        if lease.state not in {"ACTIVE", "RELEASED"}:
            raise ValueError("L5_LEASE_STATE_INVALID")
        return {
''',
)
replace_once(
    "scripts/l5_ledger_store.py",
    '            "state": state,',
    '            "state": lease.state,',
)
replace_once(
    "scripts/l5_ledger_store.py",
    '''        human_clear: bool = False,
    ) -> bool:
        """CAS repository mode through mode version plus GitHub blob identity."""
''',
    '''        human_clear: bool = False,
        post_merge_verified: bool = False,
    ) -> bool:
        """CAS repository mode through mode version plus GitHub blob identity."""
''',
)
replace_once(
    "scripts/l5_ledger_store.py",
    '''                new_mode=mode,
                human_clear=human_clear,
            )
''',
    '''                new_mode=mode,
                human_clear=human_clear,
                post_merge_verified=post_merge_verified,
            )
''',
)

# Bind verification to the exact merge intent, preserve MERGE_LOCKED freezes,
# and turn deterministic authorization errors into BLOCKED results.
replace_once(
    "scripts/l5_controller.py",
    '''    governance_mode,
    intent_recovery,''',
    '''    governance_mode,
    idem_key,
    intent_recovery,''',
)
replace_once(
    "scripts/l5_controller.py",
    '''    resolve_intent,
)''',
    '''    resolve_intent,
    verify_intent,
)''',
)
replace_once(
    "scripts/l5_controller.py",
    '''        current = store.read(key)
        if current is not None and current.expires_at > now:
            continue
''',
    '''        current = store.read(key)
        if current is not None and (
            current.expires_at > now
            or (current.intent is not None and current.intent.state == "PENDING")
        ):
            continue
''',
)
replace_once(
    "scripts/l5_controller.py",
    '''def _find_merged_unverified(
    io: ControllerIO,
    items: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    """Return exactly one merged-unverified item while the repo is locked."""
    found = [
        item
        for item in items
        if classify_item(item, io.budget_for(item)) == ItemState.MERGED_UNVERIFIED
    ]
    if len(found) != 1:
        return None
    return found[0]
''',
    '''def _find_merged_unverified(
    repo_id: str,
    lock: Lease,
    io: ControllerIO,
    items: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    """Return the merged-unverified item bound to the durable merge intent."""
    if lock.intent is None or lock.intent.operation not in {"merge", "revert"}:
        return None
    found = []
    for item in items:
        if classify_item(item, io.budget_for(item)) != ItemState.MERGED_UNVERIFIED:
            continue
        item_id = _item_id(item)
        bound = idem_key(
            repo_id,
            item_id,
            lock.intent.expected_head,
            lock.intent.expected_base,
            lock.intent.operation,
        )
        if bound == lock.intent.idem_key:
            found.append(item)
    return found[0] if len(found) == 1 else None
''',
)
replace_once(
    "scripts/l5_controller.py",
    '''    item = _find_merged_unverified(io, items)
    if item is None:
        return RunResult(
            rid,
            RunPhase.POST_MERGE_VERIFY,
            "WAIT",
            reason="MERGE_LOCK_RECONCILIATION_REQUIRED",
        )

    item_id = _item_id(item)
    lock_key = repo_merge_lock_key(repo_id)
    lock = store.read(lock_key)
    if (
        lock is None
        or lock.intent is None
        or lock.intent.state != "DONE"
        or lock.intent.operation not in {"merge", "revert"}
    ):
''',
    '''    lock_key = repo_merge_lock_key(repo_id)
    lock = store.read(lock_key)
    if (
        lock is None
        or lock.intent is None
        or lock.intent.state not in {"DONE", "VERIFIED"}
        or lock.intent.operation not in {"merge", "revert"}
    ):
        return RunResult(
            rid,
            RunPhase.POST_MERGE_VERIFY,
            "WAIT",
            reason="MERGE_LOCK_EVIDENCE_INVALID",
        )

    item = _find_merged_unverified(repo_id, lock, io, items)
    if item is None:
        return RunResult(
            rid,
            RunPhase.POST_MERGE_VERIFY,
            "WAIT",
            reason="MERGE_LOCK_RECONCILIATION_REQUIRED",
        )

    item_id = _item_id(item)
    if (
        lock.intent.idem_key
        != idem_key(
            repo_id,
            item_id,
            lock.intent.expected_head,
            lock.intent.expected_base,
            lock.intent.operation,
        )
    ):
''',
)
replace_once(
    "scripts/l5_controller.py",
    '''    release_now = _trusted_now(io)
    released = release(store, lock, now_srv=release_now)
    if released is None:
        return RunResult(
            rid,
            RunPhase.POST_MERGE_VERIFY,
            "WAIT",
            item_id=item_id,
            reason="MERGE_LOCK_RELEASE_CAS_FAILED",
        )

    current_mode, mode_version = store.read_repo_mode(repo_id)
''',
    '''    if lock.intent.state == "DONE":
        verified = verify_intent(store, lock)
        if verified is None:
            return RunResult(
                rid,
                RunPhase.POST_MERGE_VERIFY,
                "WAIT",
                item_id=item_id,
                reason="POST_MERGE_VERIFY_CAS_FAILED",
            )
        lock = verified

    release_now = _trusted_now(io)
    released = release(store, lock, now_srv=release_now)
    if released is None:
        return RunResult(
            rid,
            RunPhase.POST_MERGE_VERIFY,
            "WAIT",
            item_id=item_id,
            reason="MERGE_LOCK_RELEASE_CAS_FAILED",
        )

    current_mode, mode_version = store.read_repo_mode(repo_id)
''',
)
replace_once(
    "scripts/l5_controller.py",
    '''    if not store.cas_repo_mode(repo_id, mode_version, target_mode):
''',
    '''    if not store.cas_repo_mode(
        repo_id,
        mode_version,
        target_mode,
        post_merge_verified=True,
    ):
''',
)
replace_once(
    "scripts/l5_controller.py",
    '''            if current_mode not in HUMAN_CLEAR_ONLY:
                store.cas_repo_mode(repo_id, version, derived)
''',
    '''            if current_mode not in HUMAN_CLEAR_ONLY and current_mode != RepoMode.MERGE_LOCKED:
                store.cas_repo_mode(repo_id, version, derived)
''',
)
replace_once(
    "scripts/l5_controller.py",
    '''        auth = authorize_mutation(snapshot)
        expected = {
''',
    '''        try:
            auth = authorize_mutation(snapshot)
        except ValueError as exc:
            return {
                "status": "BLOCKED",
                "reason": f"AUTHORIZATION_INVALID:{exc}",
            }
        expected = {
''',
)

# Strengthen the intent/restraint hostile oracle.
replace_once(
    "scripts/l5_intent_hostile_sim.py",
    '''def scenario(sid: int, rng: random.Random):
    snap = valid(rng); ev = dict(snap["intent_restraint"]); snap["intent_restraint"] = ev
''',
    '''def scenario(sid: int, rng: random.Random):
    snap = valid(rng)
    assert intent_restraint_status(snap) == ("PASS", ()), sid
    ev = dict(snap["intent_restraint"]); snap["intent_restraint"] = ev
''',
)
replace_once(
    "scripts/l5_intent_hostile_sim.py",
    '''    else: raise AssertionError(sid)
    state, reasons = intent_restraint_status(snap)
    assert state == "FAILED" and reasons, (sid, state, reasons)
''',
    '''    else: raise AssertionError(sid)
    expected = {
        31: "INTENT_DRIFT",
        32: "INTENT_DRIFT",
        33: "INTENT_DRIFT",
        34: "SELF_REVIEW",
        35: "OVERENGINEERED",
        36: "PERFORMANCE_REGRESSION",
        37: "SEMANTIC_CHANGE",
        38: "DIFF_DISPROPORTIONATE",
        39: "UNRESOLVED_DELETION_CANDIDATES",
        40: "ATTESTATION_INCOMPLETE",
    }[sid]
    state, reasons = intent_restraint_status(snap)
    assert state == "FAILED", (sid, state, reasons)
    assert expected in reasons, (sid, reasons)
''',
)

# Regression tests for the new durable invariants.
replace_once(
    "tests/test_l5_controller.py",
    '''    def test_deterministic_selection_prefers_repair_over_review(self):
''',
    '''    def test_merge_locked_survives_governance_drift(self):
        """A live governance freeze cannot erase pending post-merge verification."""
        store = MemoryCASStore()
        store.modes["repo"] = (RepoMode.MERGE_LOCKED, 3)
        io = FakeIO(repo_snapshot(rulesets_or_protection_active=False))
        result = run_once("repo", io, store)
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(result.reason, "GOVERNANCE_DRIFT")
        self.assertEqual(store.read_repo_mode("repo")[0], RepoMode.MERGE_LOCKED)

    def test_bridge_invalid_authorization_is_blocked(self):
        """Pre-write authorization errors abort through the normal BLOCKED path."""
        obs = Observation("a" * 40, "b" * 40)
        intent = Intent("op", "f" * 64, "ci_rerun", obs.head, obs.base, 1)
        lease = Lease("k", "run", 1, obs, 0.0, 300.0, 1, intent)
        bridge = GuardedWriteBridge(object(), object())
        result = bridge.execute_guarded("retry_ci", {"activation_snapshot": {}}, lease)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertTrue(result["reason"].startswith("AUTHORIZATION_INVALID:"))

    def test_expired_pending_lease_does_not_starve_other_work(self):
        """An expired PENDING lease is skipped instead of being reselected forever."""
        blocked = {
            "item_id": "9",
            "head_sha": "a" * 40,
            "base_sha": "b" * 40,
            "ci": "DETERMINISTIC_FAILED",
        }
        other = {
            "item_id": "1",
            "head_sha": "a" * 40,
            "base_sha": "b" * 40,
            "ci": "GREEN",
            "independent_review_pass": False,
        }
        store = MemoryCASStore()
        obs = Observation("a" * 40, "b" * 40)
        key = lease_key("repo", "item", "9", "REMEDIATE_REVIEW")
        lease = acquire(store, key, "old", obs, now_srv=0.0, ttl=1.0)
        self.assertIsNotNone(lease)
        pending = attach_intent(store, lease, "repo", "9", "push", now_srv=0.5)
        self.assertIsNotNone(pending)
        io = FakeIO(items=[blocked, other])
        io.clock = 2.0
        result = run_once("repo", io, store)
        self.assertEqual(result.item_id, "1")
        self.assertEqual(result.action, "dispatch_review")

    def test_deterministic_selection_prefers_repair_over_review(self):
''',
)
replace_once(
    "tests/test_l5_ledger.py",
    '''    def test_lease_delete_forbidden(self):
''',
    '''    def test_merge_locked_exit_requires_post_merge_verification(self):
        doc = base_doc()
        doc["mode"] = "MERGE_LOCKED"
        doc["human_clear_required"] = False
        with self.assertRaises(LedgerConflict):
            cas_mode(doc, expected_revision=0, expected_mode_version=1, new_mode=RepoMode.NORMAL)
        out = cas_mode(
            doc,
            expected_revision=0,
            expected_mode_version=1,
            new_mode=RepoMode.NORMAL,
            post_merge_verified=True,
        )
        self.assertEqual(out["mode"], "NORMAL")

    def test_lease_delete_forbidden(self):
''',
)
replace_once(
    "tests/test_l5_ledger_store.py",
    '''    def test_blob_race_rejects_stale_write(self):
''',
    '''    def test_release_after_ttl_is_still_a_released_tombstone(self):
        """Late terminal release is explicitly persisted as RELEASED."""
        backend = FakeBackend(empty_ledger())
        store = DurableLedgerCASStore("repo", backend)
        obs = Observation("a" * 40, "b" * 40)
        lease = acquire(store, "k", "run-1", obs, now_srv=1, ttl=5)
        intended = attach_intent(store, lease, "repo", "1", "push", now_srv=2)
        done = resolve_intent(store, intended, "DONE")
        released = release(store, done, now_srv=10)
        self.assertIsNotNone(released)
        self.assertEqual(backend.doc["leases"]["k"]["state"], "RELEASED")

    def test_merge_locked_mode_exit_needs_verified_transition(self):
        """The durable ledger refuses an unverified MERGE_LOCKED exit."""
        doc = empty_ledger()
        doc["mode"] = "MERGE_LOCKED"
        backend = FakeBackend(doc)
        store = DurableLedgerCASStore("repo", backend)
        self.assertFalse(store.cas_repo_mode("repo", 1, RepoMode.NORMAL))
        self.assertTrue(
            store.cas_repo_mode(
                "repo",
                1,
                RepoMode.NORMAL,
                post_merge_verified=True,
            )
        )

    def test_blob_race_rejects_stale_write(self):
''',
)

print("L5 final hardening patch applied")
