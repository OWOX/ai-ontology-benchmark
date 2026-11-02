# evaluate

Files: `src/evaluate/evaluate.py` (command line, checks, writing) and `src/evaluate/metrics.py` (`compute()` and the metric maths). Both are assessment files.

## Purpose

The [`evaluate`](../definitions.md#workflows) workflow. Re-validate every raw record of one experiment under one release, and compute the [metrics](../definitions.md#metrics). No AI model takes part, and it never edits raw records. Running it twice gives the same output.

## Inputs

1. `--experiment ID`. Reads `results/<ID>/experiment.toml` and every file in `results/<ID>/raw/`.
2. `--release VERSION`, default the release in the experiment config. It must be that release or a [mirror](../definitions.md#releases-and-experiments) of it: same major and minor, the same `inputs.jsonl` hash, and the same `prompt_versions`, and the same `decision_prompt_versions` when both releases hold it. For example, an experiment run on `1.1.0` can be scored under `1.1.1`, never under `1.2.0`.
3. The assessment files in the working tree must hash to that release's `assessment_sha256`, and the working tree must render exactly the prompt versions the release froze (the same checks [run](run.md) makes). To score under an older release, check out its tag first.
4. Token prices. On the first evaluate of an experiment, `config/prices.toml` is copied to `results/<ID>/prices.toml`. Every later evaluate reads the copy, so a price change never rewrites a committed report. To use new prices, delete the copy on purpose.
5. Every AI model in the experiment config needs a price in the prices file, whether or not it has records.
6. Raw files are read with the shared `read_raw` helper from [run](run.md) (`src/run/raw.py`, an assessment file): a line that does not parse as a JSON object is skipped and counted, and the count goes to the report as `Torn raw lines skipped`. A record that lacks a required field is a checked error that names the file. A repeated (input id, setup, AI model, attempt number) is also a checked error that names the file.
7. Optional `--releases`, `--results`, and `--prices` paths, for tests.

`evaluate` exits with code 1 and writes nothing if any check fails.

## Outputs

1. `compute(raw_records, release_dir, prices, models=None, decision_models=frozenset()) -> (attempt_rows, metric_rows, summary_rows)`. `models` is the list of AI model names in config order, used to sort the rows; it defaults to the names found in the records.
   `evaluate` builds `decision_models` from the experiment config: the names of the AI models whose provider is a decision provider. `compute` passes the flag to the [validator](validator.md#decision-path) for their records, so those raw responses are read as arrays of calls.
   1. `attempt_rows` has one row per raw record: its identifying fields, the outcome from re-validation, and the outcome stored in the raw record.
   2. `metric_rows` has one row per puzzle, setup, AI model, scramble depth, and validity label, with these columns:
      1. `attempts` and `infrastructure_failure_count`.
      2. `success_rate`, `hallucination_rate`, `mismatch_detection_rate` (invalid rows only), `false_mismatch_rate` (valid rows only), and `malformed_output_rate`. Each rate has three more columns: `<rate>_n`, its denominator, and `<rate>_low` and `<rate>_high`, its 95% Wilson score interval.
      3. `efficiency` (valid rows only), `consistency`, and `latency_per_attempt_s`.
      4. `input_tokens_per_attempt`, `output_tokens_per_attempt`, and `cost_per_success`.
   3. `summary_rows`: the same rates and their intervals, pooled over puzzles and depths, with one row per AI model, setup, and validity label. Valid and invalid inputs are never pooled together.
2. `results/<ID>/<VERSION>.metrics.csv`: `metric_rows`, for analysis in other tools.
3. `results/<ID>/<VERSION>.md`: the experiment report, written by [report](report.md).

Every metric follows its definition in [definitions.md](../definitions.md#metrics), including which attempts each one leaves out. A metric with no data is `n/a`. `efficiency` is also `n/a` where the engine's `reference_length()` raises `NotImplementedError`.

Cost is `(input_tokens + retry_input_tokens) × price_input_per_mtok / 1,000,000` plus the same for output tokens.

## How to test

1. A hand-built fixture of 12 raw records on 2x2 inputs, covering every outcome, gives metrics equal to values worked out by hand in the test file.
2. The Wilson interval for 7 successes out of 10 is (0.397, 0.892), to three places.
3. Adding infrastructure failures to the fixture changes no rate, efficiency, consistency, or latency, but raises `infrastructure_failure_count`, tokens per attempt, and cost per success.
4. A group with no successes has `cost_per_success` of `n/a`.
5. A raw record whose stored outcome differs from re-validation shows both outcomes in `attempt_rows`, and the metrics use the re-validated one.
6. Scoring an experiment from `1.1.0` under `1.2.0` exits with code 1. Scoring it under a mirror `1.1.1` works.
7. Assessment files that don't match the release make it exit with code 1.
8. After the first evaluate, editing `config/prices.toml` doesn't change the output. Deleting `results/<ID>/prices.toml` makes the next evaluate use the new prices.
9. A torn line in the middle of a raw file, including one that ends in `}`, is skipped and counted. A duplicated attempt makes `evaluate` exit with code 1 and write nothing.
10. A config model without a price makes it exit with code 1 and write nothing.
11. Raw files are byte-identical before and after `evaluate`, and two runs give byte-identical output.
