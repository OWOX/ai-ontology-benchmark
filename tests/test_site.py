# Spec: docs/specs/site.md
import json
import subprocess
from pathlib import Path
import sys

import pytest

from src.puzzles.registry import get_engine
from src.site import export as site
from ui.gitdata import GitData

ROOT = Path(__file__).resolve().parents[1]

DEFINITIONS = """# Definitions

## Metrics

1. **Precision.** Share of [right](x.md) answers.
2. **Hallucination rate.** The share of attempts with *at least* one
   impossible `move`.
3. **Mismatch detection rate.** The share flagged.

## Prices
"""

SITE_TOML = '''title = "T"
description = "D"
intro = "I"
experiments = ["b-exp", "a-exp"]
'''

EXPERIMENT_TOML = '''release = "1.0.0"
attempts = 2

[[models]]
name = "m1"
provider = "openai"
kind = "system-2"
'''


def record(model, input_id, attempt, outcome="success", created="2026-01-01T00:00:01Z", release="1.0.0"):
    return {"model": model, "puzzle": "2x2", "input_id": input_id, "validity": "valid", "setup": "none",
            "attempt_number": attempt, "scramble_depth": 5, "parsed_moves": ["R"], "outcome": outcome,
            "mismatch": False, "created_at": created, "release_version": release}


def commit(root, message):
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", message], cwd=root, check=True)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True).stdout.strip()


def write_experiment(root, experiment_id, records, toml=EXPERIMENT_TOML):
    folder = root / "results" / experiment_id
    (folder / "raw").mkdir(parents=True)
    (folder / "experiment.toml").write_text(toml)
    (folder / "raw" / "m.jsonl").write_text("\n".join(json.dumps(r) for r in records) + "\n")
    commit(root, experiment_id)


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "site.toml").write_text(SITE_TOML)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "definitions.md").write_text(DEFINITIONS)
    (tmp_path / "releases" / "1.0.0").mkdir(parents=True)
    inputs = [{"input_id": "i1", "state": "S1", "corruption": None},
              {"input_id": "i2", "state": "S2", "corruption": "twisted corner UFL clockwise"}]
    (tmp_path / "releases" / "1.0.0" / "inputs.jsonl").write_text("\n".join(json.dumps(r) for r in inputs) + "\n")
    commit(tmp_path, "main")
    return tmp_path


def test_attempts_sorted_and_filtered(repo):
    write_experiment(repo, "a-exp", [
        record("m2", "i2", 1), record("m1", "i2", 2), record("m1", "i2", 1),
        record("m1", "i1", 1, outcome="infrastructure_failure"), record("m1", "gone", 1)])
    write_experiment(repo, "b-exp", [record("m1", "i1", 1)])
    data, skipped = site.export(GitData(repo), "main")
    assert skipped == 1
    assert [e["experimentId"] for e in data["experiments"]] == ["a-exp", "b-exp"]
    a = data["experiments"][0]
    assert [(x["model"], x["attempt"]) for x in a["attempts"]] == [("m1", 1), ("m1", 2), ("m2", 1)]
    assert a["attemptCount"] == 3 and a["attemptsPerInput"] == 2 and a["release"] == "1.0.0"
    assert a["attempts"][0] == {
        "model": "m1", "puzzle": "2x2", "inputId": "i2", "validity": "valid", "setup": "none", "attempt": 1,
        "depth": 5, "state": "S2", "corruption": "twisted corner UFL clockwise", "moves": ["R"],
        "outcome": "success", "mismatch": False}
    assert a["models"] == [{"name": "m1", "provider": "openai", "kind": "system-2"},
                           {"name": "m2", "provider": "unknown", "kind": "unknown"}]
    assert data["page"] == {"title": "T", "description": "D", "intro": "I"}
    assert data["legalMoves"] == {"2x2": list(get_engine("2x2").legal_moves())}


def test_missing_experiment_is_checked_error(repo, tmp_path):
    write_experiment(repo, "a-exp", [record("m1", "i1", 1)])
    out = tmp_path / "out.json"
    code = subprocess.run([sys.executable, "-m", "src.site.export", "--root", str(repo), "--ref", "main",
                           "--no-fetch", "--out", str(out)], capture_output=True, text=True,
                          cwd=ROOT)
    assert code.returncode == 1
    assert "b-exp" in code.stderr
    assert not out.exists()


def test_definitions_parsing_and_missing_name():
    found, missing = site.read_definitions(DEFINITIONS)
    assert missing == ["Success rate"]
    assert [d["key"] for d in found] == ["hallucination", "detection"]
    assert found[0]["definition"] == "The share of attempts with at least one impossible move."


def test_experiment_without_kept_records_is_checked_error(repo, tmp_path):
    write_experiment(repo, "a-exp", [record("m1", "i1", 1, outcome="infrastructure_failure")])
    write_experiment(repo, "b-exp", [record("m1", "i1", 1)])
    done = subprocess.run([sys.executable, "-m", "src.site.export", "--root", str(repo), "--ref", "main",
                           "--no-fetch", "--out", str(tmp_path / "o.json")], capture_output=True, text=True, cwd=ROOT)
    assert done.returncode == 1
    assert "a-exp" in done.stderr


def test_duplicate_experiment_id_is_checked_error(repo):
    (repo / "config" / "site.toml").write_text(SITE_TOML.replace('["b-exp", "a-exp"]', '["a-exp", "b-exp", "a-exp"]'))
    commit(repo, "duplicate id")
    with pytest.raises(site.ExportError, match="duplicate experiment id a-exp"):
        site.export(GitData(repo), "main")
