# Spec: docs/specs/setup.md
"""Checks the setup spec: no API keys in tracked files."""
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
KEY_PATTERN = re.compile(r"sk-[A-Za-z0-9]{10,}|AIza[0-9A-Za-z_-]{10,}")


def test_no_api_key_in_tracked_files() -> None:
    listing = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    )
    offenders = []
    for name in listing.stdout.splitlines():
        path = REPO_ROOT / name
        if not path.is_file():
            continue
        text = path.read_text(errors="ignore")
        if KEY_PATTERN.search(text):
            offenders.append(name)
    assert offenders == []
