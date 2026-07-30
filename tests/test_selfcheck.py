from __future__ import annotations

from pathlib import Path

from viva_marketplace import selfcheck


def test_run_reports_unregistered_name(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(selfcheck, "load_modules", lambda: [])
    monkeypatch.setattr(selfcheck, "load_ecosystem_index", lambda: {"repos": []})
    report = selfcheck.run("not-registered", tmp_path)
    assert report["registered"] is False
    assert any("not in modules.json" in w for w in report["warnings"])


def test_run_flags_count_drift_against_the_index(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "proc.py").write_text(
        "class Process:\n    pass\n\nclass Local(Process):\n    description = 'x'\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        selfcheck, "load_modules",
        lambda: [{"name": "my-repo", "description": "d", "tags": ["t"]}],
    )
    monkeypatch.setattr(
        selfcheck, "load_ecosystem_index",
        lambda: {"repos": [{
            "name": "my-repo",
            "counts": {"processes": 0, "steps": 0, "composites": 0, "studies": 0, "investigations": 0},
        }]},
    )
    report = selfcheck.run("my-repo", tmp_path)
    assert report["registered"] is True
    assert report["local_counts"]["processes"] == 1
    assert any("processes" in w for w in report["warnings"])


def test_run_no_drift_when_counts_match(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        selfcheck, "load_modules",
        lambda: [{"name": "my-repo", "description": "d", "tags": ["t"]}],
    )
    monkeypatch.setattr(
        selfcheck, "load_ecosystem_index",
        lambda: {"repos": [{
            "name": "my-repo",
            "counts": {"processes": 0, "steps": 0, "composites": 0, "studies": 0, "investigations": 0},
        }]},
    )
    report = selfcheck.run("my-repo", tmp_path)
    assert report["warnings"] == []
