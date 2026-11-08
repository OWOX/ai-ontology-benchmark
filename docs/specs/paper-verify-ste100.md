# paper-verify-ste100

File: `paper/verify_ste100.py`.

## Purpose

Check an HTML file against the ASD-STE100 sentence rules and the paper's paragraph structure. [paper-ste-check](paper-ste-check.md) runs it and imports its regular expressions and helpers.

## Inputs

One HTML file, as the first argument. Default: `paper/build/main.check.html`.

## Outputs

A report on stdout and exit code 0 when there are no violations, 1 otherwise. It checks:

1. Every `<p>` outside procedure steps and reference items has sentences of at most 25 words.
2. Every procedure step (`<ol class="procedure">`) is one sentence of at most 20 words that starts with an imperative verb.
3. No `<h2>` or `<h3>` has a hardcoded section number.
4. Every body `<p>` outside lists has at least 2 sentences, with a mean of at least 3.
5. Every bullet in `<ul class="compact-list">` keeps its sentences in one `<li><p>` and has at least 2.

## How to test

1. Run it on `paper/build/main.check.html` after a build. It reports 0 violations.
2. Add a numbered heading such as `<h2>1 Introduction</h2>` to a copy of the file. It exits with 1.

`tests/test_paper_verify_ste100.py` runs both checks on small HTML files, plus a long sentence and a missing file.
