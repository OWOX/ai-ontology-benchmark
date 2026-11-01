# Ontology hallucination paper: arXiv template

**Paper:** "Deterministic Measurement of Ontology-Grounded Hallucination and Solvability Detection in LLMs Using Twisty Puzzles", by Vlad Flaks and Mykhailo Flaks.

**Status:** template, built 2026-11-01. It has no measured results, because no Release 1.1.2 run exists yet. Every number without a `% SRC:` comment in `main.tex` is a red `[VALUE: …]` or `[TODO: …]` marker.

## Files

| File | Purpose |
|---|---|
| `main.tex` | Paper source: two-column article, 10 pt, US letter. Sections use `\label`/`\cref`, so no number is hardcoded. |
| `placeholders.sty` | TikZ macros for the placeholders: `\phpanel`, `\phsingle`, and the `phcanvas` environment. |
| `refs.bib` | Bibliography (natbib, `unsrtnat`). 14 entries carry `[AUTHORS: TODO]`. |
| `../prompts/<setup>/3x3.txt` | The approved 3x3 prompt templates, read from the repo for Appendix A. No copy lives in `paper/`. |
| `main.pdf` | Rendered paper, 13 pages. |
| `ste_check.py` | Converts `main.tex` to `build/main.check.html` and runs `verify_ste100.py` on it. It also checks for 3–5 sentences per paragraph, forbidden terms, and hardcoded references. |
| `make_previews.py` | Renders `previews/page-NN.png` and the contact sheet `preview.png` (first 8 pages). |
| `build.sh` / `Makefile` | Builds the PDF, runs the check, and renders the previews. The box has no `make`, so use `./build.sh` there. |
| `previews/figure-heavy-pageN.png` | The page with the most placeholder stamps, at 150 dpi. `build.sh` picks it automatically. |
| `ids.py` | Checks each stamped ID against its printed number in the PDF, writes `build/id-map.tsv`, and regenerates the ID table below. |

**Build:** `./build.sh` from `paper/`. It needs `latexmk` and `pdflatex` (TinyTeX or MacTeX), poppler (`pdftoppm`, `pdfinfo`, `pdftotext`), and Python 3 with Pillow. If the TeX binaries are not on `PATH`, set `TEXBIN` to their folder. The appendix prompt listings read `../prompts/<setup>/3x3.txt` straight from the repo.

**arXiv upload:** send `main.tex`, `main.bbl`, `placeholders.sty`, `refs.bib`, and the three `prompts/<setup>/3x3.txt` files (fix the `\lstinputlisting` paths to match). Category cs.CL, cross-listed to cs.AI.

## Placeholder format

- Each figure is a grey rectangle at its final size: `figure` is one column wide and `figure*` is the full text width.
- Lines cross the rectangle from corner to corner.
- The short purpose statement is rotated by exactly atan(h/w) of its box or panel. It is centred on the box centre and sits a small gap (`\phgap`, 1.5 pt) above the rising diagonal, and its fill hides the falling diagonal behind it. The macro tries several line widths and keeps the one that fits best. If no width fits at full size, it scales the block down until the block stays at least `\phmargin` (4 pt) inside the box, and logs `placeholders: scaled text in <ID> by <s>` in `main.log`. The smallest scale in the current build is 0.94.
- The ID is stamped at the bottom centre of each rectangle. The macro builds it from the float counter: `fig-onto-N` in a figure, `fig-onto-NA` for a panel, and `tab-onto-N` in a table. Never type it by hand. `ste_check.py` fails if a literal `fig-onto-<digit>` or `tab-onto-<digit>` appears in `main.tex`.
- Panels have large bold letters (A, B, C) in the top-left corner.
- Below each placeholder is a real caption: short, but more detailed than the text inside.
- Table placeholders (`tab-onto-N`) use the same format, with the caption above.
- **Layout:** a `\clearpage` before the bibliography flushes every pending float, so Figures 7–12 print before the references (Figures 7–10 on page 8, Figures 11 and 12 on page 9). Figures 9–12 use `[!htbp]`. The paper is 13 pages, and the figure numbers follow reading order.

## Figures and table placeholders

`placeholders.sty` derives each stamped ID from the LaTeX float counter, so the ID always equals the printed number. `ids.py` reads the compiled PDF and confirms that each stamp sits on the same page as its caption. It also regenerates the table below between the IDMAP markers. Do not edit the table by hand. The data tables (vocabulary, prompt bytes, prices, limits, fixtures) keep their own numbers, and the placeholder tables take whatever number their counter gives them.

