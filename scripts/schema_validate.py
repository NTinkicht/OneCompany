#!/usr/bin/env python3
"""Dependency-free validation for the JSON-Schema subset used by OneCompany."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from onecompany_lib import CONTROL


def is_type(value: Any, expected: str) -> bool:
    if expected == "object": return isinstance(value, dict)
    if expected == "array": return isinstance(value, list)
    if expected == "string": return isinstance(value, str)
    if expected == "boolean": return isinstance(value, bool)
    if expected == "integer": return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number": return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "null": return value is None
    return True


def validate(value: Any, schema: dict[str, Any], path: str, errors: list[str]) -> None:
    if "const" in schema and value != schema["const"]: errors.append(f"{path}: expected const {schema['const']!r}, got {value!r}")
    if "enum" in schema and value not in schema["enum"]: errors.append(f"{path}: {value!r} not in enum {schema['enum']!r}")
    expected = schema.get("type")
    if expected is not None:
        allowed = expected if isinstance(expected, list) else [expected]
        if not any(is_type(value, item) for item in allowed): errors.append(f"{path}: expected type {allowed}, got {type(value).__name__}"); return
    if isinstance(value, dict):
        required = schema.get("required", [])
        for key in required:
            if key not in value: errors.append(f"{path}: missing required property {key!r}")
        properties = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        for key, item in value.items():
            child = f"{path}.{key}"
            if key in properties: validate(item, properties[key], child, errors)
            elif additional is False: errors.append(f"{child}: additional property is not allowed")
            elif isinstance(additional, dict): validate(item, additional, child, errors)
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]: errors.append(f"{path}: requires at least {schema['minItems']} item(s)")
        if "maxItems" in schema and len(value) > schema["maxItems"]: errors.append(f"{path}: allows at most {schema['maxItems']} item(s)")
        if schema.get("uniqueItems"):
            encoded = [json.dumps(item, sort_keys=True, ensure_ascii=False) for item in value]
            if len(encoded) != len(set(encoded)): errors.append(f"{path}: items must be unique")
        # OneCompany extension: key-level uniqueness and complete enum coverage for
        # inventories whose full records legitimately have distinct metadata. JSON
        # Schema uniqueItems alone does not enforce unique IDs on object arrays.
        for key in schema.get("x-uniqueByProperties", []):
            seen: dict[str, int] = {}
            for index, item in enumerate(value):
                if not isinstance(item, dict) or key not in item:
                    continue  # Standard required/type validation reports the missing key.
                encoded = json.dumps(item[key], sort_keys=True, ensure_ascii=False)
                if encoded in seen:
                    errors.append(f"{path}[{index}].{key}: duplicate of {path}[{seen[encoded]}].{key}")
                else:
                    seen[encoded] = index
        for key in schema.get("x-requireEnumCoverage", []):
            item_schema = schema.get("items", {})
            prop_schema = item_schema.get("properties", {}).get(key, {}) if isinstance(item_schema, dict) else {}
            allowed = prop_schema.get("enum")
            if not isinstance(allowed, list):
                errors.append(f"{path}: x-requireEnumCoverage requires items.properties.{key}.enum")
                continue
            present = {json.dumps(item[key], sort_keys=True, ensure_ascii=False)
                       for item in value if isinstance(item, dict) and key in item}
            missing = [entry for entry in allowed
                       if json.dumps(entry, sort_keys=True, ensure_ascii=False) not in present]
            if missing:
                errors.append(f"{path}: missing required {key} enum value(s): {missing!r}")
        if isinstance(schema.get("items"), dict):
            for index, item in enumerate(value): validate(item, schema["items"], f"{path}[{index}]", errors)
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]: errors.append(f"{path}: string shorter than {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]: errors.append(f"{path}: string longer than {schema['maxLength']}")
        if "pattern" in schema and re.search(schema["pattern"], value) is None: errors.append(f"{path}: does not match pattern {schema['pattern']!r}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]: errors.append(f"{path}: below minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]: errors.append(f"{path}: above maximum {schema['maximum']}")
    for keyword in ("allOf", "anyOf", "oneOf", "not", "$ref", "if", "then", "else"):
        if keyword in schema: errors.append(f"{path}: unsupported schema keyword {keyword!r}; extend schema_validate.py before relying on it")


def main() -> int:
    errors: list[str] = []
    schemas_dir = CONTROL / "schemas"
    for path in sorted(schemas_dir.glob("*.json")):
        try: json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc: errors.append(f"{path.relative_to(CONTROL.parent)}: invalid schema JSON: {exc}")
    for document_path in sorted(CONTROL.glob("*.json")):
        try: document = json.loads(document_path.read_text(encoding="utf-8"))
        except Exception as exc: errors.append(f"{document_path.name}: invalid JSON: {exc}"); continue
        schema_ref = document.get("$schema")
        if not isinstance(schema_ref, str) or not schema_ref.startswith("./schemas/"):
            errors.append(f"{document_path.name}: missing local $schema reference"); continue
        schema_path = CONTROL / schema_ref[2:]
        if not schema_path.exists(): errors.append(f"{document_path.name}: schema does not exist: {schema_ref}"); continue
        try: schema = json.loads(schema_path.read_text(encoding="utf-8"))
        except Exception as exc: errors.append(f"{document_path.name}: cannot load schema {schema_ref}: {exc}"); continue
        validate(document, schema, document_path.name, errors)
    if errors:
        for error in errors: print(f"ERROR: {error}")
        print(f"Schema validation FAILED ({len(errors)} error(s)).")
        return 1
    print("Schema validation PASS.")
    return 0


if __name__ == "__main__": sys.exit(main())
