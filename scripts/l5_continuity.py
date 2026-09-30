#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

POLICY_PATH = Path('.onecompany/l5.json')
MAX_PAGES = 10


def gh(path: str):
    result = subprocess.run(['gh', 'api', path], text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f'GitHub API failed: {path}')
    return json.loads(result.stdout) if result.stdout.strip() else {}


def paged(repo: str, path: str):
    items = []
    for page in range(1, MAX_PAGES + 1):
        sep = '&' if '?' in path else '?'
        batch = gh(f'repos/{repo}/{path}{sep}per_page=100&page={page}')
        if not isinstance(batch, list):
            raise RuntimeError('PAGINATED_RESPONSE_INVALID')
        items.extend(batch)
        if len(batch) < 100:
            return items
    raise RuntimeError('PAGINATION_BOUND_EXCEEDED')


def label_names(item: dict) -> set[str]:
    result = set()
    for label in item.get('labels') or []:
        name = label.get('name') if isinstance(label, dict) else label
        if isinstance(name, str):
            result.add(name.lower())
    return result


def active_internal_prs(repo: str, base: str, pulls: list[dict]) -> list[int]:
    result = []
    for pr in pulls:
        head_repo = ((pr.get('head') or {}).get('repo') or {}).get('full_name')
        if (pr.get('base') or {}).get('ref') == base and head_repo == repo:
            if isinstance(pr.get('number'), int):
                result.append(pr['number'])
    return sorted(result)


def eligible_issues(issues: list[dict], ready: set[str], blocked: set[str]) -> list[dict]:
    candidates = []
    for issue in issues:
        if issue.get('pull_request') is not None or issue.get('state') != 'open':
            continue
        labels = label_names(issue)
        if not labels.intersection(ready) or labels.intersection(blocked):
            continue
        if isinstance(issue.get('number'), int):
            candidates.append(issue)
    return sorted(candidates, key=lambda x: x['number'])


def repo_plan(repo_cfg: dict, policy: dict) -> dict:
    repo = str(repo_cfg['repository'])
    base = str(repo_cfg.get('base_branch') or 'main')
    target = int(repo_cfg['target_open_prs'])
    pulls = active_internal_prs(repo, base, paged(repo, 'pulls?state=open'))
    deficit = max(0, target - len(pulls))
    issues = eligible_issues(
        paged(repo, 'issues?state=open'),
        {x.lower() for x in policy.get('ready_labels', [])},
        {x.lower() for x in policy.get('blocking_labels', [])},
    )
    selected = issues[:deficit]
    return {
        'repository': repo,
        'target_open_prs': target,
        'active_prs': pulls,
        'deficit': deficit,
        'selected_ready_issues': [
            {'number': row['number'], 'title': row.get('title')} for row in selected
        ],
        'unfilled_slots': max(0, deficit - len(selected)),
        'status': 'QUOTA_SATISFIED' if deficit == 0 else (
            'REPLENISHMENT_PLANNED' if selected else 'IDLE_CAPACITY_NO_READY_WORK'
        ),
    }


def plan(policy: dict) -> dict:
    if policy.get('mutation_mode') != 'PLAN_ONLY':
        raise RuntimeError('UNREVIEWED_MUTATION_MODE')
    repos = policy.get('repositories')
    if not isinstance(repos, list) or not repos:
        raise RuntimeError('L5_REPOSITORIES_INVALID')
    rows = [repo_plan(cfg, policy) for cfg in repos]
    return {
        'level': policy.get('level'),
        'phase': policy.get('phase'),
        'mutation_mode': policy.get('mutation_mode'),
        'repositories': rows,
        'total_target_prs': sum(x['target_open_prs'] for x in rows),
        'total_active_prs': sum(len(x['active_prs']) for x in rows),
        'total_deficit': sum(x['deficit'] for x in rows),
        'all_quotas_satisfied': all(x['deficit'] == 0 for x in rows),
    }


def selftest() -> None:
    pulls = [
        {'number': 5, 'base': {'ref': 'main'}, 'head': {'repo': {'full_name': 'NTinkicht/OneCompany'}}},
        {'number': 6, 'base': {'ref': 'main'}, 'head': {'repo': {'full_name': 'fork/example'}}},
    ]
    assert active_internal_prs('NTinkicht/OneCompany', 'main', pulls) == [5]
    issues = [
        {'number': 4, 'state': 'open', 'labels': [{'name': 'l5-ready'}]},
        {'number': 2, 'state': 'open', 'labels': [{'name': 'l4-ready'}, {'name': 'human-only'}]},
    ]
    assert [x['number'] for x in eligible_issues(issues, {'l5-ready', 'l4-ready'}, {'human-only'})] == [4]
    print('l5_continuity selftest PASS')


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--selftest', action='store_true')
    args = parser.parse_args()
    if args.selftest:
        selftest()
        return 0
    if os.environ.get('GITHUB_REPOSITORY') != 'NTinkicht/OneCompany':
        raise SystemExit('L5_BLOCKED: wrong control-plane repository')
    policy = json.loads(POLICY_PATH.read_text(encoding='utf-8'))
    print(json.dumps(plan(policy), indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
