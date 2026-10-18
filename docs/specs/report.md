# report

File: `src/evaluate/report.py`.

## Purpose

Write the [experiment report](../definitions.md#releases-and-experiments): one Markdown file per experiment and release, committed to GitHub and readable there without running anything. It shows results only. It names the release and links to its inputs and prompts, and never copies them. It isn't part of the assessment, so changing its layout never needs a release.

## Inputs

`write_report(path, experiment_id, experiment_config, release_dir, prices, attempt_rows, metric_rows, summary_rows, torn_lines=0)`. [evaluate](evaluate.md) calls it with what `compute()` returned and the count of torn raw lines it skipped.

## Outputs

`results/<experiment id>/<release version>.md`. Paths are relative so the links work on GitHub. Sections in this order:

1. **Title.** `# Experiment <experiment id> on release <version>`.
2. **Release.** The first lines of the file:
   1. Release version and tag, linked to `releases/<version>/README.md`.
   2. The release this experiment ran on, and whether this report is a mirror of it.
   3. The assessment hash.
   4. Links to `inputs.jsonl` and the `prompts/` folder in the release.
3. **Experiment.** Linked to `experiment.toml`.
   1. A table of AI models with name, provider, API model id, every served model id seen in the raw records, and `params`, or "provider defaults" when there are none.
   2. Attempts, retry cap, and maximum output tokens.
   3. First and last `created_at` across raw records.
   4. The line `Torn raw lines skipped: <n>.`
   5. The token prices used, linked to `prices.toml` in the experiment folder.
4. **Summary.** For each AI model, two tables with setups as columns:
   1. Valid inputs: success rate, hallucination rate, false mismatch rate, malformed output rate, and cost per success.
   2. Invalid inputs: success rate, mismatch detection rate, hallucination rate, and malformed output rate.

   Every rate cell reads `0.42 (0.30–0.55) n=60`: the rate, its 95% interval, and its denominator.
5. **Metrics.** Every row of `metric_rows`, one table per puzzle, with rates shown the same way.
6. **Attempts.** One table per input, headed by the input id linked to its line in the release's `inputs.jsonl` (`#L<n>`). The heading also shows the validity label and depth. Columns are AI model, setup, attempt, outcome, moves joined with spaces, mismatch, input and output tokens, and latency. The token columns are headed `Input tokens (excl. retries)` and `Output tokens (excl. retries)`, because they leave out the retry tokens that the cost and the metrics tables include. Where re-validation changed an outcome, the cell shows `stored → current`.
7. **Raw responses.** Not copied. One link to the `raw/` folder.

## How to test

1. A fixture with 2 inputs, 1 AI model, and 3 setups gives a file equal to a stored expected file.
2. Every relative link in the output points at a file that exists in the fixture tree.
3. The output contains no prompt text and no rendered state.
4. The first heading names the release version, and the next lines link its tag and README.
5. No summary table mixes valid and invalid inputs.
6. A changed outcome shows as `stored → current`.

## Risk

GitHub stops rendering Markdown files over about 512 KB. At roughly 150 bytes per attempt row, that is about 3,000 attempts in one report. Past that, split the attempts section into one file per puzzle and link them from the report.
