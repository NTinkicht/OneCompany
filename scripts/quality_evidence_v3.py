#!/usr/bin/env python3
"""Low-overhead v3 runner for OneCompany's trusted quality-evidence producer.

This module deliberately reuses the reviewed v2 aggregation, mutation, family,
and serialization logic from a sibling trusted copy while replacing only the
coverage execution mechanism. Python 3.12's sys.monitoring LINE and BRANCH
events provide the same exact line and conditional-branch destination facts
without tracing every opcode in every product frame.

The workflow copies both this file and quality_evidence.py from the reviewed
base revision before normal execution. The only exception is the explicitly
base-SHA-bound v2->v3 recovery transition documented in the workflow itself.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

TRUSTED_V2_NAME = "quality_evidence_v2.py"


def _load_v2():
    path = Path(__file__).resolve().with_name(TRUSTED_V2_NAME)
    if not path.is_file():
        raise RuntimeError(f"trusted v2 sibling is missing: {path}")
    spec = importlib.util.spec_from_file_location("_onecompany_trusted_quality_v2", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load trusted v2 sibling: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V2 = _load_v2()


def _coverage_worker(root: Path) -> dict[str, Any]:
    """Run candidate tests with bounded low-overhead line/branch monitoring."""
    monitoring = getattr(sys, "monitoring", None)
    if monitoring is None:
        raise RuntimeError("Python 3.12+ sys.monitoring is required")

    root = root.resolve()
    executed: set[tuple[str, int]] = set()
    observed_edges: set[tuple[tuple[str, int, str], int, int]] = set()
    observed_by_source: dict[tuple[tuple[str, int, str], int], set[int]] = {}
    events = monitoring.events
    tool_id = monitoring.COVERAGE_ID

    # Hot callbacks must never call Path.resolve() or repeatedly inspect the
    # filesystem. Build an immutable filename index once, then cache every code
    # object's classification. The previous v3 attempt resolved paths on every
    # PY_START/LINE/BRANCH callback and was slower than the tests themselves by
    # two orders of magnitude.
    product_index: dict[str, str] = {}
    for path in V2._product_sources(root):
        relative = path.relative_to(root).as_posix()
        absolute = str(path.resolve())
        product_index[str(path)] = relative
        product_index[absolute] = relative

    code_cache: dict[Any, tuple[str, int, str] | None] = {}
    configured: set[Any] = set()

    _executable, static_edges = V2._static_model(root)
    expected_by_source: dict[tuple[tuple[str, int, str], int], set[int]] = {}
    for key, source, target in static_edges:
        expected_by_source.setdefault((key, source), set()).add(target)

    sentinel = object()

    def code_key(code):
        cached = code_cache.get(code, sentinel)
        if cached is not sentinel:
            return cached
        try:
            filename = str(code.co_filename)
            relative = product_index.get(filename)
            if relative is None:
                candidate = Path(filename)
                if not candidate.is_absolute():
                    candidate = root / candidate
                relative = product_index.get(str(candidate.absolute()))
            value = (
                (relative, int(code.co_firstlineno), str(code.co_name))
                if relative is not None
                else None
            )
        except (AttributeError, OSError, TypeError, ValueError):
            value = None
        code_cache[code] = value
        return value

    def py_start(code, _instruction_offset):
        key = code_key(code)
        if key is not None and code not in configured:
            monitoring.set_local_events(tool_id, code, events.LINE | events.BRANCH)
            configured.add(code)
        # PY_START is a local event even when globally enabled. Python 3.12
        # permits DISABLE here, so each code-start location is classified once.
        return monitoring.DISABLE

    def line(code, line_number):
        key = code_key(code)
        if key is not None and isinstance(line_number, int) and line_number > 0:
            executed.add((key[0], line_number))
        # Coverage only needs to know whether a line was observed at least once.
        return monitoring.DISABLE

    def branch(code, instruction_offset, destination_offset):
        key = code_key(code)
        if key is None:
            return monitoring.DISABLE
        source = int(instruction_offset)
        target = int(destination_offset)
        observed_edges.add((key, source, target))
        branch_key = (key, source)
        seen = observed_by_source.setdefault(branch_key, set())
        seen.add(target)
        expected = expected_by_source.get(branch_key)
        # Do not disable a conditional branch until every statically-known
        # destination has been observed; otherwise one outcome could hide the
        # other and inflate branch coverage.
        if expected and expected.issubset(seen):
            return monitoring.DISABLE
        return None

    suite = V2._discover_suite(root)
    output = V2.io.StringIO()
    runner = V2.unittest.TextTestRunner(stream=output, verbosity=0)
    old_cwd, old_argv = Path.cwd(), list(sys.argv)
    inserted: list[str] = []
    for value in (str(root / "scripts"), str(root)):
        if value not in sys.path:
            sys.path.insert(0, value)
            inserted.append(value)

    if monitoring.get_tool(tool_id) is not None:
        raise RuntimeError(f"sys.monitoring coverage tool id {tool_id} is already in use")

    try:
        monitoring.use_tool_id(tool_id, "onecompany-quality-evidence-v3")
        monitoring.register_callback(tool_id, events.PY_START, py_start)
        monitoring.register_callback(tool_id, events.LINE, line)
        monitoring.register_callback(tool_id, events.BRANCH, branch)
        monitoring.set_events(tool_id, events.PY_START)

        V2.os.chdir(root)
        sys.argv = ["quality-evidence-coverage-worker-v3"]
        with V2.contextlib.redirect_stdout(output), V2.contextlib.redirect_stderr(output):
            result = runner.run(suite)
    finally:
        try:
            monitoring.set_events(tool_id, events.NO_EVENTS)
            monitoring.register_callback(tool_id, events.PY_START, None)
            monitoring.register_callback(tool_id, events.LINE, None)
            monitoring.register_callback(tool_id, events.BRANCH, None)
            monitoring.free_tool_id(tool_id)
        finally:
            sys.argv = old_argv
            V2.os.chdir(old_cwd)
            for value in inserted:
                if value in sys.path:
                    sys.path.remove(value)

    return {
        "tests_successful": result.wasSuccessful(),
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "executed_lines": sorted([list(value) for value in executed]),
        "observed_edges": sorted(
            [
                [[key[0], key[1], key[2]], source, target]
                for key, source, target in observed_edges
            ]
        ),
        "test_output_tail": output.getvalue()[-4000:],
        "collector": "sys.monitoring-cached-line-branch",
        "classified_code_objects": len(code_cache),
        "instrumented_code_objects": len(configured),
    }


def _coverage_measurement(root: Path) -> tuple[dict[str, float], dict[str, Any]]:
    """Aggregate v3 worker observations using v2's static coverage model."""
    executable, branch_edges = V2._static_model(root)
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--coverage-worker",
        "--repo-root",
        str(root),
    ]
    started = time.monotonic()
    try:
        child = subprocess.run(
            command,
            cwd=str(root),
            check=False,
            text=True,
            capture_output=True,
            timeout=180,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"coverage worker timed out: {exc}") from exc

    protocol_line = next(
        (
            line
            for line in reversed(child.stdout.splitlines())
            if line.startswith(V2.WORKER_MARKER)
        ),
        None,
    )
    if protocol_line is None:
        raise RuntimeError(
            "coverage worker returned no trusted protocol payload; "
            f"stderr={child.stderr[-1000:]}"
        )
    try:
        raw = json.loads(protocol_line[len(V2.WORKER_MARKER) :])
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"coverage worker protocol was invalid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise RuntimeError("coverage worker protocol must be an object")

    executed: set[tuple[str, int]] = set()
    for item in raw.get("executed_lines", []):
        if (
            isinstance(item, list)
            and len(item) == 2
            and isinstance(item[0], str)
            and isinstance(item[1], int)
        ):
            executed.add((item[0], item[1]))

    observed_edges: set[tuple[tuple[str, int, str], int, int]] = set()
    for item in raw.get("observed_edges", []):
        if not isinstance(item, list) or len(item) != 3:
            continue
        key, source, target = item
        if (
            isinstance(key, list)
            and len(key) == 3
            and isinstance(key[0], str)
            and isinstance(key[1], int)
            and isinstance(key[2], str)
            and isinstance(source, int)
            and isinstance(target, int)
        ):
            observed_edges.add(((key[0], key[1], key[2]), source, target))

    covered_lines = executable & executed
    observed = branch_edges & observed_edges
    line_pct = 100.0 * len(covered_lines) / len(executable) if executable else 0.0
    branch_pct = 100.0 * len(observed) / len(branch_edges) if branch_edges else 100.0
    details = {
        "worker_process_isolated": True,
        "worker_returncode": child.returncode,
        "worker_duration_seconds": round(time.monotonic() - started, 3),
        "tests_successful": raw.get("tests_successful") is True,
        "tests_run": int(raw.get("tests_run") or 0),
        "failures": int(raw.get("failures") or 0),
        "errors": int(raw.get("errors") or 0),
        "executable_lines": len(executable),
        "covered_lines": len(covered_lines),
        "branch_edges": len(branch_edges),
        "covered_branch_edges": len(observed),
        "executed_lines": sorted([list(value) for value in executed]),
        "test_output_tail": str(raw.get("test_output_tail") or "")[-4000:],
        "collector": str(raw.get("collector") or "sys.monitoring-cached-line-branch"),
        "classified_code_objects": int(raw.get("classified_code_objects") or 0),
        "instrumented_code_objects": int(raw.get("instrumented_code_objects") or 0),
    }
    return {"line": round(line_pct, 2), "branch": round(branch_pct, 2)}, details


def main() -> int:
    V2._coverage_worker = _coverage_worker
    V2._coverage_measurement = _coverage_measurement
    V2.TOOL_VERSION = 3
    return V2.main()


if __name__ == "__main__":
    raise SystemExit(main())
