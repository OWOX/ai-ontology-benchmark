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
   max_output_tokens = 32000
   max_moves = 14                 # optional; decision models only; default is twice the largest scramble depth
   puzzles = ["2x2"]              # optional; default is every puzzle in the release

   [[models]]
   name = "example-model"        # the AI model name written into raw records
   provider = "anthropic"        # anthropic | openai | google | typesafe | cloudflare | fake | fake_decision
   api_model_id = "example-model-2026-01-01"
   kind = "system-2"             # optional; system-1 | system-2
   params = { temperature = 1.0 } # optional, passed to the SDK call unchanged

   [budget]                       # optional, in USD; these values are the defaults
   per_request_usd = 2.00
   per_model_usd = 25.00
   per_experiment_usd = 50.00
   ```

   [Budgets](../definitions.md#baseline-and-prices) limit what the experiment can spend. `[budget]` and each of its fields are optional. A missing field takes the default shown. It is the only part of an experiment config that may change after the experiment starts, so a stopped run can resume with a higher budget.

   `kind` says whether the AI model is a [system-1 or system-2 model](../definitions.md#setups). It is optional in an experiment config, because experiments committed before the field existed have none and must still evaluate.

   `params` pins every sampling setting the experiment uses, such as temperature or reasoning effort, in the provider's own parameter names. Anything left out takes the provider's default, and the report says so.

3. `config/prices.toml`, read by [run](run.md) for budgets and by [evaluate](evaluate.md) for cost. Prices live apart from the experiment so that a price change never touches an experiment config.

   ```toml
   [example-model]
   price_input_per_mtok = 3.00   # price per million input tokens
   price_output_per_mtok = 15.00 # price per million output tokens
   ```

## Outputs

`load_release_config(path)`, `load_experiment_config(path)`, and `load_prices(path)`. Each returns a dict after these checks, and raises `ValueError` naming the file and field on the first one that fails.

`parse_experiment_config(text, experiment_id, source)` makes the same checks as `load_experiment_config` on TOML text that is not in a file, such as the config [run](run.md) reads from stdin. `source` stands in for the path in error messages, for example `<stdin>`. `load_experiment_config(path)` reads the file and calls it, with the file name as the experiment id.

The checks:

1. Every field shown is present and has the type shown.
2. `seed`, `scramble_count`, `attempts`, `max_output_tokens`, and every scramble depth are at least 1. `retry_cap` is at least 0. `max_moves`, if present, is an integer of at least 1. `max_moves(config, release_config)` returns it, or twice the largest scramble depth in the release when it is absent.
3. `valid_invalid_split` is between 0 and 1.
4. Every puzzle is a name in the [registry](registry.md).
5. `release` matches `MAJOR.MINOR.PATCH`.
6. `models` has at least one entry, model names are unique, and `provider` is one of the seven listed. `typesafe` and `cloudflare` are [decision models](../definitions.md#setups), and `fake_decision` is the offline stand-in for them. `params` is a table, if present, and doesn't set any of these keys, which `models` and the run script set themselves: `model`, `model_id`, `api_model_id`, `prompt`, `messages`, `system`, `input`, `contents`, `max_tokens`, `max_output_tokens`, `max_completion_tokens`, `instructions`, `system_instruction`, `response_format`, `response_mime_type`, `response_schema`, `tools`, and `tool_choice`. That keeps the request the same shape for every AI model. `kind`, if present, is a string and is `system-1` or `system-2`.
7. Every budget is a number above 0. They aren't checked against each other, so setting only `per_experiment_usd = 2` is valid, and a model budget above the experiment budget never binds. `load_experiment_config` returns `budget` with every default filled in.
8. `puzzles`, if present in an experiment config, is a non-empty list of unique strings, each a name in the [registry](registry.md). When it is absent, the experiment covers every puzzle in the release, and `load_experiment_config` leaves the key out of the dict it returns. [run](run.md) checks the names against the release.
9. The experiment id contains only letters, digits, `-`, and `_`, because it becomes a folder name.

## How to test

1. The example files above load without error.
2. For each check above, a file that breaks it raises `ValueError`, and the message contains the field name.
3. A config with no `[budget]` returns the three defaults. A config that sets only `per_experiment_usd = 25` returns 25 for it and the defaults for the other two.
4. `parse_experiment_config` on the text of a valid file returns the same dict as `load_experiment_config` on that file, and its errors name `source`.
5. In an experiment config, `puzzles` accepts a valid list, and raises `ValueError` naming `puzzles` for an empty list, a repeated name, a value that isn't a list of strings, and an unknown name. With no `puzzles`, the returned dict has no `puzzles` key.
6. In an experiment config, a model with `kind` set to `system-1` or `system-2` loads, and a model with no `kind` loads. `kind` raises `ValueError` naming `kind` for any other string and for a value that isn't a string.
