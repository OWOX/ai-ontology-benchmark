# Spec: docs/specs/site.md
import json
import subprocess
from pathlib import Path
import sys

import pytest

from src.puzzles.registry import get_engine
from src.evaluate.metrics import answer_class
from src.site.metrics import metric_rows
from src.validator import offered_reasons
from src.site import export as site
from ui.gitdata import GitData

ROOT = Path(__file__).resolve().parents[1]

DEFINITIONS = """# Definitions

## Metrics

1. **Balanced precision.** Share of [right](x.md) answers.
2. **Hallucination rate.** The share of attempts with *at least* one
   impossible `move`.
3. **Critical thinking.** The mean of two rates.

## Prices
"""

SITE_TOML = '''min_release = "1.0.0"
title = "T"
description = "D"
intro = "I"
'''

PRICES = '''["m1"]
price_input_per_mtok = 1.0
price_output_per_mtok = 2.0

["m2"]
price_input_per_mtok = 1.0
price_output_per_mtok = 2.0
'''

EXPERIMENT_TOML = '''release = "{release}"
attempts = 2

[[models]]
name = "m1"
provider = "openai"
kind = "system-2"

[[models]]
name = "m2"
provider = "{m2}"
kind = "system-2"
'''

# Real 2x2 inputs of release 3.0.0: a valid one with its invalid copy, and a second pair.
INPUTS = [
    {"corruption": None, "input_id": "v1", "puzzle": "2x2", "scramble": ["L2", "D", "B", "F'", "R"],
     "scramble_depth": 5, "state": "RLRLUUDDFFBBLRLRUUDDBBFF", "validity": "valid"},
    {"corruption": "recoloured sticker L3 D to U", "input_id": "i1", "puzzle": "2x2",
     "scramble": ["L2", "D", "B", "F'", "R"], "scramble_depth": 5, "state": "RLRLUUDDFFBBLRLRUUUDBBFF",
     "validity": "invalid"},
    {"corruption": None, "input_id": "v2", "puzzle": "2x2", "scramble": ["R2", "L2", "U2", "L", "U2"],
     "scramble_depth": 5, "state": "DBDFLRRRBUDBFUBULLLRDFFU", "validity": "valid"},
]


TEMPLATES = {
    "no_model": "Solve this 2x2 cube.\n\n{state}\n\nReasons: {mismatch_reasons}.\n",
    "prescriptive": "Pick from {legal_moves}.\n\n{state}\n",
}


def solution(input_id: str) -> str:
    scramble = next(i for i in INPUTS if i["input_id"] == input_id)["scramble"]
    return "\n".join(m[:-1] if m.endswith("'") else m if m.endswith("2") else m + "'" for m in reversed(scramble))


def raw(model, input_id, attempt, response, outcome="success", setup="no_model", stop="ok",
        created="2026-01-01T00:00:01Z", **extra):
    source = next((i for i in INPUTS if i["input_id"] == input_id), INPUTS[0])
    return {"model": model, "puzzle": "2x2", "input_id": input_id, "validity": source["validity"], "setup": setup,
            "attempt_number": attempt, "scramble_depth": 5, "outcome": outcome, "created_at": created,
            "raw_response": response, "stop_reason": stop, "input_tokens": 1000, "output_tokens": 500,
            "retry_input_tokens": 0, "retry_output_tokens": 0, "latency_s": 1.0, "served_model": model,
            "release_version": "1.0.0", **extra}


def commit(root, message):
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", message], cwd=root, check=True)


