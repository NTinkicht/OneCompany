#!/usr/bin/env python3
"""Dependency-free pre-import trust boundary for future ACTIVE L5 execution."""
from __future__ import annotations
import os, sys
_BOOTSTRAP_SOURCE=os.path.abspath(__file__); _BOOTSTRAP_SCRIPTS=os.path.dirname(_BOOTSTRAP_SOURCE); _BOOTSTRAP_ROOT=os.path.dirname(_BOOTSTRAP_SCRIPTS)
_ORIGINAL_SYS_PATH=list(sys.path); _PYTHONPATH_ENTRIES={os.path.abspath(e) for e in os.environ.get("PYTHONPATH","").split(os.pathsep) if e}
_BLOCKED_IMPORT_ROOTS={os.path.abspath(_BOOTSTRAP_ROOT),os.path.abspath(_BOOTSTRAP_SCRIPTS),os.path.abspath(os.getcwd()),*_PYTHONPATH_ENTRIES}
try:
 sys.path[:]=[e for e in sys.path if e and os.path.abspath(e) not in _BLOCKED_IMPORT_ROOTS]
 import hashlib,json,re,subprocess
 from pathlib import Path
 from typing import Mapping
finally: sys.path[:]=_ORIGINAL_SYS_PATH
SOURCE_FILE=Path(_BOOTSTRAP_SOURCE); ROOT=SOURCE_FILE.parent.parent; MANIFEST=ROOT/".l5"/"control-plane.json"; SHA40=re.compile(r"^[0-9a-f]{40}$"); PY_SOURCE=re.compile(r"^scripts/(?:[^/]+/)*[^/]+\.py$"); BOOTSTRAP_PATH="scripts/control_plane_bootstrap.py"
TRUSTED_CONTROL_REFS=frozenset({"88d2c6632543d937add00e1e9da493a260638057"}); _ATTESTATION:tuple[str,str]|None=None

def _manifest_path(path:Path|None=None)->Path:
 if path is not None:return path
 override=os.environ.get("L5_CONTROL_PLANE_MANIFEST"); return Path(override) if override else MANIFEST

def _assert_regular_runtime_roots(root:Path)->None:
 for path in (root,root/"scripts",root/".l5"):
  try:
   if path.is_symlink() or not path.is_dir():raise RuntimeError("L5_BOOTSTRAP_RUNTIME_ROOT_INVALID")
  except OSError as exc:raise RuntimeError("L5_BOOTSTRAP_RUNTIME_ROOT_UNVERIFIABLE") from exc

def _walk_python_tree(scripts:Path)->tuple[list[Path],list[Path]]:
 sources=[];caches=[]
 try:
  for directory,dirnames,filenames in os.walk(scripts,followlinks=False):
   current=Path(directory)
   if current.is_symlink() or not current.is_dir():raise RuntimeError("L5_BOOTSTRAP_RUNTIME_SOURCE_INVALID")
   for dirname in list(dirnames):
    child=current/dirname
    if child.is_symlink() or not child.is_dir():raise RuntimeError("L5_BOOTSTRAP_RUNTIME_SOURCE_INVALID")
   for filename in filenames:
    path=current/filename
    if path.is_symlink() or not path.is_file():raise RuntimeError("L5_BOOTSTRAP_RUNTIME_SOURCE_INVALID")
    if filename.endswith(".py"):sources.append(path)
    elif filename.endswith(".pyc"):caches.append(path)
 except OSError as exc:raise RuntimeError("L5_BOOTSTRAP_RUNTIME_SOURCE_UNAVAILABLE") from exc
 return sorted(sources),sorted(caches)

def prepare_source_only_l5_imports(root:Path|None=None)->None:
 runtime_root=root or ROOT;_assert_regular_runtime_roots(runtime_root)
 if sys.pycache_prefix is not None:raise RuntimeError("L5_BOOTSTRAP_PYCACHE_PREFIX_REDIRECTED")
 _sources,caches=_walk_python_tree(runtime_root/"scripts")
 try:
  for path in caches:path.unlink()
 except OSError as exc:raise RuntimeError("L5_BOOTSTRAP_BYTECODE_CLEAN_FAILED") from exc
 sys.dont_write_bytecode=True

def _git_executable()->str:
 override=os.environ.get("L5_GIT_EXECUTABLE")
 if override:
  p=Path(override)
  if p.is_absolute() and p.is_file():return str(p)
  raise RuntimeError("L5_BOOTSTRAP_GIT_EXECUTABLE_INVALID")
 for p in (Path("/usr/bin/git"),Path("/usr/local/bin/git")):
  if p.is_file():return str(p)
 raise RuntimeError("L5_BOOTSTRAP_GIT_EXECUTABLE_UNAVAILABLE")

def _git_env()->dict[str,str]:
 clean={k:v for k in ("SYSTEMROOT","WINDIR") if (v:=os.environ.get(k))};clean.update({"GIT_NO_REPLACE_OBJECTS":"1","GIT_CONFIG_NOSYSTEM":"1","GIT_CONFIG_GLOBAL":os.devnull});return clean

