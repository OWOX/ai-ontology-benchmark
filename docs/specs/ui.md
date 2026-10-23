# ui

Files: `ui/server.py`, `ui/app.py`, `ui/experiments.py`, `ui/jobs.py`, `ui/commit.py`, `ui/project.py`, `ui/common.py`, `ui/tomlw.py`, `ui/static/index.html`, `ui/static/app.js`, `ui/static/style.css`, `config/models.toml`.

## Purpose

A local web page that runs one [experiment](../definitions.md#releases-and-experiments) end to end: pick puzzles and AI models, set the parameters, watch every attempt land, score it, and open a pull request with the results. The page starts the existing scripts as subprocesses and reads the files they write. It adds no logic to them.

The UI may run `release` (which calls `generate` for a major bump) on a branch other than `main`, and never runs `generate` on its own. It never edits anything in `releases/`, `prompts/`, or `results/<id>/raw/`, and never writes to `main`. It writes exactly one kind of file itself: `config/experiments/<id>.toml`.

## Start

```
python -m ui.server [--port 8765] [--root .]
```

It binds to `127.0.0.1` only and prints the URL. `--root` is the repo root, for tests. It exits with code 1 if the port is taken or `--root` has no `releases/` folder.

The server uses `http.server.ThreadingHTTPServer` with `daemon_threads = True`. Shared job state sits behind one `threading.Lock`.

On Ctrl-C or SIGTERM the server stops every live job the way `POST /api/stop` does (SIGINT, wait up to 10 seconds, then SIGTERM) before it exits, so no run outlives it.

The page polls. The server has no event stream.

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
4. API keys, one provider each for `src.run.models.KEY_VARIABLES`. A key is stored in `secrets/<provider>.json` as `{"api_key": "..."}`. The folder has mode 0700 and each file 0600, written atomically (a temp file in the folder, then replace). Saving over an existing key first copies the old file to `<provider>.json.bak`, and clearing deletes the file but keeps the `.bak`. The server merges the saved keys under `os.environ`, so a real env var wins and the file is then ignored. The merged env goes to subprocesses only. The page gets only whether a key is set, where it comes from (`env`, `file`, or `missing`), and its last 4 characters, never a whole key. A model whose provider key is missing is shown disabled with the reason "no API key: add it in Setup". The `fake` provider needs no key. There is no `.env` support. Terminal users export the variables themselves.

## Security

1. At start the server makes a token with `secrets.token_urlsafe(24)` and writes it into `index.html` as `<meta name="ui-token" content="...">`.
2. Every request whose `Host` header is not `127.0.0.1:<port>` or `localhost:<port>` gets 403.
3. Every `POST` without the header `X-Token: <token>` gets 403. So does every `GET /api/commit/<id>`, because the preview runs `git fetch`, and `GET /api/secrets`.
4. Static files come from an allowlist: `/` serves `index.html`, and `/static/app.js` and `/static/style.css`. Any other path gets 404. Nothing outside `ui/static/` is ever served, so `secrets/` can't be reached.
5. A `POST` body is JSON of at most 64 KiB, or 400.

## HTTP API

Every JSON error is `{"error": "<message>"}` with a 4xx status. The message names the field at fault.

1. `GET /api/catalogue` returns:

   ```json
   {"releases": [{"version": "1.0.0", "puzzles": ["2x2", "3x3"], "input_count": 120,
                  "input_counts": {"2x2": 60, "3x3": 60}}],
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
   2. A file exists and equals the new config: write nothing. Status `unchanged`. A missing `puzzles` in the file counts as every puzzle of its release, so a config made on the command line compares equal to the same choice made on the page.
   3. A file exists, differs, and `results/<id>/experiment.toml` does not exist, so nothing has run: write it. Status `updated`.
   4. A file exists, `results/<id>/experiment.toml` exists, and the config differs only in `[budget]`: write it. Status `budget_updated`.
   5. Any other difference once `results/<id>/experiment.toml` exists: 409, "experiment <id> exists with a different config; load it or pick a new id". Nothing is written.

   It returns `{"id": "...", "status": "..."}`. A disabled model, an unknown release, or a puzzle that isn't in the release gives 400.
4. `GET /api/state/<id>` returns the live snapshot:

   ```json
   {"id": "...", "release": "1.0.0", "setups": ["no_model", "descriptive", "prescriptive"],
    "attempts": 3, "models": ["example-model"],
    "inputs": [{"input_id": "2x2-d5-001", "puzzle": "2x2", "scramble_depth": 5,
                "validity": "valid", "state": "RUUL..."}],
    "records": [{"model": "...", "input_id": "...", "setup": "...", "attempt_number": 1,
                 "outcome": "success", "mismatch": false}],
    "jobs": {"run:example-model": "running"},
    "report": "results/<id>/1.0.0.md"}
   ```

   `inputs` holds only the experiment's puzzles, in release order. `records` comes from `src.run.raw.read_raw` over each model's raw file. `jobs` maps each job name of the id to its state. `report` is the report path if it exists, else `null`. The snapshot holds no in-progress attempt: the page works that out (see Polling).
5. `POST /api/estimate {"id"}` starts `python -u -m src.run.run --experiment <id> --estimate`.
6. `POST /api/run {"id", "limit": null}` starts one run job per model of the experiment, all at once: `python -u -m src.run.run --experiment <id> --model <name>`, plus `--limit N` if `limit` is set. The processes can race to write `results/<id>/experiment.toml` because `run` writes it atomically ([run.md](run.md#outputs)). A run job already alive for the id gives 409, and so does a live evaluate job.
7. `POST /api/stop {"id"}` sends SIGINT to every live run job of the id, waits up to 10 seconds, then sends SIGTERM to any still alive. A request that is in flight when the job stops may be paid for and never recorded, so the page says to prefer `limit` for small runs.
8. `POST /api/evaluate {"id", "release": null}` starts `python -u -m src.evaluate.evaluate --experiment <id>`, plus `--release <version>` if `release` is set (a bad version gives 400). 409 while a run job of the id is alive.
9. `GET /api/commit/<id>` returns the commit preview: `{"branch": "results/<id>", "base": "<sha>", "files": [...], "diffstat": "..."}`. 409 while any job of the id is alive, before the report exists, or when the report is older than any file in `results/<id>/raw/` (message "the report is older than the raw records; evaluate again first"). The age is the file modification times.
10. `POST /api/commit {"id"}` makes the commit and the pull request, and returns `{"branch": "...", "commit": "<sha>", "pr_url": "..."}`. The same 409 rules apply.
11. `GET /api/log?after=<seq>` returns the terminal lines newer than `seq` (default 0) and the job states:

    ```json
    {"lines": [{"seq": 41, "job": "run:example-model", "stream": "stdout", "text": "..."}],
     "last": 41,
     "jobs": [{"id": "t1", "job": "run:example-model", "state": "running", "code": null}]}
    ```

    The server keeps one in-memory list of lines for all jobs, at most 5,000, dropping the oldest. `stream` is `cmd`, `stdout`, or `stderr`. The `cmd` line is the full command, logged before the process starts. `seq` counts up from 1 for the life of the server. `state` is `running`, `done`, `failed`, `budget`, or `stopped`. `budget` means the job exited 1 with a stderr line starting `error: budget reached:`. `stopped` means the UI stopped it.
12. `GET /api/secrets` returns `{"<provider>": {"variable": "ANTHROPIC_API_KEY", "configured": true, "tail": "ab12", "source": "env" | "file" | "missing", "location": "secrets/anthropic.json" | "env var ANTHROPIC_API_KEY" | null}}` for each provider. `POST /api/secrets {"provider", "action": "save" | "clear", "api_key"}` saves a stripped key or deletes the file, and returns the same listing. An empty key, or one with whitespace inside, gives 400 naming `api_key`. `POST /api/secrets/import {"text"}` takes `.env`-style text, saves each known variable with a value, and returns `{"saved": ["anthropic"]}`. Text with no known variable gives 400. All three need the token.

Project jobs belong to no experiment and use the id `""`. Their names are `install`, `tests`, `release`, and `push`. Each is echoed to the terminal like the others.

13. `GET /api/project` needs no token. It returns `{"branch", "clean", "latest_release", "python", "packages": {"anthropic": true, "openai": true, "google-genai": true, "pytest": true}, "gh": true}`. `branch` is `git rev-parse --abbrev-ref HEAD`, `clean` is true when `git status --porcelain` is empty, `latest_release` is `src.release.release.latest_version`, each package is checked with `importlib.util.find_spec` and never imported, and `gh` is whether the `gh` binary is found.
14. `POST /api/install` starts `python -u -m pip install -e .[test]`, with `.[test]` as one argument.
15. `POST /api/tests` starts `python -u -m pytest -q -p no:cacheprovider`.
16. `POST /api/release {"bump", "note"}` starts `python -u -m src.release.release --bump <bump> --note <note>`. A `bump` that is not `major`, `minor`, or `patch`, or a blank `note`, gives 400.
17. `POST /api/push` runs `git push -u origin <branch>`, then `git push origin <tag>...` for the `release-*` tags reachable from the branch (`git tag --merged <branch> --list 'release-*'`; skipped when there are none), then finds the open pull request with `gh pr view` or makes one with `gh pr create --base main --head <branch> --fill`, and returns `{"branch", "pr_url"}`. It adds no attribution. It runs inline, like commit.
18. `POST /api/dry-run {"id"}` starts `python -u -m src.run.run --experiment <id> --dry-run`.
19. Release and push give 409 when the branch is `main` or HEAD is detached. Install, release, and push give 409 while any job of any experiment, or any project job, is running, and while one of them runs every other job gives 409. Release also gives 409, naming up to 10 paths, when `git status --porcelain` is not empty. `tests` and `dry-run` give 409 only while the same job is running.

Job names are `run:<model>`, `estimate`, `dry-run`, `evaluate`, and `commit`, plus the project jobs above. Every job runs with `cwd` at the root and the merged env from Inputs 4. The registry keys a job by experiment id and name, so a job that belongs to no experiment can use the id `""`.

## Polling

1. Snapshot. The page loads `GET /api/state/<id>` on load, and again every 1.5 seconds while any job of that experiment is alive. The poll that sees the last job end is the final one. With no job alive it loads once and stops.
2. Log. The page polls `GET /api/log?after=<seq>` every second while any job is alive and every 5 seconds otherwise.
3. In-progress attempt. For each model with a running `run:<model>` job, the page marks the first attempt with no record, in the loop order of [run.md](run.md#outputs): input in release order, then setup, then attempt number. It is an inference, as `run` doesn't report the attempt it is on.

## Commit

The commit never touches the working tree, the index, or `HEAD`:

1. `git fetch origin main`, then `git fetch origin results/<id>`. The parent is `origin/results/<id>` if that fetch succeeds, else `origin/main`.
2. With `GIT_INDEX_FILE` set to a temporary file: `git read-tree <parent>`, then `git add -- config/experiments/<id>.toml results/<id>`, then `git write-tree`. Only those two paths are ever added.
3. Preview: the files are `git diff --name-only <parent> <tree>`, and the diffstat is `git diff --stat <parent> <tree>`. No files and no branch on the remote means 409 "nothing to commit".
4. Commit, in this order, so a failure at any step can be run again: `git commit-tree <tree> -p <parent> -m "Results: experiment <id>"`, then `git push origin <commit>:refs/heads/results/<id>`, and only after the push succeeds `git update-ref refs/heads/results/<id> <commit>`. With no files but a branch already on the remote, there is no new commit and the step goes straight to the pull request.
5. Pull request: if `gh pr view results/<id> --json url,state` finds one whose state is `OPEN`, return its URL. A closed or merged pull request doesn't count. With no files and an open pull request, 409 "nothing to commit". Else `gh pr create --base main --head results/<id> --title "Results: experiment <id>" --body "<body>"`. The body lists the release, puzzles, models, attempts, and a link to the report path. It carries no attribution line.
6. The `gh` binary is `$UI_GH` if set, else `gh`, so tests can stub it.

Every git and gh command is echoed to the terminal as a `commit` job.

## Page

Two columns. The left column holds five numbered steps. The right column is the terminal, sticky to the viewport height.

1. Shapes. A release picker (default latest), then one `<button aria-pressed>` card per puzzle in that release: the puzzle name, its input count, and, for an `NxN` name only, an SVG cube net in solved colours with `n` taken from the name. Any other puzzle shows its name with no net. Click toggles selection. At least one is needed.
2. Models. Grouped by provider in the order anthropic, openai, google, fake. Each group header has a text badge: a coloured circle with the provider's initial. There are no third-party logos. Disabled models show their reason.
3. Parameters. Experiment id (default `ui-YYYYMMDD-HHMMSS`, editable, with a "Load existing" button that fills the form from `GET /api/experiment/<id>`), attempts (labelled "Attempts per input and setup: sends the same input N times"), retry cap, max output tokens, the three budgets, and "Limit per model" (optional). Buttons: Estimate, Run, Stop. Run first posts the form to `/api/experiment`, then calls `/api/run`.
4. Progress. A legend, then one accordion per model, inside it one per puzzle, inside that one row per input. Headers show done/total and a count per outcome. Each row has a ring SVG split into `3 × attempts` arcs, in setup order then attempt order, with the input's cube net inside the ring, the input id, the depth, and the validity. Rows render when their accordion first opens. Hovering an arc shows setup, attempt, outcome, and, on invalid inputs, mismatch. A later snapshot only adds records, so open accordions stay open.
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

Banners: a job in state `failed` shows its last stderr line. A job in state `budget` shows "Budget reached" and a plain note to raise the budget under Parameters and press Run. Running again posts the form, which the server accepts as `budget_updated`, and resumes. The banner notes that parallel AI models can each pass the experiment budget by one worst-case request, and that "attempts left" in the message counts one AI model's attempts.

## How to test

`tests/test_ui.py`, with temporary folders, the `fake` provider, and no network. The server is started on port 0 in a thread.

1. Keys: file modes, the `.bak` copy, a real env var winning, and only the last 4 characters in any `GET` body. Import parses `KEY=VALUE` text (comments, blanks, `export`, quotes, unknown names ignored) and refuses text with no known key. Every secrets route needs the token.
2. The catalogue marks a model with no price, and a model with no key, as disabled, with the reasons above.
3. `POST /api/experiment` for each of `created`, `unchanged`, `budget_updated`, and 409. On 409 the file is byte-identical afterwards.
4. `updated` while `results/<id>/experiment.toml` is missing, and a config without `puzzles` comparing equal to the same choice made on the page.
5. A config the server writes loads with `load_experiment_config` and holds `puzzles`.
6. A POST without the token, or with a foreign `Host`, gets 403. `GET /static/../secrets/anthropic.json` and `GET /secrets/anthropic.json` get 404.
7. The log keeps only the newest lines at the cap, and `after` returns the newer ones.
8. A full run through the API on a one-puzzle release: records appear while the run is alive, the snapshot has no `in_progress`, and the run job ends `done`.
9. Run is refused while evaluate is alive, and evaluate while a run is.
10. Stop, and stop on server shutdown: a server given SIGTERM leaves no run alive.
11. Commit against a temporary bare remote, with `UI_GH` pointing at a stub script: the branch exists on the remote with only the two paths changed, the working tree and `HEAD` are unchanged, and a second commit with no changes gives 409.
12. A failed push and a failed `gh pr create` can each be run again, and only an open pull request counts.
13. Commit is refused when the report is older than a raw file.
14. Project jobs: the argv of each job, the 409 on `main` and on a detached HEAD, the blank-note 400, mutating jobs refused while any job runs, the `/api/project` shape, and push against a temporary bare remote with a stub `gh`.
15. Outcome colours and the in-progress inference are in `app.js` and are not tested here. `app.js` keeps the colour table in one object.
