#!/usr/bin/env python3
"""Build ``viva_marketplace/ecosystem-index.json`` from the repo registry.

For every repo in ``modules.json`` we **shallow-clone the repo and scan its
source** — no published dashboard required. What we extract:

- **composites** — ``@composite_generator(name=…, description=…)`` decorators
  (AST) plus any ``*.composite.yaml`` files.
- **processes / steps** — top-level classes whose base ends in ``Process`` /
  ``Step`` (AST), with the description taken from a ``description`` class
  attribute or the class docstring.
- **studies** — ``**/studies/*/study.yaml`` (name + objective/title).
- **investigations** — ``**/investigations/*/investigation.yaml`` (name + title).

This gives complete coverage across the ecosystem regardless of whether a repo
publishes a workbench dashboard. Repos that can't be cloned are still listed
(empty artifacts, ``cloned: false``).

Usage:  python scripts/build_ecosystem_index.py [--out PATH] [--timeout N] [--jobs N]
Needs: git + PyYAML.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "viva_marketplace"

_PROC_BASE = re.compile(r"(Process|Step)$")

# A repo "publishes to the marketplace" by adding this GitHub topic. Membership
# is discovered from the org (no hand-maintained list) — see discover_modules.
MARKETPLACE_TOPIC = "viva-marketplace"
ORG = "vivarium-collective"


def discover_modules(timeout: float = 60.0) -> list[dict]:
    """Discover the marketplace registry from GitHub: every PUBLIC, non-archived
    ``vivarium-collective`` repo carrying the ``viva-marketplace`` topic.

    This replaces the hand-maintained ``modules.json`` membership list — a repo
    joins the marketplace by adding the topic (``gh repo edit --add-topic
    viva-marketplace``), and the daily index build picks it up automatically.
    Returns registry entries in the same shape modules.json used
    (name/source/ref/package/homepage/description/tags), sorted by name.
    """
    import urllib.parse
    import urllib.request

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    q = f"org:{ORG} topic:{MARKETPLACE_TOPIC} archived:false"
    modules: list[dict] = []
    page = 1
    while True:
        url = ("https://api.github.com/search/repositories?q="
               + urllib.parse.quote(q)
               + f"&per_page=100&page={page}&sort=full_name&order=asc")
        headers = {"Accept": "application/vnd.github+json",
                   "User-Agent": "viva-marketplace-index"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        items = data.get("items", []) or []
        for it in items:
            modules.append({
                "name": it["name"],
                "source": it.get("clone_url") or f"{it['html_url']}.git",
                "ref": it.get("default_branch") or "main",
                "package": it["name"].replace("-", "_"),
                "homepage": it.get("html_url"),
                "description": it.get("description") or "",
                "tags": sorted(t for t in (it.get("topics") or [])
                               if t != MARKETPLACE_TOPIC),
            })
        total = int(data.get("total_count") or 0)
        if len(items) < 100 or len(modules) >= total:
            break
        page += 1
    modules.sort(key=lambda m: m["name"].lower())
    return modules


def _org_repo(source: str) -> tuple[str, str]:
    s = re.sub(r"\.git$", "", (source or "").strip())
    s = re.sub(r"^git@github\.com:", "https://github.com/", s)
    m = re.search(r"github\.com[/:]([^/]+)/([^/]+)/?$", s)
    return (m.group(1), m.group(2)) if m else ("vivarium-collective", s.rsplit("/", 1)[-1])


def _clone(url: str, ref: str, dest: Path, timeout: float) -> bool:
    """Shallow-clone url@ref into dest. Falls back to the default branch if the
    ref doesn't exist. Returns True on success."""
    base = ["git", "clone", "--depth", "1", "--quiet"]
    for args in ([*base, "--branch", ref, url, str(dest)] if ref else None,
                 [*base, url, str(dest)]):
        if args is None:
            continue
        try:
            subprocess.run(args, check=True, capture_output=True, text=True, timeout=timeout)
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            continue
    return False


def _class_description(node: ast.ClassDef) -> str:
    # Prefer a `description = "..."` class attribute (pbg convention), else the
    # first line of the docstring.
    for stmt in node.body:
        if (isinstance(stmt, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "description" for t in stmt.targets)
                and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str)):
            return stmt.value.value.strip().splitlines()[0]
    doc = ast.get_docstring(node) or ""
    return doc.strip().splitlines()[0] if doc.strip() else ""


def _kw_str(call: ast.Call, name: str) -> str:
    for kw in call.keywords:
        if kw.arg == name and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
            return kw.value.value
    return ""


