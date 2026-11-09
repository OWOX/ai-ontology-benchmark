# Spec: docs/specs/site.md
"""Reads config/site.toml, docs/definitions.md, and the releases at one git ref, and every experiment with raw
records: a results/<id>/ folder at that ref or a <remote>/results/<id> branch (the branch wins). Scores every raw record again with the current assessment and writes one JSON file for the static results page.
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

from src.config import check_prices_table
from src.evaluate.metrics import EvalError, make_attempt_rows
from src.puzzles.registry import get_engine
from src.release.release import parse_version
from src.run.models import DECISION_PROVIDERS
from src.run.prompts import SETUPS, build_prompt, prompt_versions
from src.run.raw import parse_raw_text
from src.site.metrics import metric_rows
from ui.gitdata import FETCH_TIMEOUT_S, GitData

METRIC_NAMES = {
    "Balanced precision": "precision",
    "Hallucination rate": "hallucination",
    "Critical thinking": "critical",
}


class ExportError(Exception):
    pass


def read_inputs(gd: GitData, ref: str, release: str, cache: dict) -> list[dict]:
    if release not in cache:
        path = f"releases/{release}/inputs.jsonl"
        text = gd.show(ref, path)
        if text is None:
            raise ExportError(f"{ref}:{path}: not found")
        cache[release] = parse_raw_text(text)[0]
    return cache[release]


def read_prices(gd: GitData, ref: str, source: str, experiment_id: str) -> dict:
    """The experiment's own prices.toml at `source`, else config/prices.toml at `ref`."""
    for where, path in ((source, f"results/{experiment_id}/prices.toml"), (ref, "config/prices.toml")):
        text = gd.show(where, path)
        if text is not None:
            try:
                return check_prices_table(tomllib.loads(text), f"{where}:{path}")
            except (ValueError, tomllib.TOMLDecodeError) as error:
                raise ExportError(str(error)) from None
    raise ExportError(f"{ref}: no prices.toml for experiment {experiment_id} and no config/prices.toml")


def discover(gd: GitData, ref: str, remote: str) -> list[tuple[str, str, str]]:
    """`(id, source ref, branch)` for every experiment with at least one raw file: the `results/<id>/` folders at
    the ref (branch `main`) and the `<remote>/results/<id>` branches (branch `results/<id>`), a branch winning over
    a folder of the same id. Any other folder or branch is named on stderr."""
    prefix = f"refs/remotes/{remote}/results/"
    sources = {i: (ref, "main") for i in gd.ls(ref, "results")}
    sources.update({i: (prefix + i, f"results/{i}") for i in gd._ids(prefix)})
    found = []
    for experiment_id in sorted(sources):
        source, branch = sources[experiment_id]
        if any(n.endswith(".jsonl") for n in gd.ls(source, f"results/{experiment_id}/raw")):
            found.append((experiment_id, source, branch))
        else:
            print(f"skipped results/{experiment_id}: no raw records", file=sys.stderr)
    return found


