# Spec: docs/specs/ui.md (How to test)
"""Checks the page scripts with node: a syntax check of every ui/static/**/*.js and the markdown renderer's tests."""
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from test_release import repo  # noqa: F401  (a fixture of exp)
from test_run import exp  # noqa: F401  (a fixture)

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")


def test_every_script_passes_node_check():
    scripts = sorted((ROOT / "ui" / "static").rglob("*.js"))
    assert scripts
    for script in scripts:
        run = subprocess.run([NODE, "--check", str(script)], capture_output=True, text=True)
        assert run.returncode == 0, f"{script.name}: {run.stderr}"


def test_markdown_renderer():
    run = subprocess.run([NODE, "tests/js/markdown.test.mjs"], cwd=ROOT, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr + run.stdout


def test_summary_intervals_pooled_from_a_report_are_marked():
    run = subprocess.run([NODE, "tests/js/expmetrics.test.mjs"], cwd=ROOT, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr + run.stdout


def test_named_net_follows_the_net_order():
    run = subprocess.run([NODE, "tests/js/cube.test.mjs"], cwd=ROOT, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr + run.stdout


def test_terminal_pattern_reads_runs_progress_line():
    """The terminal turns a run progress line into an attempt block with a regex of its own: keep the two in step."""
    import json
    import re

    from src.run.progress import Progress
    price = {"price_input_per_mtok": 1.0, "price_output_per_mtok": 2.0}
    record = {"model": "m-1", "puzzle": "3x3", "input_id": "3x3-d5-002-x", "setup": "no_model", "attempt_number": 2,
              "outcome": "hallucination", "input_tokens": 5, "output_tokens": 6, "retry_input_tokens": 0,
              "retry_output_tokens": 0, "validity": "invalid", "mismatch": True}
    progress = Progress({"models": [{"name": "m-1"}]}, {"m-1": price}, {("m-1", "3x3"): 4}, [])
    progress.count(record)
    line = progress.plain_line(record)
    source = (ROOT / "ui" / "static" / "terminal.js").read_text(encoding="utf-8")
    pattern = re.search(r"const RUN_LINE = /(.*)/;", source).group(1)
    script = f"const m = new RegExp({json.dumps(pattern)}).exec({json.dumps(line)}); console.log(JSON.stringify(m && m.slice(1)));"
    run = subprocess.run([NODE, "-e", script], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout) == ["m-1", "3x3", "3x3-d5-002-x", "no_model", "2", "hallucination"]


def test_in_flight_attempts_are_the_first_n_without_a_record():
    run = subprocess.run([NODE, "tests/js/progress.test.mjs"], cwd=ROOT, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr + run.stdout


def test_benchmarks_colouring_gate_and_stale_models_fallback():
    run = subprocess.run([NODE, "tests/js/benchmarks.test.mjs"], cwd=ROOT, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr + run.stdout


def test_usd_reproduces_each_pages_former_output():
    env = {**os.environ, "LC_ALL": "de_DE.UTF-8"}  # the Models page formats in the browser's locale
    probe = subprocess.run([NODE, "-p", "new Intl.NumberFormat().resolvedOptions().locale"], capture_output=True, text=True, env=env)
    if probe.stdout.strip() != "de-DE":
        pytest.skip(f"node does not honour LC_ALL=de_DE.UTF-8 here (small-icu, Windows, or no Intl): it resolved {probe.stdout.strip() or probe.stderr.strip()!r}")
    run = subprocess.run([NODE, "tests/js/usd.test.mjs"], cwd=ROOT, capture_output=True, text=True, env=env)
    assert run.returncode == 0, run.stderr + run.stdout


def test_dropdown_and_check_picker_behaviour():
    run = subprocess.run([NODE, "tests/js/pickers.test.mjs"], cwd=ROOT, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr + run.stdout


def test_estimate_patterns_read_runs_estimate_lines(exp, capsys):
    """New Experiment reads `run --estimate` into a table with regexes of its own: keep the two in step."""
    import json
    import re

    from test_run import go
    assert go("--estimate") == 0
    lines = capsys.readouterr().out.splitlines()
    source = (ROOT / "ui" / "static" / "pages" / "new.js").read_text(encoding="utf-8")
    patterns = {name: re.search(rf"const {name} = /(.*)/;", source).group(1) for name in ("ESTIMATE_MODEL", "ESTIMATE_TOTAL")}
    script = (f"const p = {json.dumps(patterns)}, lines = {json.dumps(lines)};"
              "console.log(JSON.stringify(lines.map((l) => [new RegExp(p.ESTIMATE_MODEL).test(l), new RegExp(p.ESTIMATE_TOTAL).test(l)])));")
    run = subprocess.run([NODE, "-e", script], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    matched = json.loads(run.stdout)
    assert len(lines) >= 2 and all(m == [True, False] for m in matched[:-1]) and matched[-1] == [False, True], lines


def test_new_experiment_fills_the_reasoning_effort_a_stale_cached_bundle_lacks():
    import json
    import re
    source = (ROOT / "ui" / "static" / "pages" / "new.js").read_text(encoding="utf-8")
    body = re.search(r"  function fillEffort\(vals, defaults\) \{.*?\n  \}\n", source, re.S).group(0)
    script = (body + "const out = [];"
              "for (const [vals, d] of [[{}, {}], [{}, {reasoning_effort: 'high'}], [{reasoning_effort: ''}, {reasoning_effort: 'medium'}],"
              " [{reasoning_effort: 'low'}, {reasoning_effort: 'medium'}]]) { fillEffort(vals, d); out.push(vals.reasoning_effort); }"
              "console.log(JSON.stringify(out));")
    run = subprocess.run([NODE, "-e", script], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout) == ["medium", "high", "", "low"]


def test_new_experiment_key_warning_follows_the_providers_key_info():
    import json
    import re
    source = (ROOT / "ui" / "static" / "pages" / "new.js").read_text(encoding="utf-8")
    body = re.search(r"  function keyProblem\(p\) \{.*?\n  \}\n", source, re.S).group(0)
    providers = [{}, {"key": None}, {"key": {"configured": True, "source": "env"}}, {"key": {"configured": False, "source": "missing"}},
                 {"key": {"configured": False, "source": "file", "account": {"source": "missing"}}}]
    run = subprocess.run([NODE, "-e", body + f"console.log(JSON.stringify({json.dumps(providers)}.map(keyProblem)));"],
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout) == [None, None, None, "no API key: add it under Models", "no account id: add it under Models"]


def test_experiments_default_columns_follow_the_spec():
    source = (ROOT / "ui" / "static" / "pages" / "experiments.js").read_text()
    columns = re.findall(r'\["(\w+)", "[^"]+"\]', source[source.index("const COLUMNS"):source.index("// Hidden when")])
    hidden = re.search(r"DEFAULT_HIDDEN = \[(.*?)\]", source, re.S).group(1)
    hidden = re.findall(r'"(\w+)"', hidden)
    assert [c for c in columns if c not in hidden] == [
        "id", "started_at", "model", "puzzle", "attempts", "success_rate", "hallucination_rate",
        "mismatch_detection_rate", "cost_usd"]
