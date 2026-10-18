# Spec: docs/specs/README.md
"""End-to-end test. In a temporary git repo it runs the real commands by subprocess: a major
release of a tiny 2x2 input set, run with the fake provider, evaluate, then an assessment fix,
a patch release and a second evaluate. The 1.0.0 report is compared with a stored expected
file, ignoring the lines that hold dates. Set UPDATE_FIXTURES=1 to regenerate that file.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

from test_release import commit_all, git, repo  # noqa: F401  (repo is a fixture)

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


def normalize(text: str) -> str:
    """Drop lines that hold dates and replace every 64-hex hash with a placeholder."""
    dated = ("created_at", "First and last attempt")
    kept = []
    for line in text.splitlines(keepends=True):
        if any(marker in line for marker in dated):
            continue
        kept.append(re.sub(r"[0-9a-f]{64}", "<hash>", line))
    return "".join(kept)


def assessment_hash(text: str) -> str:
    match = re.search(r"Assessment hash: `([0-9a-f]{64})`", text)
    assert match, "no assessment hash line"
    return match.group(1)


def raw_bytes(folder: Path) -> dict:
    return {path.name: path.read_bytes() for path in sorted(folder.glob("*.jsonl"))}


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
        FIXTURE.write_text(normalize(first), encoding="utf-8")
    assert normalize(first) == FIXTURE.read_text(encoding="utf-8")

    commit_all(repo, "results")
    raw_before = raw_bytes(repo / "results" / "e1" / "raw")
    assert raw_before
    validator = repo / "src" / "validator.py"
    validator.write_text(validator.read_text(encoding="utf-8") + "\n# assessment fix\n", encoding="utf-8")
    commit_all(repo, "validator")
    python_m(repo, "src.release.release", "--bump", "patch", "--note", "Fix: comment")
    python_m(repo, "src.evaluate.evaluate", "--experiment", "e1", "--release", "1.0.1")

    assert report.read_text(encoding="utf-8") == first
    second = (repo / "results" / "e1" / "1.0.1.md").read_text(encoding="utf-8")
    assert second.startswith("# Experiment e1 on release 1.0.1")
    assert assessment_hash(second) != assessment_hash(first)
    assert raw_bytes(repo / "results" / "e1" / "raw") == raw_before
    assert "mirror of release 1.0.0" in second
    assert git(repo, "tag", "--list") == "release-1.0.0\nrelease-1.0.1"
