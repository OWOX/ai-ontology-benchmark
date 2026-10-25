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
