from __future__ import annotations

from pathlib import Path

from viva_marketplace import scanner


def test_scan_python_detects_process_and_step(tmp_path: Path) -> None:
    (tmp_path / "procs.py").write_text(
        """
class Process:
    pass

class Step:
    pass

class MyThing(Process):
    description = "does a thing"

class MyStep(Step):
    '''First line of the docstring.

    More detail that should be ignored.
    '''
""",
        encoding="utf-8",
    )
    composites, processes, steps = scanner.scan_python(tmp_path)
    assert composites == []
    assert processes == [{"name": "MyThing", "description": "does a thing"}]
    assert steps == [{"name": "MyStep", "description": "First line of the docstring."}]


def test_scan_python_ignores_base_classes_and_test_dirs(tmp_path: Path) -> None:
    (tmp_path / "base.py").write_text("class Process:\n    pass\n", encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_foo.py").write_text(
        "class NoiseProcess(Process):\n    pass\n", encoding="utf-8"
    )
    _, processes, steps = scanner.scan_python(tmp_path)
    assert processes == []
    assert steps == []


def test_scan_python_detects_composite_generator(tmp_path: Path) -> None:
    (tmp_path / "comp.py").write_text(
        '@composite_generator(name="my-comp", description="wires things")\n'
        "def build():\n    ...\n",
        encoding="utf-8",
    )
    composites, _, _ = scanner.scan_python(tmp_path)
    assert composites == [{"name": "my-comp", "description": "wires things"}]


def test_scan_python_extracts_static_ports(tmp_path: Path) -> None:
    (tmp_path / "ports.py").write_text(
        """
class Process:
    pass

class StaticPortsProcess(Process):
    description = "has literal ports"

    def inputs(self):
        return {"concentration": "float", "volume": {"_type": "float"}}

    def outputs(self):
        return {"flux": "float"}

class DynamicPortsProcess(Process):
    description = "computes ports from config"

    def inputs(self):
        return {k: "float" for k in self.config["species"]}
""",
        encoding="utf-8",
    )
    _, processes, _ = scanner.scan_python(tmp_path)
    by_name = {p["name"]: p for p in processes}

    assert by_name["StaticPortsProcess"]["ports"] == {
        "inputs": {"concentration": "float", "volume": "float"},
        "outputs": {"flux": "float"},
    }
    # Dynamically-computed ports must NOT be reported as if they were known.
    assert "ports" not in by_name["DynamicPortsProcess"]


def test_scan_specs_reads_study_yaml(tmp_path: Path) -> None:
    study_dir = tmp_path / "studies" / "my-study"
    study_dir.mkdir(parents=True)
    (study_dir / "study.yaml").write_text(
        "name: my-study\nobjective: check growth rate\n", encoding="utf-8"
    )
    out = scanner.scan_specs(tmp_path, "studies", "study.yaml", ("objective", "purpose", "title"))
    assert out == [{"name": "my-study", "description": "check growth rate"}]


def test_attest_pinned_ref_and_lockfile(tmp_path: Path) -> None:
    (tmp_path / "uv.lock").write_text("", encoding="utf-8")
    (tmp_path / "LICENSE").write_text("MIT", encoding="utf-8")
    sha = "a" * 40
    result = scanner.attest(tmp_path, sha)
    assert result["pinned_ref"] is True
    assert result["has_lockfile"] is True
    assert result["has_license"] is True
    assert result["has_citation"] is False
    assert result["studies_total"] == 0
    assert 0.0 < result["score"] <= 1.0


def test_attest_floating_ref_scores_lower_than_pinned(tmp_path: Path) -> None:
    pinned = scanner.attest(tmp_path, "a" * 40)
    floating = scanner.attest(tmp_path, "main")
    assert floating["pinned_ref"] is False
    assert floating["score"] < pinned["score"]


def test_attest_studies_without_criteria_lower_score(tmp_path: Path) -> None:
    study_dir = tmp_path / "studies" / "s1"
    study_dir.mkdir(parents=True)
    (study_dir / "study.yaml").write_text("name: s1\n", encoding="utf-8")
    result = scanner.attest(tmp_path, "a" * 40)
    assert result["studies_total"] == 1
    assert result["studies_with_acceptance_criteria"] == 0
    assert result["studies_with_baseline"] == 0

    study_dir2 = tmp_path / "studies" / "s2"
    study_dir2.mkdir(parents=True)
    (study_dir2 / "study.yaml").write_text(
        "name: s2\nacceptance_criteria: [x]\nbaseline: ref\n", encoding="utf-8"
    )
    better = scanner.attest(tmp_path, "a" * 40)
    assert better["score"] > result["score"]