def read_experiment(gd: GitData, ref: str, source: str, branch: str, experiment_id: str, cache: dict,
                    min_release: tuple[int, int, int]) -> tuple[dict, list[dict], int]:
    """Return (experiment, re-validated attempt rows, skipped count) for one experiment. Its own files are read at
    `source`, the releases and the fallback prices at `ref`."""
    folder = f"results/{experiment_id}"
    toml_text = gd.show(source, f"{folder}/experiment.toml")
    if toml_text is None:
        raise ExportError(f"no {folder}/experiment.toml at {source}")
    toml = tomllib.loads(toml_text)
    release = toml.get("release")
    if not isinstance(release, str):
        raise ExportError(f"{source}:{folder}/experiment.toml: field release is missing")
    try:
        too_old = parse_version(release) < min_release
    except ValueError:
        raise ExportError(f"{source}:{folder}/experiment.toml: release {release!r} is not a version") from None
    if too_old:
        print(f"skipped {folder}: release {release} is below min_release", file=sys.stderr)
        return {}, [], 0
    inputs = read_inputs(gd, ref, release, cache)
    by_id = {r["input_id"]: r for r in inputs}
    manifest = gd.show(ref, f"releases/{release}/manifest.json")
    if manifest is None:
        raise ExportError(f"{ref}:releases/{release}/manifest.json: not found")
    reasons = bool(json.loads(manifest).get("mismatch_reasons", False))
    models = {m["name"]: {"name": m["name"], "provider": m.get("provider", "unknown"),
                          "kind": m.get("kind", "unknown")} for m in toml.get("models", [])}
    decision_models = {n for n, m in models.items() if m["provider"] in DECISION_PROVIDERS}
    records, skipped = [], 0
    for name in sorted(n for n in gd.ls(source, f"{folder}/raw") if n.endswith(".jsonl")):
        found, torn = parse_raw_text(gd.show(source, f"{folder}/raw/{name}") or "")
        skipped += torn
        for r in found:
            if r.get("input_id") in by_id:
                records.append(r)
            else:
                skipped += 1
    try:
        rows = make_attempt_rows(records, inputs, read_prices(gd, ref, source, experiment_id), decision_models, reasons)
    except (KeyError, EvalError) as error:
        raise ExportError(f"{source}:{folder}: {error}") from None
    kept = [(r["created_at"], {
        "model": r["model"], "puzzle": r["puzzle"], "inputId": r["input_id"], "validity": r["validity"],
        "setup": r["setup"], "attempt": r["attempt_number"], "depth": r["scramble_depth"],
        "state": by_id[r["input_id"]]["state"], "corruption": r["corruption"], "moves": r["parsed_moves"],
        "outcome": r["outcome"], "mismatch": r["mismatch"]}) for r in rows if r["outcome"] != "infrastructure_failure"]
    if not kept:
        print(f"skipped {folder}: no usable raw records", file=sys.stderr)
        return {}, rows, skipped
    kept.sort(key=lambda k: (k[1]["model"], k[1]["puzzle"], k[1]["inputId"], k[1]["setup"], k[1]["attempt"], k[0]))
    for _, a in kept:
        models.setdefault(a["model"], {"name": a["model"], "provider": "unknown", "kind": "unknown"})
    times = sorted(k[0] for k in kept)
    per_input = toml.get("attempts")
    return {
        "experimentId": experiment_id,
        "release": release,
        "branch": branch,
        "puzzles": sorted({a["puzzle"] for _, a in kept}),
        "models": sorted(models.values(), key=lambda m: m["name"]),
        "setups": sorted({a["setup"] for _, a in kept}),
        "attemptsPerInput": per_input if type(per_input) is int else None,
        "attemptCount": len(kept), "firstAt": times[0], "lastAt": times[-1],
        "attempts": [a for _, a in kept],
    }, rows, skipped


def prompt_key(release: str, setup: str, input_id: str) -> str:
    return f"{release}/{setup}/{input_id}"


def build_prompts(gd: GitData, ref: str, experiments: list[dict], cache: dict) -> dict[str, str]:
    """The exact prompt of every (release, setup, input id) the attempts cover, once each. The templates are read
    from `releases/<release>/prompts/` at `ref` through git into a temporary directory, and `build_prompt` fills
    them. The versions they render must equal the manifest's `prompt_versions`; otherwise the release gets no
    prompts, with one stderr line naming it, so the page never shows a prompt the AI model didn't receive."""
    wanted: dict[str, dict[str, set[tuple[str, str]]]] = {}
    for e in experiments:
        pairs = wanted.setdefault(e["release"], {})
        for a in e["attempts"]:
            pairs.setdefault(a["setup"], set()).add((a["puzzle"], a["inputId"]))
    prompts: dict[str, str] = {}
    for release in sorted(wanted):
        inputs = cache[release]
        by_id = {r["input_id"]: r for r in inputs}
        with tempfile.TemporaryDirectory() as tmp:
            for setup in SETUPS:
                for name in gd.ls(ref, f"releases/{release}/prompts/{setup}"):
                    text = gd.show(ref, f"releases/{release}/prompts/{setup}/{name}")
                    if text is not None:
                        target = Path(tmp) / setup / name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_text(text, encoding="utf-8")
            manifest = json.loads(gd.show(ref, f"releases/{release}/manifest.json") or "{}")
            try:
                matches = prompt_versions(Path(tmp), inputs) == manifest.get("prompt_versions")
                reason = "its templates render other prompt versions than its manifest lists"
            except (ValueError, OSError) as error:
                matches, reason = False, str(error)
            if not matches:
                print(f"skipped prompts of {release}: {reason}", file=sys.stderr)
                continue
            for setup in sorted(wanted[release]):
                for puzzle, input_id in sorted(wanted[release][setup]):
                    prompts[prompt_key(release, setup, input_id)] = build_prompt(Path(tmp), by_id[input_id], setup)
    return prompts


