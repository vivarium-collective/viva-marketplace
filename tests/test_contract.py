"""Pins the exact on-disk shape vivarium-workbench depends on.

vivarium-workbench's `GET /api/ecosystem-index` and static-snapshot publish
call `viva_marketplace.load_ecosystem_index()` and pass the result straight
through to the frontend (`walkthrough.js`'s Registry/Marketplace tab) with no
schema validation on the consuming side — it just expects a top-level
`{"repos": [...]}` dict and, per repo, `name` plus the artifact lists it
merges into the "Available" category filter. If this test breaks, a change
here is very likely to silently break that UI in a different repo.
"""
from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

import viva_marketplace

ROOT = Path(__file__).resolve().parent.parent


def test_load_modules_returns_a_list_of_dicts() -> None:
    modules = viva_marketplace.load_modules()
    assert isinstance(modules, list)
    assert all(isinstance(m, dict) for m in modules)


def test_load_ecosystem_index_top_level_shape() -> None:
    index = viva_marketplace.load_ecosystem_index()
    assert isinstance(index, dict)
    assert "repos" in index
    assert isinstance(index["repos"], list)


def test_ecosystem_index_repo_entries_carry_the_keys_the_workbench_merges_on() -> None:
    index = viva_marketplace.load_ecosystem_index()
    for repo in index["repos"]:
        assert isinstance(repo.get("name"), str) and repo["name"]
        for kind in ("processes", "steps", "composites", "studies", "investigations"):
            assert isinstance(repo.get(kind), list), f"{repo['name']}.{kind} must be a list"
        assert isinstance(repo.get("counts"), dict)


def test_modules_json_matches_its_schema() -> None:
    data = json.loads((ROOT / "viva_marketplace" / "modules.json").read_text(encoding="utf-8"))
    schema = viva_marketplace.load_schema("modules.schema.json")
    Draft202012Validator(schema).validate(data)


def test_ecosystem_index_matches_its_schema() -> None:
    data = json.loads((ROOT / "viva_marketplace" / "ecosystem-index.json").read_text(encoding="utf-8"))
    schema = viva_marketplace.load_schema("ecosystem-index.schema.json")
    Draft202012Validator(schema).validate(data)


def test_composability_graph_matches_its_schema_if_present() -> None:
    path = ROOT / "viva_marketplace" / "composability-graph.json"
    if not path.exists():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    schema = viva_marketplace.load_schema("composability-graph.schema.json")
    Draft202012Validator(schema).validate(data)


def test_modules_json_names_are_unique() -> None:
    modules = viva_marketplace.load_modules()
    names = [m["name"] for m in modules]
    assert len(names) == len(set(names))