def write_experiment(root, experiment_id, records, release="1.0.0", m2="anthropic", prices=None, branch=False):
    """Commit the experiment on main, or with `branch` on a remote-tracking branch origin/results/<id> only."""
    if branch:
        subprocess.run(["git", "checkout", "-q", "-b", "tmp"], cwd=root, check=True)
    folder = root / "results" / experiment_id
    (folder / "raw").mkdir(parents=True)
    (folder / "experiment.toml").write_text(EXPERIMENT_TOML.format(release=release, m2=m2))
    if records is not None:
        (folder / "raw" / "m.jsonl").write_text("\n".join(json.dumps(r) for r in records) + "\n")
    if prices is not None:
        (folder / "prices.toml").write_text(prices)
    commit(root, experiment_id)
    if branch:
        subprocess.run(["git", "update-ref", f"refs/remotes/origin/results/{experiment_id}", "HEAD"], cwd=root,
                       check=True)
        subprocess.run(["git", "checkout", "-q", "main"], cwd=root, check=True)
        subprocess.run(["git", "branch", "-q", "-D", "tmp"], cwd=root, check=True)


def exported(root):
    data, skipped = site.export(GitData(root), "main")
    return data, skipped, {(m["puzzle"], m["model"]): m for m in data["metrics"]}


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "site.toml").write_text(SITE_TOML)
    (tmp_path / "config" / "prices.toml").write_text(PRICES)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "definitions.md").write_text(DEFINITIONS)
    for release, reasons in (("1.0.0", False), ("2.0.0", True)):
        folder = tmp_path / "releases" / release
        folder.mkdir(parents=True)
        (folder / "inputs.jsonl").write_text("\n".join(json.dumps(r) for r in INPUTS) + "\n")
        (folder / "manifest.json").write_text(json.dumps({"mismatch_reasons": reasons}))
        for setup, text in TEMPLATES.items():
            (folder / "prompts" / setup).mkdir(parents=True, exist_ok=True)
            (folder / "prompts" / setup / "2x2.txt").write_text(text)
    commit(tmp_path, "main")
    return tmp_path


def test_discovery_skips_folder_without_raw_records(repo, capsys):
    write_experiment(repo, "a-exp", [raw("m1", "v1", 1, solution("v1"))])
    write_experiment(repo, "b-empty", None)
    data, skipped, _ = exported(repo)
    assert [e["experimentId"] for e in data["experiments"]] == ["a-exp"]
    assert "b-empty" in capsys.readouterr().err


def test_all_infrastructure_failures_still_count_in_cost_but_not_in_experiments(repo):
    failure = dict(outcome="infrastructure_failure", stop="infrastructure_failure")
    write_experiment(repo, "a-exp", [raw("m1", "v1", 1, solution("v1")), raw("m1", "i1", 1, "MISMATCH")])
    write_experiment(repo, "b-exp", [raw("m1", "v1", 1, "", **failure), raw("m1", "v1", 2, "", **failure)])
    data, _, metrics = exported(repo)
    assert [e["experimentId"] for e in data["experiments"]] == ["a-exp"]
    # 4 rows at 0.002, precision 1, coverage 1; the two failures only add cost rows
    assert metrics[("2x2", "m1")]["cost"] == {"value": pytest.approx(0.002), "n": 4}


def test_torn_raw_lines_count_as_skipped(repo):
    write_experiment(repo, "a-exp", [raw("m1", "v1", 1, solution("v1"))])
    path = repo / "results" / "a-exp" / "raw" / "m.jsonl"
    path.write_text(path.read_text() + '{"torn": \n')
    commit(repo, "torn line")
    _, skipped, _ = exported(repo)
    assert skipped == 1


def test_missing_manifest_is_checked_error(repo, tmp_path):
    write_experiment(repo, "a-exp", [raw("m1", "v1", 1, solution("v1"))])
    (repo / "releases" / "1.0.0" / "manifest.json").unlink()
    commit(repo, "no manifest")
    done = subprocess.run([sys.executable, "-m", "src.site.export", "--root", str(repo), "--ref", "main",
                           "--no-fetch", "--out", str(tmp_path / "o.json")], capture_output=True, text=True, cwd=ROOT)
    assert done.returncode == 1 and "releases/1.0.0/manifest.json" in done.stderr


