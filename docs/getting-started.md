# Getting started

The minimum steps to run an [experiment](definitions.md#releases-and-experiments) from the terminal against an existing release and get its report. Terms are defined in [definitions.md](definitions.md). Every option is in the [run](specs/run.md) and [evaluate](specs/evaluate.md) specs.

## 1. Install

You need Python 3.11 or later and git. From the repo root:

```
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
source .venv/bin/activate
```

## 2. Export an API key

Export the key for the provider of the AI model you test:

```
export ANTHROPIC_API_KEY=...
export OPENAI_API_KEY=...
export GOOGLE_API_KEY=...
```

Never commit a key.

## 3. Write the experiment config

Create `config/experiments/<id>.toml`. The file name without `.toml` is the experiment id. Copy the model entry from `config/models.toml`. The model's `name` needs a row in `config/prices.toml`.

```
release = "1.3.1"
attempts = 1
retry_cap = 3
max_output_tokens = 32000
puzzles = ["2x2"]

[[models]]
name = "claude-haiku-5-5"
provider = "anthropic"
api_model_id = "claude-haiku-5-5"
kind = "system-2"
params = {}
```

`release` names a folder in `releases/`. `puzzles` is optional and limits the run to those puzzles. Without a `[budget]` table, the limits are 2.00 USD per request, 25.00 USD per AI model, and 50.00 USD per experiment.

## 4. Check the prompts and the cost

```
python -m src.run.run --experiment <id> --dry-run
python -m src.run.run --experiment <id> --estimate
```

`--dry-run` prints every prompt. `--estimate` prints the attempts left and the worst-case cost against each budget. Neither calls an AI model or writes anything.

## 5. Run

Try a few attempts first, then run the rest. A second run skips the attempts already recorded.

```
python -m src.run.run --experiment <id> --limit 3
python -m src.run.run --experiment <id>
```

`run` writes `results/<id>/raw/<model>.jsonl`, commits each attempt to the branch `results/<id>`, and pushes that branch to `origin` at the end. If a budget stops the run, raise it in the config and run the same command again.

## 6. Score

```
python -m src.evaluate.evaluate --experiment <id>
```

The report is `results/<id>/<release>.md`, with its metrics in `results/<id>/<release>.metrics.csv`.

## Without an API key

The `fake` provider makes no network call and costs nothing, so it checks the steps above end to end. Use this model entry in step 3 and skip step 2:

```
[[models]]
name = "example-model"
provider = "fake"
api_model_id = "example-model-2026-01-01"
params = {}
```

Every attempt answers `U`, so the outcomes mean nothing.

## Run the tests

```
pytest
```

Tests never call a real AI model API.
