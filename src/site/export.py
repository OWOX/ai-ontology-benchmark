# Spec: docs/specs/site.md
"""Reads config/site.toml, docs/definitions.md, and releases/*/inputs.jsonl at one git ref, and
results/<id>/experiment.toml and results/<id>/raw/*.jsonl from the branch <remote>/results/<id>,
for every experiment listed in the config. Writes one JSON file for the static results page.
"""

import argparse
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

METRIC_NAMES = {
    "Success rate": "success",
    "Hallucination rate": "hallucination",
    "Mismatch detection rate": "detection",
}


class ExportError(Exception):
    pass


def git(root: Path, *args: str, check: bool = True) -> str | None:
    done = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                          encoding="utf-8", stdin=subprocess.DEVNULL)
    if done.returncode != 0:
        if check:
            raise ExportError(f"git {' '.join(args)}: {done.stderr.strip()}")
        return None
    return done.stdout


def read_jsonl(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def read_inputs(root: Path, ref: str, release: str, cache: dict) -> dict:
    if release not in cache:
        text = git(root, "show", f"{ref}:releases/{release}/inputs.jsonl", check=False)
        cache[release] = {r["input_id"]: {"state": r["state"], "corruption": r.get("corruption")}
                          for r in read_jsonl(text or "")}
    return cache[release]


def read_experiment(root: Path, ref: str, remote: str, experiment_id: str, cache: dict) -> tuple[dict, int]:
    branch = f"{remote}/results/{experiment_id}"
    if git(root, "rev-parse", "--verify", "--quiet", branch, check=False) is None:
        raise ExportError(f"config/site.toml, experiments: no branch {branch} for experiment {experiment_id}")
    folder = f"results/{experiment_id}"
    toml_text = git(root, "show", f"{branch}:{folder}/experiment.toml", check=False)
    toml = tomllib.loads(toml_text) if toml_text else {}
    tree = git(root, "ls-tree", "--name-only", f"{branch}:{folder}/raw", check=False)
    kept, skipped = [], 0
    for name in sorted(n for n in (tree or "").splitlines() if n.endswith(".jsonl")):
        for r in read_jsonl(git(root, "show", f"{branch}:{folder}/raw/{name}")):
            if r["outcome"] == "infrastructure_failure":
                continue
            found = read_inputs(root, ref, r["release_version"], cache).get(r["input_id"])
            if found is None:
                skipped += 1
                continue
            kept.append((r["created_at"], {
                "model": r["model"], "puzzle": r["puzzle"], "inputId": r["input_id"],
                "validity": r["validity"], "setup": r["setup"], "attempt": r["attempt_number"],
                "depth": r["scramble_depth"], "state": found["state"], "corruption": found["corruption"],
                "moves": r["parsed_moves"], "outcome": r["outcome"], "mismatch": r["mismatch"]}))
    if not kept:
        raise ExportError(f"{branch}: experiment {experiment_id} has no raw records to show")
    kept.sort(key=lambda k: (k[1]["model"], k[1]["puzzle"], k[1]["inputId"], k[1]["setup"], k[1]["attempt"], k[0]))
    models = {m["name"]: {"name": m["name"], "provider": m.get("provider", "unknown"),
                          "kind": m.get("kind", "unknown")} for m in toml.get("models", [])}
    for _, a in kept:
        models.setdefault(a["model"], {"name": a["model"], "provider": "unknown", "kind": "unknown"})
    times = sorted(k[0] for k in kept)
    per_input = toml.get("attempts")
    return {
        "experimentId": experiment_id,
        "release": toml["release"] if isinstance(toml.get("release"), str) else "",
        "puzzles": sorted({a["puzzle"] for _, a in kept}),
        "models": sorted(models.values(), key=lambda m: m["name"]),
        "setups": sorted({a["setup"] for _, a in kept}),
        "attemptsPerInput": per_input if isinstance(per_input, int) else None,
        "attemptCount": len(kept), "firstAt": times[0], "lastAt": times[-1],
        "attempts": [a for _, a in kept],
    }, skipped


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


def export(root: Path, ref: str, remote: str) -> tuple[dict, int]:
    text = git(root, "show", f"{ref}:config/site.toml", check=False)
    if text is None:
        raise ExportError(f"config/site.toml: not found at {ref}")
    config = tomllib.loads(text)
    for field in ("title", "description", "intro", "experiments"):
        if field not in config:
            raise ExportError(f"config/site.toml: missing field {field}")
    cache: dict = {}
    experiments, skipped = [], 0
    for experiment_id in sorted(config["experiments"]):
        experiment, n = read_experiment(root, ref, remote, experiment_id, cache)
        experiments.append(experiment)
        skipped += n
    markdown = git(root, "show", f"{ref}:docs/definitions.md", check=False)
    if markdown is None:
        raise ExportError(f"docs/definitions.md: not found at {ref}")
    definitions, missing = read_definitions(markdown)
    for name in missing:
        print(f"warning: docs/definitions.md has no metric named {name}", file=sys.stderr)
    page = {k: config[k] for k in ("title", "description", "intro")}
    return {"page": page, "definitions": definitions, "experiments": experiments}, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="site/.data/site.json")
    parser.add_argument("--ref", default="origin/main")
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--root", default=".", help="the git repository to read")
    parser.add_argument("--no-fetch", action="store_true", help="skip git fetch of the remote")
    args = parser.parse_args()
    root = Path(args.root)
    try:
        if not args.no_fetch:
            git(root, "fetch", "--quiet", args.remote)
        data, skipped = export(root, args.ref, args.remote)
    except (ExportError, KeyError, ValueError) as error:
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