def test_main_exits_zero_with_a_skipped_folder(repo, tmp_path):
    write_experiment(repo, "a-exp", [raw("m1", "v1", 1, solution("v1"))])
    write_experiment(repo, "b-empty", None)
    out = tmp_path / "out.json"
    done = subprocess.run([sys.executable, "-m", "src.site.export", "--root", str(repo), "--ref", "main",
                           "--no-fetch", "--out", str(out)], capture_output=True, text=True, cwd=ROOT)
    assert done.returncode == 0 and "b-empty" in done.stderr and out.exists()


def test_attempts_sorted_filtered_and_revalidated(repo):
    write_experiment(repo, "a-exp", [
        raw("m2", "v2", 1, solution("v2")),
        raw("m1", "v2", 2, solution("v2")),
        raw("m1", "v2", 1, "R\nM", outcome="success"),  # stored success, but M is an impossible move
        raw("m1", "v1", 1, "", outcome="infrastructure_failure", stop="infrastructure_failure"),
        raw("m1", "gone", 1, "R")], )
    data, skipped, _ = exported(repo)
    assert skipped == 1
    a = data["experiments"][0]
    assert [(x["model"], x["attempt"]) for x in a["attempts"]] == [("m1", 1), ("m1", 2), ("m2", 1)]
    assert a["attemptCount"] == 3 and a["attemptsPerInput"] == 2 and a["release"] == "1.0.0"
    first = a["attempts"][0]
    assert first["outcome"] == "hallucination" and first["moves"] == ["R", "M"] and first["mismatch"] is False
    assert first["state"] == INPUTS[2]["state"] and first["inputId"] == "v2" and first["depth"] == 5
    assert a["attempts"][1]["outcome"] == "success" and a["attempts"][1]["moves"] == solution("v2").split("\n")
    assert a["models"] == [{"name": "m1", "provider": "openai", "kind": "system-2"},
                           {"name": "m2", "provider": "anthropic", "kind": "system-2"}]
    assert data["page"] == {"title": "T", "description": "D", "intro": "I"}
    assert data["legalMoves"] == {"2x2": list(get_engine("2x2").legal_moves())}


def test_metrics_values_and_sort(repo):
    write_experiment(repo, "a-exp", [
        raw("m2", "v1", 1, solution("v1")),                      # tp
        raw("m2", "i1", 1, "MISMATCH"),                          # tn (bare MISMATCH, no reasons)
        raw("m1", "v1", 1, solution("v1")),                      # tp
        raw("m1", "v2", 1, "R\nM"),                              # hallucination: fp, impossible move
        raw("m1", "i1", 1, "R"),                                 # fp on invalid
        raw("m1", "i1", 2, "MISMATCH"),                          # tn
        raw("m1", "v1", 2, "I cannot do this"),                  # abstention: not classified
        raw("m1", "v1", 3, "", outcome="infrastructure_failure", stop="infrastructure_failure"),
    ])
    _, _, metrics = exported(repo)
    assert list(metrics) == [("2x2", "m1"), ("2x2", "m2"), ("all", "m1"), ("all", "m2")]
    m1, m2 = metrics[("2x2", "m1")], metrics[("2x2", "m2")]
    assert m1["provider"] == "openai" and m2["provider"] == "anthropic"
    # valid classified: tp, fp -> 0.5; invalid classified: fp, tn -> 0.5
    assert m1["precision"] == {"value": 0.5, "n": 4}
    assert m2["precision"] == {"value": 1.0, "n": 2}
    # rows that gave moves: tp, hallucination, fp -> 1 of 3
    assert m1["hallucination"]["n"] == 3 and m1["hallucination"]["value"] == pytest.approx(1 / 3)
    assert m2["hallucination"] == {"value": 0.0, "n": 1}
    assert m1["critical"] == {"value": None, "n": 0}  # release 1.0.0 has no mismatch reasons
    # cost: mean over 6 rows (the infrastructure failure included) / precision; a row costs 0.002
    assert m1["cost"]["n"] == 6
    assert m1["cost"]["value"] == pytest.approx(0.002 / 0.5)
    # one puzzle only: the pooled row equals the puzzle's row
    assert {k: v for k, v in metrics[("all", "m1")].items() if k != "puzzle"} == {k: v for k, v in m1.items() if k != "puzzle"}
    assert m2["cost"]["value"] == pytest.approx(0.002)