def _git(control_root:Path,*args:str)->subprocess.CompletedProcess[str]:
 return subprocess.run([_git_executable(),"--no-replace-objects","-C",str(control_root),*args],text=True,capture_output=True,check=False,timeout=10,env=_git_env())

def _git_blob_sha(content:bytes)->str:return hashlib.sha1(f"blob {len(content)}\0".encode("ascii")+content).hexdigest()
def _control_repository_root()->Path:
 override=os.environ.get("L5_CONTROL_REPOSITORY_ROOT");return Path(override).absolute() if override else ROOT

def _certified_runtime(control_ref:str)->dict[str,str]:
 if control_ref not in TRUSTED_CONTROL_REFS:raise RuntimeError("L5_BOOTSTRAP_CONTROL_REF_NOT_TRUSTED")
 root=_control_repository_root();_assert_regular_runtime_roots(root)
 try:commit=_git(root,"cat-file","-e",f"{control_ref}^{{commit}}");tree=_git(root,"ls-tree","-r",control_ref,"--","scripts",".l5/trust-policy.json")
 except (OSError,subprocess.SubprocessError) as exc:raise RuntimeError("L5_BOOTSTRAP_CERTIFIED_REF_UNAVAILABLE") from exc
 if commit.returncode or tree.returncode:raise RuntimeError("L5_BOOTSTRAP_CERTIFIED_REF_UNAVAILABLE")
 blobs={}
 try:
  for line in tree.stdout.splitlines():
   metadata,path=line.split("\t",1);mode,typ,sha=metadata.split(" ",2)
   if path!=".l5/trust-policy.json" and not PY_SOURCE.fullmatch(path):continue
   if typ!="blob" or mode not in {"100644","100755"} or not SHA40.fullmatch(sha) or path in blobs:raise RuntimeError("L5_BOOTSTRAP_CERTIFIED_RUNTIME_INVALID")
   blobs[path]=sha
 except ValueError as exc:raise RuntimeError("L5_BOOTSTRAP_CERTIFIED_RUNTIME_INVALID") from exc
 if BOOTSTRAP_PATH not in blobs or ".l5/trust-policy.json" not in blobs:raise RuntimeError("L5_BOOTSTRAP_CERTIFIED_RUNTIME_INCOMPLETE")
 return blobs

def _local_runtime(root:Path)->dict[str,str]:
 _assert_regular_runtime_roots(root);sources,caches=_walk_python_tree(root/"scripts")
 if caches:raise RuntimeError("L5_BOOTSTRAP_BYTECODE_ARTIFACT_PRESENT")
 blobs={}
 for path in [root/".l5"/"trust-policy.json",*sources]:
  try:
   if path.is_symlink() or not path.is_file():raise RuntimeError("L5_BOOTSTRAP_RUNTIME_SOURCE_INVALID")
   rel=path.relative_to(root).as_posix()
   if rel!=".l5/trust-policy.json" and not PY_SOURCE.fullmatch(rel):raise RuntimeError("L5_BOOTSTRAP_RUNTIME_SOURCE_INVALID")
   if rel in blobs:raise RuntimeError("L5_BOOTSTRAP_RUNTIME_SOURCE_INVALID")
   blobs[rel]=_git_blob_sha(path.read_bytes())
  except OSError as exc:raise RuntimeError("L5_BOOTSTRAP_RUNTIME_SOURCE_UNAVAILABLE") from exc
 return blobs

def bootstrap_runtime(manifest_path:Path|None=None)->tuple[bool,str]:
 global _ATTESTATION;_ATTESTATION=None;prepare_source_only_l5_imports()
 try:value=json.loads(_manifest_path(manifest_path).read_text(encoding="utf-8"))
 except (OSError,json.JSONDecodeError):return False,"L5_BOOTSTRAP_MANIFEST_UNAVAILABLE"
 if not isinstance(value,Mapping):return False,"L5_BOOTSTRAP_MANIFEST_INVALID"
 if value.get("execution_mode")!="ACTIVE":return True,"L5_BOOTSTRAP_NON_ACTIVE"
 ref=value.get("control_ref")
 if not isinstance(ref,str) or not SHA40.fullmatch(ref):return False,"L5_BOOTSTRAP_CONTROL_REF_NOT_PINNED"
 try:certified=_certified_runtime(ref);local=_local_runtime(ROOT)
 except RuntimeError as exc:return False,str(exc)
 if set(certified)!=set(local):return False,"L5_BOOTSTRAP_RUNTIME_FILE_SET_MISMATCH"
 if certified!=local:return False,"L5_BOOTSTRAP_RUNTIME_SOURCE_MISMATCH"
 digest=hashlib.sha256(json.dumps(certified,sort_keys=True,separators=(",",":")).encode()).hexdigest();_ATTESTATION=(ref,digest);return True,"L5_BOOTSTRAP_ACTIVE_ATTESTED"

def active_attestation_matches(control_ref:str)->bool:return _ATTESTATION is not None and _ATTESTATION[0]==control_ref
