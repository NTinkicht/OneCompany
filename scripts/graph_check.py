#!/usr/bin/env python3
"""Deterministic, read-only product-graph check (OC-P1-03 slice 1, #467).

Input: ``{"revision": 40-hex, "change_base": 40-hex, "nodes": [{"id", "kind":
objective|feature|requirement|ac|wu, "satisfies": id|null, "depends_on": [id], "effort": int>=0}]}``.
Rejects dependency cycles, a change edited from a stale revision, a node that satisfies the wrong
kind of parent, and requirements/ACs nobody builds on; reports the critical path over ``depends_on``
(longest total effort, ties broken by id). No network, no writes, no clock.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HEX40 = re.compile(r"[0-9a-fA-F]{40}")
PARENT = {"feature": "objective", "requirement": "feature", "ac": "requirement", "wu": "ac"}
NEEDS_CHILD = {"objective": "feature", "feature": "requirement", "requirement": "ac", "ac": "wu"}


def _name(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def load_report(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"report unreadable: {path.name} ({exc.__class__.__name__})") from exc
    if not isinstance(data, dict):
        raise ValueError("report is not an object")
    for key in ("revision", "change_base"):
        if not isinstance(data.get(key), str) or not HEX40.fullmatch(data[key]):
            raise ValueError(f"report needs a 40-hex {key}")
    nodes = data.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise ValueError("nodes must be a non-empty list")
    ids: set[str] = set()
    for n in nodes:
        if not isinstance(n, dict) or not _name(n.get("id")):
            raise ValueError("node needs a non-empty string id")
        if n["id"] in ids:
            raise ValueError(f"duplicate node id: {n['id']}")
        ids.add(n["id"])
    for n in nodes:
        if n.get("kind") != "objective" and (not isinstance(n.get("kind"), str) or n["kind"] not in PARENT):
            raise ValueError(f"{n['id']} has unknown kind")
        sat = n.get("satisfies")
        if n["kind"] == "objective":
            if sat is not None:
                raise ValueError(f"{n['id']} objective cannot satisfy anything")
        elif not isinstance(sat, str) or sat not in ids:
            raise ValueError(f"{n['id']} satisfies an unknown node")
        deps = n.get("depends_on", [])
        if not isinstance(deps, list) or any(not isinstance(d, str) or d not in ids for d in deps):
            raise ValueError(f"{n['id']} depends_on references an unknown node")
        eff = n.get("effort", 0)
        if isinstance(eff, bool) or not isinstance(eff, int) or eff < 0:
            raise ValueError(f"{n['id']} effort must be a non-negative integer")
    return data


def _cycle_nodes(deps: dict[str, list[str]]) -> set[str]:
    """Members of true cycles (SCCs of size > 1, or self-loops), via iterative Tarjan."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    members: set[str] = set()
    counter = 0
    for root in sorted(deps):
        if root in index:
            continue
        work = [(root, iter(deps[root]))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        while work:
            v, it = work[-1]
            advanced = False
            for w in it:
                if w not in index:
                    index[w] = low[w] = counter
                    counter += 1
                    stack.append(w)
                    on_stack.add(w)
                    work.append((w, iter(deps[w])))
                    advanced = True
                    break
                if w in on_stack:
                    low[v] = min(low[v], index[w])
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[v])
            if low[v] == index[v]:
                comp = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                if len(comp) > 1 or v in deps[v]:
                    members.update(comp)
    return members


def _topological(deps: dict[str, list[str]], skip: set[str]) -> list[str]:
    """Dependencies-first order over nodes outside ``skip`` (Kahn, id-ordered, no recursion)."""
    pending = {i: {d for d in ds if d not in skip} for i, ds in deps.items() if i not in skip}
    order: list[str] = []
    ready = sorted(i for i, d in pending.items() if not d)
    while ready:
        i = ready.pop(0)
        order.append(i)
        for k in sorted(pending):
            if i in pending[k]:
                pending[k].discard(i)
                if not pending[k]:
                    ready.append(k)
        ready.sort()
    return order


def evaluate(report: dict) -> dict:
    problems: list[str] = []
    nodes = {n["id"]: n for n in report["nodes"]}
    if report["change_base"].lower() != report["revision"].lower():
        problems.append(f"STALE_CHANGE edited from {report['change_base']} but current is {report['revision']}")
    deps = {i: sorted(set(n.get("depends_on", []))) for i, n in nodes.items()}
    cyclic = _cycle_nodes(deps)
    blocked: set[str] = set()
    if cyclic:
        problems.append(f"CYCLE among {','.join(sorted(cyclic))}")
        changed = True
        blocked = set(cyclic)
        while changed:
            changed = False
            for i in deps:
                if i not in blocked and any(d in blocked for d in deps[i]):
                    blocked.add(i)
                    changed = True
        if blocked - cyclic:
            problems.append(f"BLOCKED_BY_CYCLE {','.join(sorted(blocked - cyclic))} depend on a cycle")
    for i in sorted(nodes):
        n = nodes[i]
        want = PARENT.get(n["kind"])
        if want and nodes[n["satisfies"]]["kind"] != want:
            problems.append(f"LEVEL_SKIP {i} ({n['kind']}) satisfies {n['satisfies']} ({nodes[n['satisfies']]['kind']})")
    for i in sorted(nodes):
        child = NEEDS_CHILD.get(nodes[i]["kind"])
        if child and nodes[i]["kind"] in ("requirement", "ac") and not any(
                m["kind"] == child and m.get("satisfies") == i for m in nodes.values()):
            problems.append(f"UNCOVERED {i} ({nodes[i]['kind']}) has no {child}")
    path: list[str] = []
    best: dict[str, tuple[int, list[str]]] = {}
    for i in _topological(deps, blocked):
        tail = min((best[d] for d in deps[i]), key=lambda t: (-t[0], t[1]), default=(0, []))
        best[i] = (tail[0] + nodes[i].get("effort", 0), tail[1] + [i])
    wus = [i for i in sorted(best) if nodes[i]["kind"] == "wu"]
    if wus:
        total = max(best[i][0] for i in wus)
        path = min(best[i][1] for i in wus if best[i][0] == total)
    return {"nodes": len(nodes), "critical_path": path, "problems": problems}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only product graph check.")
    parser.add_argument("report", help="graph report JSON file")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    args = parser.parse_args(argv)
    try:
        result = evaluate(load_report(Path(args.report)))
    except ValueError as exc:
        print(f"graph-check: UNABLE TO VERIFY ({exc})", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(f"graph-check: {result['nodes']} nodes, critical path {' > '.join(result['critical_path']) or '-'}, "
              f"{len(result['problems'])} problems")
        for item in result["problems"]:
            print(f"  {item}")
    return 1 if result["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
