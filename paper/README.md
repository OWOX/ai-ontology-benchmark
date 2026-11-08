# Ontology hallucination paper: arXiv template

**Paper:** "Deterministic Measurement of Ontology-Grounded Hallucination and Solvability Detection in LLMs Using Twisty Puzzles", by Vlad Flaks and Mykhailo Flaks.

**Status:** template, updated 2026-11-08 to the method on `main`. The evidence release is 3.0.0, the held-out input set (input set id 3, seed 20261108). Releases 1.x and 2.x hold the development input sets, and their results are not evidence. The paper has no measured results. Every number without a `% SRC:` comment in `main.tex` is a red `[VALUE: …]` or `[TODO: …]` marker.

**`main.pdf` predates this update.** No TeX was available when the text changed, so the PDF, the page numbers in the ID table below, and the page count are from the earlier build. Run `./build.sh` to rebuild them. `ids.py` then regenerates the ID table.

## Files

| File | Purpose |
|---|---|
| `main.tex` | Paper source: two-column article, 10 pt, US letter. Sections use `\label`/`\cref`, so no number is hardcoded. |
| `placeholders.sty` | TikZ macros for the placeholders: `\phpanel`, `\phsingle`, and the `phcanvas` environment. |
| `refs.bib` | Bibliography (natbib, `unsrtnat`). 15 of the 19 entries carry `[AUTHORS: TODO]`. |
| `../releases/3.0.0/prompts/<setup>/3x3.txt` | The 3x3 prompt templates of Release 3.0.0, read from the repo for Appendix A. No copy lives in `paper/`. |
| `main.pdf` | Rendered paper. Built before the Release 3.0.0 update, so rebuild it with `./build.sh`. |
| `ste_check.py` | Converts `main.tex` to `build/main.check.html` and runs `verify_ste100.py` on it. It also checks for 3–5 sentences per paragraph, forbidden terms, and hardcoded references. |
| `make_previews.py` | Renders `previews/page-NN.png` and the contact sheet `preview.png` (every page). |
| `build.sh` / `Makefile` | Builds the PDF, runs the check, and renders the previews. The box has no `make`, so use `./build.sh` there. |
| `previews/figure-heavy-pageN.png` | The page with the most placeholder stamps, at 150 dpi. `build.sh` picks it automatically. |
| `ids.py` | Checks each stamped ID against its printed number in the PDF, writes `build/id-map.tsv`, and regenerates the ID table below. |

**Build:** `./build.sh` from `paper/`. It needs `latexmk` and `pdflatex` (TinyTeX or MacTeX), poppler (`pdftoppm`, `pdfinfo`, `pdftotext`), and Python 3 with Pillow. If the TeX binaries are not on `PATH`, set `TEXBIN` to their folder. `TEXBIN` is optional. `build.sh` and the Makefile look for TinyTeX in `~/Library/TinyTeX/bin/universal-darwin`, `~/.TinyTeX/bin/universal-darwin`, and `~/.TinyTeX/bin/x86_64-linux`, and otherwise use `PATH`. The appendix prompt listings read `../releases/3.0.0/prompts/<setup>/3x3.txt` straight from the repo.

**arXiv upload:** send `main.tex`, `main.bbl`, `placeholders.sty`, `refs.bib`, and the three `releases/3.0.0/prompts/<setup>/3x3.txt` files (fix the `\lstinputlisting` paths to match). Category cs.CL, cross-listed to cs.AI.

## Placeholder format

- Each figure is a grey rectangle at its final size: `figure` is one column wide and `figure*` is the full text width.
- Lines cross the rectangle from corner to corner.
- The short purpose statement is rotated by exactly atan(h/w) of its box or panel. It is centred on the box centre and sits a small gap (`\phgap`, 1.5 pt) above the rising diagonal, and its fill hides the falling diagonal behind it. The macro tries several line widths and keeps the one that fits best. If no width fits at full size, it scales the block down until the block stays at least `\phmargin` (4 pt) inside the box, and logs `placeholders: scaled text in <ID> by <s>` in `main.log`. The smallest scale in the current build is 0.94.
- The ID is stamped at the bottom centre of each rectangle. The macro builds it from the float counter: `fig-onto-N` in a figure, `fig-onto-NA` for a panel, and `tab-onto-N` in a table. Never type it by hand. `ste_check.py` fails if a literal `fig-onto-<digit>` or `tab-onto-<digit>` appears in `main.tex`.
- Panels have large bold letters (A, B, C) in the top-left corner.
- Below each placeholder is a real caption: short, but more detailed than the text inside.
- Table placeholders (`tab-onto-N`) use the same format, with the caption above.
- **Layout:** a `\clearpage` before the bibliography flushes every pending float, so Figures 7–12 print before the references. Figures 9–12 use `[!htbp]`. The figure numbers follow reading order. Check the page layout after the next build.