def _scan_python(root: Path) -> tuple[list, list, list]:
    composites, processes, steps = [], [], []
    seen_c, seen_p, seen_s = set(), set(), set()
    for py in root.rglob("*.py"):
        # Skip vendored / test / build noise.
        parts = set(py.parts)
        if parts & {".git", "tests", "test", "build", "dist", "node_modules", ".venv", "venv"}:
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8", errors="ignore"))
        except (SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for b in node.bases:
                    bname = b.attr if isinstance(b, ast.Attribute) else (b.id if isinstance(b, ast.Name) else "")
                    if not _PROC_BASE.search(bname or "") or node.name in ("Process", "Step"):
                        continue
                    if bname.endswith("Step"):
                        if node.name not in seen_s:
                            seen_s.add(node.name)
                            steps.append({"name": node.name, "description": _class_description(node)})
                    else:
                        if node.name not in seen_p:
                            seen_p.add(node.name)
                            processes.append({"name": node.name, "description": _class_description(node)})
                    break
            elif isinstance(node, ast.Call):
                fn = node.func
                fname = fn.attr if isinstance(fn, ast.Attribute) else (fn.id if isinstance(fn, ast.Name) else "")
                if fname == "composite_generator":
                    nm = _kw_str(node, "name")
                    if nm and nm not in seen_c:
                        seen_c.add(nm)
                        composites.append({"name": nm, "description": _kw_str(node, "description")})
    # *.composite.yaml files
    for cy in root.rglob("*.composite.yaml"):
        if ".git" in cy.parts:
            continue
        nm = cy.name[: -len(".composite.yaml")]
        desc = ""
        if yaml:
            try:
                d = yaml.safe_load(cy.read_text(encoding="utf-8")) or {}
                nm = d.get("name") or nm
                desc = d.get("description") or ""
            except Exception:  # noqa: BLE001
                pass
        if nm not in seen_c:
            seen_c.add(nm)
            composites.append({"name": nm, "description": desc})
    return composites, processes, steps


def _scan_specs(root: Path, kind: str, spec_name: str, desc_keys) -> list:
    out, seen = [], set()
    for spec in root.rglob(f"{kind}/*/{spec_name}"):
        if ".git" in spec.parts:
            continue
        name, desc = spec.parent.name, ""
        if yaml:
            try:
                d = yaml.safe_load(spec.read_text(encoding="utf-8")) or {}
                name = d.get("name") or name
                for k in desc_keys:
                    v = d.get(k)
                    if isinstance(v, dict):
                        v = v.get("question") or v.get("objective")
                    if v:
                        desc = str(v); break
            except Exception:  # noqa: BLE001
                pass
        if name not in seen:
            seen.add(name)
            out.append({"name": name, "description": desc})
    return out


def harvest_repo(module: dict, timeout: float) -> dict:
    name = module.get("name") or module.get("package") or ""
    source = module.get("source") or module.get("homepage") or ""
    ref = module.get("ref") or ""
    org, repo = _org_repo(source)
    entry = {
        "name": name, "repo": repo, "source": re.sub(r"\.git$", "", source),
        "homepage": module.get("homepage") or f"https://github.com/{org}/{repo}",
        "description": module.get("description") or "", "tags": module.get("tags") or [],
        "cloned": False, "processes": [], "steps": [], "composites": [],
        "studies": [], "investigations": [],
    }
    with tempfile.TemporaryDirectory() as td:
        dest = Path(td) / repo
        if _clone(re.sub(r"^git@github\.com:", "https://github.com/", source) or f"https://github.com/{org}/{repo}.git",
                  ref, dest, timeout):
            entry["cloned"] = True
            comps, procs, steps = _scan_python(dest)
            entry["composites"] = comps
            entry["processes"] = procs
            entry["steps"] = steps
            entry["studies"] = _scan_specs(dest, "studies", "study.yaml",
                                           ("objective", "purpose", "title", "description"))
            entry["investigations"] = _scan_specs(dest, "investigations", "investigation.yaml",
                                                  ("title", "description", "objective"))
    entry["counts"] = {k: len(entry[k]) for k in
                       ("processes", "steps", "composites", "studies", "investigations")}
    return entry


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(PKG / "ecosystem-index.json"))
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--stamp", default=None)
    ap.add_argument("--only", default=None, help="comma-separated repo names to limit (debug)")
    ap.add_argument("--no-discover", action="store_true",
                    help="skip GitHub topic discovery; use the committed modules.json as-is "
                         "(offline / no token)")
    args = ap.parse_args(argv)

    # Discover the registry from the `viva-marketplace` GitHub topic and refresh
    # the committed modules.json (the generated cache). Fall back to the committed
    # list if discovery fails (offline / API error) so the build never breaks.
    if not args.no_discover:
        try:
            discovered = discover_modules(args.timeout)
            (PKG / "modules.json").write_text(
                json.dumps(discovered, indent=2) + "\n", encoding="utf-8")
            print(f"discovered {len(discovered)} repos via topic "
                  f"'{MARKETPLACE_TOPIC}' -> refreshed modules.json", file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            print(f"WARNING: topic discovery failed ({e}); using committed "
                  f"modules.json", file=sys.stderr)

    modules = json.loads((PKG / "modules.json").read_text(encoding="utf-8"))
    if isinstance(modules, dict):
        modules = modules.get("modules") or []
    only = set(args.only.split(",")) if args.only else None

    repos = []
    for m in modules:
        if not isinstance(m, dict):
            continue
        if only and m.get("name") not in only:
            continue
        entry = harvest_repo(m, args.timeout)
        c = entry["counts"]
        print(f"  {entry['name']:24} cloned={str(entry['cloned']):5} "
              f"proc={c['processes']} step={c['steps']} comp={c['composites']} "
              f"study={c['studies']} inv={c['investigations']}", file=sys.stderr)
        repos.append(entry)

    index = {
        "generated_at": args.stamp or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_repos": len(repos),
        "n_cloned": sum(1 for r in repos if r["cloned"]),
        "repos": repos,
    }
    Path(args.out).write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out}: {index['n_repos']} repos, {index['n_cloned']} cloned", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