def test_precision_null_without_one_label_and_cost_null_when_precision_zero(repo):
    write_experiment(repo, "a-exp", [
        raw("m1", "v1", 1, solution("v1")),                      # only valid inputs
        raw("m2", "v1", 1, "R"),                                 # valid fp
        raw("m2", "i1", 1, "R"),                                 # invalid fp: precision 0
    ])
    _, _, metrics = exported(repo)
    assert metrics[("2x2", "m1")]["precision"] == {"value": None, "n": 1}
    assert metrics[("2x2", "m1")]["cost"] == {"value": None, "n": 1}
    assert metrics[("2x2", "m2")]["precision"]["value"] == 0.0
    assert metrics[("2x2", "m2")]["cost"] == {"value": None, "n": 2}


def test_critical_thinking_with_mismatch_reasons(repo):
    write_experiment(repo, "a-exp", [
        raw("m1", "i1", 1, "MISMATCH recoloured sticker", release_version="2.0.0"),   # diagnosis
        raw("m1", "i1", 2, "MISMATCH twisted corner", release_version="2.0.0"),       # wrong reason
        raw("m1", "v1", 1, "MISMATCH twisted corner", release_version="2.0.0"),       # false mismatch
        raw("m1", "v1", 2, solution("v1"), release_version="2.0.0"),
        raw("m2", "v1", 1, solution("v1"), release_version="2.0.0"),                  # no invalid input
    ], release="2.0.0")
    _, _, metrics = exported(repo)
    # diagnosis rate 1/2, false mismatch rate 1/2 -> (0.5 + 0.5) / 2
    assert metrics[("2x2", "m1")]["critical"] == {"value": 0.5, "n": 4}
    assert metrics[("2x2", "m2")]["critical"] == {"value": None, "n": 1}


def test_decision_model_hallucination_is_null(repo):
    legal = list(get_engine("2x2").legal_moves())
    moves = solution("v1").split("\n")
    calls = [{"answers": {"next_move": {"choice": f"move_{legal.index(m) + 1}"}}} for m in moves]
    calls.append({"answers": {"next_move": {"choice": "done"}}})
    write_experiment(repo, "a-exp", [raw("m2", "v1", 1, json.dumps(calls), decision=True),
                                     raw("m1", "v1", 1, solution("v1"))], m2="fake_decision")
    _, _, metrics = exported(repo)
    assert metrics[("2x2", "m2")]["hallucination"] == {"value": None, "n": 0}
    assert metrics[("2x2", "m1")]["hallucination"] == {"value": 0.0, "n": 1}


def test_prices_fall_back_to_config_and_experiment_prices_win(repo):
    cheap = PRICES.replace("1.0\n", "0.0\n").replace("2.0\n", "0.0\n")
    write_experiment(repo, "a-exp", [raw("m1", "v1", 1, solution("v1")), raw("m1", "i1", 1, "MISMATCH")])
    write_experiment(repo, "b-exp", [raw("m2", "v1", 1, solution("v1")), raw("m2", "i1", 1, "MISMATCH")],
                     prices=cheap)
    _, _, metrics = exported(repo)
    assert metrics[("2x2", "m1")]["cost"]["value"] == pytest.approx(0.002)
    assert metrics[("2x2", "m2")]["cost"]["value"] == 0.0  # b-exp holds its own zero prices


def test_model_without_prices_is_checked_error(repo):
    write_experiment(repo, "a-exp", [raw("m3", "v1", 1, solution("v1"))])
    with pytest.raises(site.ExportError, match="m3"):
        site.export(GitData(repo), "main")


