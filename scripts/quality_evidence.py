#!/usr/bin/env python3
"""Produce deterministic Python quality evidence using only the standard library.

The trusted workflow copies this producer from its reviewed base revision and
runs it against the candidate checkout. It never consumes packet-authored
quality numbers. Evidence comes from executed tests, bytecode branch edges, the
exact base/head diff, and bounded deterministic mutations of changed Python
production files.
"""
from __future__ import annotations

import argparse
import ast
import datetime as dt
import dis
import io
import json
import os
import re
import subprocess
import sys
import time
import unittest
from collections import deque
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "onecompany-quality-evidence-v1"
TOOL_VERSION = 1
EXCLUDED_SOURCE_NAMES = {"quality_evidence.py", "smoke_bootstrap.py", "smoke_init.py"}
EXCLUDED_PREFIXES = ("simulate",)


def _run(command: list[str], cwd: Path, timeout: int = 180) -> dict[str, Any]:
    started = time.monotonic()
    try:
        result = subprocess.run(command, cwd=str(cwd), check=False, text=True, capture_output=True, timeout=timeout)
        return {
            "command": command,
            "returncode": result.returncode,
            "duration_seconds": round(time.monotonic() - started, 3),
            "stdout_tail": result.stdout[-4000:],
            "stderr_tail": result.stderr[-4000:],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": command,
            "returncode": 124,
            "duration_seconds": round(time.monotonic() - started, 3),
            "stdout_tail": (exc.stdout or "")[-4000:] if isinstance(exc.stdout, str) else "",
            "stderr_tail": (exc.stderr or "")[-4000:] if isinstance(exc.stderr, str) else "",
            "timeout": True,
        }


