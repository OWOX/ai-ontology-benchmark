# Spec: docs/specs/paper-ids.md
"""Check stamped placeholder IDs against printed numbers and regenerate the README ID list.

1. Reads main.aux for the number and page of every fig:/tab: label.
2. Reads main.pdf page by page (pdftotext) and checks that every stamped ID
   fig-onto-N[A-C] / tab-onto-N sits on a page that prints "Figure N:" / "Table N:".
3. Writes build/id-map.tsv and replaces the block between the IDMAP markers in README.md.
4. Prints the page with the most stamps (the figure-heavy page) on the last line.
"""
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# label -> (size, purpose, data source, status). Numbers and IDs come from the build.
META = {
    "fig:workflow": ("full", "Pipeline (generate → release → run → evaluate), reachable vs corrupted states, and what each setup adds", "`docs/definitions.md` (Workflows); `src/puzzles/cube.py`", "To draw (new)"),
    "fig:example": ("column", "Puzzle and ontology example: rendered valid input, its corrupted copy, one reply per outcome", "`releases/3.0.0/inputs.jsonl`, `engine.render()`, `validate()` in `src/validator.py`", "Data exists. To draw (new)"),
    "fig:prompt-sizes": ("column", "Prompt template sizes by setup and puzzle under Release 3.0.0, in bytes and tokens", "`tab:prompt-bytes` (byte sizes of `releases/3.0.0/prompts/`); 3.0.0 raw records", "Bytes exist. Tokens pending the 3.0.0 run"),
    "fig:cost": ("column", "Worst-case cost per model for one pass against the default 25.00 USD model budget", "`tab:limits`, `config/prices.toml`, `worst_case_request_cost()` in `src/run/budget.py`", "Pending recompute from `releases/3.0.0/prompts/`"),
    "fig:hallucination": ("full", "Hallucination rate per model × setup with bootstrap intervals, split into solvable (A) and corrupted (B) inputs", "evaluate report and CSV; `bootstrap_interval()` in `src/evaluate/metrics.py`", "Pending 3.0.0 run"),
    "fig:setup-effect": ("column", "Paired change in hallucination rate per model (descriptive − no_model, prescriptive − no_model)", "paired setup test: `paired_tests()` in `src/evaluate/metrics.py`", "Pending 3.0.0 run. Plot to write"),
    "fig:outcomes": ("full", "Share of all eight outcomes per model × setup (error taxonomy)", "evaluate outcome counts", "Pending 3.0.0 run (new)"),
    "fig:confusion": ("full", "Classified-answer confusion matrices per setup, pooled over models", "answer classes: `answer_class()` in `src/evaluate/metrics.py`", "Pending 3.0.0 run (new)"),
    "fig:flag-roc": ("column", "Mismatch detection rate vs false mismatch rate per model × setup (in place of a calibration plot)", "`detection_rows()` in `src/evaluate/metrics.py`", "Pending 3.0.0 run (new)"),
    "fig:depth": ("column", "Precision on valid inputs vs scramble depth for the 2x2 (A), 3x3 (B), 4x4 (C), and 5x5 (D), each with its own depths", "evaluate split by depth", "Pending 3.0.0 run (new)"),
    "fig:tokens": ("column", "Output tokens vs scramble depth per setup", "raw record token fields", "Pending 3.0.0 run (new)"),
    "fig:pareto": ("column", "Cost efficiency vs balanced precision, with the Pareto front", "evaluate; `config/prices.toml`", "Pending 3.0.0 run (new)"),
    "fig:taxonomy": ("column (appendix)", "Impossible moves by type (slice, wide, lowercase, rotation, prime sign, invented)", "parsed moves not in `legal_moves()`", "Pending 3.0.0 run. Needs a post-hoc classifier (new code)"),
    "fig:per-puzzle": ("column (appendix)", "Per-puzzle breakdown: balanced precision (A) and hallucination rate (B), 2x2 to 5x5", "evaluate split by puzzle", "Pending 3.0.0 run (new)"),
    "fig:consistency": ("column (appendix)", "Consistency heat map over K repeated attempts", "`consistency()` in `src/evaluate/metrics.py`", "Pending 3.0.0 run (new)"),
    "fig:diagnosis": ("column (appendix)", "Diagnosis rate by corruption type and setup, with the best fixed answer", "corruption CSV: `corruption_rows()` in `src/evaluate/metrics.py`", "Pending 3.0.0 run (new)"),
    "tab:main": ("full", "Main results: 12 models × 3 setups, headline metrics with intervals", "evaluate CSV", "Pending 3.0.0 run"),
    "tab:full": ("full (appendix)", "Full results per model, setup, puzzle, and depth", "evaluate CSV", "Pending 3.0.0 run"),
    "tab:datasheet": ("column (appendix)", "Croissant and Responsible AI fields for NeurIPS E&D", "NeurIPS E&D track requirements", "To write"),
}


