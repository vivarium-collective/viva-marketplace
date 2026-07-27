#!/usr/bin/env python3
"""Build ``viva_marketplace/ecosystem-index.json`` from the repo registry.

For every repo in ``modules.json`` we try its ALREADY-PUBLISHED read-only
workbench dashboard — a v2ecoli-style repo publishes
``https://<org>.github.io/<repo>/dashboard/api/{registry,composites,
investigation-summaries,investigations}.json`` — and harvest the artifact names
+ descriptions from there. No new per-repo format is required: this reuses the
JSON the workbench's ``publish.py`` already emits.

Repos that don't publish a dashboard are still listed (with empty artifact lists
and ``published: false``) so the ledger is complete and the gap is visible; a
clone+introspect fallback (``vivarium-workbench gen-index``) can fill those in a
later pass.

Usage:  python scripts/build_ecosystem_index.py [--out <path>] [--timeout N]
Pure stdlib so CI needs no dependencies.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "viva_marketplace"


def _org_repo(source: str) -> tuple[str, str]:
    """('https://github.com/vivarium-collective/pbg-copasi.git') → ('vivarium-collective', 'pbg-copasi')."""
    s = re.sub(r"\.git$", "", (source or "").strip())
    s = re.sub(r"^git@github\.com:", "https://github.com/", s)
    m = re.search(r"github\.com[/:]([^/]+)/([^/]+)/?$", s)
    if m:
        return m.group(1), m.group(2)
    return "vivarium-collective", s.rsplit("/", 1)[-1]


def _fetch_json(url: str, timeout: float):
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            return json.loads(resp.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 — a missing/broken dashboard is expected, not fatal
        return None


def _named(items, name_keys=("name",), desc_keys=("description", "title", "objective")):
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            if isinstance(it, str):
                out.append({"name": it, "description": ""})
            continue
        name = next((it.get(k) for k in name_keys if it.get(k)), None)
        if not name:
            continue
        desc = next((it.get(k) for k in desc_keys if it.get(k)), "") or ""
        out.append({"name": str(name), "description": str(desc)})
    return out


def harvest_repo(module: dict, timeout: float) -> dict:
    name = module.get("name") or module.get("package") or ""
    source = module.get("source") or module.get("homepage") or ""
    org, repo = _org_repo(source)
    base = f"https://{org}.github.io/{repo}/dashboard/api"

    reg = _fetch_json(f"{base}/registry.json", timeout)
    comps = _fetch_json(f"{base}/composites.json", timeout)
    isets = _fetch_json(f"{base}/investigation-summaries.json", timeout)
    studies_raw = _fetch_json(f"{base}/investigations.json", timeout)
    published = any(x is not None for x in (reg, comps, isets, studies_raw))

    procs = [p for p in ((reg or {}).get("processes") or []) if p.get("kind") == "process"]
    steps = [p for p in ((reg or {}).get("processes") or []) if p.get("kind") == "step"]
    comp_list = comps if isinstance(comps, list) else (comps or {}).get("composites") or []
    iset_list = (isets or {}).get("investigations") or []
    study_list = (studies_raw or {}).get("investigations") or []

    processes = _named(procs, desc_keys=("description",))
    steps_n = _named(steps, desc_keys=("description",))
    composites = _named(comp_list, desc_keys=("description",))
    investigations = _named(iset_list, desc_keys=("title", "description"))
    studies = _named(study_list, desc_keys=("description", "objective"))

    return {
        "name": name,
        "repo": repo,
        "source": re.sub(r"\.git$", "", source),
        "homepage": module.get("homepage") or f"https://github.com/{org}/{repo}",
        "description": module.get("description") or "",
        "tags": module.get("tags") or [],
        "published": published,
        "dashboard": f"https://{org}.github.io/{repo}/dashboard" if published else None,
        "processes": processes,
        "steps": steps_n,
        "composites": composites,
        "studies": studies,
        "investigations": investigations,
        "counts": {
            "processes": len(processes), "steps": len(steps_n),
            "composites": len(composites), "studies": len(studies),
            "investigations": len(investigations),
        },
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(PKG / "ecosystem-index.json"))
    ap.add_argument("--timeout", type=float, default=15.0)
    ap.add_argument("--stamp", default=None,
                    help="ISO timestamp for generated_at (default: now, UTC)")
    args = ap.parse_args(argv)

    modules = json.loads((PKG / "modules.json").read_text(encoding="utf-8"))
    if isinstance(modules, dict):
        modules = modules.get("modules") or []

    repos = []
    for m in modules:
        if not isinstance(m, dict):
            continue
        entry = harvest_repo(m, args.timeout)
        c = entry["counts"]
        print(f"  {entry['name']:24} published={str(entry['published']):5} "
              f"proc={c['processes']} step={c['steps']} comp={c['composites']} "
              f"study={c['studies']} inv={c['investigations']}", file=sys.stderr)
        repos.append(entry)

    index = {
        "generated_at": args.stamp or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_repos": len(repos),
        "n_published": sum(1 for r in repos if r["published"]),
        "repos": repos,
    }
    Path(args.out).write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out}: {index['n_repos']} repos, {index['n_published']} published",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
