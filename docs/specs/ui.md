# ui

Files: `ui/server.py`, `ui/experiments.py`, `ui/jobs.py`, `ui/commit.py`, `ui/static/index.html`, `ui/static/app.js`, `ui/static/style.css`, `config/models.toml`.

## Purpose

A local web page that runs one [experiment](../definitions.md#releases-and-experiments) end to end: pick puzzles and AI models, set the parameters, watch every attempt land, score it, and open a pull request with the results. The page starts the existing scripts as subprocesses and reads the files they write. It adds no logic to them.

The UI never runs `generate` or `release`, never edits anything in `releases/`, `prompts/`, or `results/<id>/raw/`, and never writes to `main`. It writes exactly one kind of file itself: `config/experiments/<id>.toml`.

## Start

```
python -m ui.server [--port 8765] [--root .]
```

It binds to `127.0.0.1` only and prints the URL. `--root` is the repo root, for tests. It exits with code 1 if the port is taken or `--root` has no `releases/` folder.

The server uses `http.server.ThreadingHTTPServer` with `daemon_threads = True`. Shared job state sits behind one `threading.Lock`.

## Inputs

1. `releases/<version>/manifest.json` and `inputs.jsonl`, for the release list, each release's puzzles (`manifest["release_config"]["puzzles"]`), and input states. The default release is `src.release.release.latest_version`.
2. `config/models.toml`, the model catalogue, read by the UI only. Each entry has the same shape as a `[[models]]` entry in an experiment config, so the UI copies it unchanged:

   ```toml
   [[models]]
   name = "example-model"
   provider = "fake"
   api_model_id = "example-model-2026-01-01"
   params = { temperature = 1.0 }
   ```

3. `config/prices.toml`. A catalogue model with no price there is shown disabled with the reason "no price in config/prices.toml".
4. API keys. The server reads `.env` at the root (lines of `KEY=VALUE`, `#` comments and blank lines skipped, surrounding quotes stripped) and merges it under `os.environ`, so a real env var wins. The merged env goes to subprocesses only, never to the page. A model whose provider key (`src.run.models.KEY_VARIABLES`) is missing is shown disabled with the reason "no API key: set <VAR>". The `fake` provider needs no key.

## Security

1. At start the server makes a token with `secrets.token_urlsafe(24)` and writes it into `index.html` as `<meta name="ui-token" content="...">`.
2. Every request whose `Host` header is not `127.0.0.1:<port>` or `localhost:<port>` gets 403.
3. Every `POST` without the header `X-Token: <token>` gets 403.
4. Static files come from an allowlist: `/` serves `index.html`, and `/static/app.js` and `/static/style.css`. Any other path gets 404. Nothing outside `ui/static/` is ever served, so `.env` can't be reached.
5. A `POST` body is JSON of at most 64 KiB, or 400.

## HTTP API

Every JSON error is `{"error": "<message>"}` with a 4xx status. The message names the field at fault.

1. `GET /api/catalogue` returns:

   ```json
   {"releases": [{"version": "1.0.0", "puzzles": ["2x2", "3x3"], "input_count": 120}],
    "latest": "1.0.0",
    "models": [{"name": "...", "provider": "...", "api_model_id": "...", "params": {},
                "disabled_reason": null}],
    "defaults": {"attempts": 3, "retry_cap": 3, "max_output_tokens": 4096,
                 "budget": {"per_request_usd": 0.5, "per_model_usd": 5.0, "per_experiment_usd": 10.0}}}
   ```

   The default budgets come from the constants in `src/config.py`.
2. `GET /api/experiment/<id>` returns the existing `config/experiments/<id>.toml` as JSON (the same shape as the form below), or 404.
3. `POST /api/experiment` with the form:

   ```json
   {"id": "ui-20261018-101500", "release": "1.0.0", "puzzles": ["2x2"], "models": ["example-model"],
    "attempts": 3, "retry_cap": 3, "max_output_tokens": 4096,
    "budget": {"per_request_usd": 0.5, "per_model_usd": 5.0, "per_experiment_usd": 10.0}}
   ```

   `models` holds catalogue names. The server builds the experiment config, with `puzzles` always written, and checks it with `src.config.load_experiment_config` on a copy in a temporary folder before it touches the real file. Then:
   1. No file for that id: write it. Status `created`.
   2. A file exists and equals the new config: write nothing. Status `unchanged`.
   3. A file exists and differs only in `[budget]`: write it. Status `budget_updated`.
   4. A file exists and differs in anything else: 409, "experiment <id> exists with a different config; load it or pick a new id". Nothing is written.

   It returns `{"id": "...", "status": "..."}`. A disabled model, an unknown release, or a puzzle that isn't in the release gives 400.
4. `GET /api/state/<id>` returns the live snapshot:

   ```json
   {"id": "...", "release": "1.0.0", "setups": ["no_model", "descriptive", "prescriptive"],
    "attempts": 3, "models": ["example-model"],
    "inputs": [{"input_id": "2x2-d5-001", "puzzle": "2x2", "scramble_depth": 5,
                "validity": "valid", "state": "RUUL..."}],
    "records": [{"model": "...", "input_id": "...", "setup": "...", "attempt_number": 1,
                 "outcome": "success", "mismatch": false}],
    "in_progress": {"example-model": {"input_id": "...", "setup": "...", "attempt_number": 2}},
    "jobs": {"run:example-model": "running"},
    "report": "results/<id>/1.0.0.md"}
   ```

   `inputs` holds only the experiment's puzzles, in release order. `records` comes from `src.run.raw.read_raw` over each model's raw file. `in_progress[model]` is the first item of `src.run.run.pending_attempts(config, inputs, raw_dir, model)` while that model's run job is alive, else `null`. It is an inference: run doesn't report the attempt it is on. `report` is the report path if it exists, else `null`.
5. `POST /api/estimate {"id"}` starts `python -u -m src.run.run --experiment <id> --estimate`.
6. `POST /api/run {"id", "limit": null}` starts one run job per model of the experiment: `python -u -m src.run.run --experiment <id> --model <name>`, plus `--limit N` if `limit` is set. It starts the first model alone, waits until `results/<id>/experiment.toml` exists with the same bytes as the config (or the first job has exited, or 10 seconds pass), then starts the rest together. That stops the processes racing to write the experiment copy. A run job already alive for the id gives 409.
7. `POST /api/stop {"id"}` sends SIGINT to every live run job of the id, waits up to 10 seconds, then sends SIGTERM to any still alive. A request that is in flight when the job stops may be paid for and never recorded, so the page says to prefer `limit` for small runs.
8. `POST /api/evaluate {"id"}` starts `python -u -m src.evaluate.evaluate --experiment <id>`. 409 while a run job of the id is alive.
9. `GET /api/commit/<id>` returns the commit preview: `{"branch": "results/<id>", "base": "<sha>", "files": [...], "diffstat": "..."}`. 409 while any job of the id is alive, or before the report exists.
10. `POST /api/commit {"id"}` makes the commit and the pull request, and returns `{"branch": "...", "commit": "<sha>", "pr_url": "..."}`. The same 409 rules apply.
11. `GET /api/events` is one Server-Sent Events stream for the whole page. The page opens one `EventSource` and never more. A comment line `: keep-alive` goes out every 15 seconds. Events:
    1. `terminal`: `{"job": "run:example-model", "stream": "cmd"|"stdout"|"stderr", "text": "..."}`. The `cmd` line is the full command, sent before the process starts. Output goes out line by line.
    2. `record`: `{"id": "...", "record": {<same fields as in the snapshot>}}`, one per new raw record.
    3. `in_progress`: `{"id": "...", "model": "...", "attempt": {...} | null}`.
    4. `job`: `{"id": "...", "job": "run:<model>"|"estimate"|"evaluate"|"commit", "state": "running"|"done"|"failed"|"budget"|"stopped", "code": 0|1|null}`. `budget` means the job exited 1 with a stderr line starting `error: budget reached:`. `stopped` means the UI stopped it.

Job names are `run:<model>`, `estimate`, `evaluate`, and `commit`. Every job runs with `cwd` at the root and the merged env from Inputs 4.

## Live records

`ui/jobs.py` polls `results/<id>/raw/*.jsonl` every 0.5 seconds while any run job of the id is alive, and once more after the last one exits. It keeps a byte offset per file and reads only up to the last `\n`, so a torn line is never half-read. Each complete line is parsed as `read_raw` does: a line that isn't a JSON object is skipped. Every new record becomes a `record` event, and the model's `in_progress` is recomputed and sent.

## Commit

The commit never touches the working tree, the index, or `HEAD`:

1. `git fetch origin main`. The parent is the tip of `results/<id>` if that branch exists locally, else `origin/main`.
2. With `GIT_INDEX_FILE` set to a temporary file: `git read-tree <parent>`, then `git add -- config/experiments/<id>.toml results/<id>`, then `git write-tree`. Only those two paths are ever added.
3. Preview: the files are `git diff --name-only <parent> <tree>`, and the diffstat is `git diff --stat <parent> <tree>`. No files means 409 "nothing to commit".
4. Commit: `git commit-tree <tree> -p <parent> -m "Results: experiment <id>"`, `git update-ref refs/heads/results/<id> <commit>`, `git push -u origin results/<id>`.
5. Pull request: if `gh pr view results/<id> --json url` finds one, return its URL. Else `gh pr create --base main --head results/<id> --title "Results: experiment <id>" --body "<body>"`. The body lists the release, puzzles, models, attempts, and a link to the report path. It carries no attribution line.
6. The `gh` binary is `$UI_GH` if set, else `gh`, so tests can stub it.

Every git and gh command is echoed to the terminal as a `commit` job.

## Page

Two columns. The left column holds five numbered steps. The right column is the terminal, sticky to the viewport height.

1. Shapes. A release picker (default latest), then one card per puzzle in that release: an SVG cube net in solved colours, the puzzle name, and its input count. Click toggles selection. At least one is needed.
2. Models. Grouped by provider in the order anthropic, openai, google, fake. Each group header has a text badge: a coloured circle with the provider's initial. There are no third-party logos. Disabled models show their reason.
3. Parameters. Experiment id (default `ui-YYYYMMDD-HHMMSS`, editable, with a "Load existing" button that fills the form from `GET /api/experiment/<id>`), attempts (labelled "Attempts per input and setup: sends the same input N times"), retry cap, max output tokens, the three budgets, and "Limit per model" (optional). Buttons: Estimate, Run, Stop. Run first posts the form to `/api/experiment`, then calls `/api/run`.
4. Progress. A legend, then one accordion per model, inside it one per puzzle, inside that one row per input. Headers show done/total and a count per outcome. Each row has a ring SVG split into `3 × attempts` arcs, in setup order then attempt order, with the input's cube net inside the ring, the input id, the depth, and the validity. Rows render when their accordion first opens. Hovering an arc shows setup, attempt, outcome, and, on invalid inputs, mismatch.
5. Evaluate and commit. Evaluate runs the evaluate job and then shows the report path. Commit opens a dialog with the preview's branch, files, and diffstat, and Confirm calls `POST /api/commit` and shows the PR link. Commit is disabled while any job is alive or before the report exists.

Arc colours:

| State | Colour |
|---|---|
| pending | `#d0d4da` |
| in progress | `#f2b705`, pulsing |
| `success` | `#2e9e5b` |
| `failure` | `#d64545` |
| `hallucination` | `#8e44ad` |
| `malformed_output` | `#1a9bb0` |
| `infrastructure_failure` | `#5d6d7e` |

Cube net: a state is `6·n·n` characters over `URFDLB`, faces in that order, each face row-major. The net puts U above F, L, F, R, and B in a row, and D below F. Sticker colours: U white, R red, F green, D yellow, L orange, B blue. These colours live in `app.js` only.

Banners: a job in state `failed` shows its last stderr line. A job in state `budget` shows "Budget reached" with a "Raise budget and resume" button that scrolls to the budget fields. Running again posts the form, which the server accepts as `budget_updated`, and resumes. The banner notes that parallel AI models can each pass the experiment budget by one worst-case request, and that "attempts left" in the message counts one AI model's attempts.

## How to test

`tests/test_ui.py`, with temporary folders, the `fake` provider, and no network. The server is started on port 0 in a thread.

1. `.env` parsing: comments, blanks, quotes, and a real env var winning.
2. The catalogue marks a model with no price, and a model with no key, as disabled, with the reasons above.
3. `POST /api/experiment` for each of `created`, `unchanged`, `budget_updated`, and 409. On 409 the file is byte-identical afterwards.
4. A config the server writes loads with `load_experiment_config` and holds `puzzles`.
5. A POST without the token, or with a foreign `Host`, gets 403. `GET /static/../.env` and `GET /.env` get 404.
6. The tailer reads a file in two writes, the first ending mid-line, and gives each record once.
7. A full run through the API on a one-puzzle release: every expected record arrives as an event, `in_progress` ends `null`, and the run job ends `done`.
8. Commit against a temporary bare remote, with `UI_GH` pointing at a stub script: the branch exists on the remote with only the two paths changed, the working tree and `HEAD` are unchanged, and a second commit with no changes gives 409.
9. Outcome colours are not tested here. `app.js` keeps the colour table in one object.
