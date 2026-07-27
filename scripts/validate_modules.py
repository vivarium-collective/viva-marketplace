#!/usr/bin/env python3
"""Validate ``viva_marketplace/modules.json`` — the PR gate for the registry.

Checks that keep the ledger sane without being heavy-handed:
  - the file is a JSON list of objects
  - every entry has a non-empty ``name`` and a GitHub ``source`` URL
  - ``name`` values are unique
  - optional fields have the right shape (``tags`` is a list, ``ref`` /
    ``description`` / ``package`` are strings)

Exits non-zero (printing every problem) so a bad PR fails CI. Pure stdlib.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

MODULES = Path(__file__).resolve().parent.parent / "viva_marketplace" / "modules.json"
_GH = re.compile(r"^(https://github\.com/|git@github\.com:)[\w.-]+/[\w.-]+", re.I)


def validate(path: Path = MODULES) -> list[str]:
    errors: list[str] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return [f"{path.name}: not valid JSON — {e}"]

    mods = data.get("modules") if isinstance(data, dict) else data
    if not isinstance(mods, list):
        return [f"{path.name}: expected a JSON list of module objects"]

    seen: dict[str, int] = {}
    for i, m in enumerate(mods):
        where = f"entry[{i}]"
        if not isinstance(m, dict):
            errors.append(f"{where}: must be an object")
            continue
        name = m.get("name")
        where = f"{where} ({name!r})"
        if not (isinstance(name, str) and name.strip()):
            errors.append(f"{where}: missing/empty 'name'")
        else:
            if name in seen:
                errors.append(f"{where}: duplicate 'name' (also entry[{seen[name]}])")
            seen[name] = i
        src = m.get("source") or ""
        if not (isinstance(src, str) and _GH.match(src)):
            errors.append(f"{where}: 'source' must be a GitHub URL (got {src!r})")
        if "tags" in m and not isinstance(m["tags"], list):
            errors.append(f"{where}: 'tags' must be a list")
        for k in ("ref", "description", "package", "display_name", "homepage"):
            if k in m and not isinstance(m[k], str):
                errors.append(f"{where}: '{k}' must be a string")
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