def plain_text(md: str) -> str:
    md = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", md)
    md = re.sub(r"\*\*([^*]+)\*\*", r"\1", md)
    md = re.sub(r"(^|[^\w*])\*([^*\s][^*]*?)\*(?![\w*])", r"\1\2", md, flags=re.ASCII)
    md = re.sub(r"(^|[^\w_])_([^_\s][^_]*?)_(?![\w_])", r"\1\2", md, flags=re.ASCII)
    md = re.sub(r"`([^`]+)`", r"\1", md)
    return re.sub(r"\s+", " ", md).strip()


def read_definitions(markdown: str) -> tuple[list[dict], list[str]]:
    lines = markdown.splitlines()
    start = next((i for i, l in enumerate(lines) if re.fullmatch(r"## Metrics\s*", l)), None)
    items: list[dict] = []
    if start is not None:
        is_open = False
        for line in lines[start + 1:]:
            if line.startswith("## "):
                break
            m = re.match(r"^\s*\d+\.\s+\*\*([^*]+?)\.?\*\*\s*(.*)$", line)
            if m:
                items.append({"name": m.group(1).strip(), "text": m.group(2)})
                is_open = True
            elif re.match(r"^\s*\d+\.\s", line) or not line.strip():
                is_open = False
            elif is_open:
                items[-1]["text"] += " " + line.strip()
    found: dict[str, dict] = {}
    for it in items:
        key = METRIC_NAMES.get(it["name"])
        definition = re.sub(r"^[.:]\s*", "", plain_text(it["text"]))
        if key and definition and key not in found:
            found[key] = {"key": key, "name": it["name"], "definition": definition}
    missing = [n for n, k in METRIC_NAMES.items() if k not in found]
    return list(found.values()), missing


def fetch(gd: GitData, remote: str) -> None:
    refspecs = [f"+refs/heads/main:refs/remotes/{remote}/main",
                f"+refs/heads/results/*:refs/remotes/{remote}/results/*"]
    try:
        done = gd._git("fetch", "--prune", "--quiet", remote, *refspecs, timeout=FETCH_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as error:
        raise ExportError(f"git fetch {remote}: {error}") from None
    if done.returncode != 0:
        raise ExportError(f"git fetch {remote}: {done.stderr.strip()}")


def export(gd: GitData, ref: str, remote: str = "origin") -> tuple[dict, int]:
    text = gd.show(ref, "config/site.toml")
    if text is None:
        raise ExportError(f"config/site.toml: not found at {ref}")
    config = tomllib.loads(text)
    for field in ("title", "description", "intro", "min_release"):
        if field not in config:
            raise ExportError(f"config/site.toml: missing field {field}")
    try:
        min_release = parse_version(str(config["min_release"]))
    except ValueError:
        raise ExportError(f"config/site.toml: min_release {config['min_release']!r} is not a version") from None
    cache: dict = {}
    experiments, all_rows, skipped = [], [], 0
    for experiment_id, source, branch in discover(gd, ref, remote):
        experiment, rows, n = read_experiment(gd, ref, source, branch, experiment_id, cache, min_release)
        skipped += n
        all_rows += rows
        if experiment:
            experiments.append(experiment)
    markdown = gd.show(ref, "docs/definitions.md")
    if markdown is None:
        raise ExportError(f"docs/definitions.md: not found at {ref}")
    definitions, missing = read_definitions(markdown)
    for name in missing:
        print(f"warning: docs/definitions.md has no metric named {name}", file=sys.stderr)
    page = {k: config[k] for k in ("title", "description", "intro")}
    puzzles = sorted({a["puzzle"] for e in experiments for a in e["attempts"]})
    legal_moves = {name: list(get_engine(name).legal_moves()) for name in puzzles}
    providers: dict[str, str] = {}
    for m in (m for e in experiments for m in e["models"]):
        if m["provider"] != "unknown":
            providers.setdefault(m["name"], m["provider"])
    return {"page": page, "legalMoves": legal_moves, "definitions": definitions,
            "metrics": metric_rows(all_rows, providers),
            "prompts": build_prompts(gd, ref, experiments, cache),
            "experiments": experiments}, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="site/.data/site.json")
    parser.add_argument("--ref", default="origin/main")
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--root", default=".", help="the git repository to read")
    parser.add_argument("--no-fetch", action="store_true", help="skip git fetch of the remote")
    args = parser.parse_args()
    gd = GitData(Path(args.root))
    try:
        if not args.no_fetch:
            fetch(gd, args.remote)
        data, skipped = export(gd, args.ref, args.remote)
    except (ExportError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    attempts = sum(e["attemptCount"] for e in data["experiments"])
    print(f"{len(data['experiments'])} experiments, {attempts} attempts, {skipped} skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