Status legend: *data exists* means the source numbers are in the repo or this template, *pending run* means the figure needs the Release 1.1.2 experiment, and *new code* means it needs a script the repo does not have yet.

<!-- IDMAP:BEGIN -->
| Stamped ID | Printed as | Label | Size | Page | Purpose | Data source | Status |
|---|---|---|---|---|---|---|---|
| fig-onto-1 | Figure 1 | `fig:workflow` | full | 2 | Pipeline (generate → release → run → evaluate), reachable vs corrupted states, and what each setup adds | SVG Figure 1 in the arXiv HTML draft `ontology_hallucination_arxiv.html` (outside the repo); `src/puzzles/cube.py` | Schematic exists as SVG. Export it and draw panel C |
| fig-onto-2 | Figure 2 | `fig:example` | column | 3 | Puzzle and ontology example: rendered valid input, its corrupted copy, one JSON reply per outcome | `releases/1.0.0/inputs.jsonl`, `engine.render()`, `validator.py` | Data exists. To draw (new) |
| fig-onto-3 | Figure 3 | `fig:prompt-sizes` | column | 4 | Prompt template sizes, Release 1.0.0 vs 1.1.2, in bytes (and tokens under 1.1.2) | `tab:prompt-bytes` (byte sizes of `releases/1.0.0/prompts/` and `releases/1.1.2/prompts/`); 1.1.2 raw records | Bytes exist. Tokens pending the 1.1.2 run |
| fig-onto-4 | Figure 4 | `fig:cost` | column | 5 | Worst-case cost per model for one pass against the $5 model budget | `tab:limits` (MD Table 3), `config/prices.toml`, `src/run/budget.py` | Data exists. SVG Figure 3 exists in the HTML build |
| fig-onto-5 | Figure 5 | `fig:hallucination` | full | 6 | Hallucination rate per model × setup with Wilson CIs, split into solvable (A) and corrupted (B) inputs | evaluate report and CSV; `metrics.py` Wilson CI | Pending run (T-17 Fig 4) |
| fig-onto-6 | Figure 6 | `fig:setup-effect` | column | 7 | Paired change in hallucination rate per model (descriptive − no_model, prescriptive − no_model) | raw records, paired per input | Pending run. Needs a paired test (new) |
| fig-onto-7 | Figure 7 | `fig:outcomes` | full | 8 | Share of all five outcomes per model × setup (error taxonomy) | evaluate outcome counts | Pending run (new) |
| fig-onto-8 | Figure 8 | `fig:confusion` | full | 8 | Solvability confusion matrices per setup, pooled over models | mismatch flag vs validity label | Pending run (T-17 Fig 5) |
| fig-onto-9 | Figure 9 | `fig:flag-roc` | column | 8 | Detection rate vs false mismatch rate per model × setup (in place of a calibration plot) | evaluate | Pending run (new) |
| fig-onto-10 | Figure 10 | `fig:depth` | column | 8 | Accuracy vs scramble depth (5, 10, 20) for 2x2 (A) and 3x3 (B) | evaluate split by depth | Pending run (T-17 Fig 6) |
| fig-onto-11 | Figure 11 | `fig:tokens` | column | 9 | Output tokens vs scramble depth per setup | raw record token fields | Pending run (new) |
| fig-onto-12 | Figure 12 | `fig:pareto` | column | 9 | Cost per success vs success rate, with the Pareto front | evaluate; `config/prices.toml` | Pending run (T-17 Fig 7) |
| fig-onto-13 | Figure 13 | `fig:taxonomy` | column (appendix) | 11 | Impossible moves by type (slice, wide, lowercase, rotation, prime sign, invented) | parsed moves not in `legal_moves()` | Pending run. Needs a post-hoc classifier (new code) |
| fig-onto-14 | Figure 14 | `fig:per-puzzle` | column (appendix) | 11 | Per-puzzle breakdown: success (A) and hallucination (B), 2x2 vs 3x3 | evaluate split by puzzle | Pending run (new) |
| fig-onto-15 | Figure 15 | `fig:consistency` | column (appendix) | 12 | Consistency heat map over K repeated attempts | `consistency()`, metrics.py L65–75 | Pending run (new) |
| fig-onto-16 | Figure 16 | `fig:efficiency` | column (appendix) | 12 | Move count / reference length, 2x2 only | `efficiency()`, metrics.py L97–103 | Pending run. 3x3 is blocked by the missing solver |
| tab-onto-5 | Table 5 | `tab:main` | full | 6 | Main results: 9 models × 3 setups × 5 rates with CIs | evaluate CSV | Pending run |
| tab-onto-7 | Table 7 | `tab:full` | full (appendix) | 13 | Full results per model, setup, puzzle, and depth | evaluate CSV | Pending run |
| tab-onto-8 | Table 8 | `tab:datasheet` | column (appendix) | 13 | Croissant and Responsible AI fields for NeurIPS E&D | Vlad's doc, venue table | To write |
<!-- IDMAP:END -->

