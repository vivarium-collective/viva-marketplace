"""viva_marketplace.scanner — clone + statically scan a process-bigraph repo's source.

Extracted so this extraction logic is importable, not just script-local: it's
shared by ``scripts/build_ecosystem_index.py`` (the nightly ledger builder,
which clones each registered repo) and ``viva_marketplace.selfcheck`` (a repo
maintainer scanning their own local checkout before opening a registry PR).

What we extract from a repo's source, whether cloned or a local working tree:

- **composites** — ``@composite_generator(name=…, description=…)`` decorators
  (AST) plus any ``*.composite.yaml`` files.
- **processes / steps** — top-level classes whose base ends in ``Process`` /
  ``Step`` (AST), described by a ``description`` class attribute or the class
  docstring, plus a best-effort ``ports`` dict when ``inputs()``/``outputs()``
  resolve to a literal ``return {...}`` (many real implementations compute
  ports dynamically — those are simply omitted, see ``_extract_ports_method``).
- **studies** — ``**/studies/*/study.yaml`` (name + objective/title).
- **investigations** — ``**/investigations/*/investigation.yaml`` (name + title).
- **attestation** — a static, mechanically-verifiable reproducibility/FAIR-style
  score (pinned commit, lockfile/license/citation presence, schema_version,
  acceptance-criteria/baseline coverage). A heuristic signal, not a certification
  — see ``attest()``.
"""
from __future__ import annotations

import ast
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

__all__ = [
    "attest",
    "clone",
    "harvest_all",
    "harvest_repo",
    "org_repo",
    "scan_local",
    "scan_python",
    "scan_specs",
]

_PROC_BASE = re.compile(r"(Process|Step)$")
_ARTIFACT_KEYS = ("processes", "steps", "composites", "studies", "investigations")

_LOCKFILE_NAMES = (
    "uv.lock", "poetry.lock", "Pipfile.lock", "package-lock.json",
    "yarn.lock", "pnpm-lock.yaml", "environment.lock.yml",
)
_LICENSE_NAMES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "LICENSE.rst", "COPYING")
_CITATION_NAMES = ("CITATION.cff", "CITATION.bib", "CITATION")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def org_repo(source: str) -> tuple[str, str]:
    s = re.sub(r"\.git$", "", (source or "").strip())
    s = re.sub(r"^git@github\.com:", "https://github.com/", s)
    m = re.search(r"github\.com[/:]([^/]+)/([^/]+)/?$", s)
    return (m.group(1), m.group(2)) if m else ("vivarium-collective", s.rsplit("/", 1)[-1])


def _run(args: list[str], timeout: float) -> bool:
    try:
        subprocess.run(args, check=True, capture_output=True, text=True, timeout=timeout)
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def clone(url: str, ref: str, dest: Path, timeout: float) -> bool:
    """Shallow-clone url@ref into dest. Falls back to the default branch if the
    ref doesn't resolve. Returns True on success.

    A 40-hex-char ref is fetched by exact commit: ``git clone --branch`` only
    resolves branch/tag *names* against the remote's ref advertisement, so
    ``git clone --branch <full-sha>`` fails outright even when the commit
    exists — verified against a real GitHub repo. Pinned refs are instead
    fetched directly (``fetch --depth 1 origin <sha>`` + ``checkout
    FETCH_HEAD``), which GitHub supports for reachable commits. Without this,
    a maintainer who pins ``ref`` to a commit SHA would silently get the
    default branch instead — while ``attest()``'s pinned_ref axis (the
    heaviest-weighted one) would still score them as pinned.
    """
    ref = (ref or "").strip()
    if _SHA_RE.match(ref):
        if (_run(["git", "init", "--quiet", str(dest)], timeout)
                and _run(["git", "-C", str(dest), "remote", "add", "origin", url], timeout)
                and _run(["git", "-C", str(dest), "fetch", "--quiet", "--depth", "1", "origin", ref], timeout)
                and _run(["git", "-C", str(dest), "checkout", "--quiet", "FETCH_HEAD"], timeout)):
            return True
        shutil.rmtree(dest, ignore_errors=True)

    base = ["git", "clone", "--depth", "1", "--quiet"]
    for args in ([*base, "--branch", ref, url, str(dest)] if ref and not _SHA_RE.match(ref) else None,
                 [*base, url, str(dest)]):
        if args is None:
            continue
        if _run(args, timeout):
            return True
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