## Figures and table placeholders

`placeholders.sty` derives each stamped ID from the LaTeX float counter, so the ID always equals the printed number. `ids.py` reads the compiled PDF and confirms that each stamp sits on the same page as its caption. It also regenerates the table below between the IDMAP markers. Do not edit the table by hand. The data tables (vocabulary, prompt bytes, prices, limits) keep their own numbers, and the placeholder tables take whatever number their counter gives them.

Status legend: *data exists* means the source numbers are in the repo or this template, *pending run* means the figure needs the Release 3.0.0 experiment, and *new code* means it needs a script the repo does not have yet.

<!-- IDMAP:BEGIN -->
| Stamped ID | Printed as | Label | Size | Page | Purpose | Data source | Status |
|---|---|---|---|---|---|---|---|
| fig-onto-1 | Figure 1 | `fig:workflow` | full | 2 | Pipeline (generate → release → run → evaluate), reachable vs corrupted states, and what each setup adds | `docs/definitions.md` (Workflows); `src/puzzles/cube.py` | To draw (new) |
| fig-onto-2 | Figure 2 | `fig:example` | column | 3 | Puzzle and ontology example: rendered valid input, its corrupted copy, one reply per outcome | `releases/3.0.0/inputs.jsonl`, `engine.render()`, `validate()` in `src/validator.py` | Data exists. To draw (new) |
| fig-onto-3 | Figure 3 | `fig:prompt-sizes` | column | 4 | Prompt template sizes by setup and puzzle under Release 3.0.0, in bytes and tokens | `tab:prompt-bytes` (byte sizes of `releases/3.0.0/prompts/`); 3.0.0 raw records | Bytes exist. Tokens pending the 3.0.0 run |
| fig-onto-4 | Figure 4 | `fig:cost` | column | 5 | Worst-case cost per model for one pass against the default 25.00 USD model budget | `tab:limits`, `config/prices.toml`, `worst_case_request_cost()` in `src/run/budget.py` | Pending recompute from `releases/3.0.0/prompts/` |
| fig-onto-5 | Figure 5 | `fig:hallucination` | full | 6 | Hallucination rate per model × setup with bootstrap intervals, split into solvable (A) and corrupted (B) inputs | evaluate report and CSV; `bootstrap_interval()` in `src/evaluate/metrics.py` | Pending 3.0.0 run |
| fig-onto-6 | Figure 6 | `fig:setup-effect` | column | 7 | Paired change in hallucination rate per model (descriptive − no_model, prescriptive − no_model) | paired setup test: `paired_tests()` in `src/evaluate/metrics.py` | Pending 3.0.0 run. Plot to write |
| fig-onto-7 | Figure 7 | `fig:outcomes` | full | 8 | Share of the seven outcomes in the rates per model × setup, with the infrastructure failure count | evaluate outcome counts | Pending 3.0.0 run (new) |
| fig-onto-8 | Figure 8 | `fig:confusion` | full | 8 | Classified-answer confusion matrices per setup, pooled over models | answer classes: `answer_class()` in `src/evaluate/metrics.py` | Pending 3.0.0 run (new) |
| fig-onto-9 | Figure 9 | `fig:flag-roc` | column | 8 | Mismatch detection rate vs false mismatch rate per model × setup (in place of a calibration plot) | `detection_rows()` in `src/evaluate/metrics.py` | Pending 3.0.0 run (new) |
| fig-onto-10 | Figure 10 | `fig:depth` | column | 8 | Precision on valid inputs vs scramble depth for the 2x2 (A), 3x3 (B), 4x4 (C), and 5x5 (D), each with its own depths | evaluate split by depth | Pending 3.0.0 run (new) |
| fig-onto-11 | Figure 11 | `fig:tokens` | column | 9 | Output tokens vs scramble depth per setup | raw record token fields | Pending 3.0.0 run (new) |
| fig-onto-12 | Figure 12 | `fig:pareto` | column | 9 | Cost efficiency vs balanced precision, with the Pareto front | evaluate; `config/prices.toml` | Pending 3.0.0 run (new) |
| fig-onto-13 | Figure 13 | `fig:taxonomy` | column (appendix) | 11 | Impossible moves by type (slice, wide, lowercase, rotation, layer-count, doubled suffix) | parsed moves not in `legal_moves()` | Pending 3.0.0 run. Needs a post-hoc classifier (new code) |
| fig-onto-14 | Figure 14 | `fig:per-puzzle` | column (appendix) | 11 | Per-puzzle breakdown: balanced precision (A) and hallucination rate (B), 2x2 to 5x5 | evaluate split by puzzle | Pending 3.0.0 run (new) |
| fig-onto-15 | Figure 15 | `fig:consistency` | column (appendix) | 12 | Consistency heat map over K repeated attempts | `consistency()` in `src/evaluate/metrics.py` | Pending 3.0.0 run (new) |
| fig-onto-16 | Figure 16 | `fig:diagnosis` | column (appendix) | 12 | Diagnosis rate by corruption type and setup | corruption CSV: `corruption_rows()` in `src/evaluate/metrics.py` | Pending 3.0.0 run (new) |
| tab-onto-5 | Table 5 | `tab:main` | full | 6 | Main results: 12 models × 3 setups, headline metrics with intervals | evaluate CSV | Pending 3.0.0 run |
| tab-onto-6 | Table 6 | `tab:full` | full (appendix) | 13 | Full results per model, setup, puzzle, and depth | evaluate CSV | Pending 3.0.0 run |
| tab-onto-7 | Table 7 | `tab:datasheet` | column (appendix) | 13 | Croissant and Responsible AI fields for NeurIPS E&D | NeurIPS E&D track requirements | To write |
<!-- IDMAP:END -->

