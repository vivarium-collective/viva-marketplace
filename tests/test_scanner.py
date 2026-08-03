from __future__ import annotations

import subprocess
from pathlib import Path

from viva_marketplace import scanner


def _make_remote(tmp_path: Path) -> tuple[Path, str, str]:
    """A local bare repo with two commits, usable as a `clone()` remote via a
    file:// URL — no network access needed. Returns (bare repo path, first
    commit sha, second/HEAD commit sha)."""
    work = tmp_path / "work"
    work.mkdir()
    subprocess.run(["git", "init", "--quiet", "-b", "main", str(work)], check=True)
    subprocess.run(["git", "-C", str(work), "config", "user.email", "t@example.com"], check=True)
    subprocess.run(["git", "-C", str(work), "config", "user.name", "t"], check=True)
    (work / "f.txt").write_text("v1", encoding="utf-8")
    subprocess.run(["git", "-C", str(work), "add", "f.txt"], check=True)
    subprocess.run(["git", "-C", str(work), "commit", "--quiet", "-m", "c1"], check=True)
    sha1 = subprocess.run(
        ["git", "-C", str(work), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    (work / "f.txt").write_text("v2", encoding="utf-8")
    subprocess.run(["git", "-C", str(work), "commit", "--quiet", "-am", "c2"], check=True)
    sha2 = subprocess.run(
        ["git", "-C", str(work), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    bare = tmp_path / "bare.git"
    subprocess.run(["git", "clone", "--quiet", "--bare", str(work), str(bare)], check=True)
    subprocess.run(["git", "-C", str(bare), "config", "uploadpack.allowReachableSHA1InWant", "true"], check=True)
    return bare, sha1, sha2


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


def test_clone_pinned_sha_checks_out_that_exact_commit(tmp_path: Path) -> None:
    bare, sha1, sha2 = _make_remote(tmp_path)
    dest = tmp_path / "dest"
    assert scanner.clone(f"file://{bare}", sha1, dest, timeout=30)
    assert (dest / "f.txt").read_text(encoding="utf-8") == "v1"
    head = subprocess.run(
        ["git", "-C", str(dest), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    assert head == sha1 != sha2  # pinned to the OLDER commit, not whatever HEAD/main points to


def test_clone_branch_name_uses_default_branch(tmp_path: Path) -> None:
    bare, _sha1, sha2 = _make_remote(tmp_path)
    dest = tmp_path / "dest"
    assert scanner.clone(f"file://{bare}", "main", dest, timeout=30)
    assert (dest / "f.txt").read_text(encoding="utf-8") == "v2"
    head = subprocess.run(
        ["git", "-C", str(dest), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    assert head == sha2


def test_clone_unreachable_sha_falls_back_to_default_branch(tmp_path: Path) -> None:
    bare, _sha1, sha2 = _make_remote(tmp_path)
    dest = tmp_path / "dest"
    bogus_sha = "f" * 40
    assert scanner.clone(f"file://{bare}", bogus_sha, dest, timeout=30)
    head = subprocess.run(
        ["git", "-C", str(dest), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    assert head == sha2


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


def test_attest_pinning_reachable_false_excludes_pinned_axis(tmp_path: Path) -> None:
    (tmp_path / "LICENSE").write_text("MIT", encoding="utf-8")
    penalized = scanner.attest(tmp_path, "main", pinning_reachable=True)
    excluded = scanner.attest(tmp_path, "main", pinning_reachable=False)
    assert penalized["pinned_ref"] is False
    assert excluded["pinned_ref"] is False
    assert excluded["pinning_reachable"] is False
    assert excluded["score"] > penalized["score"]


def test_attest_pinning_reachable_true_still_scores_actually_pinned_repo(tmp_path: Path) -> None:
    result = scanner.attest(tmp_path, "a" * 40, pinning_reachable=False)
    assert result["pinned_ref"] is True
    assert result["score"] > 0.0


def test_harvest_all_pinning_reachable_is_batch_wide(tmp_path: Path) -> None:
    bare, sha1, _sha2 = _make_remote(tmp_path)
    url = f"file://{bare}"
    modules = [
        {"name": "pinned-repo", "source": url, "ref": sha1},
        {"name": "floating-repo", "source": url, "ref": "main"},
    ]
    results = scanner.harvest_all(modules, timeout=30)
    by_name = {r["name"]: r for r in results}
    assert by_name["pinned-repo"]["attestation"]["pinned_ref"] is True
    assert by_name["floating-repo"]["attestation"]["pinned_ref"] is False
    # at least one repo in the batch is actually pinned, so it's demonstrably
    # achievable this run — the floating repo is penalized, not excused.
    assert by_name["floating-repo"]["attestation"]["pinning_reachable"] is True


def test_harvest_all_excludes_pinned_ref_axis_when_nobody_in_the_batch_pins(tmp_path: Path) -> None:
    bare, _sha1, _sha2 = _make_remote(tmp_path)
    modules = [{"name": "floating-only", "source": f"file://{bare}", "ref": "main"}]
    [result] = scanner.harvest_all(modules, timeout=30)
    assert result["attestation"]["pinned_ref"] is False
    assert result["attestation"]["pinning_reachable"] is False


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
