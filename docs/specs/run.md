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
   4. If `results/<ID>/experiment.toml` exists, it is byte-identical to the experiment config. An experiment never changes once it starts.

   It exits with code 1 before any call if a check fails.
3. API keys from env vars, through [models](models.md).
4. Optional flags:
   1. `--model NAME` runs one AI model from the experiment. Separate processes can run different AI models at the same time, because each writes its own file.
   2. `--limit N` stops after N new attempts. For smoke tests.
   3. `--dry-run` prints each prompt and writes nothing.
   4. `--estimate` prints, for each AI model, the number of attempts still to run, the input tokens estimated as prompt characters divided by 4, and the worst-case cost with every answer at `max_output_tokens`, using `config/prices.toml`. It calls nothing and writes nothing.
   5. `--releases DIR`, `--configs DIR`, `--prices PATH`, and `--results DIR`, for tests.

## Outputs

In `results/<ID>/`:

1. `experiment.toml`: a copy of the experiment config, written on the first run.
2. `raw/<model name>.jsonl`: one file per AI model. `run` only appends to it, one JSON line per attempt, flushed after each line.

Loop order: for each input, for each AI model, for each setup (`no_model`, `descriptive`, `prescriptive`), for attempt number 1 to `attempts`:

1. Skip the attempt if its record already exists, keyed by input id, setup, AI model, and attempt number. That lets a stopped run start again where it left off.
2. Build the prompt with [prompts](prompts.md) from the release's templates.
3. Call [models](models.md). On `InfrastructureError`, retry up to `retry_cap` times, adding any token counts from the failed calls to the retry token fields. Never retry for any other reason.
4. If the cap is reached, the raw response is empty and `stop_reason` is `infrastructure_failure`.
5. Run the [validator](validator.md) and write the record.

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
10. Changing the experiment config after the first run makes `run` exit with code 1.
11. Every record has every field listed above, and no other.
12. `--dry-run` and `--estimate` write no file and make no call, and `--estimate` prints the attempt count the full run would make.