The page numbers above are from the earlier build and may shift. The table numbers of `tab:full` and `tab:datasheet` were renumbered by hand, because `tab:fixtures` was removed. `ids.py` rewrites the table on the next build.

### Why the extra figures are there

The bullets use labels, because the numbers come from the build. The table above maps each label to its current ID.

- **`fig:example` (puzzle example):** a reader has to see the exact input and reply format before any rate means anything. Reviewers of evaluation papers ask for this.
- **`fig:setup-effect` (paired effect):** the paper's question is about the effect of the setup on the same inputs. The paired setup test answers it directly, which the gap between bars in `fig:hallucination` does not.
- **`fig:outcomes` (outcome breakdown):** a lower hallucination rate can come from more malformed output or more failures. The validator already separates the eight outcomes, so this costs nothing extra.
- **`fig:confusion` and `fig:flag-roc` (detection):** the answer classes read the mismatch reason, and the detection plot reads the mismatch flag only. The reply has no confidence, so a true calibration curve is impossible. Adding a confidence field would break AGENTS.md invariant 9 and need a new release.
- **`fig:tokens` (tokens vs depth):** the ontology makes the prompt longer, so the cost argument needs the token side. Gemini bills hidden thoughts as output.
- **`fig:taxonomy` (impossible-move types):** strict string matching means notation noise counts as hallucination. Readers need to see how much of the count it accounts for.
- **`fig:per-puzzle`, `fig:consistency`, `fig:diagnosis`:** these show the cube size effect, the consistency over repeated attempts, and which corruption types the AI models diagnose. The diagnosis figure replaces the dropped efficiency figure.
- **`tab:datasheet`:** the NeurIPS 2027 E&D track flags or desk-rejects submissions that have no Croissant metadata with Responsible AI fields.

## Real numbers kept, with sources

Each one has a `% SRC:` comment in `main.tex`.

