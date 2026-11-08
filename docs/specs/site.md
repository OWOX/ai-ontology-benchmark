# site

`src/site/export.py` and `config/site.toml`. Exports the data for the public results page in `site/`. Terms are defined in [definitions.md](../definitions.md).

## Inputs

1. `config/site.toml` at `--ref` (default `origin/main`): `title`, `description`, `intro`, and `experiments`, the experiment ids shown on the page.
2. `docs/definitions.md` and `releases/<release version>/inputs.jsonl` at `--ref`.
3. For each listed experiment, the branch `<remote>/results/<experiment id>` (`--remote`, default `origin`): `results/<id>/experiment.toml` and every `results/<id>/raw/*.jsonl`.

The script first runs `git fetch --prune <remote>` with the refspecs `+refs/heads/main:refs/remotes/<remote>/main` and `+refs/heads/results/*:refs/remotes/<remote>/results/*` and a 60 second timeout, so `<remote>/main` is current and deleted results branches no longer export, unless `--no-fetch` is given. It reads git objects only, never the work tree.

## Output

`--out` (default `site/.data/site.json`), one JSON file:

```json
{ "page": { "title": "", "description": "", "intro": "" },
  "definitions": [ { "key": "hallucination", "name": "Hallucination rate", "definition": "" } ],
  "experiments": [ { "experimentId": "", "release": "", "puzzles": [], "models": [{ "name": "", "provider": "", "kind": "" }],
    "setups": [], "attemptsPerInput": 3, "attemptCount": 0, "firstAt": "", "lastAt": "",
    "attempts": [ { "model": "", "puzzle": "", "inputId": "", "validity": "valid", "setup": "", "attempt": 1,
      "depth": 5, "state": "", "corruption": null, "moves": [], "outcome": "", "mismatch": false } ] } ] }
```

It prints one line: experiments, attempts, skipped.

## Rules

1. Experiments are sorted by id. Attempts are sorted by model, puzzle, input id, setup, attempt number, and creation time.
2. Attempts with outcome `infrastructure_failure` are dropped. A record whose input is missing from its release's `inputs.jsonl` is dropped and counted as skipped.
3. A model absent from `[[models]]` gets provider and kind `unknown`.
4. A listed experiment with no branch or no usable raw records is a checked error: exit 1, naming the experiment id.
5. `definitions` holds the items of the `## Metrics` section matched by bold name: `success` is "Success rate", `hallucination` is "Hallucination rate", and `detection` is "Mismatch detection rate". Markdown is stripped to plain text. A name not found is left out, with one warning line on stderr per name.

## Build and publish

After the export, `npm ci && npm run build` in `site/` builds the static page. Publishing is the manual `workflow_dispatch` workflow `.github/workflows/pages.yml`, which fetches `main` and `results/*`, runs the export with `--ref origin/main`, builds, and deploys `site/dist` to GitHub Pages. It has no other trigger while the repo is private.

## Test

`tests/test_site.py` builds a throwaway git repo with a main commit and a results branch, and covers attempt fields and order, dropped and skipped records, provider `unknown`, a missing branch, and the definitions parser. Run `pytest tests/test_site.py`.
