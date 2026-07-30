#!/usr/bin/env python3
"""Build ``viva_marketplace/ecosystem-index.json`` from the repo registry.

For every repo in ``modules.json`` we **shallow-clone the repo and scan its
source** — no published dashboard required. The clone+scan logic itself lives
in ``viva_marketplace.scanner`` (shared with ``viva_marketplace.selfcheck``);
this script is just the CLI: read the registry, harvest every entry
(optionally in parallel), write the index, and report a build summary.

Usage:  python scripts/build_ecosystem_index.py [--out PATH] [--timeout N] [--jobs N] [--only NAMES]
Needs: git + PyYAML + jsonschema.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "viva_marketplace"

# Allow running straight from a checkout (`python scripts/build_ecosystem_index.py`)
# before `pip install -e .` has been run.
sys.path.insert(0, str(ROOT))

from viva_marketplace import composability, scanner  # noqa: E402

SCHEMA_VERSION = 1
_STALE_AFTER_HOURS = 48


def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_summary(previous: dict | None, index: dict) -> None:
    """Emit a GitHub Actions job summary: repo-count deltas since the last
    build, and a warning if the previous index was stale (catches a silently
    broken nightly cron before a stale registry misleads consumers)."""
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return

    lines = [
        "## ecosystem-index.json rebuild",
        "",
        f"- generated_at: `{index['generated_at']}`",
        f"- repos: {index['n_repos']} ({index['n_cloned']} cloned)",
    ]

    prev_generated = (previous or {}).get("generated_at")
    if prev_generated:
        try:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(prev_generated)
            if age.total_seconds() > _STALE_AFTER_HOURS * 3600:
                lines.append(
                    f"- ⚠️ previous index was stale: last generated `{prev_generated}` "
                    f"({age.days}d ago) — check the nightly build-index cron"
                )
        except ValueError:
            pass

    if previous:
        prev_by_name = {r.get("name"): r for r in previous.get("repos", []) if isinstance(r, dict)}
        deltas = []
        for r in index["repos"]:
            prev = prev_by_name.get(r["name"])
            if prev is None:
                deltas.append(f"  - **{r['name']}**: newly added to the registry")
                continue
            for k in ("processes", "steps", "composites", "studies", "investigations"):
                d = r["counts"][k] - prev.get("counts", {}).get(k, 0)
                if d:
                    deltas.append(f"  - {r['name']}: {k} {'+' if d > 0 else ''}{d}")
        if deltas:
            lines.append("- changes since last build:")
            lines.extend(deltas)

    Path(summary_path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(PKG / "ecosystem-index.json"))
    ap.add_argument("--composability-out", default=str(PKG / "composability-graph.json"),
                     help="where to write the experimental composability graph")
    ap.add_argument("--no-composability", action="store_true",
                     help="skip building the experimental composability graph")
    ap.add_argument("--timeout", type=float, default=120.0, help="per-repo clone timeout in seconds")
    ap.add_argument("--jobs", type=int, default=8, help="parallel clone+scan workers (default: 8)")
    ap.add_argument("--stamp", default=None)
    ap.add_argument("--only", default=None, help="comma-separated repo names to limit (debug)")
    args = ap.parse_args(argv)

    modules = json.loads((PKG / "modules.json").read_text(encoding="utf-8"))
    if isinstance(modules, dict):
        modules = modules.get("modules") or []
    modules = [m for m in modules if isinstance(m, dict)]
    if args.only:
        only = set(args.only.split(","))
        modules = [m for m in modules if m.get("name") in only]

    def report(entry: dict) -> None:
        c = entry["counts"]
        print(f"  {entry['name']:24} cloned={entry['cloned']!s:5} "
              f"proc={c['processes']} step={c['steps']} comp={c['composites']} "
              f"study={c['studies']} inv={c['investigations']}", file=sys.stderr)

    repos = scanner.harvest_all(modules, args.timeout, jobs=max(1, args.jobs), on_result=report)

    out_path = Path(args.out)
    previous = _load_json(out_path)

    index = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": args.stamp or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_repos": len(repos),
        "n_cloned": sum(1 for r in repos if r["cloned"]),
        "repos": repos,
    }
    out_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out_path}: {index['n_repos']} repos, {index['n_cloned']} cloned", file=sys.stderr)

    if not args.no_composability:
        graph = composability.build_graph(repos)
        graph_path = Path(args.composability_out)
        graph_path.write_text(json.dumps(graph, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {graph_path}: {graph['n_edges']} edges "
              f"({graph['n_cross_repo_edges']} cross-repo, truncated={graph['truncated']})", file=sys.stderr)

    _write_summary(previous, index)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
