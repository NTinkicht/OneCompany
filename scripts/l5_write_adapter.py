#!/usr/bin/env python3
"""Credential-isolated L5 write adapter with atomic CAS and replay safety."""
from __future__ import annotations

# Keep the pre-attestation surface to built-in/frozen modules only.
import os
import sys


def _load_bootstrap_runtime_from_source():
    """Load bootstrap source without consulting Python import/bytecode caches."""
    scripts = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(scripts)
    source_path = os.path.join(scripts, "control_plane_bootstrap.py")
    for parent in (root, scripts, os.path.join(root, ".l5")):
        if os.path.islink(parent) or not os.path.isdir(parent):
            raise RuntimeError("L5_BOOTSTRAP_RUNTIME_ROOT_INVALID")
    if os.path.islink(source_path) or not os.path.isfile(source_path):
        raise RuntimeError("L5_BOOTSTRAP_SOURCE_INVALID")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(source_path, flags)
    except OSError as exc:
        raise RuntimeError("L5_BOOTSTRAP_SOURCE_UNAVAILABLE") from exc
    try:
        info = os.fstat(fd)
        if (info.st_mode & 0o170000) != 0o100000:
            raise RuntimeError("L5_BOOTSTRAP_SOURCE_INVALID")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            source = handle.read()
    finally:
        os.close(fd)
    sys.dont_write_bytecode = True
    module = type(sys)("control_plane_bootstrap")
    module.__file__ = source_path
    module.__package__ = ""
    try:
        code = compile(source, source_path, "exec", dont_inherit=True)
        exec(code, module.__dict__)
    except Exception as exc:
        raise RuntimeError("L5_BOOTSTRAP_SOURCE_EXECUTION_FAILED") from exc
    runtime = module.__dict__.get("bootstrap_runtime")
    if not callable(runtime):
        raise RuntimeError("L5_BOOTSTRAP_RUNTIME_MISSING")
    sys.modules["control_plane_bootstrap"] = module
    return runtime


bootstrap_runtime = _load_bootstrap_runtime_from_source()
_bootstrap_ok, _bootstrap_reason = bootstrap_runtime()
if not _bootstrap_ok:
    raise RuntimeError(_bootstrap_reason)

# Import non-frozen stdlib with repository/PYTHONPATH entries excluded.
_scripts = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_scripts)
_saved_path = list(sys.path)
_env_paths = {os.path.abspath(entry) for entry in os.environ.get("PYTHONPATH", "").split(os.pathsep) if entry}
_blocked_paths = {os.path.abspath(_root), os.path.abspath(_scripts), os.path.abspath(os.getcwd()), *_env_paths}
try:
    sys.path[:] = [entry for entry in sys.path if entry and os.path.abspath(entry) not in _blocked_paths]
    import fcntl  # noqa: E402
    import json  # noqa: E402
    from pathlib import Path  # noqa: E402
    from typing import Any  # noqa: E402
finally:
    sys.path[:] = _saved_path

# Never accept a preloaded activation module. Bootstrap has removed local
# bytecode, so discarding this cache forces the current source to execute.
sys.modules.pop("l5_activation", None)
from l5_activation import (  # noqa: E402
    HARD_BOUNDARY_FIELDS,
    RETRYABLE_MUTATIONS,
    SAFE_MUTATIONS,
    TOKEN64,
    authorize_mutation,
    required_bool,
)

MUTATIONS = frozenset(SAFE_MUTATIONS.values())
REVIEW_SENSITIVE = frozenset({"dispatch_review", "merge_expected_head"})
_UNSET = object()


class LostResponse(Exception):
    """Raised when a write may have been applied but its response was lost."""


class AlreadyExists(Exception):
    """Raised by clients when an idempotent create already exists."""


class WriteRejected(Exception):
    """Raised only when the client proves the remote write was not applied."""


def _refresh_activation_api():
    """Re-attest and source-reload activation before reproducing a write."""
    ok, reason = bootstrap_runtime()
    if not ok:
        raise RuntimeError(str(reason))
    sys.modules.pop("l5_activation", None)
    import l5_activation as current
    if (
        current.HARD_BOUNDARY_FIELDS != HARD_BOUNDARY_FIELDS
        or current.RETRYABLE_MUTATIONS != RETRYABLE_MUTATIONS
        or current.SAFE_MUTATIONS != SAFE_MUTATIONS
        or current.TOKEN64.pattern != TOKEN64.pattern
    ):
        raise RuntimeError("L5_ACTIVATION_API_DRIFT")
    return current


def stream_key(auth: dict[str, Any], snapshot: dict[str, Any]) -> str:
    return json.dumps([snapshot.get("repository"), auth.get("issue"), auth.get("canonical_pr")], separators=(",", ":"))


def _blocked(reason: str, token: Any = None) -> dict[str, Any]:
    return {"status": "BLOCKED", "reason": reason, "mutation_token": token, "written": False}


