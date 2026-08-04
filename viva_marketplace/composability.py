"""viva_marketplace.composability — EXPERIMENTAL cross-repo port compatibility graph.

Process-bigraph Processes/Steps declare typed ``inputs()``/``outputs()``
ports. ``viva_marketplace.scanner`` extracts those ports only when they're
statically knowable (a literal ``return {...}`` — see
``scanner._extract_ports_method``); most real implementations compute ports
from ``self.config`` and simply have no ports recorded here.

This module takes whatever ports *were* extracted, across every repo in the
registry, and matches producer output types to consumer input types by exact
string equality. The result is a hint about which processes from
independently-authored repos *might* wire together — genuinely useful for
discovering composition opportunities across an ecosystem nobody has fully
inventoried by hand, but it is NOT a verified compatibility guarantee:
matching only compares type-name strings, ignores unit/shape semantics, and
coverage is inherently partial (ports computed dynamically are invisible to
it). Always confirm by actually wiring the composite.

**Generic-type matches are labeled, not hidden.** ``_GENERIC_TYPES`` is
process-bigraph's own built-in/primitive core type vocabulary (see
process_bigraph.type_system / bigraph-schema) — ``float``, ``string``,
``integer``, bare ``map``/``list``, etc. Any two ports typed e.g. plain
``float`` "match" this way regardless of what they actually mean, so a bare
generic-type edge carries far less signal than one on a domain-specific type
like ``pymunk_agent`` or ``bulk_array``. Every edge is still emitted (an
overly aggressive filter would just hide real candidates), but each is
tagged ``generic_type`` and the summary separates ``n_generic_type_edges``
from the cross-repo, non-generic count that's the actually-trustworthy
headline number.
"""
from __future__ import annotations

from typing import Any

__all__ = ["build_graph"]

SCHEMA_VERSION = 2
_MAX_EDGES = 5000

# process-bigraph's own built-in/primitive core type names (bigraph-schema's
# base type vocabulary) — matching on one of these alone says nothing about
# domain compatibility, since virtually every process has e.g. a `float` port
# somewhere. Parametrized forms (`map[pymunk_agent]`, `list[float]`, …) are
# NOT included here even when their outer container is generic, because the
# parameter itself already carries a domain hint.
_GENERIC_TYPES = frozenset({
    "any", "string", "float", "integer", "number", "boolean",
    "list", "map", "tuple", "array", "tree", "maybe", "union", "wildcard",
})


def _collect(repos: list[dict[str, Any]], side: str) -> list[tuple[str, str, str, str]]:
    """side: "inputs" or "outputs" -> list of (repo, process_name, port_name, type)."""
    out: list[tuple[str, str, str, str]] = []
    for repo in repos:
        repo_name = repo.get("name", "")
        for kind in ("processes", "steps"):
            for item in repo.get(kind) or []:
                ports = item.get("ports")
                if not ports:
                    continue
                for port_name, port_type in (ports.get(side) or {}).items():
                    out.append((repo_name, item.get("name", ""), port_name, port_type))
    return out


def build_graph(repos: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the best-effort composability graph from already-harvested repo
    entries (as produced by ``scanner.harvest_all`` — each process/step item
    may carry a ``ports`` dict)."""
    outputs = _collect(repos, "outputs")
    inputs = _collect(repos, "inputs")

    edges: list[dict[str, Any]] = []
    truncated = False
    for orepo, oproc, oport, otype in outputs:
        for irepo, iproc, iport, itype in inputs:
            if otype != itype:
                continue
            if orepo == irepo and oproc == iproc:
                continue  # not a composition, just the same class's own port
            if len(edges) >= _MAX_EDGES:
                truncated = True
                break
            edges.append({
                "type": otype,
                "from": {"repo": orepo, "process": oproc, "port": oport},
                "to": {"repo": irepo, "process": iproc, "port": iport},
                "cross_repo": orepo != irepo,
                "generic_type": otype in _GENERIC_TYPES,
            })
        if truncated:
            break

    processes_with_ports = {(r, p) for r, p, _, _ in outputs} | {(r, p) for r, p, _, _ in inputs}
    n_cross_repo = sum(1 for e in edges if e["cross_repo"])
    n_cross_repo_specific = sum(1 for e in edges if e["cross_repo"] and not e["generic_type"])

    return {
        "schema_version": SCHEMA_VERSION,
        "experimental": True,
        "note": (
            "Best-effort static extraction of literal inputs()/outputs() port "
            "declarations, matched by exact type-name string equality. Absence "
            "of an edge does NOT mean incompatibility — most ports are computed "
            "dynamically and aren't visible to this scan. Not a verified wiring "
            "guarantee; confirm by actually composing. Edges on a bare "
            "process-bigraph core type (float, string, map, …) are tagged "
            "generic_type=true — they match on type name alone and carry much "
            "weaker signal than a domain-specific type; "
            "n_cross_repo_specific_type_edges excludes them and is the more "
            "trustworthy headline count."
        ),
        "n_processes_with_ports": len(processes_with_ports),
        "n_edges": len(edges),
        "n_cross_repo_edges": n_cross_repo,
        "n_generic_type_edges": sum(1 for e in edges if e["generic_type"]),
        "n_cross_repo_specific_type_edges": n_cross_repo_specific,
        "truncated": truncated,
        "edges": edges,
    }
