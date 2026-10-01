import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from l5_kernel import MemoryCASStore, Observation, RepoMode, acquire, attach_intent, fence_ok, new_run_id


def test_only_one_live_holder():
    s = MemoryCASStore(); o = Observation("a" * 40, "b" * 40)
    first = acquire(s, "r:p:1:MERGE", new_run_id(), o, now=1000)
    assert first is not None
    assert acquire(s, "r:p:1:MERGE", new_run_id(), o, now=1001) is None


def test_changed_head_fails_fence():
    s = MemoryCASStore(); o = Observation("a" * 40, "b" * 40)
    lease = acquire(s, "r:p:1:MERGE", new_run_id(), o, now=1000)
    lease = attach_intent(s, lease, "r", "p:1", "merge")
    ok, reason = fence_ok(s, "r", lease, Observation("c" * 40, "b" * 40), now=1010)
    assert not ok and reason == "OBSERVATION_CHANGED"


def test_freeze_blocks_merge():
    s = MemoryCASStore(); o = Observation("a" * 40, "b" * 40)
    lease = acquire(s, "r:p:1:MERGE", new_run_id(), o, now=1000)
    lease = attach_intent(s, lease, "r", "p:1", "merge")
    s.modes["r"] = RepoMode.GOVERNANCE_DRIFT
    ok, reason = fence_ok(s, "r", lease, o, now=1010)
    assert not ok and reason == "REPO_MODE_GOVERNANCE_DRIFT"


def test_intent_required():
    s = MemoryCASStore(); o = Observation("a" * 40, "b" * 40)
    lease = acquire(s, "r:p:1:MERGE", new_run_id(), o, now=1000)
    ok, reason = fence_ok(s, "r", lease, o, now=1010)
    assert not ok and reason == "INTENT_INVALID"