def test_provider_unknown_without_models_entry(repo):
    write_experiment(repo, "a-exp", [raw("m3", "v1", 1, solution("v1"))], prices=PRICES.replace("m2", "m3"))
    data, _, metrics = exported(repo)
    assert metrics[("2x2", "m3")]["provider"] == "unknown"
    assert {"name": "m3", "provider": "unknown", "kind": "unknown"} in data["experiments"][0]["models"]


def test_definitions_parsing_and_missing_name():
    found, missing = site.read_definitions(DEFINITIONS)
    assert missing == ["Cost efficiency"]
    assert [d["key"] for d in found] == ["precision", "hallucination", "critical"]
    assert found[1]["definition"] == "The share of attempts with at least one impossible move."


def test_branch_only_experiment_is_exported_with_releases_from_main(repo):
    write_experiment(repo, "a-exp", [raw("m1", "v1", 1, solution("v1"))])
    write_experiment(repo, "b-branch", [raw("m1", "v2", 1, solution("v2"))], release="2.0.0", branch=True)
    assert not (repo / "results" / "b-branch").exists()
    data, _, _ = exported(repo)
    assert [(e["experimentId"], e["branch"], e["release"]) for e in data["experiments"]] == [
        ("a-exp", "main", "1.0.0"), ("b-branch", "results/b-branch", "2.0.0")]
    assert data["experiments"][1]["attempts"][0]["outcome"] == "success"


