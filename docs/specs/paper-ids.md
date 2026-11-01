# paper-ids

File: `paper/ids.py`.

## Purpose

Check that every placeholder ID stamped inside a figure or table box in `paper/main.pdf` matches the number LaTeX printed in its caption. Regenerate the placeholder table in `paper/README.md`. `paper/build.sh` runs it after LaTeX.

## Inputs

1. `paper/main.aux`: the number and page of every `fig:` and `tab:` label.
2. `paper/main.pdf`, read page by page with `pdftotext`, for the stamps `fig-onto-N[A-C]` and `tab-onto-N`.
3. The `META` table in the script: size, purpose, data source, and status per label.

## Outputs

1. `paper/build/id-map.tsv`: label, number, stamped ID, and page, one line per placeholder.
2. The block between `<!-- IDMAP:BEGIN -->` and `<!-- IDMAP:END -->` in `paper/README.md`, replaced.
3. On stdout, the checks and a last line `FIGURE_HEAVY_PAGE <page>`: the page with the most stamps.
4. Exit code 0 when every stamp matches, 1 when a stamp is missing, a `META` label is missing from `main.aux`, or the README markers are missing.

## How to test

1. Run `./build.sh` in `paper/`. The ID check reports 0 mismatches.
2. Swap two `\label`s in `main.tex` and rebuild. The check exits with 1.

`tests/test_paper_ids.py` covers both checks. It skips when there is no local build.
