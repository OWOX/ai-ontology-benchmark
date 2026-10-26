# Spec: docs/specs/ui.md
"""Builds the `puzzles` part of the bundle for one release: input counts, description, prompt
templates, the engine's move group, and the impossible moves seen in raw records. Reads
`main` and the release through GitData and the loaded experiments. Writes nothing.
"""

import re
from collections import defaultdict
from typing import Callable

from src.puzzles.registry import ENGINES
from src.run.prompts import SETUPS
from ui import expdata
from ui.gitdata import GitData

Link = Callable[[str], "str | None"]


def first_paragraph(text: str) -> str | None:
    """The first paragraph after the `#` title, or the first one when there is no title."""
    lines = text.splitlines()
    start = next((i + 1 for i, line in enumerate(lines) if line.startswith("# ")), 0)
    paragraph: list[str] = []
    for line in lines[start:]:
        if line.strip():
            paragraph.append(line.strip())
        elif paragraph:
            break
    return " ".join(paragraph) or None


def impossible_seen(puzzle: str, legal: list[str], experiments: list[dict]) -> list[dict]:
    seen: dict[str, dict] = defaultdict(lambda: {"count": 0, "models": set(), "experiments": set()})
    for exp in experiments:
        if exp["error"]:
            continue
        try:
            found = [(m, r.get("model")) for rs in exp["records"].values() for r in rs
                     if r.get("puzzle") == puzzle for m in expdata.impossible_moves(r, legal)]
        except Exception:
            continue  # one unreadable experiment never blocks the bundle
        for move, model in found:
            entry = seen[move]
            entry["count"] += 1
            entry["models"].add(model)
            entry["experiments"].add(exp["id"])
    ranked = sorted(seen.items(), key=lambda item: (-item[1]["count"], item[0]))
    return [{"move": move, "count": e["count"], "models": sorted(m for m in e["models"] if m),
             "experiments": sorted(e["experiments"])} for move, e in ranked]


def build_puzzle(git: GitData, main: str, link: Link, release: str, manifest: dict, name: str,
                 inputs: list[dict], experiments: list[dict]) -> dict:
    mine = [r for r in inputs if r["puzzle"] == name]
    text = git.show(main, f"docs/puzzles/{name}.md")
    description = first_paragraph(text) if text is not None else None
    prompts = {}
    for setup in SETUPS:
        path = f"releases/{release}/prompts/{setup}/{name}.txt"
        template = git.show(main, path)
        if template is not None:
            version = manifest.get("prompt_versions", {}).get(setup, {}).get(name)
            prompts[setup] = {"text": template, "version": version, "source": link(path)}
    shape = re.fullmatch(r"(\d+)x\1", name)
    engine = ENGINES.get(name)
    legal = list(engine.legal_moves()) if engine else None
    return {"name": name, "n": int(shape.group(1)) if shape else None, "input_count": len(mine),
            "depths": sorted({r["scramble_depth"] for r in mine}),
            "valid": sum(r["validity"] == "valid" for r in mine),
            "invalid": sum(r["validity"] == "invalid" for r in mine),
            "description": {"text": description, "source": link(f"docs/puzzles/{name}.md") if text is not None else None},
            "prompts": prompts, "legal_moves": legal,
            "legal_moves_source": link(type(engine).__module__.replace(".", "/") + ".py") if engine else None,
            "impossible_seen": impossible_seen(name, legal, experiments) if legal is not None else [],
            "inputs_source": link(f"releases/{release}/inputs.jsonl")}
