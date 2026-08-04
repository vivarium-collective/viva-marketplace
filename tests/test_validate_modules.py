from __future__ import annotations

import json
from pathlib import Path

import validate_modules  # from scripts/, see conftest.py


def _write(tmp_path: Path, data) -> Path:
    p = tmp_path / "modules.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_valid_registry_passes(tmp_path: Path) -> None:
    data = [
        {"name": "pbg-foo", "source": "https://github.com/vivarium-collective/pbg-foo.git"},
        {"name": "pbg-bar", "source": "https://github.com/vivarium-collective/pbg-bar", "tags": ["ode"]},
    ]
    assert validate_modules.validate(_write(tmp_path, data)) == []


def test_missing_name_and_source_fail(tmp_path: Path) -> None:
    errs = validate_modules.validate(_write(tmp_path, [{"description": "no name or source"}]))
    assert errs
    assert any("name" in e for e in errs)


def test_non_github_source_fails(tmp_path: Path) -> None:
    errs = validate_modules.validate(
        _write(tmp_path, [{"name": "x", "source": "https://gitlab.com/foo/bar"}])
    )
    assert errs


def test_duplicate_name_fails(tmp_path: Path) -> None:
    data = [
        {"name": "dup", "source": "https://github.com/vivarium-collective/a"},
        {"name": "dup", "source": "https://github.com/vivarium-collective/b"},
    ]
    errs = validate_modules.validate(_write(tmp_path, data))
    assert any("duplicate" in e for e in errs)


def test_tags_must_be_a_list(tmp_path: Path) -> None:
    errs = validate_modules.validate(
        _write(tmp_path, [{
            "name": "x", "source": "https://github.com/vivarium-collective/x", "tags": "not-a-list",
        }])
    )
    assert errs


def test_not_a_json_list_fails(tmp_path: Path) -> None:
    p = tmp_path / "modules.json"
    p.write_text('{"oops": true}', encoding="utf-8")
    errs = validate_modules.validate(p)
    assert errs
