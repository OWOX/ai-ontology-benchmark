# Spec: docs/specs/paper-ids.md
"""Tests for paper/ids.py. They need main.aux from a local build and poppler, and skip without
them. They copy the inputs to a temporary folder, so nothing in paper/ is written.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PAPER = Path(__file__).resolve().parent.parent / "paper"

pytestmark = pytest.mark.skipif(
    not (PAPER / "main.aux").is_file() or shutil.which("pdftotext") is None,
    reason="needs paper/main.aux from ./build.sh and poppler",
)


def copy_paper(tmp_path: Path) -> Path:
    for name in ("ids.py", "README.md", "main.aux", "main.pdf"):
        shutil.copy(PAPER / name, tmp_path / name)
    return tmp_path


def run(folder: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(folder / "ids.py")], capture_output=True, text=True, cwd=folder)


def test_stamps_match_printed_numbers(tmp_path):
    result = run(copy_paper(tmp_path))
    assert result.returncode == 0, result.stdout
    assert "ID mismatches                : 0" in result.stdout
    assert result.stdout.strip().splitlines()[-1].startswith("FIGURE_HEAVY_PAGE ")
    assert len((tmp_path / "build" / "id-map.tsv").read_text().splitlines()) == 20


def test_missing_readme_markers_fail(tmp_path):
    folder = copy_paper(tmp_path)
    (folder / "README.md").write_text("# no markers\n", encoding="utf-8")
    result = run(folder)
    assert result.returncode == 1
    assert "IDMAP markers not found" in result.stdout