def _literal_type_repr(node: ast.AST) -> str | None:
    """Best-effort: resolve a port's declared type to a short string, only
    when it's a literal a static reader can trust — a bare type-name string,
    or a bigraph-schema dict literal with a literal ``_type`` key."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Dict):
        for k, v in zip(node.keys, node.values, strict=True):
            if (isinstance(k, ast.Constant) and k.value == "_type"
                    and isinstance(v, ast.Constant) and isinstance(v.value, str)):
                return v.value
    return None


def _extract_ports_method(node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, str] | None:
    """Extract a ``inputs()``/``outputs()`` method's port->type mapping, but
    only when its body is exactly a single ``return {...}`` literal (ignoring
    a leading docstring) and every key/value resolves statically. Anything
    else (computed from ``self.config``, conditionals, etc. — the common
    case) returns None: absence here just means "not statically knowable",
    not "no ports"."""
    body = [
        s for s in node.body
        if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant) and isinstance(s.value.value, str))
    ]
    if len(body) != 1 or not isinstance(body[0], ast.Return) or not isinstance(body[0].value, ast.Dict):
        return None
    d = body[0].value
    ports: dict[str, str] = {}
    for k, v in zip(d.keys, d.values, strict=True):
        if not (isinstance(k, ast.Constant) and isinstance(k.value, str)):
            return None
        t = _literal_type_repr(v)
        if t is None:
            return None
        ports[k.value] = t
    return ports


def _extract_ports(class_node: ast.ClassDef) -> dict[str, dict[str, str]] | None:
    """Best-effort ``{"inputs": {...}, "outputs": {...}}`` for a Process/Step
    class, including only the sides that resolved statically. Returns None
    when neither side is statically extractable."""
    ports: dict[str, dict[str, str]] = {}
    for stmt in class_node.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and stmt.name in ("inputs", "outputs"):
            resolved = _extract_ports_method(stmt)
            if resolved is not None:
                ports[stmt.name] = resolved
    return ports or None


def scan_python(root: Path) -> tuple[list, list, list]:
    """Return (composites, processes, steps) found under ``root``."""
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
                    item: dict[str, Any] = {"name": node.name, "description": _class_description(node)}
                    ports = _extract_ports(node)
                    if ports is not None:
                        item["ports"] = ports
                    if bname.endswith("Step"):
                        if node.name not in seen_s:
                            seen_s.add(node.name)
                            steps.append(item)
                    else:
                        if node.name not in seen_p:
                            seen_p.add(node.name)
                            processes.append(item)
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
            except Exception:
                pass
        if nm not in seen_c:
            seen_c.add(nm)
            composites.append({"name": nm, "description": desc})
    return composites, processes, steps


def scan_specs(root: Path, kind: str, spec_name: str, desc_keys) -> list:
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
                        desc = str(v)
                        break
            except Exception:
                pass
        if name not in seen:
            seen.add(name)
            out.append({"name": name, "description": desc})
    return out


def scan_local(root: Path) -> dict[str, Any]:
    """Scan a local working tree (no clone) and return the artifact shape used
    both by ``harvest_repo`` and by ``viva_marketplace.selfcheck``."""
    comps, procs, steps = scan_python(root)
    entry: dict[str, Any] = {
        "composites": comps,
        "processes": procs,
        "steps": steps,
        "studies": scan_specs(root, "studies", "study.yaml",
                               ("objective", "purpose", "title", "description")),
        "investigations": scan_specs(root, "investigations", "investigation.yaml",
                                      ("title", "description", "objective")),
    }
    entry["counts"] = {k: len(entry[k]) for k in _ARTIFACT_KEYS}
    return entry


def _root_has_any(root: Path, names: tuple[str, ...]) -> bool:
    return any((root / n).is_file() for n in names)


def _study_flags(root: Path) -> tuple[int, int, int]:
    """(total studies, studies declaring acceptance_criteria, studies declaring baseline)."""
    total = with_ac = with_base = 0
    if not yaml:
        return total, with_ac, with_base
    for spec in root.rglob("studies/*/study.yaml"):
        if ".git" in spec.parts:
            continue
        total += 1
        try:
            d = yaml.safe_load(spec.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        if d.get("acceptance_criteria"):
            with_ac += 1
        if d.get("baseline"):
            with_base += 1
    return total, with_ac, with_base


def _schema_version_present(root: Path) -> bool:
    if not yaml:
        return False
    for spec in root.rglob("workspace.yaml"):
        if ".git" in spec.parts:
            continue
        try:
            d = yaml.safe_load(spec.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        if d.get("schema_version") is not None:
            return True
    return False


def attest(root: Path, declared_ref: str, pinning_reachable: bool = True) -> dict[str, Any]:
    """Static, mechanically-verifiable reproducibility/FAIR-style attestation
    for a cloned repo — computed from artifacts already on disk during the
    same pass that scans processes/composites, no simulation execution
    required. This is a HEURISTIC signal (presence of these artifacts
    correlates with reproducibility, it doesn't guarantee it), not a
    certification; the exact weights are documented in CONTRIBUTING.md.

    Axes:
      - pinned_ref (0.25): registry `ref` is a full 40-hex commit SHA, not a
        floating branch/tag — a floating ref means "what gets built" silently
        changes over time. Excluded from the weighted average (not scored 0)
        when ``pinning_reachable`` is False — see below.
      - has_lockfile (0.15) / has_license (0.15) / has_citation (0.10)
      - schema_version_present (0.10): a workspace.yaml declares its schema
        version, so tooling changes don't silently reinterpret it.
      - acceptance_criteria / baseline coverage across studies (0.15 / 0.10):
        excluded from the weighted average (not just scored 0) when a repo
        has zero studies, so process-library repos aren't penalized for a
        study convention that doesn't apply to them.

    ``pinning_reachable`` extends that same "exclude what can't apply" rule to
    ``pinned_ref``: under GitHub-topic discovery, ``ref`` is always set to the
    repo's default branch for every entry (see ``discover_modules()`` in
    ``scripts/build_ecosystem_index.py``), so an unpinned repo isn't failing a
    hygiene check it could pass — pinning is structurally unreachable for the
    whole batch. ``harvest_all`` computes this once per build (True if *any*
    entry in the batch is actually pinned, proving it's achievable this run)
    and threads it down here; a caller scoring a single repo in isolation gets
    the conservative default (``True`` — score normally) unless it says
    otherwise.
    """
    pinned = bool(_SHA_RE.match((declared_ref or "").strip()))
    has_lockfile = _root_has_any(root, _LOCKFILE_NAMES) or any(root.glob("requirements*.txt"))
    has_license = _root_has_any(root, _LICENSE_NAMES)
    has_citation = _root_has_any(root, _CITATION_NAMES)
    has_schema_version = _schema_version_present(root)
    studies_total, studies_ac, studies_base = _study_flags(root)

    axes: list[tuple[float, float | None]] = [
        (0.25, (1.0 if pinned else 0.0) if (pinned or pinning_reachable) else None),
        (0.15, 1.0 if has_lockfile else 0.0),
        (0.15, 1.0 if has_license else 0.0),
        (0.10, 1.0 if has_citation else 0.0),
        (0.10, 1.0 if has_schema_version else 0.0),
        (0.15, (studies_ac / studies_total) if studies_total else None),
        (0.10, (studies_base / studies_total) if studies_total else None),
    ]
    weight_sum = sum(w for w, v in axes if v is not None)
    score = (sum(w * v for w, v in axes if v is not None) / weight_sum) if weight_sum else 0.0

    return {
        "pinned_ref": pinned,
        "pinning_reachable": pinning_reachable,
        "has_lockfile": has_lockfile,
        "has_license": has_license,
        "has_citation": has_citation,
        "schema_version_present": has_schema_version,
        "studies_total": studies_total,
        "studies_with_acceptance_criteria": studies_ac,
        "studies_with_baseline": studies_base,
        "score": round(score, 3),
    }


def harvest_repo(module: dict, timeout: float, pinning_reachable: bool = True) -> dict[str, Any]:
    """Shallow-clone and scan a single registry entry. Never raises — a repo
    that fails to clone is still returned, with ``cloned: False`` and empty
    artifact lists, so the index stays a complete enumeration of the registry.

    ``pinning_reachable`` is forwarded to ``attest()`` — see its docstring;
    ``harvest_all`` computes the batch-wide value, a lone caller gets the
    conservative default.
    """
    name = module.get("name") or module.get("package") or ""
    source = module.get("source") or module.get("homepage") or ""
    ref = module.get("ref") or ""
    org, repo = org_repo(source)
    entry: dict[str, Any] = {
        "name": name, "repo": repo, "source": re.sub(r"\.git$", "", source),
        "homepage": module.get("homepage") or f"https://github.com/{org}/{repo}",
        "description": module.get("description") or "", "tags": module.get("tags") or [],
        "cloned": False, "processes": [], "steps": [], "composites": [],
        "studies": [], "investigations": [],
    }
    with tempfile.TemporaryDirectory() as td:
        dest = Path(td) / repo
        url = re.sub(r"^git@github\.com:", "https://github.com/", source) or f"https://github.com/{org}/{repo}.git"
        if clone(url, ref, dest, timeout):
            entry["cloned"] = True
            entry.update(scan_local(dest))
            entry["attestation"] = attest(dest, ref, pinning_reachable)
    entry["counts"] = {k: len(entry[k]) for k in _ARTIFACT_KEYS}
    return entry


def harvest_all(
    modules: list[dict],
    timeout: float,
    jobs: int = 1,
    on_result: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """Harvest every registry entry, optionally concurrently (cloning is
    I/O-bound, so a thread pool is sufficient — no multiprocessing needed).

    Output order always matches ``modules`` input order regardless of which
    worker finishes first, so the written index stays deterministic (no
    reorder-only diffs from run to run).

    Whether ``pinned_ref`` counts against a repo's attestation score depends
    on whether pinning is reachable *at all* in this batch: computed once,
    up front, from the declared refs already in ``modules`` (no clone
    needed) — True if at least one entry is genuinely SHA-pinned, proving
    it's achievable this run; False means every entry is on a floating ref
    (e.g. the whole registry came from topic discovery, which always writes
    the default branch), so the axis is excluded rather than penalizing
    every repo for a structural gap none of them can close.
    """
    pinning_reachable = any(_SHA_RE.match((m.get("ref") or "").strip()) for m in modules)

    if jobs <= 1:
        results = []
        for m in modules:
            r = harvest_repo(m, timeout, pinning_reachable)
            if on_result:
                on_result(r)
            results.append(r)
        return results

    slots: list[dict[str, Any] | None] = [None] * len(modules)
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        futures = {ex.submit(harvest_repo, m, timeout, pinning_reachable): i for i, m in enumerate(modules)}
        for fut in as_completed(futures):
            i = futures[fut]
            r = fut.result()
            slots[i] = r
            if on_result:
                on_result(r)
    return [s for s in slots if s is not None]