def test_branch_overrides_a_folder_of_the_same_id(repo):
    write_experiment(repo, "a-exp", [raw("m1", "v1", 1, solution("v1"))])
    write_experiment(repo, "a-exp2", [raw("m1", "v1", 1, solution("v1"))])
    subprocess.run(["git", "checkout", "-q", "-b", "tmp"], cwd=repo, check=True)
    path = repo / "results" / "a-exp" / "raw" / "m.jsonl"
    path.write_text("\n".join(json.dumps(raw("m1", "v1", n, solution("v1"))) for n in (1, 2, 3)) + "\n")
    commit(repo, "more")
    subprocess.run(["git", "update-ref", "refs/remotes/origin/results/a-exp", "HEAD"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-q", "main"], cwd=repo, check=True)
    data, _, _ = exported(repo)
    by_id = {e["experimentId"]: e for e in data["experiments"]}
    assert by_id["a-exp"]["branch"] == "results/a-exp" and by_id["a-exp"]["attemptCount"] == 3
    assert by_id["a-exp2"]["branch"] == "main" and by_id["a-exp2"]["attemptCount"] == 1


def test_remote_option_picks_the_branches_of_that_remote(repo):
    write_experiment(repo, "b-branch", [raw("m1", "v1", 1, solution("v1"))], branch=True)
    subprocess.run(["git", "update-ref", "refs/remotes/other/results/b-branch",
                    "refs/remotes/origin/results/b-branch"], cwd=repo, check=True)
    subprocess.run(["git", "update-ref", "-d", "refs/remotes/origin/results/b-branch"], cwd=repo, check=True)
    assert site.export(GitData(repo), "main")[0]["experiments"] == []
    assert len(site.export(GitData(repo), "main", "other")[0]["experiments"]) == 1


def test_experiment_below_min_release_is_skipped(repo, capsys):
    (repo / "config" / "site.toml").write_text(SITE_TOML.replace('"1.0.0"', '"2.0.0"'))
    commit(repo, "min release")
    write_experiment(repo, "a-old", [raw("m1", "v1", 1, solution("v1"))])
    write_experiment(repo, "b-new", [raw("m2", "v1", 1, solution("v1"))], release="2.0.0")
    data, _, metrics = exported(repo)
    assert [e["experimentId"] for e in data["experiments"]] == ["b-new"]
    assert list(metrics) == [("2x2", "m2"), ("all", "m2")]
    err = capsys.readouterr().err
    assert "a-old" in err and "1.0.0" in err


def test_missing_min_release_is_checked_error(repo):
    (repo / "config" / "site.toml").write_text(SITE_TOML.replace('min_release = "1.0.0"\n', ""))
    commit(repo, "no min release")
    with pytest.raises(site.ExportError, match="min_release"):
        site.export(GitData(repo), "main")


def test_all_row_pools_every_puzzle():
    def row(puzzle, validity, outcome, cost=0.01, moves=("R",), mismatch=False, corruption=None):
        return {"puzzle": puzzle, "model": "m", "validity": validity, "outcome": outcome, "mismatch": mismatch,
                "parsed_moves": list(moves), "reasons": False, "corruption": corruption, "cost": cost,
                "decision": False, "impossible_move": False}
    rows = [
        row("2x2", "valid", "success"),                                                         # tp
        row("3x3", "valid", "failure"),                                                         # fp
        row("3x3", "invalid", "success", moves=(), mismatch=True, corruption="twisted corner"),  # tn
        row("2x2", "invalid", "infrastructure_failure", cost=0.04, moves=()),
    ]
    for r in rows:
        r["answer_class"] = answer_class(r)
    got = {r["puzzle"]: r for r in metric_rows(rows, {"m": "openai"})}
    assert list(got) == ["2x2", "3x3", "all"]
    # valid precision 1 of 2, invalid 1 of 1; the failure is left out of precision but counts in cost
    assert got["all"]["precision"] == {"value": 0.75, "n": 3}
    assert got["all"]["cost"]["n"] == 4
    assert got["all"]["cost"]["value"] == pytest.approx(0.0175 / 0.75)
    assert got["all"]["provider"] == "openai"


def test_prompts_are_built_from_the_release_templates_once_per_release_setup_and_input(repo):
    records = [raw("m1", "v1", 1, solution("v1")), raw("m1", "v1", 2, solution("v1")), raw("m2", "v1", 1, solution("v1")),
               raw("m1", "v1", 1, solution("v1"), setup="prescriptive"), raw("m1", "i1", 1, "MISMATCH", setup="no_model")]
    write_experiment(repo, "a-exp", records)
    data, _, _ = exported(repo)
    assert sorted(data["prompts"]) == ["1.0.0/no_model/i1", "1.0.0/no_model/v1", "1.0.0/prescriptive/v1"]
    engine = get_engine("2x2")
    state = INPUTS[0]["state"]
    assert data["prompts"]["1.0.0/no_model/v1"] == (
        f"Solve this 2x2 cube.\n\n{engine.render(state)}\n\nReasons: "
        + ", ".join(f"`{r}`" for r in offered_reasons(engine)) + ".\n")
    assert data["prompts"]["1.0.0/prescriptive/v1"] == f"Pick from {' '.join(engine.legal_moves())}.\n\n{engine.render(state)}\n"
    assert engine.render(INPUTS[1]["state"]) in data["prompts"]["1.0.0/no_model/i1"]


def test_prompts_of_two_experiments_on_one_release_are_shared(repo):
    write_experiment(repo, "a-exp", [raw("m1", "v1", 1, solution("v1"))])
    write_experiment(repo, "b-exp", [raw("m2", "v1", 1, solution("v1"))])
    data, _, _ = exported(repo)
    assert list(data["prompts"]) == ["1.0.0/no_model/v1"]


def test_missing_template_leaves_its_prompts_out(repo, capsys):
    (repo / "releases" / "1.0.0" / "prompts" / "no_model" / "2x2.txt").unlink()
    commit(repo, "drop template")
    write_experiment(repo, "a-exp", [raw("m1", "v1", 1, solution("v1")), raw("m1", "v1", 1, solution("v1"), setup="prescriptive")])
    data, _, _ = exported(repo)
    assert list(data["prompts"]) == ["1.0.0/prescriptive/v1"]
    assert "no_model" in capsys.readouterr().err