def _live_gate(auth: dict[str, Any], stream: str, client: Any, store: Any, *, retry_check: bool, observed_retry: tuple[int, str | None] | None = None) -> str | None:
    boundaries = client.fetch_boundaries()
    if not isinstance(boundaries, dict): return "BOUNDARY_STATE_UNKNOWN"
    try:
        if any(required_bool(boundaries, key) for key in HARD_BOUNDARY_FIELDS): return "HARD_BOUNDARY"
    except ValueError: return "BOUNDARY_STATE_UNKNOWN"
    live = client.fetch_live(auth["canonical_pr"])
    if not isinstance(live, dict): return "LIVE_STATE_UNKNOWN"
    if live.get("head_sha") != auth["expected_head_sha"] or live.get("base_sha") != auth["expected_base_sha"]: return "STALE_HEAD_OR_BASE"
    mutation = auth["mutation"]; expected_state = "merged" if mutation == "reserve_next_wu" else "open"
    if live.get("pr_state") != expected_state: return "PR_STATE_MISMATCH"
    streams = live.get("open_streams")
    if not isinstance(streams, dict): return "LIVE_STATE_UNKNOWN"
    if mutation == "reserve_next_wu":
        if any(bool(prs) for prs in streams.values()): return "DUPLICATE_STREAM"
    elif streams.get(auth["issue"]) != [auth["canonical_pr"]] or sum(len(v) for v in streams.values()) != 1: return "DUPLICATE_STREAM"
    if mutation in REVIEW_SENSITIVE and live.get("review_eligible_nonauthor") is not True: return "REVIEWER_NOT_ELIGIBLE"
    if retry_check and mutation in RETRYABLE_MUTATIONS:
        prior_count, prior_scope = observed_retry if observed_retry is not None else store.retry_state(stream)
        scope = auth.get("retry_action_after"); expected = auth.get("retry_count_after")
        if (prior_count if prior_scope == scope else 0) + 1 != expected: return "RETRY_STATE_STALE"
    return None


def _params(auth):
    return {"canonical_pr":auth["canonical_pr"],"issue":auth["issue"],"expected_head_sha":auth["expected_head_sha"],"expected_base_sha":auth["expected_base_sha"],"selected_issue":auth.get("selected_issue"),"idempotency_key":auth["mutation_token"]}


def _reconcile(auth,client,store,*,written):
    token=auth["mutation_token"]
    if client.verify_effect(auth["mutation"],_params(auth)) is True:
        store.set_status(token,"COMPLETE"); return {"status":"COMPLETE","reason":"EFFECT_VERIFIED","mutation_token":token,"written":written}
    return {"status":"IN_PROGRESS","reason":"EFFECT_NOT_YET_VERIFIED","mutation_token":token,"written":written}


def _reproduce(auth,snapshot):
    try:
        current = _refresh_activation_api()
        reproduced=current.authorize_mutation(snapshot,enforce_control_plane=True)
    except (ValueError, RuntimeError):
        return False
    return reproduced==auth


def _persisted_record_matches(auth,record):
    return isinstance(record,dict) and record.get("mutation")==auth.get("mutation") and record.get("canonical_pr")==auth.get("canonical_pr") and record.get("expected_head_sha")==auth.get("expected_head_sha") and record.get("expected_base_sha")==auth.get("expected_base_sha")


def execute_mutation(auth,snapshot,client,store):
    token=auth.get("mutation_token") if isinstance(auth,dict) else None
    if not isinstance(auth,dict) or auth.get("authorized") is not True or auth.get("mutation_allowed") is not True: return _blocked("NOT_AUTHORIZED",token)
    if auth.get("mutation") not in MUTATIONS or not isinstance(token,str) or not TOKEN64.fullmatch(token): return _blocked("AUTHORIZATION_INVALID",token)
    stream=stream_key(auth,snapshot); prior=store.get(token)
    if prior:
        status=prior.get("status")
        if status in {"COMPLETE","PENDING"}:
            if not _persisted_record_matches(auth,prior): return _blocked("AUTHORIZATION_MISMATCH",token)
            if status=="COMPLETE": return {"status":"REPLAY_NOOP","reason":"ALREADY_COMPLETE","mutation_token":token,"written":False}
            return _reconcile(auth,client,store,written=False)
        if status!="RETRYABLE": return _blocked(f"PRIOR_{status}",token)
    if not _reproduce(auth,snapshot): return _blocked("AUTHORIZATION_MISMATCH",token)
    observed_retry=store.retry_state(stream) if auth["mutation"] in RETRYABLE_MUTATIONS else None
    observed_owner=store.retry_owner(stream) if auth["mutation"] in RETRYABLE_MUTATIONS else _UNSET
    reason=_live_gate(auth,stream,client,store,retry_check=True,observed_retry=observed_retry)
    if reason:return _blocked(reason,token)
    perform_cas=getattr(client,"perform_cas",None)
    if not callable(perform_cas):return _blocked("ATOMIC_CAS_UNAVAILABLE",token)
    record={"status":"PENDING","mutation":auth["mutation"],"canonical_pr":auth["canonical_pr"],"expected_head_sha":auth["expected_head_sha"],"expected_base_sha":auth["expected_base_sha"]}
    started=store.begin(token,record,stream,auth.get("retry_count_after"),auth.get("retry_action_after"),expected_retry=observed_retry,expected_owner=observed_owner)
    if not started:
        existing=store.get(token)
        if existing is not None and existing.get("status")=="PENDING": return {"status":"REPLAY_NOOP","reason":"TOKEN_ALREADY_PERSISTED","mutation_token":token,"written":False}
        return _blocked("RETRY_STATE_STALE",token)
    try: reason=_live_gate(auth,stream,client,store,retry_check=False)
    except Exception as exc:
        store.fail_and_restore(token,f"{type(exc).__name__}: {exc}",stream,observed_retry); return {"status":"FAILED","reason":"UNEXPECTED_ERROR","mutation_token":token,"written":False}
    if reason: store.fail_and_restore(token,reason,stream,observed_retry); return _blocked(reason,token)
    try:
        result=perform_cas(auth["mutation"],_params(auth))
        if result is False: raise WriteRejected("ATOMIC_CAS_REJECTED")
        if result is not True:return _reconcile(auth,client,store,written=False)
    except WriteRejected as exc:
        store.fail_and_restore(token,str(exc),stream,observed_retry); return {"status":"FAILED","reason":"WRITE_REJECTED","mutation_token":token,"written":False}
    except Exception:return _reconcile(auth,client,store,written=False)
    return _reconcile(auth,client,store,written=True)