### Why the figures beyond T-17 are there

The bullets use labels, because the numbers come from the build. The table above maps each label to its current ID.

- **`fig:example` (puzzle example):** a reader has to see the exact input and reply format before any rate means anything. Reviewers of evaluation papers ask for this.
- **`fig:setup-effect` (paired effect):** the paper's question is about the effect of the setup on the same inputs. In `fig:hallucination` that effect shows only as a gap between bars, so a paired view is the figure that answers the question directly.
- **`fig:outcomes` (outcome breakdown):** a lower hallucination rate can come from more malformed output or more failures. The validator already separates the five outcomes, so this costs nothing extra.
- **`fig:flag-roc` (flag quality instead of calibration):** the reply has only a Boolean `mismatch` flag and no confidence, so a true calibration curve is impossible. Adding a confidence field would break AGENTS.md invariant 9 and need a new release. Detection rate against false-flag rate is the honest substitute, and the text says so in an Uncertainty callout.
- **`fig:tokens` (tokens vs depth):** the ontology makes the prompt longer, so the cost argument needs the token side. Gemini bills hidden thoughts as output.
- **`fig:taxonomy` (impossible-move types):** strict string matching (Open Item 6) means notation noise counts as hallucination. Readers need to see how much of the count it accounts for.
- **`fig:per-puzzle`, `fig:consistency`, `fig:efficiency`:** these answer README side questions 3 and 4 (cube size, consistency) and report the efficiency metric that the paper defines.
- **`tab:datasheet`:** the NeurIPS 2027 E&D track flags or desk-rejects submissions that have no Croissant metadata with Responsible AI fields.

## Real numbers kept, with sources

Each one has a `% SRC:` comment in `main.tex`.

- **Inputs:** 90 inputs, seed 20261017, depths 5/10/20, and 10 valid plus 5 corrupted per puzzle and depth.
- **State-space sizes:** 43,252,003,274,489,856,000 reachable states for the 3x3 and 3,674,160 for the 2x2.
- **Vocabulary:** the controlled vocabulary in the table comes from MD Table 1.
- **Prompt template bytes:**
  - Release 1.0.0: 298, 428, and 365 bytes.
  - Release 1.1.2 (the approved templates, identical to `prompts/`): 690, 1422/1489, and 1536/1603 bytes.
  - Source: `releases/1.0.0/prompts/` and the `release-1.1.2` tag.
- **Prices:** model prices and the dates they rise come from `config/prices.toml`.
- **Budget limits:** $0.50, $5, and $10.
- **Worst-case costs:** recomputed from the 270 Release 1.1.2 prompts and `config/prices.toml` (mean 334.5 input tokens). They replace MD Table 3.
- **Fixture verification rates:** MD Table 2.
- **Credit-request budget:** 810 attempts, 1,500 input and 4,096 output tokens, giving 109/215/58 USD (about 380 USD). Source: Vlad's doc.
- **Derived here:** the maximum Wilson half widths, 0.072 at n=180 and 0.101 at n=90, and the template growth of 2.3–4.4×.

## Discrepancies found in the sources

1. **MD Table 3, column K=1/T=1024:** the MD values are 1–2% higher than a recompute. Recomputed from the Release 1.1.2 prompts (mean 334.5 input tokens, not 337), gpt-6-astra comes out at $14.73, against $14.91 in the MD. The table now uses the recomputed values.
2. **The $182.97 total in the MD:** the recomputed K=3/T=2048 column adds up to **$183.67**. Confirm it with `run --dry-run`.
3. **Two budget bases:**
   - The paper uses K=3, T=2048, and 334.5 mean input tokens, for about $184.
   - Vlad's doc uses 1,500 input and 4,096 output tokens, for about $380.
   - The template states both and has a TODO to pick one.
