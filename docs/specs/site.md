# site

`src/site/export.py`, `config/site.toml`, `site/`, and `.github/workflows/pages.yml`. Exports the data for the public results page and builds and publishes it from `site/`. The files under `site/src/components/islands/` and `site/src/lib/benchmark.ts` are ported from the personal site, and `site/src/lib/types.ts` holds the three types they use. Terms are defined in [definitions.md](../definitions.md).

## Inputs

1. `config/site.toml` at `--ref` (default `origin/main`): `title`, `description`, `intro`, and `experiments`, the experiment ids shown on the page.
2. `docs/definitions.md` and `releases/<release version>/inputs.jsonl` at `--ref`.
3. For each listed experiment, `results/<id>/experiment.toml` and every `results/<id>/raw/*.jsonl` at `--ref`. Results live on `main`, not on per-experiment branches.

The script first runs `git fetch --prune <remote>` (`--remote`, default `origin`) with the refspec `+refs/heads/main:refs/remotes/<remote>/main` and a 60 second timeout, so `<remote>/main` is current, unless `--no-fetch` is given. It reads git objects only, never the work tree.

## Output

`--out` (default `site/.data/site.json`), one JSON file:

```json
{ "page": { "title": "", "description": "", "intro": "" },
  "legalMoves": { "2x2": [] },
  "definitions": [ { "key": "hallucination", "name": "Hallucination rate", "definition": "" } ],
  "experiments": [ { "experimentId": "", "release": "", "puzzles": [], "models": [{ "name": "", "provider": "", "kind": "" }],
    "setups": [], "attemptsPerInput": 3, "attemptCount": 0, "firstAt": "", "lastAt": "",
    "attempts": [ { "model": "", "puzzle": "", "inputId": "", "validity": "valid", "setup": "", "attempt": 1,
      "depth": 5, "state": "", "corruption": null, "moves": [], "outcome": "", "mismatch": false } ] } ] }
```

`legalMoves` holds, for every puzzle in the exported attempts, the list from that puzzle's engine `legal_moves()` (`src.puzzles.registry.get_engine`). The page passes it to the player, which uses it to find the first impossible move of an attempt. No move list exists in `site/`, so invariant 14 holds.

It prints one line: experiments, attempts, skipped.

## Rules

1. Experiments are sorted by id. Attempts are sorted by model, puzzle, input id, setup, attempt number, and creation time.
2. Attempts with outcome `infrastructure_failure` are dropped. A record whose input is missing from its release's `inputs.jsonl` is dropped and counted as skipped.
3. A model absent from `[[models]]` gets provider and kind `unknown`.
4. A listed experiment with no `results/<id>/` folder at the ref, or no usable raw records, is a checked error: exit 1, naming the experiment id and the ref.
5. `definitions` holds the items of the `## Metrics` section matched by bold name: `success` is "Success rate", `hallucination` is "Hallucination rate", and `detection` is "Mismatch detection rate". Markdown is stripped to plain text. A name not found is left out, with one warning line on stderr per name.
6. A duplicate experiment id in `config/site.toml` is a checked error: exit 1, naming the id.

## Build and publish

After the export, `npm ci && npm run build` in `site/` builds the static page. Publishing is the manual `workflow_dispatch` workflow `.github/workflows/pages.yml`, which runs the export with `--ref origin/main`, builds, and deploys `site/dist` to GitHub Pages. The export fetches `main` itself. The workflow reads data and `config/site.toml` from `origin/main`, so dispatch it from `main`. It has no other trigger while the repo is private.

## Test

`tests/test_site.py` builds a throwaway git repo with a main commit that holds the results under `results/<id>/`, and covers attempt fields and order, `legalMoves`, a duplicate experiment id, dropped and skipped records, provider `unknown`, a missing experiment, and the definitions parser. Run `pytest tests/test_site.py`.