class MemoryStore:
    def __init__(self): self.records={}; self.retry={}; self.retry_owners={}
    def get(self,token): return dict(self.records[token]) if token in self.records else None
    def begin(self,token,record,stream,count,action,*,expected_retry=None,expected_owner=_UNSET):
        existing=self.records.get(token)
        if existing is not None and existing.get("status")!="RETRYABLE":return False
        if count is not None:
            current=self.retry.get(stream,(0,None))
            if expected_retry is not None and current!=expected_retry:return False
            current_owner=self.retry_owners.get(stream)
            if expected_owner is not _UNSET and current_owner!=expected_owner:return False
            self.retry[stream]=(count,action); self.retry_owners[stream]=token
        self.records[token]=dict(record); return True
    def set_status(self,token,status):
        if token in self.records:self.records[token]["status"]=status
    def retry_state(self,stream):return self.retry.get(stream,(0,None))
    def retry_owner(self,stream):return self.retry_owners.get(stream)
    def fail_and_restore(self,token,reason,stream,prior_retry):
        record=self.records.get(token)
        if record is not None:record["status"]="RETRYABLE";record["reason"]=reason
        if prior_retry is not None and self.retry_owners.get(stream)==token:
            self.retry[stream]=prior_retry
            self.retry_owners[stream]=token


class FileStore(MemoryStore):
    def __init__(self,path):
        super().__init__();self.path=Path(path);self.lock_path=self.path.with_suffix(self.path.suffix+".lock");self.path.parent.mkdir(parents=True,exist_ok=True)
        if self.path.exists():self._reload()
    def _flush(self):
        tmp=self.path.with_suffix(self.path.suffix+f".{os.getpid()}.tmp")
        try:
            with tmp.open("w") as fh:
                json.dump({"records":self.records,"retry":self.retry,"retry_owners":self.retry_owners},fh,sort_keys=True)
                fh.flush();os.fsync(fh.fileno())
            os.replace(tmp,self.path)
        except Exception:
            try:tmp.unlink(missing_ok=True)
            except OSError:pass
            raise
        dir_fd=os.open(str(self.path.parent),os.O_RDONLY)
        try:os.fsync(dir_fd)
        finally:os.close(dir_fd)
    def begin(self,*args,**kwargs):
        with self._lock():self._reload();ok=super().begin(*args,**kwargs);self._flush() if ok else None;return ok
    def set_status(self,token,status):
        with self._lock():self._reload();super().set_status(token,status);self._flush()
    def fail_and_restore(self,token,reason,stream,prior_retry):
        with self._lock():self._reload();super().fail_and_restore(token,reason,stream,prior_retry);self._flush()
    def get(self,token):
        with self._lock():self._reload();return super().get(token)
    def retry_state(self,stream):
        with self._lock():self._reload();return super().retry_state(stream)
    def retry_owner(self,stream):
        with self._lock():self._reload();return super().retry_owner(stream)
    def _reload(self):
        if self.path.exists():
            data=json.loads(self.path.read_text());self.records=data.get("records",{});self.retry={k:tuple(v) for k,v in data.get("retry",{}).items()};self.retry_owners=data.get("retry_owners",{})
    def _lock(self):
        self.lock_path.touch(exist_ok=True);fh=self.lock_path.open("r+")
        class _Lock:
            def __enter__(self_nonlocal):fcntl.flock(fh.fileno(),fcntl.LOCK_EX);return fh
            def __exit__(self_nonlocal,*_):fcntl.flock(fh.fileno(),fcntl.LOCK_UN);fh.close()
        return _Lock()


JsonFileStore = FileStore
