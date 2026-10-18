# Spec: docs/specs/README.md
"""End-to-end test. In a temporary git repo it runs the real commands by subprocess: a major
release of a tiny 2x2 input set, run with the fake provider, evaluate, then an assessment fix,
a patch release and a second evaluate. The 1.0.0 report is compared with a stored expected
file, ignoring the lines that hold dates. Set UPDATE_FIXTURES=1 to regenerate that file.
"""

import os
import subprocess
import sys
from pathlib import Path

from test_release import commit_all, edit, git, repo  # noqa: F401  (repo is a fixture)

FIXTURE = Path(__file__).parent / "fixtures" / "pipeline-1.0.0.md"
RELEASE_CONFIG = (
    'seed = 7\npuzzles = ["2x2"]\nscramble_depths = [1]\n'
    "scramble_count = 2\nvalid_invalid_split = 0.5\n"
)
EXPERIMENT = (
    'release = "1.0.0"\nattempts = 2\nretry_cap = 3\nmax_output_tokens = 100\n'
    '[[models]]\nname = "A"\nprovider = "fake"\napi_model_id = "a-1"\n'
)
PRICES = "[A]\nprice_input_per_mtok = 1.0\nprice_output_per_mtok = 2.0\n"


def python_m(repo: Path, module: str, *args: str) -> None:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    result = subprocess.run([sys.executable, "-m", module, *args], cwd=repo, env=env,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def without_dates(text: str) -> str:
    """Drop the lines that hold timestamps: the first and last attempt line, and any created_at."""
    dated = ("created_at", "First and last attempt")
    return "".join(line for line in text.splitlines(keepends=True) if not any(d in line for d in dated))


def test_whole_flow(repo):
    (repo / "config" / "release.toml").write_text(RELEASE_CONFIG, encoding="utf-8")
    (repo / "config" / "experiments").mkdir()
    (repo / "config" / "experiments" / "e1.toml").write_text(EXPERIMENT, encoding="utf-8")
    (repo / "config" / "prices.toml").write_text(PRICES, encoding="utf-8")
    commit_all(repo, "config")

    python_m(repo, "src.release.release", "--bump", "major", "--note", "First input set")
    python_m(repo, "src.run.run", "--experiment", "e1")
    python_m(repo, "src.evaluate.evaluate", "--experiment", "e1")
    report = repo / "results" / "e1" / "1.0.0.md"
    assert report.exists()
    first = report.read_text(encoding="utf-8")

    if os.environ.get("UPDATE_FIXTURES") == "1":
        FIXTURE.parent.mkdir(exist_ok=True)
        FIXTURE.write_text(without_dates(first), encoding="utf-8")
    assert without_dates(first) == FIXTURE.read_text(encoding="utf-8")

    commit_all(repo, "results")
    validator = repo / "src" / "validator.py"
    validator.write_text(validator.read_text(encoding="utf-8") + "\n# assessment fix\n", encoding="utf-8")
    commit_all(repo, "validator")
    python_m(repo, "src.release.release", "--bump", "patch", "--note", "Fix: comment")
    python_m(repo, "src.evaluate.evaluate", "--experiment", "e1", "--release", "1.0.1")

    assert report.read_text(encoding="utf-8") == first
    second = (repo / "results" / "e1" / "1.0.1.md").read_text(encoding="utf-8")
    assert "1.0.1" in second
    assert "mirror of release 1.0.0" in second
    assert git(repo, "tag", "--list") == "release-1.0.0\nrelease-1.0.1"
