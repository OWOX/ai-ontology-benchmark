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
   `evaluate` builds `decision_models` from the experiment config: the names of the AI models whose provider is a decision provider. `compute` decides each record with `is_decision_record(record, decision_models)`: the record's own `decision` field when it has one, else whether its AI model is in `decision_models`. It passes the result to the [validator](validator.md#decision-path), so decision raw responses are read as arrays of calls. `REQUIRED` fields in `read_raw_dir` do not include `decision` or `requested_model`, because older records lack them.
   1. `attempt_rows` has one row per raw record: its identifying fields, the outcome from re-validation, and the outcome stored in the raw record.
   2. `metric_rows` has one row per puzzle, setup, AI model, scramble depth, and validity label, with these columns:
      1. `attempts` and `infrastructure_failure_count`.
      2. `success_rate`, `hallucination_rate`, `mismatch_detection_rate` (invalid rows only), `false_mismatch_rate` (valid rows only), `malformed_output_rate`, `truncated_rate`, `abstention_rate`, and `format_error_rate`. `hallucination_rate` is `n/a` with `_n` 0 for a group whose attempts all come from a [decision model](../definitions.md#setups), read from each attempt row's `decision` value (the raw record's `decision`, or the config rule for an old record). Each rate has four more columns: `<rate>_n`, the attempts behind it, `<rate>_inputs`, the inputs behind it, and `<rate>_low` and `<rate>_high`, its 95% bootstrap interval over inputs (see below).
      3. `consistency`, and `latency_per_attempt_s`.
      4. `input_tokens_per_attempt`, `output_tokens_per_attempt`, and `cost_per_success`.
   3. `summary_rows`: the same rates and their intervals, pooled over puzzles and depths, with one row per AI model, setup, and validity label. Valid and invalid inputs are never pooled together.
2. `paired_tests(attempt_rows, models=None) -> paired_rows` in `metrics.py`: the [paired setup test](../definitions.md#metrics), pooled over scramble depths and never over validity labels, one row per AI model, puzzle, validity label, metric, and setup pair, with columns `model, puzzle, validity, metric, setup_a, setup_b, inputs_paired, a_higher, b_higher, mean_difference, p_value, p_holm, significant`.
   1. `models` is the list of AI model names in config order. It defaults to the names found in the rows, sorted, the same as `compute`.
   2. `metric` is one of `success_rate`, `hallucination_rate`, and `mismatch_detection_rate` (invalid rows only). There are no `hallucination_rate` rows for a group whose attempts are all decision-model attempts.
   3. Setup pairs follow `SETUPS` order: (no_model, descriptive), (no_model, prescriptive), (descriptive, prescriptive).
   4. `mean_difference` is the mean over paired inputs of share_b − share_a.
   5. Rows are sorted by AI model (the order of `models`), puzzle, validity (valid first), metric (the order above), and pair.
   6. `significant` is `p_holm < 0.05`. When `inputs_paired` is 0, `mean_difference`, `p_value`, `p_holm`, and `significant` are `n/a`, and the row is left out of the Holm family.
   7. Holm: sort the family's p-values ascending. The adjusted p_(i) is the maximum over j ≤ i of min(1, (m − j + 1) × p_(j)), with m the family size.
3. `bootstrap_interval(cells, key) -> (rate, low, high)` in `metrics.py`: `cells` is one `(hits, attempts)` pair per input, sorted by input id. The rate is total hits over total attempts. Each of 2000 draws (`BOOTSTRAP_DRAWS`) picks as many inputs as there are, with replacement, and takes the rate over the picked cells. `low` and `high` are `sorted[int(0.025 * B)]` and `sorted[int(0.975 * B) - 1]` of the draw rates. The generator is `random.Random` seeded with the sha256 of `bootstrap-v1|<key>` (`BOOTSTRAP_SEED`), where `key` names the group and the metric (the group's key fields joined with `|`, then the rate name; summary rows start with `summary|`), so the result never depends on group order. The result is `n/a` three times for 0 attempts, and `(rate, n/a, n/a)` for fewer than 2 inputs. A rate whose every attempt is a hit, or none is, has `low` and `high` equal to the rate. `rates()` builds the cells once per rate from each group's rows. The [report CSV pooling in the UI](ui.md) has no per-input cells and keeps a Wilson score interval for display only, marked `*`.
4. `detection_rows(attempt_rows, models=None) -> detection_rows` in `metrics.py`: [balanced accuracy](../definitions.md#metrics) of mismatch detection, one row per AI model, puzzle, and setup, pooled over scramble depths, with columns `model, puzzle, setup, detection_rate, detection_n, false_mismatch_rate, false_mismatch_n, balanced_accuracy, balanced_accuracy_low, balanced_accuracy_high`.
   1. Attempts with outcome `infrastructure_failure` are left out. Rows are sorted by AI model (the order of `models`), puzzle (registry order), and setup (`SETUPS` order).
   2. Detection is over invalid attempts, false mismatch over valid ones. A rate is `n/a` when its n is 0, and balanced accuracy is `n/a` when either rate is.
   3. `balanced_accuracy_low` and `balanced_accuracy_high` come from `interval_for_balanced_accuracy(rows)`: a stratified bootstrap with the same draws and percentiles, where each draw picks valid and invalid inputs separately, each side as many as it has, and takes the balanced accuracy of the draw. The key is `<model>|<puzzle>|<setup>|balanced_accuracy`. It returns `n/a` for both when either side has fewer than 2 inputs.
5. `results/<ID>/<VERSION>.metrics.csv`: `metric_rows`, for analysis in other tools.
6. `results/<ID>/<VERSION>.paired.csv`: `paired_rows`, with the same CSV conventions as the metrics CSV, except that `p_value` and `p_holm` are written with 6 significant digits (`{:.6g}`), so a small p-value is not rounded to zero.
7. `results/<ID>/<VERSION>.detection.csv`: `detection_rows`, with the same CSV conventions as the metrics CSV.
8. `results/<ID>/<VERSION>.md`: the experiment report, written by [report](report.md).

Every metric follows its definition in [definitions.md](../definitions.md#metrics), including which attempts each one leaves out. A metric with no data is `n/a`.

Cost is `(input_tokens + retry_input_tokens) × price_input_per_mtok / 1,000,000` plus the same for output tokens.

## How to test

1. A hand-built fixture of 12 raw records on 2x2 inputs, covering every outcome, gives metrics equal to values worked out by hand in the test file.
2. `bootstrap_interval` is deterministic, gives `(2/3, n/a, n/a)` for one input and `n/a` three times for none, gives (1.0, 1.0, 1.0) for ten all-hit inputs, and is wider for 10 all-or-nothing inputs of 3 attempts each than for 30 independent attempts with the same hit share.
3. Adding infrastructure failures to the fixture changes no rate, consistency, or latency, but raises `infrastructure_failure_count`, tokens per attempt, and cost per success.
4. A group with no successes has `cost_per_success` of `n/a`.
5. A raw record whose stored outcome differs from re-validation shows both outcomes in `attempt_rows`, and the metrics use the re-validated one.
6. Scoring an experiment from `1.1.0` under `1.2.0` exits with code 1. Scoring it under a mirror `1.1.1` works.
7. Assessment files that don't match the release make it exit with code 1.
8. After the first evaluate, editing `config/prices.toml` doesn't change the output. Deleting `results/<ID>/prices.toml` makes the next evaluate use the new prices.
9. A torn line in the middle of a raw file, including one that ends in `}`, is skipped and counted. A duplicated attempt makes `evaluate` exit with code 1 and write nothing.
10. A config model without a price makes it exit with code 1 and write nothing.
11. Raw files are byte-identical before and after `evaluate`, and two runs give byte-identical output.
12. Sign test: 8 against 2 discordant inputs gives p = 0.109375 (exact), 0 against 0 gives 1.0, and 10 against 0 gives 0.001953125.
13. Holm on (0.01, 0.04, 0.03) gives (0.03, 0.06, 0.06).
14. An input with attempts under only one setup, or only infrastructure failures under one setup, is not paired.
15. Two attempts on one input count as one paired input. Shares of 0.5 and 1.0 make one discordant input.
16. Valid inputs get no `mismatch_detection_rate` rows.
17. `detection_rows`: 4 valid inputs with 1 flagged and 4 invalid inputs with 3 flagged give balanced accuracy 0.75, and an always-`MISMATCH` group gives 0.5.
