"""viva_marketplace.selfcheck — drift check for a repo's own registry listing.

A `pbg-*` maintainer can run this against their local checkout, before
opening a PR to `modules.json`, to see:

  - whether their local artifacts (processes/steps/composites/studies) match
    what the last nightly `ecosystem-index.json` build recorded for them
  - whether their `modules.json` entry's `description`/`tags` look stale

It reuses the exact same extraction logic (`viva_marketplace.scanner`) as the
nightly index builder, just pointed at a local working tree instead of a
fresh clone — so "what the ledger will see" and "what selfcheck sees" can
never drift apart from using two different scanners.

As a forward-looking, opt-in extension point (mirroring pbg-ptools'
`workbench_viewers.get_viewers` duck-typed discovery), if the registry
entry's `package` is installed and exposes `<package>.marketplace_info`
with a `get_info()` function, selfcheck calls it and folds the result into
the comparison. No package needs to implement this today — its absence is
silently skipped, same as pbg-ptools does for viewers.

Entirely informational: this never fails a build and never writes to
`modules.json` — the registry stays hand-edited and PR-reviewed. Non-zero
exit is reserved for "the given name isn't registered at all".
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import Any

from viva_marketplace import load_ecosystem_index, load_modules, scanner

__all__ = ["main", "run"]

_COUNT_KEYS = ("processes", "steps", "composites", "studies", "investigations")


def _find_entry(entries: list[dict], name: str) -> dict | None:
    for e in entries:
        if e.get("name") == name:
            return e
    return None


def _probe_marketplace_info(package: str) -> dict[str, Any] | None:
    """Best-effort, soft-fail — see module docstring. Never raises."""
    if not package:
        return None
    try:
        mod = importlib.import_module(f"{package}.marketplace_info")
    except ImportError:
        return None
    get_info = getattr(mod, "get_info", None)
    if not callable(get_info):
        return None
    try:
        info = get_info()
    except Exception:
        return None
    return info if isinstance(info, dict) else None


def run(name: str, path: Path) -> dict[str, Any]:
    """Compute the drift report as a plain dict (used by both the CLI and tests)."""
    registry_entry = _find_entry(load_modules(), name)
    indexed_entry = _find_entry(load_ecosystem_index().get("repos", []), name)

    report: dict[str, Any] = {
        "name": name,
        "path": str(path),
        "registered": registry_entry is not None,
        "warnings": [],
    }
    if registry_entry is None:
        report["warnings"].append(
            f"'{name}' is not in modules.json — nothing to compare against. "
            "Open a PR adding it (see CONTRIBUTING.md) before running selfcheck."
        )
        return report

    local = scanner.scan_local(path)
    report["local_counts"] = local["counts"]

    if indexed_entry is None:
        report["warnings"].append(
            "no ecosystem-index.json entry yet for this repo — it hasn't been built by CI, "
            "or the last build couldn't clone it. Local counts shown, nothing to diff against."
        )
    else:
        report["indexed_counts"] = indexed_entry.get("counts", {})
        for k in _COUNT_KEYS:
            local_n = local["counts"].get(k, 0)
            indexed_n = indexed_entry.get("counts", {}).get(k, 0)
            if local_n != indexed_n:
                report["warnings"].append(
                    f"{k}: local scan finds {local_n}, last published index has {indexed_n} "
                    f"(index may just be stale until the next nightly build)"
                )
        report["attestation"] = indexed_entry.get("attestation")

    if not (registry_entry.get("description") or "").strip():
        report["warnings"].append("modules.json entry has no 'description' — add one.")
    if not registry_entry.get("tags"):
        report["warnings"].append("modules.json entry has no 'tags' — consider adding some for discoverability.")

    self_declared = _probe_marketplace_info(registry_entry.get("package") or "")
    if self_declared is not None:
        report["self_declared"] = self_declared
        for field in ("description", "tags"):
            if field in self_declared and self_declared[field] != registry_entry.get(field):
                report["warnings"].append(
                    f"{registry_entry.get('package')}.marketplace_info declares a different "
                    f"'{field}' than modules.json — consider syncing the registry PR."
                )

    return report


def _print_report(report: dict[str, Any]) -> None:
    print(f"selfcheck: {report['name']} ({report['path']})")
    if not report["registered"]:
        for w in report["warnings"]:
            print(f"  ✗ {w}")
        return
    if "local_counts" in report:
        print(f"  local counts:   {report['local_counts']}")
    if "indexed_counts" in report:
        print(f"  indexed counts: {report['indexed_counts']}")
    if report.get("attestation"):
        print(f"  attestation score: {report['attestation'].get('score')}")
    if report.get("self_declared"):
        print(f"  self-declared (via {'.'.join(['<package>', 'marketplace_info'])}): {report['self_declared']}")
    if report["warnings"]:
        for w in report["warnings"]:
            print(f"  ⚠ {w}")
    else:
        print("  ✓ no drift detected")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("name", help="the 'name' key of this repo's modules.json entry")
    ap.add_argument("--path", default=".", help="local checkout to scan (default: cwd)")
    ap.add_argument("--json", action="store_true", help="print the report as JSON instead of text")
    args = ap.parse_args(argv)

    path = Path(args.path).resolve()
    if not path.is_dir():
        print(f"error: --path {path} is not a directory", file=sys.stderr)
        return 2

    report = run(args.name, path)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_report(report)

    return 0 if report["registered"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
