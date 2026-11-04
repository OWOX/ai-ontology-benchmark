# Getting started

The minimum steps to run an [experiment](definitions.md#releases-and-experiments) from the terminal and get its report. Every option is in the [run](specs/run.md) and [evaluate](specs/evaluate.md) specs.

## 1. Install

You need Python 3.11 or later and git. From the repo root:

```
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
```

## 2. Copy a config template

Pick the template for your provider in `config/templates/`: `anthropic`, `openai`, `google`, or `fake`. The `fake` one needs no API key and costs nothing, so it checks the steps end to end. The file name you copy to is the experiment id.

```
cp config/templates/anthropic.toml config/experiments/my-test.toml
export ANTHROPIC_API_KEY=...
```

The other providers read `OPENAI_API_KEY` and `GOOGLE_API_KEY`. Set `release` in the copy to the newest folder in `releases/`.

## 3. Check the cost and run

```
python -m src.run.run --experiment my-test --estimate
python -m src.run.run --experiment my-test --limit 3
python -m src.run.run --experiment my-test
```

`--estimate` prints the worst-case cost against each [budget](definitions.md#baseline-and-prices) and calls nothing. `--limit 3` runs three attempts as a smoke test. The last command runs the rest and skips attempts already recorded. `run` commits each attempt to the branch `results/my-test` and pushes it to `origin` at the end.

## 4. Score

```
python -m src.evaluate.evaluate --experiment my-test
```

The report is `results/my-test/<release>.md`.

## Run the tests

```
pytest
```
