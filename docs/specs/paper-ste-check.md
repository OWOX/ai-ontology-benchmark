# paper-ste-check

File: `paper/ste_check.py`.

## Purpose

Check the prose in `paper/main.tex` against the ASD-STE100 sentence rules and the paper's own writing rules. `paper/build.sh` runs it after LaTeX.

## Inputs

1. `paper/main.tex`.
2. [paper-verify-ste100](paper-verify-ste100.md), imported from `paper/verify_ste100.py`.

## Outputs

1. `paper/build/main.check.html`: the LaTeX mapped onto the HTML structure the verifier reads. Sections become `<h2>`/`<h3>`, body paragraphs `<p>`, bullets `<ul class="compact-list">`, procedure steps `<ol class="procedure">`, and captions and placeholder texts `<ol class="ref-list">`.
2. The verifier's report on stdout, then its own checks: 3 to 5 sentences per body paragraph, forbidden terms, hardcoded "Section/Figure/Table N" references, and literal `fig-onto-N` or `tab-onto-N` IDs in the source.
3. Exit code 0 when there are no violations, 1 otherwise.

## How to test

1. Run `python3 ste_check.py` in `paper/`. It reports 0 violations.
2. Add a sentence of more than 25 words to a body paragraph. The check exits with 1 and names the sentence.

`tests/test_paper_ste_check.py` runs both checks, and a third for a hardcoded reference, on a copy in a temporary folder.