def main() -> int:
    aux = (HERE / "main.aux").read_text(encoding="utf-8")
    labels = {}
    for m in re.finditer(r"\\newlabel\{((?:fig|tab):[^}]*)\}\{\{([^}]*)\}\{([^}]*)\}", aux):
        labels[m.group(1)] = (m.group(2), m.group(3))
    npages = int(re.search(r"Pages:\s+(\d+)", subprocess.run(["pdfinfo", str(HERE / "main.pdf")], capture_output=True, text=True).stdout).group(1))
    errors, stamps_per_page, stamp_page = [], {}, {}
    for pg in range(1, npages + 1):
        txt = subprocess.run(["pdftotext", "-f", str(pg), "-l", str(pg), "-layout", str(HERE / "main.pdf"), "-"], capture_output=True, text=True).stdout
        stamps = re.findall(r"\b(fig|tab)-onto-(\d+|\?)([A-C]?)\b", txt)
        stamps_per_page[pg] = len(stamps)
        for kind, num, panel in stamps:
            sid = f"{kind}-onto-{num}{panel}"
            stamp_page.setdefault(f"{kind}-onto-{num}", pg)
            word = "Figure" if kind == "fig" else "Table"
            if num == "?" or not re.search(rf"\b{word} {num}:", txt):
                errors.append(f"page {pg}: stamp {sid} has no '{word} {num}:' caption on its page")
    rows, tsv = [], ["label\tnumber\tid\tpage"]
    placeholder_labels = [l for l in labels if l in META]
    for lab in sorted(placeholder_labels, key=lambda l: (l.startswith("tab"), int(labels[l][0]))):
        num, page = labels[lab]
        kind = "fig" if lab.startswith("fig") else "tab"
        sid = f"{kind}-onto-{num}"
        if sid not in stamp_page:
            errors.append(f"{lab}: printed as {num} but no stamp {sid} found in the PDF")
        size, purpose, source, status = META[lab]
        word = "Figure" if kind == "fig" else "Table"
        rows.append(f"| {sid} | {word} {num} | `{lab}` | {size} | {page} | {purpose} | {source} | {status} |")
        tsv.append(f"{lab}\t{num}\t{sid}\t{page}")
    missing = sorted(set(META) - set(labels))
    errors += [f"{l}: label not found in main.aux" for l in missing]
    (HERE / "build").mkdir(exist_ok=True)
    (HERE / "build" / "id-map.tsv").write_text("\n".join(tsv) + "\n", encoding="utf-8")
    table = ("| Stamped ID | Printed as | Label | Size | Page | Purpose | Data source | Status |\n"
             "|---|---|---|---|---|---|---|---|\n" + "\n".join(rows))
    readme = HERE / "README.md"
    r = readme.read_text(encoding="utf-8")
    r, nsub = re.subn(r"(<!-- IDMAP:BEGIN -->\n).*?(<!-- IDMAP:END -->)", lambda m: m.group(1) + table + "\n" + m.group(2), r, flags=re.S)
    if nsub != 1:
        errors.append("README.md: IDMAP markers not found")
    readme.write_text(r, encoding="utf-8")
    print("=== Placeholder ID check (stamp == printed number) ===")
    print(f"Placeholders checked         : {len(rows)}")
    print(f"ID mismatches                : {len(errors)}")
    for e in errors:
        print("  -", e)
    heavy = max(stamps_per_page, key=lambda p: stamps_per_page[p])
    print(f"FIGURE_HEAVY_PAGE {heavy}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
