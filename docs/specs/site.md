# site

`src/site/export.py`, `src/site/metrics.py`, `config/site.toml`, `site/`, and `.github/workflows/pages.yml`. Exports the data for the public results page and builds and publishes it from `site/`. The files under `site/src/components/islands/` and `site/src/lib/benchmark.ts` are ported from the personal site, and `site/src/lib/types.ts` holds the types they use. Terms are defined in [definitions.md](../definitions.md).

## Inputs

1. `config/site.toml` at `--ref` (default `origin/main`): `title`, `description`, and `intro`.
2. `docs/definitions.md` at `--ref`.
3. Every experiment folder `results/<id>/` at `--ref` that holds at least one `raw/*.jsonl` file: its `experiment.toml` and raw files, the `releases/<experiment release>/inputs.jsonl` and `manifest.json` of its release, and its prices, from `results/<id>/prices.toml` or else `config/prices.toml` (the same order `evaluate` uses, checked by `src.config.check_prices_table`). Results live on `main`, not on per-experiment branches. A folder without a raw file is skipped with one stderr line naming it.

The script first runs `git fetch --prune <remote>` (`--remote`, default `origin`) with the refspec `+refs/heads/main:refs/remotes/<remote>/main` and a 60 second timeout, so `<remote>/main` is current, unless `--no-fetch` is given. It reads git objects only, never the work tree.

## Scoring

Every raw record is scored again by the assessment in this checkout, whatever release made it: `make_attempt_rows` from `src/evaluate/metrics.py` is called on the records, the inputs of the experiment's release, the prices, the config's decision models (providers in `DECISION_PROVIDERS`), and whether the release's manifest has `mismatch_reasons` (false when absent). `load_release` is not called, because it refuses a release whose assessment differs from the current one, which is expected here. A record whose input is not in the release's `inputs.jsonl` is not scored and is counted as skipped.

## Output

`--out` (default `site/.data/site.json`), one JSON file:

```json
{ "page": { "title": "", "description": "", "intro": "" },
  "legalMoves": { "2x2": [] },
  "definitions": [ { "key": "precision", "name": "Balanced precision", "definition": "" } ],
  "metrics": [ { "puzzle": "2x2", "model": "", "provider": "",
    "precision": { "value": 0.5, "n": 10 }, "hallucination": { "value": null, "n": 0 },
    "critical": { "value": null, "n": 0 }, "cost": { "value": 0.01, "n": 12 } } ],
  "experiments": [ { "experimentId": "", "release": "", "puzzles": [], "models": [{ "name": "", "provider": "", "kind": "" }],
    "setups": [], "attemptsPerInput": 3, "attemptCount": 0, "firstAt": "", "lastAt": "",
    "attempts": [ { "model": "", "puzzle": "", "inputId": "", "validity": "valid", "setup": "", "attempt": 1,
      "depth": 5, "state": "", "corruption": null, "moves": [], "outcome": "", "mismatch": false } ] } ] }
```

`legalMoves` holds, for every puzzle in the exported attempts, the list from that puzzle's engine `legal_moves()` (`src.puzzles.registry.get_engine`). The page passes it to the player, which uses it to find the first impossible move of an attempt. No move list exists in `site/`, so invariant 14 holds.

An attempt's `outcome`, `mismatch`, and `moves` come from the scoring above (`outcome`, `mismatch`, `parsed_moves`), so the player agrees with the charts.

`metrics` is built by `src/site/metrics.py`: one row per puzzle and AI model, sorted by puzzle then model, pooled over every setup, depth, and experiment. `provider` is the first provider other than `unknown` in the experiments' `[[models]]`. With `everything` the group's scored rows and `rows` those whose outcome is not `infrastructure_failure`, every `value` is null when it is n/a, and `n` is its denominator:

1. `precision`: [balanced precision](../definitions.md#metrics) over the classified answers of `rows`. `n` is the number of classified answers.
2. `hallucination`: the [hallucination rate](../definitions.md#metrics), over the rows that gave moves. Null, with `n` 0, when none did and when every row is a decision-model row.
3. `critical`: [critical thinking](../definitions.md#metrics), over the rows from releases with mismatch reasons only. Null when either validity label has none of them. `n` is the number of those rows.
4. `cost`: [cost efficiency](../definitions.md#metrics), the mean cost over `everything` divided by balanced precision times coverage. Null when balanced precision or coverage is null or their product is 0. `n` is the number of rows in `everything`.

It prints one line: experiments, attempts, skipped.

## Rules

1. Experiments are sorted by id. Attempts are sorted by model, puzzle, input id, setup, attempt number, and creation time.
2. Attempts with outcome `infrastructure_failure` are dropped from `experiments`, but count in `cost`.
3. A model absent from `[[models]]` gets provider and kind `unknown`.
4. An experiment folder with no raw file is skipped with one stderr line and does not fail the export. One whose records are all infrastructure failures gets no entry in `experiments`, with one stderr line, but its rows still count in `metrics` (`cost` includes them). A missing `experiment.toml`, `release`, input file, release `manifest.json`, or price for a model is a checked error: exit 1, naming the ref and the file or experiment.
5. The skipped count in the printed line adds records whose input is not in the release and raw lines that do not parse as a record.
6. `definitions` holds the items of the `## Metrics` section matched by bold name: `precision` is "Balanced precision", `hallucination` is "Hallucination rate", `critical` is "Critical thinking", and `cost` is "Cost efficiency". Markdown is stripped to plain text. A name not found is left out, with one warning line on stderr per name.

## The page

`site/src/components/islands/benchmark/BenchmarkView.tsx` shows four metric tabs, in this order, with `precision` the default (a `#metric=` value that is not one of the four falls back to it, except that the old id `detection` means `critical`):

1. Precision (`precision`), a percentage, higher is better.
2. Hallucination rate (`hallucination`), a percentage, lower is better.
3. Critical thinking (`critical`), a percentage, higher is better.
4. Cost efficiency (`cost`), USD per right answer, lower is better.

A percentage bar runs on a fixed 0 to 100% scale. A cost reads `$0.0123` (four decimals, two from $1 up), and its bar is as wide as its share of the largest cost shown. A null value reads `n/a` and has no bar. Best and worst are ranked on the text shown. On a narrow screen the tablist scrolls sideways, its scrollbar hidden and its tabs unwrapped, and a "?" button follows its tab, hiding when the tab is scrolled out of the tablist, which also closes its open definition. Selecting a tab scrolls the tablist, never the page, until the tab is fully shown.

## Build and publish

After the export, `npm ci && npm run build` in `site/` builds the static page. Publishing is the manual `workflow_dispatch` workflow `.github/workflows/pages.yml`, which runs the export with `--ref origin/main`, builds, and deploys `site/dist` to GitHub Pages. The export fetches `main` itself. The workflow reads data and `config/site.toml` from `origin/main`, so dispatch it from `main`. It has no other trigger while the repo is private.

## Test

`tests/test_site.py` builds a throwaway git repo with a main commit that holds the releases and the results under `results/<id>/`, and covers discovery and the skipped folder, attempt fields, order, and re-validated outcomes, `legalMoves`, dropped and skipped records, each metric with its null cases, decision models, the prices fallback, provider `unknown`, and the definitions parser. Run `pytest tests/test_site.py`.