def _is_product_source(path: Path, root: Path) -> bool:
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    if relative == Path("onecompany.py"):
        return True
    if len(relative.parts) < 2 or relative.parts[0] != "scripts" or path.suffix != ".py":
        return False
    if path.name in EXCLUDED_SOURCE_NAMES or any(path.stem.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
        return False
    return True


def _product_sources(root: Path) -> list[Path]:
    values = [root / "onecompany.py", *sorted((root / "scripts").rglob("*.py"))]
    return [path for path in values if path.is_file() and _is_product_source(path, root)]


def _code_key(code: Any, root: Path) -> tuple[str, int, str] | None:
    try:
        relative = Path(code.co_filename).resolve().relative_to(root.resolve()).as_posix()
    except (AttributeError, ValueError):
        return None
    return relative, int(code.co_firstlineno), str(code.co_name)


def _iter_code_objects(code: Any) -> Iterable[Any]:
    yield code
    for value in code.co_consts:
        if hasattr(value, "co_code"):
            yield from _iter_code_objects(value)


def _conditional_jump(instruction: dis.Instruction) -> bool:
    name = instruction.opname
    return name == "FOR_ITER" or "JUMP_IF" in name or "POP_JUMP" in name


def _static_model(root: Path) -> tuple[set[tuple[str, int]], set[tuple[tuple[str, int, str], int, int]]]:
    executable: set[tuple[str, int]] = set()
    branches: set[tuple[tuple[str, int, str], int, int]] = set()
    for path in _product_sources(root):
        relative = path.relative_to(root).as_posix()
        try:
            code = compile(path.read_text(encoding="utf-8"), str(path.resolve()), "exec")
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        for child in _iter_code_objects(code):
            key = (relative, int(child.co_firstlineno), str(child.co_name))
            for _start, _end, lineno in child.co_lines():
                if isinstance(lineno, int) and lineno > 0:
                    executable.add((relative, lineno))
            instructions = list(dis.get_instructions(child))
            for index, instruction in enumerate(instructions):
                if not _conditional_jump(instruction) or not isinstance(instruction.argval, int):
                    continue
                branches.add((key, instruction.offset, int(instruction.argval)))
                if index + 1 < len(instructions):
                    branches.add((key, instruction.offset, instructions[index + 1].offset))
    return executable, branches


def _discover_suite(root: Path) -> unittest.TestSuite:
    combined = unittest.TestSuite()
    for directory in (root / ".onecompany" / "selftest", root / "tests"):
        if directory.is_dir():
            combined.addTests(unittest.TestLoader().discover(str(directory), pattern="test_*.py"))
    return combined


def _coverage_measurement(root: Path) -> tuple[dict[str, float], dict[str, Any]]:
    executable, branch_edges = _static_model(root)
    executed: set[tuple[str, int]] = set()
    observed_edges: set[tuple[tuple[str, int, str], int, int]] = set()
    last_opcode: dict[int, tuple[tuple[str, int, str], int]] = {}
    offset_line_cache: dict[Any, dict[int, int]] = {}

    def tracer(frame, event, arg):
        filename = Path(frame.f_code.co_filename)
        if not _is_product_source(filename, root):
            return tracer
        key = _code_key(frame.f_code, root)
        if key is None:
            return tracer
        if event == "call":
            frame.f_trace_opcodes = True
            return tracer
        if event == "line":
            executed.add((key[0], int(frame.f_lineno)))
            return tracer
        if event == "opcode":
            current = int(frame.f_lasti)
            frame_id = id(frame)
            previous = last_opcode.get(frame_id)
            if previous is not None and previous[0] == key:
                observed_edges.add((key, previous[1], current))
            last_opcode[frame_id] = (key, current)
            if frame.f_code not in offset_line_cache:
                offset_line_cache[frame.f_code] = {
                    item.offset: int(item.positions.lineno)
                    for item in dis.get_instructions(frame.f_code)
                    if item.positions and isinstance(item.positions.lineno, int)
                }
            lineno = offset_line_cache[frame.f_code].get(current)
            if lineno:
                executed.add((key[0], lineno))
            return tracer
        if event == "return":
            last_opcode.pop(id(frame), None)
        return tracer

    suite = _discover_suite(root)
    output = io.StringIO()
    runner = unittest.TextTestRunner(stream=output, verbosity=0)
    old_trace, old_cwd, old_argv = sys.gettrace(), Path.cwd(), list(sys.argv)
    for value in (str(root / "scripts"), str(root)):
        if value not in sys.path:
            sys.path.insert(0, value)
    try:
        os.chdir(root)
        sys.argv = ["quality-evidence-tests"]
        sys.settrace(tracer)
        result = runner.run(suite)
    finally:
        sys.settrace(old_trace)
        sys.argv = old_argv
        os.chdir(old_cwd)

    covered_lines = executable & executed
    observed = branch_edges & observed_edges
    line_pct = 100.0 * len(covered_lines) / len(executable) if executable else 0.0
    branch_pct = 100.0 * len(observed) / len(branch_edges) if branch_edges else 100.0
    return (
        {"line": round(line_pct, 2), "branch": round(branch_pct, 2)},
        {
            "tests_successful": result.wasSuccessful(),
            "tests_run": result.testsRun,
            "failures": len(result.failures),
            "errors": len(result.errors),
            "executable_lines": len(executable),
            "covered_lines": len(covered_lines),
            "branch_edges": len(branch_edges),
            "covered_branch_edges": len(observed),
            "executed_lines": sorted([list(value) for value in executed]),
            "test_output_tail": output.getvalue()[-4000:],
        },
    )


def _git_diff(root: Path, base_sha: str, candidate_sha: str, *args: str) -> str:
    result = subprocess.run(
        ["git", "diff", *args, base_sha, candidate_sha, "--", "scripts", "onecompany.py"],
        cwd=str(root), check=False, text=True, capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git diff failed")
    return result.stdout


def _changed_lines(root: Path, base_sha: str, candidate_sha: str) -> set[tuple[str, int]]:
    text = _git_diff(root, base_sha, candidate_sha, "--unified=0", "--no-color")
    changed: set[tuple[str, int]] = set()
    current: str | None = None
    hunk = re.compile(r"^@@\s+-\d+(?:,\d+)?\s+\+(\d+)(?:,(\d+))?\s+@@")
    for line in text.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
            if not _is_product_source(root / current, root):
                current = None
            continue
        match = hunk.match(line)
        if current and match:
            start, count = int(match.group(1)), int(match.group(2) or "1")
            changed.update((current, lineno) for lineno in range(start, start + count))
    return changed


def _changed_line_coverage(root: Path, base_sha: str, candidate_sha: str, coverage_details: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    executable, _ = _static_model(root)
    executable_changed = _changed_lines(root, base_sha, candidate_sha) & executable
    executed = {
        (str(item[0]), int(item[1]))
        for item in coverage_details.get("executed_lines", [])
        if isinstance(item, list) and len(item) == 2
    }
    covered = executable_changed & executed
    percentage = 100.0 if not executable_changed else 100.0 * len(covered) / len(executable_changed)
    return round(percentage, 2), {"changed_executable_lines": len(executable_changed), "covered_changed_lines": len(covered)}


def _changed_python_files(root: Path, base_sha: str, candidate_sha: str) -> list[Path]:
    text = _git_diff(root, base_sha, candidate_sha, "--name-only")
    values = [root / raw.strip() for raw in text.splitlines() if raw.strip()]
    return sorted(path for path in values if path.is_file() and _is_product_source(path, root))


COMPARE_MUTATIONS = {
    ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.Lt: ast.GtE, ast.LtE: ast.Gt,
    ast.Gt: ast.LtE, ast.GtE: ast.Lt, ast.Is: ast.IsNot, ast.IsNot: ast.Is,
    ast.In: ast.NotIn, ast.NotIn: ast.In,
}
BINOP_MUTATIONS = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.FloorDiv, ast.FloorDiv: ast.Mult}


def _mutation_kind(node: ast.AST) -> str | None:
    if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in COMPARE_MUTATIONS:
        return "compare"
    if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
        return "boolop"
    if isinstance(node, ast.Constant) and isinstance(node.value, bool):
        return "bool"
    if isinstance(node, ast.BinOp) and type(node.op) in BINOP_MUTATIONS:
        return "binop"
    return None


class _SingleMutator(ast.NodeTransformer):
    def __init__(self, target: int):
        self.target, self.index, self.applied = target, -1, False

    def generic_visit(self, node):
        kind = _mutation_kind(node)
        if kind is not None:
            self.index += 1
            if self.index == self.target:
                self.applied = True
                if kind == "compare": node.ops[0] = COMPARE_MUTATIONS[type(node.ops[0])]()
                elif kind == "boolop": node.op = ast.Or() if isinstance(node.op, ast.And) else ast.And()
                elif kind == "bool": node.value = not node.value
                elif kind == "binop": node.op = BINOP_MUTATIONS[type(node.op)]()
                return node
        return super().generic_visit(node)


def _mutation_specs(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return list(range(sum(1 for node in ast.walk(tree) if _mutation_kind(node) is not None)))


def _bounded_mutation_candidates(files: list[Path], max_mutants: int) -> list[tuple[Path, int]]:
    queues = deque((path, deque(_mutation_specs(path))) for path in files)
    result: list[tuple[Path, int]] = []
    while queues and len(result) < max_mutants:
        path, indexes = queues.popleft()
        if indexes:
            result.append((path, indexes.popleft()))
        if indexes:
            queues.append((path, indexes))
    return result


def _tests_kill_mutant(root: Path, timeout: int = 120) -> tuple[bool, list[dict[str, Any]]]:
    commands = [
        (root / ".onecompany" / "selftest", [sys.executable, "-m", "unittest", "discover", "-s", ".onecompany/selftest", "-p", "test_*.py"]),
        (root / "tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"]),
    ]
    results: list[dict[str, Any]] = []
    for directory, command in commands:
        if not directory.is_dir():
            continue
        result = _run(command, root, timeout=timeout)
        results.append(result)
        if result["returncode"] != 0:
            return True, results
    return False, results


def _mutation_score(root: Path, base_sha: str, candidate_sha: str, max_mutants: int) -> tuple[float | None, dict[str, Any]]:
    candidates = _bounded_mutation_candidates(_changed_python_files(root, base_sha, candidate_sha), max_mutants)
    if not candidates:
        return None, {"generated": 0, "killed": 0, "survived": 0, "bounded_max": max_mutants, "survivors": []}

    killed, survivors = 0, []
    for path, index in candidates:
        original = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(original, filename=str(path))
            mutator = _SingleMutator(index)
            mutated = mutator.visit(tree)
            if not mutator.applied:
                continue
            ast.fix_missing_locations(mutated)
            path.write_text(ast.unparse(mutated) + "\n", encoding="utf-8")
            is_killed, _results = _tests_kill_mutant(root)
            if is_killed:
                killed += 1
            else:
                survivors.append({"path": path.relative_to(root).as_posix(), "mutation_index": index})
        finally:
            path.write_text(original, encoding="utf-8")
    total = len(candidates)
    score = 100.0 * killed / total if total else None
    return (round(score, 2) if score is not None else None), {
        "generated": total, "killed": killed, "survived": total - killed,
        "bounded_max": max_mutants, "survivors": survivors[:50],
    }


def _family_results(root: Path) -> tuple[dict[str, str], dict[str, Any]]:
    python = sys.executable
    families: dict[str, list[list[str]]] = {
        "static": [[python, "onecompany.py", "validate"], [python, "-m", "compileall", "-q", "scripts", ".onecompany/selftest", "onecompany.py"]],
        "unit": [[python, "-m", "unittest", "discover", "-s", ".onecompany/selftest", "-p", "test_*.py"], [python, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"]],
        "integration": [[python, "onecompany.py", "simulate-ledger"], [python, "onecompany.py", "simulate-parallel"]],
        "contract": [[python, "scripts/schema_validate.py"]],
        "e2e": [[python, "scripts/smoke_bootstrap.py"], [python, "scripts/smoke_init.py"]],
        "acceptance": [[python, "onecompany.py", "assurance", ".onecompany/reference/assurance/WU900.json"]],
        "regression": [[python, "-m", "unittest", "discover", "-s", ".onecompany/selftest", "-p", "test_*.py"]],
        "security": [[python, "onecompany.py", "hardening-audit"]],
        "operations": [[python, "onecompany.py", "simulate-supervision"]],
    }
    statuses, details = {}, {}
    for family, commands in families.items():
        usable = []
        for command in commands:
            if "-s" in command:
                directory = root / command[command.index("-s") + 1]
                if not directory.is_dir():
                    continue
            usable.append(command)
        results = [_run(command, root) for command in usable]
        statuses[family] = "pass" if results and all(item["returncode"] == 0 for item in results) else "fail"
        details[family] = results
    return statuses, details


def produce(root: Path, candidate_sha: str, base_sha: str, max_mutants: int) -> dict[str, Any]:
    coverage, coverage_details = _coverage_measurement(root)
    changed_line, changed_details = _changed_line_coverage(root, base_sha, candidate_sha, coverage_details)
    coverage["changed_line"] = changed_line
    mutation, mutation_details = _mutation_score(root, base_sha, candidate_sha, max_mutants)
    if mutation is not None:
        coverage["mutation"] = mutation
    families, family_details = _family_results(root)
    families["mutation"] = "pass" if mutation is not None else "skipped"
    return {
        "schema": SCHEMA,
        "candidate_sha": candidate_sha,
        "base_sha": base_sha,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "coverage": coverage,
        "test_families": families,
        "tool": {
            "name": "onecompany-quality-evidence", "version": TOOL_VERSION,
            "implementation": "python-stdlib-bytecode-trace-and-bounded-mutation",
            "mutation_operators": ["compare", "boolop", "bool-constant", "binop"],
            "max_mutants": max_mutants,
        },
        "details": {
            "coverage": coverage_details,
            "changed_line": changed_details,
            "mutation": mutation_details,
            "families": family_details,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Produce exact-head OneCompany quality evidence")
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-mutants", type=int, default=30)
    args = parser.parse_args()
    root = args.repo_root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    try:
        evidence = produce(root, args.candidate_sha, args.base_sha, max(1, args.max_mutants))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except Exception as exc:
        print(f"quality evidence generation failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"output": str(output), "coverage": evidence["coverage"], "test_families": evidence["test_families"]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
