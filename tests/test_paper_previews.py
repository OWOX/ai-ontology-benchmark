# Spec: docs/specs/paper-previews.md
"""Tests for paper/make_previews.py. They need poppler and Pillow, and skip without them. They
copy the committed main.pdf to a temporary folder, so nothing in paper/ is written.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PAPER = Path(__file__).resolve().parent.parent / "paper"


def test_renders_every_page_and_a_contact_sheet(tmp_path):
    pytest.importorskip("PIL")
    if shutil.which("pdftoppm") is None or shutil.which("pdfinfo") is None:
        pytest.skip("needs poppler")
    for name in ("make_previews.py", "main.pdf"):
        shutil.copy(PAPER / name, tmp_path / name)
    result = subprocess.run([sys.executable, str(tmp_path / "make_previews.py"), "8"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    info = subprocess.run(["pdfinfo", str(tmp_path / "main.pdf")], capture_output=True, text=True).stdout
    pages = int(next(line.split()[1] for line in info.splitlines() if line.startswith("Pages:")))
    assert len(list((tmp_path / "previews").glob("page-*.png"))) == pages
    assert (tmp_path / "preview.png").is_file()
