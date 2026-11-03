# Spec: docs/specs/ui.md (How to test)
"""Checks the page scripts with node: a syntax check of every ui/static/**/*.js and the markdown renderer's tests."""
import shutil
import subprocess
from pathlib import Path

import pytest

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
