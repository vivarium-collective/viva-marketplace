from __future__ import annotations

from viva_marketplace import composability


def _repo(name: str, processes=None, steps=None):
    return {"name": name, "processes": processes or [], "steps": steps or []}


def test_build_graph_matches_cross_repo_ports() -> None:
    repos = [
        _repo("producer-repo", processes=[
            {"name": "Producer", "description": "", "ports": {"outputs": {"flux": "float"}}},
        ]),
        _repo("consumer-repo", processes=[
            {"name": "Consumer", "description": "", "ports": {"inputs": {"in_flux": "float"}}},
        ]),
    ]
    graph = composability.build_graph(repos)
    assert graph["experimental"] is True
    assert graph["n_edges"] == 1
    assert graph["n_cross_repo_edges"] == 1
    edge = graph["edges"][0]
    assert edge["type"] == "float"
    assert edge["from"] == {"repo": "producer-repo", "process": "Producer", "port": "flux"}
    assert edge["to"] == {"repo": "consumer-repo", "process": "Consumer", "port": "in_flux"}
    assert edge["cross_repo"] is True


def test_build_graph_type_mismatch_produces_no_edge() -> None:
    repos = [
        _repo("a", processes=[{"name": "A", "description": "", "ports": {"outputs": {"x": "float"}}}]),
        _repo("b", processes=[{"name": "B", "description": "", "ports": {"inputs": {"y": "int"}}}]),
    ]
    graph = composability.build_graph(repos)
    assert graph["n_edges"] == 0


def test_build_graph_excludes_self_loops_on_same_class() -> None:
    repos = [
        _repo("a", processes=[{
            "name": "SelfWiring", "description": "",
            "ports": {"inputs": {"x": "float"}, "outputs": {"x": "float"}},
        }]),
    ]
    graph = composability.build_graph(repos)
    assert graph["n_edges"] == 0


def test_build_graph_ignores_items_without_ports() -> None:
    repos = [_repo("a", processes=[{"name": "NoPorts", "description": ""}])]
    graph = composability.build_graph(repos)
    assert graph["edges"] == []
    assert graph["n_processes_with_ports"] == 0
