# config

Files: `config/release.toml`, `config/experiments/<experiment id>.toml`, `config/prices.toml`, `src/config.py`.

## Purpose

Hold every study parameter in three kinds of file, and refuse a config with a missing or wrong value before any work starts.

## Inputs

1. `config/release.toml`, read by [release](release.md) for a major release:

   ```toml
   seed = 20261017
   puzzles = ["2x2", "3x3"]
   scramble_depths = [5, 10, 20]
   scramble_count = 10
   valid_invalid_split = 0.5
   ```

2. `config/experiments/<experiment id>.toml`, read by [run](run.md) and [evaluate](evaluate.md). The file name is the [experiment id](../definitions.md#releases-and-experiments).

   ```toml
   release = "1.0.0"
   attempts = 3
   retry_cap = 3
   max_output_tokens = 4096

   [[models]]
   name = "example-model"        # the AI model name written into raw records
   provider = "anthropic"        # anthropic | openai | google | fake
   api_model_id = "example-model-2026-01-01"
   params = { temperature = 1.0 } # optional, passed to the SDK call unchanged

   [budget]                       # optional, in USD; these values are the defaults
   per_request_usd = 0.50
   per_model_usd = 5.00
   per_experiment_usd = 10.00
   ```

   [Budgets](../definitions.md#baseline-and-prices) limit what the experiment can spend. `[budget]` and each of its fields are optional. A missing field takes the default shown. It is the only part of an experiment config that may change after the experiment starts, so a stopped run can resume with a higher budget.

   `params` pins every sampling setting the experiment uses, such as temperature or reasoning effort, in the provider's own parameter names. Anything left out takes the provider's default, and the report says so.

3. `config/prices.toml`, read by [run](run.md) for budgets and by [evaluate](evaluate.md) for cost. Prices live apart from the experiment so that a price change never touches an experiment config.

   ```toml
   [example-model]
   price_input_per_mtok = 3.00   # price per million input tokens
   price_output_per_mtok = 15.00 # price per million output tokens
   ```

## Outputs

`load_release_config(path)`, `load_experiment_config(path)`, and `load_prices(path)`. Each returns a dict after these checks, and raises `ValueError` naming the file and field on the first one that fails:

1. Every field shown is present and has the type shown.
2. `seed`, `scramble_count`, `attempts`, `max_output_tokens`, and every scramble depth are at least 1. `retry_cap` is at least 0.
3. `valid_invalid_split` is between 0 and 1.
4. Every puzzle is a name in the [registry](registry.md).
5. `release` matches `MAJOR.MINOR.PATCH`.
6. `models` has at least one entry, model names are unique, and `provider` is one of the four listed. `params` is a table, if present, and doesn't set any of these keys, which `models` and the run script set themselves: `model`, `model_id`, `api_model_id`, `prompt`, `messages`, `system`, `input`, `contents`, `max_tokens`, `max_output_tokens`, `max_completion_tokens`, `instructions`, `system_instruction`, `response_format`, `response_mime_type`, `response_schema`, `tools`, and `tool_choice`. That keeps the request the same shape for every AI model.
7. Every budget is a number above 0. They aren't checked against each other, so setting only `per_experiment_usd = 2` is valid, and a model budget above the experiment budget never binds. `load_experiment_config` returns `budget` with every default filled in.
8. The experiment id contains only letters, digits, `-`, and `_`, because it becomes a folder name.

## How to test

1. The example files above load without error.
2. For each check above, a file that breaks it raises `ValueError`, and the message contains the field name.
3. A config with no `[budget]` returns the three defaults. A config that sets only `per_experiment_usd = 25` returns 25 for it and the defaults for the other two.
