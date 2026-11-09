# config

Files: `config/release.toml`, `config/experiments/<experiment id>.toml`, `config/templates/<provider>.toml`, `config/prices.toml`, `src/config.py`.

## Purpose

Hold every study parameter in three kinds of file, plus example configs to copy, and refuse a config with a missing or wrong value before any work starts.

## Inputs

1. `config/release.toml`, read by [release](release.md) for a major release:

   ```toml
   seed = 20261017
   puzzles = ["2x2", "3x3"]
   scramble_depths = [5, 10, 20]
   scramble_count = 10
   valid_invalid_split = 0.5
   ```

   `scramble_depths` is either one list for every puzzle, as above, or a table with one list per puzzle, and then every puzzle in `puzzles` needs an entry and no other key is allowed:

   ```toml
   [scramble_depths]
   2x2 = [5, 10, 20]
   3x3 = [5, 10, 20]
   4x4 = [10, 20, 40]
   5x5 = [15, 30, 60]
   ```

   `depths_for(release_config, puzzle) -> list[int]` returns the list for one puzzle in either form. [generate](generate.md), `max_moves`, and every other reader of depths use it.

2. `config/experiments/<experiment id>.toml`, read by [run](run.md) and [evaluate](evaluate.md). The file name is the [experiment id](../definitions.md#releases-and-experiments).

   ```toml
   release = "1.0.0"
   attempts = 3
   retry_cap = 3
   max_output_tokens = 32000
   reasoning_effort = "medium"    # optional; low, medium, or high; sent to every system-2 model; absent means the provider default
   max_moves = 14                 # optional; decision models only; default is twice the puzzle's largest scramble depth
   puzzles = ["2x2"]              # optional; default is every puzzle in the release
   inputs_per_depth = 4           # optional; valid inputs per puzzle and scramble depth; default is all of them
   batch = false                  # optional; true sends the attempts of anthropic, openai, and google models through their batch APIs; default false

   [[models]]
   name = "example-model"        # the AI model name written into raw records
   provider = "anthropic"        # anthropic | openai | google | openrouter | typesafe | cloudflare | fake | fake_decision
   api_model_id = "example-model-2026-01-01"
   kind = "system-2"             # optional; system-1 | system-2
   params = { temperature = 1.0 } # optional, passed to the SDK call unchanged

   [budget]                       # optional, in USD; these values are the defaults
   per_request_usd = 2.00
   per_model_usd = 25.00
   per_experiment_usd = 50.00
   ```

   [Budgets](../definitions.md#prices) limit what the experiment can spend. `[budget]` and each of its fields are optional. A missing field takes the default shown. It is the only part of an experiment config that may change after the experiment starts, so a stopped run can resume with a higher budget.

   `batch` turns on [batch mode](../definitions.md#batches). It is part of the experiment, so it can't change once the experiment starts: only `[budget]` may. The UI sends it as the checkbox "Batch: half price, results within 24 h" ([ui](ui.md)).

   `kind` says whether the AI model is a [system-1 or system-2 model](../definitions.md#setups). It is optional in an experiment config, because experiments committed before the field existed have none and must still evaluate.

   `params` pins every sampling setting the experiment uses, such as temperature or reasoning effort, in the provider's own parameter names. Anything left out takes the provider's default, and the report says so.

3. `config/prices.toml`, read by [run](run.md) for budgets and by [evaluate](evaluate.md) for cost. Prices live apart from the experiment so that a price change never touches an experiment config.

   ```toml
   [example-model]
   price_input_per_mtok = 3.00   # price per million input tokens
   price_output_per_mtok = 15.00 # price per million output tokens
   batch_price_input_per_mtok = 1.50   # optional; price per million input tokens in a batch
   batch_price_output_per_mtok = 7.50  # optional; price per million output tokens in a batch
   ```

   The two `batch_price_*` fields are the [batch prices](../definitions.md#prices). An entry holds both or neither, and each is written out, never computed from the token price. [run](run.md) and [evaluate](evaluate.md) need them only for an AI model that goes through a [batch](../definitions.md#batches).

4. `config/templates/<provider>.toml`, one experiment config per provider for [getting started](../getting-started.md). No script reads them. A user copies one to `config/experiments/` and runs it.

## Outputs

`load_release_config(path)`, `load_experiment_config(path)`, and `load_prices(path)`. Each returns a dict after these checks, and raises `ValueError` naming the file and field on the first one that fails.

`parse_experiment_config(text, experiment_id, source)` makes the same checks as `load_experiment_config` on TOML text that is not in a file, such as the config [run](run.md) reads from stdin. `source` stands in for the path in error messages, for example `<stdin>`. `load_experiment_config(path)` reads the file and calls it, with the file name as the experiment id.

The checks:

1. Every field shown is present and has the type shown.
2. `seed`, `scramble_count`, `attempts`, `max_output_tokens`, and every scramble depth are at least 1. `retry_cap` is at least 0. `max_moves`, if present, is an integer of at least 1. `max_moves(config, release_config, puzzle)` returns it, or twice the largest scramble depth of that puzzle in the release when it is absent. Every scramble depth in either form of `scramble_depths` is an integer of at least 1, and no list is empty. `reasoning_effort`, if present, is `low`, `medium`, or `high`.
3. `valid_invalid_split` is between 0 and 1.
4. Every puzzle is a name in the [registry](registry.md).
5. `release` is `latest` or matches `MAJOR.MINOR.PATCH`. [run](run.md) resolves `latest` to a version on the first run, so raw records, `results/<experiment id>/experiment.toml`, and reports always hold a version.
6. `models` has at least one entry, model names are unique, and `provider` is one of the eight listed. `openrouter` sends any model OpenRouter serves ([models](models.md#openrouter)). `typesafe` and `cloudflare` are [decision models](../definitions.md#setups), and `fake_decision` is the offline stand-in for them. `params` is a table, if present, and doesn't set any of these keys, which `models` and the run script set themselves: `model`, `model_id`, `api_model_id`, `prompt`, `messages`, `system`, `input`, `contents`, `max_tokens`, `max_output_tokens`, `max_completion_tokens`, `instructions`, `system_instruction`, `response_format`, `response_mime_type`, `response_schema`, `tools`, `tool_choice`, `reasoning_effort`, `output_config`, `thinking_config`, `thinking`, and `reasoning`. That keeps the request the same shape for every AI model. `kind`, if present, is a string and is `system-1` or `system-2`.
7. Every budget is a number above 0. They aren't checked against each other, so setting only `per_experiment_usd = 2` is valid, and a model budget above the experiment budget never binds. `load_experiment_config` returns `budget` with every default filled in.
8. `puzzles`, if present in an experiment config, is a non-empty list of unique strings, each a name in the [registry](registry.md). When it is absent, the experiment covers every puzzle in the release, and `load_experiment_config` leaves the key out of the dict it returns. [run](run.md) checks the names against the release.
9. `inputs_per_depth`, if present in an experiment config, is an integer of at least 1 (a float, a bool, and a string are errors). It is the [inputs per depth](../definitions.md#inputs) of the experiment. When it is absent, `load_experiment_config` leaves the key out of the dict it returns.
10. `batch`, if present, is a bool, else `ValueError` naming `batch`. With `batch = true`, a model with provider `openrouter` is refused, with the message `field 'batch' can't be true with openrouter model <name>: OpenRouter routes a batch to the cheapest upstream provider, so its answers are not comparable with direct calls`. A decision model is allowed: it has no batch API and runs direct. `BATCH_PROVIDERS` in `src/run/models.py` (`anthropic`, `openai`, `google`, and `fake` for tests) lists the providers that have one, and `src/config.py` imports it. With `batch = true`, a model whose provider has a batch API may not set `extra_body`, `extra_headers`, `extra_query`, or `timeout` in `params`, with the message `field 'models.<name>.params' must not set '<key>' when batch is true: it is a client setting, not part of the request body, so a batch line could not carry it`. That keeps a batch body equal to the direct body by construction.
11. In `load_prices`, each entry's `batch_price_input_per_mtok` and `batch_price_output_per_mtok` are both present or both absent, else `ValueError` naming the model (`must have both batch price fields or neither`), and each, if present, is a number that is not negative.
12. The experiment id contains only letters, digits, `-`, and `_`, because it becomes a folder name.

## How to test

1. The example files above load without error.
2. For each check above, a file that breaks it raises `ValueError`, and the message contains the field name.
3. A config with no `[budget]` returns the three defaults. A config that sets only `per_experiment_usd = 25` returns 25 for it and the defaults for the other two.
4. `parse_experiment_config` on the text of a valid file returns the same dict as `load_experiment_config` on that file, and its errors name `source`.
5. In an experiment config, `puzzles` accepts a valid list, and raises `ValueError` naming `puzzles` for an empty list, a repeated name, a value that isn't a list of strings, and an unknown name. With no `puzzles`, the returned dict has no `puzzles` key.
6. In an experiment config, `inputs_per_depth` accepts a valid value, and raises `ValueError` naming `inputs_per_depth` for 0, a float, a bool, and a string. With no `inputs_per_depth`, the returned dict has no such key.
7. In an experiment config, a model with `kind` set to `system-1` or `system-2` loads, and a model with no `kind` loads. `kind` raises `ValueError` naming `kind` for any other string and for a value that isn't a string.
8. `batch` accepts `true` and `false` and raises `ValueError` naming `batch` for a string or a number. `batch = true` with an `openrouter` model raises `ValueError` with the message above, and the same file with `batch = false` loads.
9. A prices entry with one batch field, or a negative one, raises `ValueError`. An entry with both loads.
10. Every file in `config/templates/` loads as an experiment config, names a release folder in `releases/` (or says `latest` while `releases/` holds one), and has a price in `config/prices.toml` for each AI model.
