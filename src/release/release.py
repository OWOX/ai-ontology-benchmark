# Spec: docs/specs/release.md
"""Freezes a new release. Reads config/release.toml (major bump only), prompts/,
the assessment files, and the latest folder in the releases folder (or the one named by --base). Writes a new
releases/<version>/ folder (read-only files), then makes a git commit and tag.
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from src.config import RELEASE_PATTERN, load_release_config
from src.generate.generate import build_inputs
from src.run.prompts import both_prompt_versions

# Globs for the assessment. src/evaluate/report.py is left out on purpose.
ASSESSMENT_PATTERNS = [
    "src/validator.py", "src/puzzles/*.py", "src/run/raw.py", "src/evaluate/evaluate.py",
    "src/evaluate/metrics.py", "src/run/decision.py", "src/run/prompts.py",
]
REPO_ROOT = Path(__file__).resolve().parents[2]
PROMPTS_DIR = Path("prompts")
RELEASE_CONFIG = Path("config/release.toml")


class ReleaseError(Exception):
    """A checked error. The message names the file or field at fault."""


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def assessment_files() -> list[Path]:
    """Return the assessment files that exist, in sorted path order."""
    found = set()
    for pattern in ASSESSMENT_PATTERNS:
        found.update(REPO_ROOT.glob(pattern))
    return sorted(found)


def assessment_sha256() -> str:
    digest = hashlib.sha256()
    for path in assessment_files():
        digest.update(path.read_bytes())
    return digest.hexdigest()


def parse_version(text: str) -> tuple[int, int, int]:
    major, minor, patch = (int(part) for part in text.split("."))
    return major, minor, patch


def version_folders(releases: Path) -> list[str]:
    """Return the names of the version folders in `releases`, empty when it does not exist."""
    if not releases.is_dir():
        return []
    return [p.name for p in releases.iterdir() if p.is_dir() and RELEASE_PATTERN.fullmatch(p.name)]


def latest_version(releases: Path) -> str | None:
    """Return the highest version folder name, compared numerically."""
    names = version_folders(releases)
    return max(names, key=parse_version) if names else None


def next_version(latest: str | None, bump: str) -> str:
    if latest is None:
        if bump != "major":
            raise ReleaseError("releases: no release yet, so the first bump must be major")
        return "1.0.0"
    major, minor, patch = parse_version(latest)
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], check=True, capture_output=True, text=True)
    return result.stdout


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def parse_inputs(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines()]


def check_bump_rules(bump: str, old: dict, new_versions: dict, old_assessment: str, new_assessment: str,
                     new_decision_versions: dict) -> None:
    """Raise ReleaseError if the changes since the latest release don't fit a minor or patch bump.
    A change in either prompt_versions or decision_prompt_versions is a prompt change for a minor
    bump, and an old release without decision_prompt_versions counts as different there. A patch
    bump against such a release compares prompt_versions only, so an assessment fix stays possible."""
    llm_same = new_versions == old["prompt_versions"]
    prompts_same = llm_same and new_decision_versions == old.get("decision_prompt_versions")
    if bump == "minor" and prompts_same:
        raise ReleaseError("prompts: a minor bump needs at least one prompt version to differ")
    if bump == "patch":
        patch_same = llm_same if "decision_prompt_versions" not in old else prompts_same
        if not patch_same:
            raise ReleaseError("prompts: a patch bump needs every prompt version to equal the latest release")
        if new_assessment == old_assessment:
            raise ReleaseError("assessment: a patch bump needs the assessment to differ from the latest release")


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def counts_table(inputs: list[dict]) -> str:
    counts = Counter((i["puzzle"], i["scramble_depth"], i["validity"]) for i in inputs)
    rows = ["| Puzzle | Depth | Validity | Inputs |", "|---|---|---|---|"]
    for (puzzle, depth, validity), n in sorted(counts.items()):
        rows.append(f"| {puzzle} | {depth} | {validity} | {n} |")
    return "\n".join(rows)


def versions_table(versions: dict) -> str:
    rows = ["| Setup | Puzzle | Prompt version |", "|---|---|---|"]
    for setup in sorted(versions):
        for puzzle in sorted(versions[setup]):
            rows.append(f"| {setup} | {puzzle} | {versions[setup][puzzle]} |")
    return "\n".join(rows)


def build_readme(version, note, created, inputs, versions, decision_versions, assessment, previous) -> str:
    link = f"[{previous}](../{previous}/README.md)" if previous else "none"
    return (
        f"# Release {version}\n\n"
        f"Note: {note}\n\nDate: {created}\n\n"
        f"## Inputs\n\n{counts_table(inputs)}\n\n"
        f"## Prompt versions\n\n{versions_table(versions)}\n\n"
        f"## Decision prompt versions\n\n{versions_table(decision_versions)}\n\n"
        f"## Assessment\n\nsha256: `{assessment}`\n\n"
        f"## Previous release\n\n{link}\n"
    )


def write_release(folder: Path, inputs_text: str, manifest: dict, readme: str) -> None:
    """Write every file, then the manifest with the hashes of all other files, then lock them."""
    folder.mkdir(parents=True)
    (folder / "inputs.jsonl").write_text(inputs_text, encoding="utf-8")
    for template in sorted(PROMPTS_DIR.glob("*/*.txt")):
        target = folder / "prompts" / template.parent.name / template.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(template, target)
    (folder / "README.md").write_text(readme, encoding="utf-8")
    others = sorted(p for p in folder.rglob("*") if p.is_file())
    manifest["files"] = {p.relative_to(folder).as_posix(): sha256_of(p.read_bytes()) for p in others}
    write_json(folder / "manifest.json", manifest)
    for path in folder.rglob("*"):
        if path.is_file():
            path.chmod(0o444)


def check_base(base: str, bump: str, releases: Path) -> None:
    """Raise ReleaseError unless base is a patch bump's target: the newest release on its MAJOR.MINOR line."""
    if bump != "patch":
        raise ReleaseError("--base: only a patch bump can name a base")
    if not RELEASE_PATTERN.fullmatch(base) or not (releases / base / "manifest.json").is_file():
        raise ReleaseError(f"{releases / base}: no such release")
    line = parse_version(base)[:2]
    newest = max((name for name in version_folders(releases) if parse_version(name)[:2] == line),
                 key=parse_version)
    if newest != base:
        raise ReleaseError(f"--base: {base} is not the newest on its line, {newest} is")


