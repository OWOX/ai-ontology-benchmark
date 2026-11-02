# Spec: docs/specs/release.md
"""Tests for release. Each test builds a temporary git repo holding copies of src/,
prompts/ and config/, then runs `python -m src.release.release` inside it. A
subprocess is used so that edits to render() in the copy are really imported.
"""

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TINY_CONFIG = (
    'seed = 7\npuzzles = ["2x2"]\nscramble_depths = [3]\n'
    "scramble_count = 2\nvalid_invalid_split = 0.5\n"
)


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def commit_all(repo: Path, message: str = "change") -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-m", message)


def run_release(repo: Path, bump: str, note: str = "a note") -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run(
        [sys.executable, "-m", "src.release.release", "--bump", bump, "--note", note],
        cwd=repo, env=env, capture_output=True, text=True,
    )


def edit(repo: Path, relative: str, old: str, new: str) -> None:
    path = repo / relative
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.name", "Test")
    git(tmp_path, "config", "user.email", "test@example.com")
    ignore = shutil.ignore_patterns("__pycache__")
    shutil.copytree(ROOT / "src", tmp_path / "src", ignore=ignore)
    shutil.copytree(ROOT / "prompts", tmp_path / "prompts")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "release.toml").write_text(TINY_CONFIG, encoding="utf-8")
    (tmp_path / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    commit_all(tmp_path, "initial")
    return tmp_path


def release_ok(repo: Path, bump: str) -> None:
    result = run_release(repo, bump)
    assert result.returncode == 0, result.stderr


def edit_template(repo: Path) -> None:
    edit(repo, "prompts/no_model/2x2.txt", "Solve this", "Please solve this")
    commit_all(repo, "template")


def edit_validator(repo: Path) -> None:
    path = repo / "src" / "validator.py"
    path.write_text(path.read_text(encoding="utf-8") + "\n# fix\n", encoding="utf-8")
    commit_all(repo, "validator")


def manifest_of(repo: Path, version: str) -> dict:
    return json.loads((repo / "releases" / version / "manifest.json").read_text(encoding="utf-8"))


def test_first_major_release(repo):
    release_ok(repo, "major")
    folder = repo / "releases" / "1.0.0"
    manifest = manifest_of(repo, "1.0.0")
    assert manifest["release_version"] == "1.0.0"
    assert manifest["input_set_id"] == "1"
    assert manifest["note"] == "a note"
    assert manifest["release_config"]["seed"] == 7
    assert len(manifest["assessment_sha256"]) == 64
    assert set(manifest["prompt_versions"]) == {"no_model", "descriptive", "prescriptive"}
    on_disk = {p.relative_to(folder).as_posix() for p in folder.rglob("*")
               if p.is_file() and p.name != "manifest.json"}
    assert set(manifest["files"]) == on_disk
    assert {"inputs.jsonl", "README.md", "prompts/no_model/2x2.txt"} <= on_disk
    for name, digest in manifest["files"].items():
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest
    # tag points at a commit holding only the new folder
    assert git(repo, "rev-parse", "release-1.0.0") == git(repo, "rev-parse", "HEAD")
    assert manifest["commit"] == git(repo, "rev-parse", "HEAD~1")
    changed = git(repo, "show", "--name-only", "--format=", "release-1.0.0").splitlines()
    assert changed and all(line.startswith("releases/1.0.0/") for line in changed)
    assert git(repo, "log", "-1", "--format=%s") == "Release 1.0.0: a note"
    readme = (folder / "README.md").read_text(encoding="utf-8")
    assert "1.0.0" in readme and "a note" in readme and "none" in readme
    assert manifest["assessment_sha256"] in readme


def test_minor_after_template_edit(repo):
    release_ok(repo, "major")
    edit_template(repo)
    release_ok(repo, "minor")
    assert (repo / "releases/1.1.0/inputs.jsonl").read_bytes() == (
        repo / "releases/1.0.0/inputs.jsonl").read_bytes()
    assert manifest_of(repo, "1.1.0")["prompt_versions"] != manifest_of(repo, "1.0.0")["prompt_versions"]
    readme = (repo / "releases/1.1.0/README.md").read_text(encoding="utf-8")
    assert "(../1.0.0/README.md)" in readme


def test_manifest_and_readme_hold_decision_prompt_versions(repo):
    release_ok(repo, "major")
    manifest = manifest_of(repo, "1.0.0")
    assert set(manifest["decision_prompt_versions"]) == {"no_model", "descriptive", "prescriptive"}
    assert manifest["decision_prompt_versions"] != manifest["prompt_versions"]
    assert "prompts/decision/questions.txt" in manifest["files"]
    readme = (repo / "releases/1.0.0/README.md").read_text(encoding="utf-8")
    assert "## Decision prompt versions" in readme


def test_minor_after_questions_edit_only(repo):
    release_ok(repo, "major")
    edit(repo, "prompts/decision/questions.txt", "Pick done", "Choose done")
    commit_all(repo, "questions")
    release_ok(repo, "minor")
    old, new = manifest_of(repo, "1.0.0"), manifest_of(repo, "1.1.0")
    assert new["prompt_versions"] == old["prompt_versions"]
    assert new["decision_prompt_versions"] != old["decision_prompt_versions"]


def test_patch_after_questions_edit_fails(repo):
    release_ok(repo, "major")
    edit(repo, "prompts/decision/questions.txt", "Pick done", "Choose done")
    edit_validator(repo)
    result = run_release(repo, "patch")
    assert result.returncode == 1
    assert "prompt" in result.stderr
    assert not (repo / "releases/1.0.1").exists()


def strip_decision_field(repo, version):
    path = repo / "releases" / version / "manifest.json"
    path.chmod(0o644)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    del manifest["decision_prompt_versions"]
    path.write_text(json.dumps(manifest), encoding="utf-8")
    commit_all(repo, "old manifest")


def test_patch_against_old_manifest_without_decision_versions(repo):
    release_ok(repo, "major")
    strip_decision_field(repo, "1.0.0")
    edit_validator(repo)
    release_ok(repo, "patch")
    new = manifest_of(repo, "1.0.1")
    assert new["prompt_versions"] == manifest_of(repo, "1.0.0")["prompt_versions"]
    assert "decision_prompt_versions" in new


def test_minor_against_old_manifest_without_decision_versions(repo):
    release_ok(repo, "major")
    strip_decision_field(repo, "1.0.0")
    release_ok(repo, "minor")


def test_minor_without_change_fails(repo):
    release_ok(repo, "major")
    result = run_release(repo, "minor")
    assert result.returncode == 1
    assert "prompts" in result.stderr
    assert not (repo / "releases/1.1.0").exists()


def test_patch_after_validator_edit(repo):
    release_ok(repo, "major")
    edit_template(repo)
    release_ok(repo, "minor")
    edit_validator(repo)
    release_ok(repo, "patch")
    old, new = manifest_of(repo, "1.1.0"), manifest_of(repo, "1.1.1")
    assert (repo / "releases/1.1.1/inputs.jsonl").read_bytes() == (
        repo / "releases/1.1.0/inputs.jsonl").read_bytes()
    assert new["prompt_versions"] == old["prompt_versions"]
    assert new["assessment_sha256"] != old["assessment_sha256"]


def test_patch_after_render_change_fails(repo):
    release_ok(repo, "major")
    edit(repo, "src/puzzles/cube.py", '"\\n\\n".join(blocks)', '"\\n\\n\\n".join(blocks)')
    commit_all(repo, "render")
    result = run_release(repo, "patch")
    assert result.returncode == 1
    assert "prompt" in result.stderr
    assert not (repo / "releases/1.0.1").exists()


def test_patch_after_report_only_change_fails(repo):
    release_ok(repo, "major")
    report = repo / "src" / "evaluate" / "report.py"
    report.write_text("# report formatting\n", encoding="utf-8")
    commit_all(repo, "report")
    result = run_release(repo, "patch")
    assert result.returncode == 1
    assert "assessment" in result.stderr


@pytest.mark.parametrize("bump", ["major", "minor", "patch"])
def test_uncommitted_changes_fail(repo, bump):
    release_ok(repo, "major")
    (repo / "prompts/no_model/2x2.txt").write_text("changed\n", encoding="utf-8")
    result = run_release(repo, bump)
    assert result.returncode == 1
    assert "uncommitted" in result.stderr


def test_uncommitted_changes_fail_before_first_release(repo):
    (repo / "stray.txt").write_text("x", encoding="utf-8")
    assert run_release(repo, "major").returncode == 1
    assert not (repo / "releases").exists()


def test_first_release_must_be_major(repo):
    assert run_release(repo, "minor").returncode == 1
    assert run_release(repo, "patch").returncode == 1


def test_major_after_major(repo):
    release_ok(repo, "major")
    release_ok(repo, "major")
    assert manifest_of(repo, "2.0.0")["input_set_id"] == "2"


def test_latest_release_is_compared_numerically(repo):
    release_ok(repo, "major")
    for _ in range(10):
        edit_validator(repo)
        release_ok(repo, "patch")
    # 1.0.10 is higher than 1.0.9, so the next patch is 1.0.11
    edit_validator(repo)
    release_ok(repo, "patch")
    assert (repo / "releases/1.0.11").is_dir()


def test_release_files_are_read_only(repo):
    release_ok(repo, "major")
    folder = repo / "releases" / "1.0.0"
    files = [p for p in folder.rglob("*") if p.is_file()]
    assert files
    for path in files:
        assert not path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
        with pytest.raises(PermissionError):
            open(path, "w")


def test_existing_tag_blocks_release(repo):
    git(repo, "tag", "release-1.0.0")
    result = run_release(repo, "major")
    assert result.returncode == 1
    assert "release-1.0.0" in result.stderr
    assert not (repo / "releases").exists()


def test_failing_commit_leaves_nothing_behind(repo):
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    result = run_release(repo, "major")
    assert result.returncode == 1
    assert not (repo / "releases" / "1.0.0").exists()
    assert git(repo, "status", "--porcelain") == ""
    hook.unlink()
    release_ok(repo, "major")