- **Inputs:** 600 inputs in Release 3.0.0, seed 20261108. Per puzzle and scramble depth: 40 valid and 10 invalid inputs, so 480 valid and 120 invalid. Depths: 5, 10, and 20 on the 2x2 and 3x3, 10, 20, and 40 on the 4x4, and 15, 30, and 60 on the 5x5. Source: `releases/3.0.0/README.md`.
- **State-space sizes:** 43,252,003,274,489,856,000 reachable states for the 3x3 and 3,674,160 for the 2x2.
- **Prompt template bytes:** measured with `wc -c` on `releases/3.0.0/prompts/` (identical to `prompts/`). `tab:prompt-bytes` has the figures.
- **Prices:** model prices and the dates they rise come from `config/prices.toml`. The decision models have an output price of zero.
- **Budget defaults:** request 2.00 USD, model 25.00 USD, experiment 50.00 USD (`docs/definitions.md`, Prices).
- **Sample size:** 120 valid inputs per puzzle give 80% power for a 20-point difference from 0.50 at α 0.05 (`docs/methodology.md`).

The worst-case cost table (`tab:limits`) holds `\val{...}` cells. It was computed for Release 1.1.2 with the old budgets, so it needs a recompute from `releases/3.0.0/prompts/` and `config/prices.toml`.

## Dropped from the earlier draft

1. **Efficiency, reference length, and the reference solver.** Dropped on 2026-11-04, because optimal solvers are not practical for the 5x5 and the other puzzles. The paper no longer defines them, and `fig:efficiency` became `fig:diagnosis`.
2. **Wilson intervals.** Replaced by 95% bootstrap intervals over inputs, and the `wilson1927` entry left `refs.bib`.
3. **The JSON reply.** Output is one move per line or a `MISMATCH` line with a reason (invariant 9).
4. **The credit-request budget (810 attempts, about 380 USD).** It came from a document outside the repo. The budget basis is a `\todo` in `main.tex`.
5. **The fixture table.** The fixtures now use bootstrap metrics, so the old table with Wilson intervals was removed.

## Venue plan

1. Publish the inputs, prompts, and raw records on Hugging Face, with a Zenodo DOI.
2. Post on arXiv in cs.CL, cross-listed to cs.AI. You need an endorser first.
3. Send a short version (about 4 pages) to an ICLR 2027 workshop, about 1 Feb 2027.
4. Submit the full paper to TMLR (rolling) or to the NeurIPS 2027 Evaluations and Datasets Track (about May 2027), if the octahedral and tetrahedral results are ready.

TMLR and NeurIPS review double-blind, so anonymize the paper and switch to their LaTeX templates. The placeholders port unchanged, because their sizes follow `\linewidth`.

## Style check

`python3 ste_check.py` runs `verify_ste100.py` on the converted HTML and adds three checks of its own:
- **Mapping:** body paragraphs become `<p>`. Bullets become `compact-list`. The Reproducibility steps become `procedure`. Captions and placeholder texts become `ref-list`, so the word limit applies to them but the paragraph rules do not.
- **Paragraph length:** every body paragraph must have 3–5 sentences.
- **Forbidden terms:** the script scans for the banned device names and the banned openings and reviewer references.
- **References:** it flags hardcoded "Section/Figure/Table N" references, and any literal `fig-onto-<digit>` or `tab-onto-<digit>` ID in `main.tex`.
- **IDs:** `ids.py` (run by `build.sh`) checks each stamped ID in the PDF against the caption number on its page.

The last run gave `STATUS: PASS (0 violations)`:
- 55 body paragraphs, with a mean of 3.91 sentences each.
- 371 descriptive sentences, the longest 25 words.
- 9 procedural steps, the longest 14 words.
- 0 extra violations.
- `ids.py`: not run since the update, because it needs the rebuilt PDF. The earlier build had 19 placeholders and 0 ID mismatches, and the placeholder count is unchanged.

## Open TODOs

- Rebuild `main.pdf` with `./build.sh` and check the page layout.
- Fill in the arXiv author lists. The arXiv API returned HTTP 503 on 2026-11-01, and the private repo is not visible to the GitHub connector.
- Choose the budget basis and recompute `tab:limits` from `releases/3.0.0/prompts/` and `config/prices.toml`.
- Confirm the number of attempts per input (`K`) and the reasoning effort of the 3.0.0 run.
- Write `scripts/plots.py` and the `make plots` target.
- Write the impossible-move classifier.
- Confirm the affiliations.
- Add the dataset URL and DOI, and confirm repo visibility.
- Add the acknowledgements once any credit award arrives.
