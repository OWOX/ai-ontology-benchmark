# Spec: docs/specs/paper-verify-ste100.md
"""Tests for paper/verify_ste100.py. They write small HTML files in a temporary folder only."""

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "paper" / "verify_ste100.py"

GOOD = """<html><body>
<h2>Introduction</h2>
<p>The cube has six faces. Each face has nine stickers. A move turns one face.</p>
<p>The validator reads the reply. It checks every move. It gives one outcome.</p>
<ol class="procedure"><li><p>Run the tests.</p></li></ol>
</body></html>
"""


def run(tmp_path: Path, html: str) -> subprocess.CompletedProcess:
    path = tmp_path / "check.html"
    path.write_text(html, encoding="utf-8")
    return subprocess.run([sys.executable, str(SCRIPT), str(path)], capture_output=True, text=True)


def test_clean_file_passes(tmp_path):
    result = run(tmp_path, GOOD)
    assert result.returncode == 0, result.stdout


def test_numbered_heading_fails(tmp_path):
    result = run(tmp_path, GOOD.replace("<h2>Introduction</h2>", "<h2>1 Introduction</h2>"))
    assert result.returncode == 1
    assert "HEADING NUMBER" in result.stdout


def test_long_sentence_fails(tmp_path):
    long = " ".join(["word"] * 30) + "."
    result = run(tmp_path, GOOD.replace("A move turns one face.", long))
    assert result.returncode == 1


def test_missing_file_fails(tmp_path):
    result = subprocess.run([sys.executable, str(SCRIPT), str(tmp_path / "none.html")], capture_output=True, text=True)
    assert result.returncode == 1
