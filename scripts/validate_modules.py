#!/usr/bin/env python3
"""Validate ``viva_marketplace/modules.json`` — the PR gate for the registry.

Structural checks (types, required fields, the GitHub-URL shape of `source`)
are delegated to ``viva_marketplace/schemas/modules.schema.json`` via
`jsonschema`, so the schema is the single source of truth for "what a valid
entry looks like" — see CONTRIBUTING.md. On top of that we check the one
thing JSON Schema can't express: that `name` values are unique across the
list.

Exits non-zero (printing every problem) so a bad PR fails CI.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
MODULES = ROOT / "viva_marketplace" / "modules.json"
SCHEMA = ROOT / "viva_marketplace" / "schemas" / "modules.schema.json"


def validate(path: Path = MODULES, schema_path: Path = SCHEMA) -> list[str]:
    errors: list[str] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return [f"{path.name}: not valid JSON — {e}"]

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    for err in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path)):
        where = "".join(f"[{p!r}]" if isinstance(p, int) else f".{p}" for p in err.absolute_path) or "(root)"
        errors.append(f"entry{where}: {err.message}")

    mods = data.get("modules") if isinstance(data, dict) else data
    if isinstance(mods, list):
        seen: dict[str, int] = {}
        for i, m in enumerate(mods):
            if not isinstance(m, dict):
                continue
            name = m.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            if name in seen:
                errors.append(f"entry[{i}] ({name!r}): duplicate 'name' (also entry[{seen[name]}])")
            else:
                seen[name] = i

    return errors


def main() -> int:
    errs = validate()
    if errs:
        print(f"✗ {MODULES.name} has {len(errs)} problem(s):", file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
        return 1
    n = len(json.loads(MODULES.read_text()))
    print(f"✓ {MODULES.name} valid — {n} repos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
