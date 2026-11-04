# report

File: `src/evaluate/report.py`.

## Purpose

Write the [experiment report](../definitions.md#releases-and-experiments): one Markdown file per experiment and release, committed to GitHub and readable there without running anything. It shows results only. It names the release and links to its inputs and prompts, and never copies them. It isn't part of the assessment, so changing its layout never needs a release.

## Inputs

`write_report(path, experiment_id, experiment_config, release_dir, prices, attempt_rows, metric_rows, summary_rows, torn_lines=0, paired_rows=())`. [evaluate](evaluate.md) calls it with what `compute()` and `paired_tests()` returned and the count of torn raw lines it skipped.

## Outputs

`results/<experiment id>/<release version>.md`. Paths are relative so the links work on GitHub. Sections in this order:

1. **Title.** `# Experiment <experiment id> on release <version>`.
2. **Release.** The first lines of the file:
   1. Release version and tag, linked to `releases/<version>/README.md`.
   2. The release this experiment ran on, and whether this report is a mirror of it.
   3. The assessment hash.
   4. Links to `inputs.jsonl` and the `prompts/` folder in the release.
3. **Experiment.** Linked to `experiment.toml`.
   1. A table of AI models with name, provider, API model id, kind (or "not set" when the config has none), every served model id seen in the raw records, and `params`, or "provider defaults" when there are none.
   2. When the config has `puzzles`, the line `Puzzles: 2x2, 3x3` with the names in config order. Without `puzzles`, the line is absent and the report is unchanged.
   3. Attempts, retry cap, and maximum output tokens.
   4. First and last `created_at` across raw records.
   5. The line `Torn raw lines skipped: <n>.`
   6. The token prices used, linked to `prices.toml` in the experiment folder.
   7. The three budgets in force, and the cost spent per AI model and in total, at the prices used.
4. **Summary.** For each AI model, two tables with setups as columns:
   1. Valid inputs: success rate, hallucination rate, false mismatch rate, malformed output rate, and cost per success.
   2. Invalid inputs: success rate, mismatch detection rate, hallucination rate, and malformed output rate.

   Every rate cell reads `0.42 (0.30–0.55) n=60`: the rate, its 95% interval, and its denominator.
5. **Setup comparison.** Present only when `paired_rows` is not empty. One sentence above the tables links the [paired setup test](../definitions.md#metrics). For each AI model, one table per puzzle with columns Validity, Metric, Setups (`a vs b`), Inputs paired, A higher, B higher, Mean difference (2 places), p (3 places), Holm p (3 places), and Significant (`yes`, `no`, or `n/a`). Mean difference, p, and Holm p show `n/a` when no input is paired.
6. **Metrics.** Every row of `metric_rows`, one table per puzzle, with rates shown the same way.
7. **Attempts.** One table per input, headed by the input id linked to its line in the release's `inputs.jsonl` (`#L<n>`). The heading also shows the validity label and depth. Columns are AI model, setup, attempt, outcome, moves joined with spaces, mismatch, input and output tokens, and latency. The token columns are headed `Input tokens (excl. retries)` and `Output tokens (excl. retries)`, because they leave out the retry tokens that the cost and the metrics tables include. Where re-validation changed an outcome, the cell shows `stored → current`.
8. **Raw responses.** Not copied. One link to the `raw/` folder.

## How to test

1. A fixture with 2 inputs, 1 AI model, and 3 setups gives a file equal to a stored expected file.
2. Every relative link in the output points at a file that exists in the fixture tree.
3. The output contains no prompt text and no rendered state.
4. The first heading names the release version, and the next lines link its tag and README.
5. No summary table mixes valid and invalid inputs.
6. A changed outcome shows as `stored → current`.
7. The `Puzzles:` line appears only when the config sets `puzzles`.
8. The Kind column shows the config's `kind`, and "not set" for a model with none.
9. With `paired_rows`, the Setup comparison section appears between Summary and Metrics, with the columns above. Without them, it is absent and the report is unchanged.

## Risk

GitHub stops rendering Markdown files over about 512 KB. At roughly 150 bytes per attempt row, that is about 3,000 attempts in one report. Past that, split the attempts section into one file per puzzle and link them from the report.
