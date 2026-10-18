# run

File: `src/run/run.py`.

## Purpose

The [`run`](../definitions.md#workflows) workflow. Send every input of one release to the AI models in one experiment, under every setup, validate each attempt, and append one raw record per attempt. It never changes a release.

## Inputs

1. `--experiment ID`. Reads `config/experiments/<ID>.toml` with [config](config.md).
2. The release named in that config, `releases/<release>/`. Before the first call, `run` checks:
   1. Every file in the release matches its sha256 in `manifest.json`.
   2. The assessment files in the working tree hash to the release's `assessment_sha256`, so the validator that writes the raw records is the one the release pins.
   3. `prompt_versions()` over the release's inputs and templates equals the manifest's `prompt_versions`, so the engine code in the working tree renders exactly the prompts the release froze.
   4. If `results/<ID>/experiment.toml` exists, it equals the experiment config apart from the `[budget]` table. An experiment never changes once it starts, except that its budget can be raised to resume.
   5. Every AI model in the experiment has a price in `config/prices.toml`.
   6. For every attempt still to run, the [worst-case request cost](../definitions.md#baseline-and-prices) is at most `per_request_usd`. The error names the AI model and its worst-case cost.

   It exits with code 1 before any call if a check fails.
3. API keys from env vars, through [models](models.md).
4. Optional flags:
   1. `--model NAME` runs one AI model from the experiment. Separate processes can run different AI models at the same time, because each writes its own file.
   2. `--limit N` stops after N new attempts. For smoke tests.
   3. `--dry-run` prints each prompt and writes nothing.
   4. `--estimate` prints, for each AI model, the number of attempts still to run, the input tokens estimated as prompt characters divided by 4, and the worst-case cost with every answer at `max_output_tokens`, using `config/prices.toml`, and the cost spent so far against each budget. It calls nothing and writes nothing.
   5. `--releases DIR`, `--configs DIR`, `--prices PATH`, and `--results DIR`, for tests.

## Outputs

In `results/<ID>/`:

1. `experiment.toml`: a copy of the experiment config, written on the first run. When a later run's config differs only in `[budget]`, `run` replaces the copy, so the report shows the budget in force.
2. `raw/<model name>.jsonl`: one file per AI model. `run` only appends to it, one JSON line per attempt, flushed after each line.

Loop order: for each input, for each AI model, for each setup (`no_model`, `descriptive`, `prescriptive`), for attempt number 1 to `attempts`:

1. Skip the attempt if its record already exists, keyed by input id, setup, AI model, and attempt number. That lets a stopped run start again where it left off. The raw file is read with `read_raw(path) -> (records, skipped_count)` in `src/run/raw.py`, which [evaluate](evaluate.md) also uses. `src/run/raw.py` is an assessment file, because it decides which raw lines get scored. It skips and counts every line that does not parse as a JSON object, because a stopped write leaves a torn line and a later run ends it with a newline, so it can sit anywhere in the file. A record that parses but lacks a key field is a checked error that names the file. Before it appends, `run` writes a newline if the file does not end with one, and it never rewrites a line.
2. Build the prompt with [prompts](prompts.md) from the release's templates.
3. Check the budgets. Spent cost is the [cost](../definitions.md#baseline-and-prices) of the raw records already written, computed by the same function [evaluate](evaluate.md) uses: this AI model's file for the model budget, and every raw file of the experiment for the experiment budget. `run` re-reads the other AI models' files before each call, so separate processes share the experiment budget. If spent cost plus the next worst-case request cost would pass `per_model_usd` or `per_experiment_usd`, `run` makes no call, writes nothing for that attempt, prints which budget stopped it, the cost spent, and the attempts left, and exits with code 1. The same check runs before every retry, counting the retry tokens so far in the attempt at the AI model's prices. If it stops a retry, `run` still writes the attempt's record as `infrastructure_failure` with those retry tokens, so paid spend is never hidden, and then exits with code 1. Raising the budget and running again resumes. Two processes running at once can each pass the experiment budget by at most one request.
4. Call [models](models.md). On `InfrastructureError`, retry up to `retry_cap` times, adding any token counts from the failed calls to the retry token fields. Never retry for any other reason.
5. If the cap is reached, the raw response is empty and `stop_reason` is `infrastructure_failure`.
6. Run the [validator](validator.md) and write the record. The loop calls the model (with retries) and passes the reply and the retry token counts to the function that builds the record, so building a record never calls an API.

Each record has every field in [invariant 13](../../AGENTS.md#invariants): `experiment_id`, `release_version`, `input_id`, `input_set_id`, `puzzle`, `scramble_depth`, `validity`, `setup`, `prompt_version`, `model`, `seed`, `input_seed`, `attempt_number`, `raw_response`, `parsed_moves`, `outcome`, `hallucination`, `mismatch`, `move_count`, `input_tokens`, `output_tokens`, `retry_input_tokens`, `retry_output_tokens`, `latency_s`, `stop_reason`, and `served_model`, plus `created_at`. It never holds a cost or a metric.

Within one process, attempts run one at a time. At the end, `run` prints a count of outcomes.

## How to test

All tests use the `fake` provider and temporary folders.

1. One run writes inputs × models × 3 setups × attempts records.
2. A second run with the same config adds no lines.
3. A run stopped with `--limit 5` and then run again ends with the same records as one full run, apart from `created_at` and `latency_s`.
4. `--model A` writes only `raw/A.jsonl`.
5. A fake that fails 5 times in a row with `retry_cap = 3` gives one record with outcome `infrastructure_failure`, an empty raw response, and 4 calls made.
6. A fake that returns malformed JSON is called once, never retried.
7. Changing one byte of the release's `inputs.jsonl` makes `run` exit with code 1 before any call.
8. Changing one byte of `src/validator.py` makes `run` exit with code 1 before any call.
9. Patching the engine's `render()` makes `run` exit with code 1 before any call.
10. Changing anything but `[budget]` in the experiment config after the first run makes `run` exit with code 1.
11. Every record has every field listed above, and no other.
12. A torn line at the end of a raw file, and one in the middle (including one that ends in `}`), is skipped, and the run resumes after it.
13. `--dry-run` and `--estimate` write no file and make no call, and `--estimate` prints the attempt count the full run would make.
14. With fake replies that each cost 0.01 USD, a worst-case request cost of 0.01 USD, `per_model_usd = 0.035`, and no records yet, `run` makes 3 calls, then exits with code 1 naming the model budget. Raising the budget to 1.00 and running again finishes the experiment.
15. Two AI models with the same costs and `per_experiment_usd = 0.045` stop after 4 calls in total, naming the experiment budget.
16. A worst-case request cost above `per_request_usd` makes `run` exit with code 1 before any call, naming the model.
17. A config with no `[budget]` uses the defaults, and changing only `[budget]` after the first run is accepted and updates `results/<ID>/experiment.toml`.
18. A model missing from `config/prices.toml` makes `run` exit with code 1 before any call.
