"""Map the raw GitHub branch rules to the report's required checks (#383).

OC-P0-01 / OC-P0-06: ``live_reconciliation_report`` judges each pull
request's exact-head check runs against the top-level ``required_checks``
list. #379 and #381 map every other GitHub-derived section; this pure module
maps that list from the rules GitHub actually enforces on ``main``, so a
required check left out, or an "any app" requirement relabelled to a trusted
app, is refused here instead of being hand-mapped into ``CONSISTENT``.

Input, exactly as GitHub returns it:

* ``rule_pages``: pages of ``GET /repos/{o}/{r}/rules/branches/main`` (lists
  of rule objects).

Only ``required_status_checks`` rules are read; other rule types are
ignored. A requirement without an ``integration_id`` lets any app satisfy
the context, so it is refused (fail closed): the report must know the
expected app. ``app_slugs`` is the caller's trusted record mapping an
integration id to the slug check runs report as ``app.slug``; an unmapped id
is refused, never guessed. The same context with the same app in several
rulesets is one requirement; the same context with two apps is refused. No
rule yields ``[]`` and the report then raises ``NO_REQUIRED_CHECKS``.

REST list pages carry no end marker in their body, so the caller states
whether it followed the ``Link`` header to the last page; an incomplete
listing is refused. Nothing is coerced or defaulted. Errors name the payload
path only, never a value. Nothing here performs a request or reads a token.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

RULE_TYPE = "required_status_checks"


class InvalidPayload(ValueError):
    """A GitHub payload is missing a field, has the wrong type or is incomplete."""


def _get(obj: object, key: str, path: str) -> Any:
    if type(obj) is not dict or key not in obj:
        raise InvalidPayload(f"missing {path}.{key}")
    return obj[key]


def _str(obj: object, key: str, path: str) -> str:
    value = _get(obj, key, path)
    if type(value) is not str or not value:
        raise InvalidPayload(f"invalid {path}.{key}")
    return value


def _rest_items(pages: object, complete: object, path: str) -> list[Any]:
    if type(complete) is not bool:
        raise InvalidPayload(f"invalid {path} completeness")
    if not complete:
        raise InvalidPayload(f"incomplete {path}")
    if type(pages) not in (list, tuple):
        raise InvalidPayload(f"invalid {path}")
    items: list[Any] = []
    for index, page in enumerate(pages):
        if type(page) is not list:
            raise InvalidPayload(f"invalid {path}[{index}]")
        items.extend(page)
    return items


def _slugs(app_slugs: object) -> dict[int, str]:
    if type(app_slugs) is not dict:
        raise InvalidPayload("invalid app_slugs")
    for key, value in app_slugs.items():
        if type(key) is not int or key <= 0 or type(value) is not str or not value:
            raise InvalidPayload("invalid app_slugs entry")
    return dict(app_slugs)


def required_check_observation(
    rule_pages: Sequence[object],
    *,
    rules_complete: bool,
    app_slugs: Mapping[int, str],
) -> list[dict[str, str]]:
    """Return the report's ``required_checks`` list, or raise InvalidPayload."""
    slugs = _slugs(app_slugs)
    required: dict[str, str] = {}
    for i, rule in enumerate(_rest_items(rule_pages, rules_complete, "rules")):
        path = f"rules[{i}]"
        if _str(rule, "type", path) != RULE_TYPE:
            continue
        params = _get(rule, "parameters", path)
        checks = _get(params, RULE_TYPE, f"{path}.parameters")
        if type(checks) is not list:
            raise InvalidPayload(f"invalid {path}.parameters.{RULE_TYPE}")
        for j, check in enumerate(checks):
            item = f"{path}.parameters.{RULE_TYPE}[{j}]"
            context = _str(check, "context", item)
            if type(check) is not dict or check.get("integration_id") is None:
                # Any app may post this context: never trusted as a requirement.
                raise InvalidPayload(f"unbound app {item}.integration_id")
            integration = check["integration_id"]
            if type(integration) is not int or integration <= 0:  # never a JSON boolean
                raise InvalidPayload(f"invalid {item}.integration_id")
            if integration not in slugs:
                raise InvalidPayload(f"unmapped app {item}.integration_id")
            app = slugs[integration]
            if required.setdefault(context, app) != app:
                raise InvalidPayload(f"conflicting app {item}.integration_id")
    return [{"name": name, "app": required[name]} for name in sorted(required)]
