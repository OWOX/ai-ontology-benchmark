# Spec: docs/specs/setup.md
"""Checks the setup spec: .env.example variables and no API keys in tracked files."""
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
KEY_PATTERN = re.compile(r"sk-[A-Za-z0-9]{10,}|AIza[0-9A-Za-z_-]{10,}")
EXPECTED_VARIABLES = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY"]


def test_env_example_lists_three_empty_variables() -> None:
    lines = (REPO_ROOT / ".env.example").read_text().splitlines()
    values = dict(line.split("=", 1) for line in lines if line.strip())
    assert sorted(values) == sorted(EXPECTED_VARIABLES)
    assert all(value == "" for value in values.values())


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