def release(bump: str, note: str, releases: Path, base: str | None = None) -> str:
    if git("status", "--porcelain").strip():
        raise ReleaseError("git: the working tree has uncommitted changes")
    if base is not None:
        check_base(base, bump, releases)
    latest = base or latest_version(releases)
    version = next_version(latest, bump)
    if (releases / version).exists():
        raise ReleaseError(f"{releases / version}: folder already exists")
    tag = subprocess.run(["git", "rev-parse", "-q", "--verify", f"refs/tags/release-{version}"],
                         capture_output=True, text=True)
    if tag.returncode == 0:
        raise ReleaseError(f"git: tag release-{version} already exists")
    old = json.loads(read_text(releases / latest / "manifest.json")) if latest else None
    if bump == "major":
        release_config = load_release_config(RELEASE_CONFIG)
        inputs_text = build_inputs(release_config, str(parse_version(version)[0]))
    else:
        release_config = old["release_config"]
        inputs_text = read_text(releases / latest / "inputs.jsonl")
    inputs = parse_inputs(inputs_text)
    versions, decision_versions = both_prompt_versions(PROMPTS_DIR, inputs)
    assessment = assessment_sha256()
    if old:
        check_bump_rules(bump, old, versions, old["assessment_sha256"], assessment, decision_versions)
    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest = {
        "release_version": version,
        "input_set_id": str(parse_version(version)[0]),
        "release_config": release_config,
        "note": note,
        "created_at": created,
        "commit": git("rev-parse", "HEAD").strip(),
        "prompt_versions": versions,
        "decision_prompt_versions": decision_versions,
        "assessment_sha256": assessment,
    }
    readme = build_readme(version, note, created, inputs, versions, decision_versions, assessment, latest)
    folder = releases / version
    write_release(folder, inputs_text, manifest, readme)
    commit_release(folder, version, note)
    return version


def commit_release(folder: Path, version: str, note: str) -> None:
    """Commit the folder and tag it. If the commit fails, remove the folder again."""
    try:
        git("add", str(folder))
        git("commit", "-m", f"Release {version}: {note}")
    except subprocess.CalledProcessError as error:
        subprocess.run(["git", "reset", "-q", "--", str(folder)], check=False)
        for path in folder.rglob("*"):
            if path.is_file():
                path.chmod(0o644)
        shutil.rmtree(folder)
        raise ReleaseError(f"git: commit of {folder} failed, folder removed: {error.stderr or error}")
    try:
        git("tag", f"release-{version}")
    except subprocess.CalledProcessError as error:
        raise ReleaseError(f"git: commit made but tag release-{version} is missing: {error.stderr or error}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Freeze a new release.")
    parser.add_argument("--bump", required=True, choices=["major", "minor", "patch"])
    parser.add_argument("--note", required=True, help="one line saying why this release exists")
    parser.add_argument("--releases", default="releases", type=Path)
    parser.add_argument("--base", help="patch bump only: the release to mirror, the newest on its MAJOR.MINOR line")
    args = parser.parse_args(argv)
    try:
        version = release(args.bump, args.note, args.releases, args.base)
    except (ReleaseError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as error:
        print(f"error: git failed: {error.stderr or error}", file=sys.stderr)
        return 1
    print(f"Released {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
