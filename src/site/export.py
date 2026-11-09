# Spec: docs/specs/site.md
"""Reads config/site.toml, docs/definitions.md, the releases, and every results/<id>/ folder with raw records,
all at one git ref. Scores every raw record again with the current assessment and writes one JSON file for the static results page.
"""

import argparse
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

from src.config import check_prices_table
from src.evaluate.metrics import EvalError, make_attempt_rows
from src.puzzles.registry import get_engine
from src.run.models import DECISION_PROVIDERS
from src.run.raw import parse_raw_text
from src.site.metrics import metric_rows
from ui.gitdata import FETCH_TIMEOUT_S, GitData

METRIC_NAMES = {
    "Balanced precision": "precision",
    "Hallucination rate": "hallucination",
    "Critical thinking": "critical",
    "Cost efficiency": "cost",
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


def read_prices(gd: GitData, ref: str, experiment_id: str) -> dict:
    for path in (f"results/{experiment_id}/prices.toml", "config/prices.toml"):
        text = gd.show(ref, path)
        if text is not None:
            try:
                return check_prices_table(tomllib.loads(text), f"{ref}:{path}")
            except (ValueError, tomllib.TOMLDecodeError) as error:
                raise ExportError(str(error)) from None
    raise ExportError(f"{ref}: no prices.toml for experiment {experiment_id} and no config/prices.toml")


def discover(gd: GitData, ref: str) -> list[str]:
    """The experiment folders at the ref that hold at least one raw file. Any other folder is named on stderr."""
    found = []
    for experiment_id in sorted(gd.ls(ref, "results")):
        if any(n.endswith(".jsonl") for n in gd.ls(ref, f"results/{experiment_id}/raw")):
            found.append(experiment_id)
        else:
            print(f"skipped results/{experiment_id}: no raw records", file=sys.stderr)
    return found


def read_experiment(gd: GitData, ref: str, experiment_id: str, cache: dict) -> tuple[dict, list[dict], int]:
    """Return (experiment, re-validated attempt rows, skipped count) for one experiment."""
    folder = f"results/{experiment_id}"
    toml_text = gd.show(ref, f"{folder}/experiment.toml")
    if toml_text is None:
        raise ExportError(f"no {folder}/experiment.toml at {ref}")
    toml = tomllib.loads(toml_text)
    release = toml.get("release")
    if not isinstance(release, str):
        raise ExportError(f"{ref}:{folder}/experiment.toml: field release is missing")
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
    for name in sorted(n for n in gd.ls(ref, f"{folder}/raw") if n.endswith(".jsonl")):
        found, torn = parse_raw_text(gd.show(ref, f"{folder}/raw/{name}") or "")
        skipped += torn
        for r in found:
            if r.get("input_id") in by_id:
                records.append(r)
            else:
                skipped += 1
    try:
        rows = make_attempt_rows(records, inputs, read_prices(gd, ref, experiment_id), decision_models, reasons)
    except (KeyError, EvalError) as error:
        raise ExportError(f"{ref}:{folder}: {error}") from None
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
        "puzzles": sorted({a["puzzle"] for _, a in kept}),
        "models": sorted(models.values(), key=lambda m: m["name"]),
        "setups": sorted({a["setup"] for _, a in kept}),
        "attemptsPerInput": per_input if type(per_input) is int else None,
        "attemptCount": len(kept), "firstAt": times[0], "lastAt": times[-1],
        "attempts": [a for _, a in kept],
    }, rows, skipped


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
    refspec = f"+refs/heads/main:refs/remotes/{remote}/main"
    try:
        done = gd._git("fetch", "--prune", "--quiet", remote, refspec, timeout=FETCH_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as error:
        raise ExportError(f"git fetch {remote}: {error}") from None
    if done.returncode != 0:
        raise ExportError(f"git fetch {remote}: {done.stderr.strip()}")


def export(gd: GitData, ref: str) -> tuple[dict, int]:
    text = gd.show(ref, "config/site.toml")
    if text is None:
        raise ExportError(f"config/site.toml: not found at {ref}")
    config = tomllib.loads(text)
    for field in ("title", "description", "intro"):
        if field not in config:
            raise ExportError(f"config/site.toml: missing field {field}")
    cache: dict = {}
    experiments, all_rows, skipped = [], [], 0
    for experiment_id in discover(gd, ref):
        experiment, rows, n = read_experiment(gd, ref, experiment_id, cache)
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
        data, skipped = export(gd, args.ref)
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
