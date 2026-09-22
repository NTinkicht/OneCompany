#!/usr/bin/env python3
"""Optional real Chromium/Playwright evidence for disposable loopback checklist."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

import local_preview_evidence as preview

SHA = re.compile(r"[0-9a-f]{40}\Z")

ROOT = Path(__file__).resolve().parents[1]


def _checkout_revision() -> str:
    """Fail closed unless the actual git checkout is at a clean full SHA."""
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True, check=False)
    if head.returncode != 0 or not SHA.fullmatch(head.stdout.strip()):
        raise ValueError("CHECKOUT_REVISION_UNAVAILABLE")
    status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"],
                            cwd=ROOT, capture_output=True, text=True, check=False)
    if status.returncode != 0 or status.stdout.strip():
        raise ValueError("CLEAN_CHECKOUT_REQUIRED")
    return head.stdout.strip()


def _load_sync_playwright():
    """Return Playwright's sync entry point or a stable blocked dependency error."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ValueError("PLAYWRIGHT_NOT_INSTALLED") from exc
    return sync_playwright


def _launch_chromium(playwright):
    """Launch Chromium while preserving the missing-browser blocked contract."""
    try:
        return playwright.chromium.launch(headless=True)
    except Exception as exc:
        message = str(exc).lower()
        if "executable doesn't exist" in message or "executable does not exist" in message:
            raise ValueError("CHROMIUM_NOT_INSTALLED") from exc
        raise ValueError("BROWSER_SMOKE_FAILED") from exc


def collect(revision: str, url: str) -> dict[str, object]:
    """Run actual browser CRUD against a clean exact-revision localhost fixture.

    No Playwright installation or browser binary means no PASS evidence. This
    does not deploy, release, authorize, create a lease or touch real user data.
    """
    if not isinstance(revision, str) or not SHA.fullmatch(revision):
        raise ValueError("EXACT_REVISION_REQUIRED")
    root = preview.validate_local_url(url)
    if _checkout_revision() != revision:
        raise ValueError("REVISION_CHECKOUT_MISMATCH")
    health = preview.collect(revision, root)
    if health.get("revision") != revision or health.get("health") != "PASS":
        raise ValueError("LOCAL_PREVIEW_HEALTH_FAILED")
    sync_playwright = _load_sync_playwright()

    title = "OneCompany browser proof"
    origin = urlsplit(root)
    try:
        with sync_playwright() as p:
            browser = _launch_chromium(p)
            try:
                page = browser.new_page()
                page.set_default_timeout(5000)

                def local_only(route):
                    target = urlsplit(route.request.url)
                    if (target.scheme == "http" and target.hostname == origin.hostname
                            and target.port == origin.port and not target.username
                            and not target.password):
                        route.continue_()
                    else:
                        route.abort()

                page.route("**/*", local_only)
                page.goto(root, wait_until="domcontentloaded", timeout=5000)
                page.get_by_role("heading", name="My checklist").wait_for()
                page.get_by_role("textbox", name="New item").fill(title)
                page.get_by_role("button", name="Add", exact=True).click()
                page.get_by_role("button", name="Complete " + title).click()
                page.get_by_role("button", name="Undo " + title).wait_for()
                page.get_by_role("button", name="Delete " + title).click()
                page.get_by_role("button", name="Delete " + title).wait_for(state="detached")
            finally:
                browser.close()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("BROWSER_SMOKE_FAILED") from exc
    return {
        "schema": "onecompany.local-playwright-evidence.v1",
        "revision": revision,
        "url": root,
        "status": "PASS",
        "browser": "chromium",
        "flow": "real_dom_add_complete_delete",
        "scope": "local_disposable",
        "deployable": False,
        "authority_granted": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Optional real browser localhost evidence")
    parser.add_argument("--revision", required=True)
    parser.add_argument("--url", required=True)
    args = parser.parse_args()
    print(json.dumps(collect(args.revision, args.url), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
