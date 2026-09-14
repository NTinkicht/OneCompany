#!/usr/bin/env python3
"""Fail-closed identity selection for OneCompany bootstrap/init flows."""
from __future__ import annotations

import re

from platform_identity import repository_owner_info


def normalize_code_owner(value: str) -> str:
    owner = value.strip()
    if not owner.startswith("@"):
        owner = "@" + owner
    if not re.fullmatch(r"@[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)?", owner):
        raise ValueError(
            "code owner must be a GitHub user or organization team such as @octocat or @org/team"
        )
    return owner


def normalize_platform_login(value: str) -> str:
    login = value.strip().lstrip("@")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", login):
        raise ValueError(
            "root principal must be one concrete GitHub user login, such as octocat"
        )
    return login


def resolve_install_principals(
    repository: str,
    *,
    code_owner: str | None,
    root_principal: str | None,
) -> tuple[str, str]:
    """Resolve safe install principals; never mistake an organization for a user."""
    if code_owner is not None and root_principal is not None:
        return normalize_code_owner(code_owner), normalize_platform_login(root_principal)

    owner, error = repository_owner_info(repository)
    if owner is None:
        raise ValueError(
            "cannot safely infer repository ownership; pass both --code-owner and "
            f"--root-principal explicitly ({error or 'owner lookup failed'})"
        )
    login = owner["login"]
    owner_type = owner["type"]
    if owner_type == "Organization":
        missing: list[str] = []
        if code_owner is None:
            missing.append("--code-owner @org/team-or-user")
        if root_principal is None:
            missing.append("--root-principal human-user")
        raise ValueError(
            "organization-owned repositories require explicit concrete governance principals: "
            + ", ".join(missing)
        )
    if owner_type != "User":
        raise ValueError(
            f"unsupported repository owner type {owner_type!r}; pass explicit governance principals"
        )
    return (
        normalize_code_owner(code_owner or login),
        normalize_platform_login(root_principal or login),
    )
