# site

`src/site/export.py`, `src/site/metrics.py`, `config/site.toml`, `site/`, and `.github/workflows/pages.yml`. Exports the data for the public results page and builds and publishes it from `site/`. The files under `site/src/components/islands/` and `site/src/lib/benchmark.ts` are ported from the personal site, and `site/src/lib/types.ts` holds the types they use. Terms are defined in [definitions.md](../definitions.md).

## Inputs

1. `config/site.toml` at `--ref` (default `origin/main`): `title`, `description`, `intro`, and `min_release`, a release version (a missing or malformed field is a checked error). Only experiments whose `experiment.toml` release is at least `min_release` are shown.
2. `docs/definitions.md` at `--ref`.
3. Every experiment with at least one `raw/*.jsonl` file, found as a `results/<id>/` folder at `--ref` or as a `<remote>/results/<id>` branch (`--remote`, default `origin`). When both exist for one id, the branch wins, as in the UI architecture rule 1 of AGENTS.md. Its `experiment.toml`, raw files, and `results/<id>/prices.toml` are read from the folder at `--ref` or from the branch ref. The `releases/<experiment release>/inputs.jsonl` and `manifest.json`, and the fallback `config/prices.toml` (the same order `evaluate` uses, checked by `src.config.check_prices_table`), are always read at `--ref`. A folder or branch without a raw file is skipped with one stderr line naming it.

The script first runs `git fetch --prune <remote>` (`--remote`, default `origin`) with the refspecs `+refs/heads/main:refs/remotes/<remote>/main` and `+refs/heads/results/*:refs/remotes/<remote>/results/*` in one call and a 60 second timeout, so `<remote>/main` and the result branches are current, unless `--no-fetch` is given. It reads git objects only, never the work tree.

## Scoring

Every raw record is scored again by the assessment in this checkout, whatever release made it: `make_attempt_rows` from `src/evaluate/metrics.py` is called on the records, the inputs of the experiment's release, the prices, the config's decision models (providers in `DECISION_PROVIDERS`), and whether the release's manifest has `mismatch_reasons` (false when absent). `load_release` is not called, because it refuses a release whose assessment differs from the current one, which is expected here. A record whose input is not in the release's `inputs.jsonl` is not scored and is counted as skipped.

## Output

`--out` (default `site/.data/site.json`), one JSON file:

```json
{ "page": { "title": "", "description": "", "intro": "" },
  "legalMoves": { "2x2": [] },
  "prompts": { "3.0.0/no_model/v1": "the exact prompt text" },
  "definitions": [ { "key": "precision", "name": "Balanced precision", "definition": "" } ],
  "metrics": [ { "puzzle": "2x2", "model": "", "provider": "",
    "precision": { "value": 0.5, "n": 10 }, "hallucination": { "value": null, "n": 0 },
    "critical": { "value": null, "n": 0 }, "cost": { "value": 0.01, "n": 12 } } ],
  "experiments": [ { "experimentId": "", "release": "", "branch": "main", "puzzles": [], "models": [{ "name": "", "provider": "", "kind": "" }],
    "setups": [], "attemptsPerInput": 3, "attemptCount": 0, "firstAt": "", "lastAt": "",
    "attempts": [ { "model": "", "puzzle": "", "inputId": "", "validity": "valid", "setup": "", "attempt": 1,
      "depth": 5, "state": "", "corruption": null, "moves": [], "outcome": "", "mismatch": false } ] } ] }
```

`legalMoves` holds, for every puzzle in the exported attempts, the list from that puzzle's engine `legal_moves()` (`src.puzzles.registry.get_engine`). The page passes it to the player, which uses it to find the first impossible move of an attempt. No move list exists in `site/`, so invariant 14 holds.

`prompts` holds the exact prompt each attempt's AI model received, once per release, setup, and input id (the key is `<release>/<setup>/<input id>`, so repeated attempts and experiments on one release share one entry). The text is `build_prompt` from `src/run/prompts.py`, filled from the input record of the experiment's release and the template `releases/<release>/prompts/<setup>/<puzzle>.txt`, both read through git at `--ref` and never from the work tree (the templates go into a temporary directory first). A template that is missing or invalid leaves its prompts out, with one stderr line. A decision model's first call receives this prompt followed by its move history, so the entry is the part of its request that is the same for every input. `prompts` is not part of the data the index page inlines: `site/src/pages/attempts.json.ts` serves it with the attempts.

`branch` is `main` for an experiment read from the folder at `--ref`, and `results/<id>` for one read from its branch. The page uses it to link an attempt's raw results.

An attempt's `outcome`, `mismatch`, and `moves` come from the scoring above (`outcome`, `mismatch`, `parsed_moves`), so the player agrees with the charts.

`metrics` is built by `src/site/metrics.py`: one row per puzzle and AI model, sorted by puzzle then model, pooled over every setup, depth, and experiment, followed by one row per AI model, sorted by model, with `"puzzle": "all"`, pooled the same way and over every puzzle too. The four metrics follow the same rules on the pooled rows. `provider` is the first provider other than `unknown` in the experiments' `[[models]]`. With `everything` the group's scored rows and `rows` those whose outcome is not `infrastructure_failure`, every `value` is null when it is n/a, and `n` is its denominator:

1. `precision`: [balanced precision](../definitions.md#metrics) over the classified answers of `rows`. `n` is the number of classified answers.
2. `hallucination`: the [hallucination rate](../definitions.md#metrics), over the rows that gave moves. Null, with `n` 0, when none did and when every row is a decision-model row.
3. `critical`: [critical thinking](../definitions.md#metrics), over the rows from releases with mismatch reasons only. Null when either validity label has none of them. `n` is the number of those rows.
4. `cost`: [cost efficiency](../definitions.md#metrics), the mean cost over `everything` divided by balanced precision. Coverage is not in it. Null when balanced precision is null or 0. `n` is the number of rows in `everything`.

It prints one line: experiments, attempts, skipped.

## Rules

1. Experiments are sorted by id. Attempts are sorted by model, puzzle, input id, setup, attempt number, and creation time.
2. An experiment whose release is below `min_release` is skipped with one stderr line naming it and its release. It adds nothing to `experiments` or `metrics`.
3. Attempts with outcome `infrastructure_failure` are dropped from `experiments`, but count in `cost`.
4. A model absent from `[[models]]` gets provider and kind `unknown`.
5. An experiment folder or branch with no raw file is skipped with one stderr line and does not fail the export. One whose records are all infrastructure failures gets no entry in `experiments`, with one stderr line, but its rows still count in `metrics` (`cost` includes them). A missing `experiment.toml`, `release`, input file, release `manifest.json`, or price for a model is a checked error: exit 1, naming the ref and the file or experiment.
6. The skipped count in the printed line adds records whose input is not in the release and raw lines that do not parse as a record.
7. `definitions` holds the items of the `## Metrics` section matched by bold name: `precision` is "Balanced precision", `hallucination` is "Hallucination rate", `critical` is "Critical thinking", and `cost` is "Cost efficiency". Markdown is stripped to plain text. A name not found is left out, with one warning line on stderr per name.
8. `attempts.json` is `{ "attempts": { "<puzzle>": [...] }, "prompts": {...} }`. Each attempt there has `prompt`, the key of its entry in `prompts`, when the export built one. `prompts` holds only the entries those attempts point at.

## The page

The Puzzle filter has "All" as its first option and its default (accessible name "All puzzles"), drawn by `OneCube.tsx` as a 1x1x1 cube, one sticker per face, in the style of the other puzzle thumbnails. Under All, the chart reads the `metrics` rows with puzzle `all`, the Model and AI provider filters list every model and provider, and the Experiment Example picks an attempt of any puzzle and draws that attempt's own puzzle. The hash writes `puzzle=` only for a puzzle other than All, so the plain page has none; `puzzle=all` and any unknown value read as All. Without `all` rows in the data, the first puzzle with data is the default and there is no All option.

`site/src/components/islands/benchmark/BenchmarkView.tsx` shows four metric tabs, in this order, with `precision` the default (a `#metric=` value that is not one of the four falls back to it, except that the old id `detection` means `critical`):

1. Precision (`precision`), a percentage, higher is better.
2. Hallucination rate (`hallucination`), a percentage, lower is better.
3. Critical thinking (`critical`), a percentage, higher is better.
4. Cost efficiency (`cost`), USD per attempt divided by balanced precision, lower is better.

A percentage bar runs on a fixed 0 to 100% scale. A cost reads `$0.0123` (four decimals, two from $1 up), and its bar is as wide as its share of the largest cost shown. A null value reads `n/a` and has no bar. Best and worst are ranked on the text shown. On a narrow screen the tablist scrolls sideways, its scrollbar hidden and its tabs unwrapped, and a "?" button follows its tab, hiding when the tab is scrolled out of the tablist, which also closes its open definition. Selecting a tab scrolls the tablist, never the page, until the tab is fully shown.

The Experiment Example (`Player.tsx`) shows State, Model, and Result. In the Model line, "Prompt" is a button styled the same way. It opens a popover with the exact prompt the AI model received for that attempt, in a monospace, pre-wrapped box that scrolls past a maximum height and fits a 390px phone. An attempt without a prompt has no button. The prompts come from `attempts.json`, not from the page data. In the State line of an unsolvable input, "not solvable" is a button styled as text with a dashed underline. It opens a popover with one or two plain sentences on why legal moves can't reach the state, chosen by the corruption type (the first two words of the corruption description): `twisted corner`, `flipped edge`, `flipped wing`, `swapped corners`, `swapped edges`, or `recoloured sticker`. Any other type gets a generic sentence. A popover toggles on a click of its button, closes on Escape (focus returns to the button) or a click outside, only one is open at a time, and the button has `aria-expanded` and `aria-controls`.

## Build and publish

After the export, `npm ci && npm run build` in `site/` builds the static page. Publishing is the manual `workflow_dispatch` workflow `.github/workflows/pages.yml`, which runs the export with `--ref origin/main`, builds, and deploys `site/dist` to GitHub Pages. The export fetches `main` itself. The workflow reads data and `config/site.toml` from `origin/main`, so dispatch it from `main`. It has no other trigger while the repo is private.

## Test

`tests/test_site.py` builds a throwaway git repo with a main commit that holds the releases and the results under `results/<id>/`, and remote-tracking branches `origin/results/<id>` made by `git update-ref`, and covers the prompt export (the exact text for a template, one entry per release, setup, and input id however many attempts and experiments, a missing template), discovery, the skipped folder, a branch-only experiment, a branch overriding a folder, `--remote`, `min_release` (skipped and missing), attempt fields, order, and re-validated outcomes, `legalMoves`, dropped and skipped records, each metric with its null cases, decision models, the prices fallback, provider `unknown`, and the definitions parser. Run `pytest tests/test_site.py`.
