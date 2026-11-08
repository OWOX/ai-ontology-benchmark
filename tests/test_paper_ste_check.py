# Spec: docs/specs/paper-ste-check.md
"""Tests for paper/ste_check.py. They copy main.tex and the two scripts to a temporary folder,
so nothing in paper/ is written.
"""

import shutil
import subprocess
import sys
from pathlib import Path

PAPER = Path(__file__).resolve().parent.parent / "paper"


def copy_paper(tmp_path: Path) -> Path:
    for name in ("main.tex", "ste_check.py", "verify_ste100.py"):
        shutil.copy(PAPER / name, tmp_path / name)
    return tmp_path


def run(folder: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(folder / "ste_check.py")], capture_output=True, text=True, cwd=folder)


def test_committed_template_passes(tmp_path):
    result = run(copy_paper(tmp_path))
    assert result.returncode == 0, result.stdout[-2000:]
    assert (tmp_path / "build" / "main.check.html").is_file()


def test_forbidden_term_fails(tmp_path):
    folder = copy_paper(tmp_path)
    tex = folder / "main.tex"
    tex.write_text(tex.read_text(encoding="utf-8") + "\nVeritasium\n", encoding="utf-8")
    result = run(folder)
    assert result.returncode == 1
    assert "FORBIDDEN TERM" in result.stdout


def test_hardcoded_reference_fails(tmp_path):
    folder = copy_paper(tmp_path)
    tex = folder / "main.tex"
    text = tex.read_text(encoding="utf-8").replace("\\end{document}", "See Figure 3 for details.\n\\end{document}")
    tex.write_text(text, encoding="utf-8")
    result = run(folder)
    assert result.returncode == 1
    assert "HARDCODED REFERENCE" in result.stdout