4. **Scope of the abstract:** Vlad's doc abstract covers five puzzles (2x2, 3x3, 5x5, octahedral, and tetrahedral). Release 1.0.0 has only the 2x2 and 3x3 cubes, so the paper abstract covers only those two.
5. **Abstract length:** T-17 asks for an abstract of at most 200 words, and the doc abstract has 231. The paper abstract is a rewrite in STE of about 190 words.

## Abstract from Vlad's doc (verbatim, 231 words, not used as-is)

> Does giving an AI model the rules of a system change how often it solves a problem in that system, and how often it hallucinates? This study answers the question with twisty puzzles: the 2x2, 3x3, and 5x5 cubes, an octahedral puzzle, and a tetrahedral puzzle. Every move is defined, AI models already know the standard notation, and a deterministic validator checks every answer, so no person or AI model has to judge correctness.
> Each puzzle state goes to every AI model under three prompt setups. The first gives no rules. The second describes the rules. The third lists every legal move and requires the AI model to choose only from that list. A hallucination is a move that does not exist on the puzzle. A third of the inputs are corrupted into states that legal moves cannot reach, which tests whether the AI model notices that the problem is impossible.
> Inputs are generated once from a recorded seed and frozen, so every AI model sees byte-identical prompts. Every attempt is stored as a raw record, and every metric can be recomputed from those records. We report success rate, hallucination rate, mismatch detection rate, efficiency against a reference solver, consistency, tokens, and cost per success, each with a 95% Wilson interval. The study compares three Anthropic, three OpenAI, and three Google AI models, and will publish its inputs, prompts, and reports.

Three of its sentences break the 25-word limit, and it uses the passive voice in several places. The paper version fixes both.

## Venue plan (from Vlad's doc)

1. Publish the inputs, prompts, and raw records on Hugging Face, with a Zenodo DOI.
2. Post on arXiv in cs.CL, cross-listed to cs.AI. You need an endorser first.
3. Send a short version (about 4 pages) to an ICLR 2027 workshop, about 1 Feb 2027.
4. Submit the full paper to TMLR (rolling) or to the NeurIPS 2027 Evaluations and Datasets Track (about May 2027), if the 5x5, octahedral, and tetrahedral results are ready.

TMLR and NeurIPS review double-blind, so anonymise the paper and switch to their LaTeX templates. The placeholders port unchanged, because their sizes follow `\linewidth`.

## Style check

`python3 ste_check.py` runs `verify_ste100.py` on the converted HTML and adds three checks of its own:
- **Mapping:** body paragraphs become `<p>`. Bullets become `compact-list`. The Reproducibility steps become `procedure`. Captions and placeholder texts become `ref-list`, so the word limit applies to them but the paragraph rules do not.
- **Paragraph length:** every body paragraph must have 3–5 sentences.
- **Forbidden terms:** the script scans for the banned device names and the banned openings and reviewer references.
- **References:** it flags hardcoded "Section/Figure/Table N" references, and any literal `fig-onto-<digit>` or `tab-onto-<digit>` ID in `main.tex`.
- **IDs:** `ids.py` (run by `build.sh`) checks each stamped ID in the PDF against the caption number on its page.

The last run gave `STATUS: PASS (0 violations)`:
- 50 body paragraphs, with a mean of 3.54 sentences each.
- 328 descriptive sentences, the longest 25 words.
- 9 procedural steps, the longest 14 words.
- 0 extra violations.
- `ids.py`: 19 placeholders checked, 0 ID mismatches.

## Open TODOs

- Fill in the arXiv author lists. The arXiv API returned HTTP 503 on 2026-11-01, and the private repo is not visible to the GitHub connector.
- Merge the Release 1.1.2 commits into `main`. The tag `release-1.1.2` (a3245a1) sits on branch `docs/mismatch-comment`, so `releases/1.1.2/` is not on `main` yet.
- Pick the paired test (McNemar, paired bootstrap, or a mixed model) and the correction for multiple comparisons.
- Choose the budget basis.
- Write `scripts/plots.py` and the `make plots` target (planned in T-17).
- Write the impossible-move classifier.
- Confirm the affiliations (an open point in Vlad's doc).
- Add the dataset URL and DOI, and confirm repo visibility.
- Add the acknowledgements once any credit award arrives.
