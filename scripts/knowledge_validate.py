#!/usr/bin/env python3
"""Validate the canonical repo-native OneCompany knowledge store."""
from __future__ import annotations

import sys

import knowledge


def main() -> int:
    try:
        entries = knowledge.load_entries()
    except knowledge.KnowledgeError as exc:
        print(f"KNOWLEDGE INVALID: {exc}")
        return 1
    print(f"KNOWLEDGE VALID: {len(entries)} entries; authority=advisory_only")
    return 0


if __name__ == "__main__":
    sys.exit(main())
