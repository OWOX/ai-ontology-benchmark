# ui

Files: `ui/server.py`, `ui/app.py`, `ui/experiments.py`, `ui/jobs.py`, `ui/commit.py`, `ui/project.py`, `ui/secrets.py`, `ui/common.py`, `ui/tomlw.py`, `ui/replay.py`, `ui/static/index.html`, `ui/static/app.js`, `ui/static/cube.js`, `ui/static/style.css`, `ui/start.sh`, `config/models.toml`.

Start: `./ui/start.sh` changes to the repo root, creates `.venv` with `python3 -m venv` (3.11 or later) and runs `pip install -e '.[test]'` only when `.venv` is missing, then runs `python -m ui.server` with its arguments, adding `--port 7991` unless they include `--port`. Before that it stops any process listening on that port: SIGTERM first, so a UI server stops its jobs, then SIGKILL for whatever still listens after 5 seconds. Later updates go through the Install button.

## Purpose

A local web page that runs one [experiment](../definitions.md#releases-and-experiments) end to end: pick puzzles and AI models, set the parameters, watch every attempt land, score it, and open a pull request with the results. The page starts the existing scripts as subprocesses and reads the files they write. It adds no logic to them.

The UI may run `release` (which calls `generate` for a major bump) on a branch other than `main`, and never runs `generate` on its own. It never edits anything in `releases/`, `prompts/`, or `results/<id>/raw/`, and never writes to `main`. It writes exactly one kind of file itself: `config/experiments/<id>.toml`.

## Start

```
python -m ui.server [--port 8765] [--root .] [--lan | --no-lan] [--allow-host NAME]
```

`--lan` is the default. It binds to `0.0.0.0` and serves every peer address, but only a `Host` that is an IP literal (IPv4, or IPv6 in brackets) or a name given with `--allow-host NAME` (repeatable, compared case-insensitively and without a trailing dot), each with any port or none, or `localhost` with the server's port. A router proxy may send its IP or its name with no port, or with `:443` or `:80`, so these need no port match. Any other `Host` gets 403 with a message that echoes the header (at most 100 characters) and says to add the name with `--allow-host`. On start it prints the loopback URL, one URL for this machine's primary LAN address from a UDP probe (in any range, not only private ones), and the line "Open to every client: anyone who can reach this port can run experiments on your API keys (use --no-lan for this machine only)", preceded by the allowed host names when there are any. `--no-lan` binds to `127.0.0.1`, serves only peers in `127.0.0.0/8` and `Host` headers of `localhost:<port>` or `127.x.x.x:<port>`, and prints only the loopback URL. With `--no-lan`, a peer outside `127.0.0.0/8` is dropped before its request is read. An idle connection times out after 30 seconds. `--root` is the repo root, for tests. A restart binds at once, even while old connections are closing. It exits with code 1 if another server answers on `127.0.0.1:<port>` (checked before binding, because macOS lets a `0.0.0.0` and a `127.0.0.1` server share a port), or if `--root` has no `releases/` folder.

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
4. API keys, one provider each for `src.run.models.KEY_VARIABLES`. A key is stored in `secrets/<provider>.json` as `{"api_key": "..."}`. The folder has mode 0700 and each file 0600, written atomically (a temp file in the folder, then replace). Saving overwrites the file and keeps no copy, and clearing deletes it. The server merges the saved keys under `os.environ`, so a real env var wins and the file is then ignored. An env var that is set but empty counts as unset. The merged env goes to subprocesses only. The page gets only whether a key is set, where it comes from (`env`, `file`, or `missing`), and its last 4 characters, never a whole key. A model whose provider key is missing is shown disabled with the reason "no API key: add it in Setup". The `fake` provider needs no key. There is no `.env` support. Terminal users export the variables themselves.

## Security

1. At start the server makes a token with `secrets.token_urlsafe(24)` and writes it into `index.html` as `<meta name="ui-token" content="...">`.
2. The default mode (`--lan`) has no network restriction: every peer address is accepted, so the server can sit behind a router's public name or proxy. It still checks `Host`, to stop DNS rebinding: a web page the owner visits can point its own hostname at this server and read the page and its token. A rebinding attack always uses a hostname, so IP literals and names passed with `--allow-host` (each with any port or none) and `localhost` (with the server's port) are the only accepted `Host` values.
3. Warning: in the default mode, anyone who can reach the port and sends an accepted `Host` gets the token, because the server puts it in the page it serves to every client that loads it. That client can start paid runs, use the saved API keys, and push. The traffic is plain HTTP, so anyone who can watch the network can read the token and any API key sent through the page. Use `--no-lan` to restrict the server to this machine. With `--no-lan`, every request from a peer outside `127.0.0.0/8` gets 403, and so does every request whose `Host` header is not `localhost:<port>` or `<ip>:<port>`, where `<ip>` is a literal address in `127.0.0.0/8`. An IPv4-mapped IPv6 peer counts as its IPv4 address. Hostnames are refused, which stops DNS rebinding.
4. Every `POST` without the header `X-Token: <token>` gets 403. So does every `GET /api/commit/<id>`, because the preview runs `git fetch`, and `GET /api/secrets`.
5. Static files come from an allowlist: `/` serves `index.html`, and `/static/app.js`, `/static/cube.js`, and `/static/style.css`. Any other path gets 404. Nothing outside `ui/static/` is ever served, so `secrets/` can't be reached.
6. A `POST` body is JSON of at most 64 KiB, or 400.

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
   5. Checked first: a job of the id is alive: 409, "a job of experiment <id> is running; stop it first", because `run` re-reads the config bytes after loading them. Nothing is written.
   6. Any other difference once `results/<id>/experiment.toml` exists: 409, "experiment <id> exists with a different config; load it or pick a new id". Nothing is written.

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
12. `GET /api/secrets` returns `{"<provider>": {"variable": "ANTHROPIC_API_KEY", "configured": true, "tail": "ab12", "source": "env" | "file" | "missing", "location": "secrets/anthropic.json" | "env var ANTHROPIC_API_KEY" | null}}` for each provider. `POST /api/secrets {"provider", "action": "save" | "clear", "api_key"}` saves a stripped key or deletes the file, and returns the same listing. An empty key, or one with whitespace inside, gives 400 naming `api_key`. Both need the token.

Project jobs belong to no experiment and use the id `""`. Their names are `install`, `tests`, `release`, and `push`. Each is echoed to the terminal like the others.

13. `GET /api/project` needs no token. It returns `{"branch", "clean", "latest_release", "python", "packages": {"anthropic": true, "openai": true, "google-genai": true, "pytest": true}, "gh": true}`. `branch` is `git rev-parse --abbrev-ref HEAD`, `clean` is true when `git status --porcelain` is empty, `latest_release` is `src.release.release.latest_version`, each package is checked with `importlib.util.find_spec` and never imported, and `gh` is whether the `gh` binary is found.
14. `POST /api/install` starts `python -u -m pip install -e .[test]`, with `.[test]` as one argument.
15. `POST /api/tests` starts `python -u -m pytest -q -p no:cacheprovider`.
16. `POST /api/release {"bump", "note"}` starts `python -u -m src.release.release --bump <bump> --note <note>`. A `bump` that is not `major`, `minor`, or `patch`, or a blank `note`, gives 400.
17. `POST /api/push` runs `git push -u origin <branch>`, then `git push origin <tag>...` for the `release-*` tags reachable from the branch (`git tag --merged <branch> --list 'release-*'`; skipped when there are none), then finds the open pull request with `gh pr view` or makes one with `gh pr create --base main --head <branch> --fill`, and returns `{"branch", "pr_url"}`. It adds no attribution. It runs inline, like commit.
18. `POST /api/dry-run {"id"}` starts `python -u -m src.run.run --experiment <id> --dry-run`.
19. Release and push give 409 when the branch is `main` or HEAD is detached. Install, release, and push give 409 while any job of any experiment, or any project job, is running, and while one of them runs every other job gives 409. Release also gives 409, naming up to 10 paths, when `git status --porcelain` is not empty. `tests` and `dry-run` give 409 only while the same job is running.

20. `GET /api/replay/<id>?model=<name>&input_id=<id>&setup=<setup>&attempt=<n>` needs no token, like `/api/state`. It plays one attempt's moves on its input and returns every state on the way:

    ```json
    {"input_id": "2x2-d5-001", "puzzle": "2x2", "outcome": "hallucination", "moves": ["R", "U'", "X"],
     "frames": ["<state 0>", "<after move 1>", "<after move 2>"], "stopped_at": 2, "solved": false}
    ```

    The record is the one in `results/<id>/raw/<model>.jsonl`, read with `src.run.raw.read_raw`, with that `input_id`, `setup`, and `attempt_number`. `moves` is its `parsed_moves`, empty for `malformed_output` and `infrastructure_failure`. `frames[0]` is the input's state from the experiment's release. Each next frame is the engine's `apply_move` of the next move. A move that is not in `legal_moves()` (exact string match) stops the replay: `stopped_at` is its index, and it and every later move get no frame. Otherwise `stopped_at` is `null`. `solved` is `is_solved` of the last frame when the replay did not stop and at least one move was applied, else false, and is for display only: `outcome` is always the record's own. A puzzle with no engine in the registry gives one frame. A missing or malformed `model`, `input_id`, `setup`, or `attempt` gives 400 naming the query field. An unknown experiment, a model outside the experiment, an unknown input, or no matching record gives 404. The move group is never sent to the page: the page only draws the frames.

Job names are `run:<model>`, `estimate`, `dry-run`, `evaluate`, and `commit`, plus the project jobs above. Every job runs with `cwd` at the root and the merged env from Inputs 4. The registry keys a job by experiment id and name, so a job that belongs to no experiment can use the id `""`.

## Polling

1. Snapshot. The page loads `GET /api/state/<id>` on load, and again every 1.5 seconds while any job of that experiment is alive. The poll that sees the last job end is the final one. With no job alive it loads once and stops.
2. Log. The page polls `GET /api/log?after=<seq>` every second while any job is alive and every 5 seconds otherwise.
3. In-progress attempt. For each model with a running `run:<model>` job, the page marks the first attempt with no record, in the loop order of [run.md](run.md#outputs): input in release order, then setup, then attempt number. It is an inference, as `run` doesn't report the attempt it is on.

## Commit

The commit never touches the working tree, the index, or `HEAD`:

1. `git fetch origin main`, then `git fetch origin results/<id>`. The parent is `origin/results/<id>` if that fetch succeeds, else `origin/main`. [run](run.md#outputs) commits to the local branch `results/<id>` as it goes, so if that branch exists and the remote branch is missing or an ancestor of it, the parent is the local branch instead. If the local branch is an ancestor of the remote one, the preview moves it forward to the remote branch. The local branch is then "ahead" when the remote branch is missing or differs from it.
2. With `GIT_INDEX_FILE` set to a temporary file: `git read-tree <parent>`, then `git add -- config/experiments/<id>.toml results/<id>`, then `git write-tree`. Only those two paths are ever added, with `--ignore-removal` so a file already on the branch is never dropped, and without the temporary copies `.experiment.toml.*.tmp`.
3. Preview: the files are `git diff --name-only <parent> <tree>`, and the diffstat is `git diff --stat <parent> <tree>`. No files, no branch on the remote, and no local commits ahead means 409 "nothing to commit".
4. Commit, in this order, so a failure at any step can be run again: `git commit-tree <tree> -p <parent> -m "Results: experiment <id>"`, then `git push origin <commit>:refs/heads/results/<id>`, and only after the push succeeds `git update-ref refs/heads/results/<id> <commit>`. With no files but a branch already on the remote, there is no new commit and the step goes straight to the pull request. With no files but local commits ahead, there is no new commit either: the step pushes the local branch, then goes to the pull request.
5. Pull request: if `gh pr view results/<id> --json url,state` finds one whose state is `OPEN`, return its URL. A closed or merged pull request doesn't count. With no files, nothing ahead, and an open pull request, 409 "nothing to commit". Else `gh pr create --base main --head results/<id> --title "Results: experiment <id>" --body "<body>"`. The body lists the release, puzzles, models, attempts, and a link to the report path. It carries no attribution line.
6. The `gh` binary is `$UI_GH` if set, else `gh`, so tests can stub it.

Every git and gh command is echoed to the terminal as a `commit` job.

## Page

Two columns. The left column holds seven numbered steps. The right column is the terminal, sticky to the viewport height. Each step header ends with a grey "?" help button in its top-right corner whose tooltip, which opens towards the left and shows on hover or keyboard focus, says in plain words what the step is for and what its controls do. The texts sit in `index.html`.

The number and title of each step form a button that folds the step to its header and unfolds it again; a triangle after the title shows the state, and `aria-expanded` carries it. The Setup step starts folded when every provider has a key, from a file or an env var. That check runs once, when the page loads. In every step, everything after the title is indented by the width of the number badge plus its gap (28 px, from two CSS variables), so the content lines up with the title text. The Cube panel and the banners count as content.

1. Setup. One row per provider, with its status and the controls for the key's source. With no key (`missing`), the status is `No key`, with a password field and Save. With a key saved in a file, the status is `Key …abcd from secrets/anthropic.json`, with Edit and Clear (after `confirm()`) and no field. Edit shows the password field, Save, and Cancel. Save stores the key and returns the row to the status view, and Cancel returns it without saving. With a key from an env var, the status is `Set by env var ANTHROPIC_API_KEY` and the row has no Edit, field, or Clear. Under the rows a note says "Keys are stored in ./secrets/ (one file per provider), which is .gitignored and never committed." Save and Clear reload the secrets panel and the catalogue, so models enable. The password field is cleared after Save and after Cancel, and a key is never shown. Below the rows are the project status from `/api/project` (branch, clean tree, packages, `gh`) and the buttons Install dependencies and Run tests. Errors show the server's text in the step's message line.
2. Shapes. A release picker (default latest), then one `<button aria-pressed>` card per puzzle in that release: the puzzle name, its input count, and, for an `NxN` name only, an SVG cube net in solved colours with `n` taken from the name. Any other puzzle shows its name with no net. Click toggles selection. At least one is needed.
3. Models. Grouped by provider in the order anthropic, openai, google, fake. The group header is the provider name alone, with no badge or logo. When a provider has no key, the header also shows "no API key: add it in Setup" once, and its models are disabled with no per-model text. Other disabled reasons, such as a missing price, show beside the model.
4. Parameters. Experiment id (default `ui-YYYYMMDD-HHMMSS`, editable, with a "Load existing" button that fills the form from `GET /api/experiment/<id>`), attempts (labelled "Attempts per input and setup: sends the same input N times"), retry cap, max output tokens, the three budgets, and "Limit per model" (optional). Buttons: Estimate, Dry run, Run, Stop. Run first posts the form to `/api/experiment`, then calls `/api/run`.
5. Progress. A Cube panel, then a legend, then one accordion per model, inside it one per puzzle, inside that one row per input. Headers show done/total and a count per outcome. Each row has a ring SVG split into `3 × attempts` arcs, in setup order then attempt order, with the input's cube net inside the ring, the input id, the depth, and the validity. Rows render when their accordion first opens. Hovering an arc shows setup, attempt, outcome, and, on invalid inputs, mismatch. A later snapshot only adds records, so open accordions stay open.
6. Evaluate and commit. An optional "Score under release" select lists every release, and its default, "experiment's release", sends `release: null`. Evaluate runs the evaluate job and then shows the report path. Commit opens a dialog with the preview's branch, files, and diffstat, and Confirm calls `POST /api/commit` and shows the PR link. Commit is disabled while any job is alive or before the report exists.
7. Release. A bump select, a note field, and a Release button, then "Push and open PR". The step shows the latest release and the branch. Release is disabled, with the reason beside it, on `main` ("on main"), on a detached HEAD ("detached HEAD"), and with a dirty tree ("working tree has changes: commit them first"). Push is disabled on `main` and on a detached HEAD. Both are also disabled while any job runs. The server enforces all of this. When an install, release, or push job ends, the page reloads the project status, the catalogue, and the release lists.

Cube panel: the first thing in the Progress step. The 3D view (`cubeIso`) is on the left and the net (`cubeNet`) of the same frame is on the right, always both. Below them are the move list, with the current move highlighted and an impossible move in the hallucination colour, and then the outcome, the input id, the setup, and the attempt number. The page never holds the move group: it draws the `frames` of `GET /api/replay/<id>`.

1. Controls: Play/Pause, Step back, Step forward, and a speed select of 0.5x, 1x, 2x, and 4x, where 1x is 300 ms per move. A frame that follows a move highlights the face named by the move's first letter. Play at the last frame starts again from the first.
2. Live mode is on by default. When a record lands in a snapshot taken during a run, the panel loads its replay and plays it. Records already there when the experiment loads are not replayed. The queue holds one record: while a replay plays, or during the pause after it, only the newest unplayed record of the followed AI model waits, and an older waiting one is dropped. When the playback ends, the panel pauses for about 600 ms and then plays the queued record, so a replay is never cut off by a newer record. While an attempt is in flight with no newer record, the panel shows that attempt's input and a slow pulse, with the text "waiting for <model>". The in-flight attempt is the page's own inference ([Polling](#polling)). When no job of the followed AI model is running, the waiting state clears and the panel shows the last replay, or stays empty. Changing the model, turning Live off, or clicking an arc drops the queue and any load still in flight. A replay error shows in the panel's own line, not in the form message. With more than one AI model, a model select picks which one the panel follows.
3. Clicking an arc that has a record replays that attempt and turns Live off. The Live toggle turns it back on.
4. A puzzle that is not an `NxN` cube, or one with no engine in the registry, shows "no drawing for <puzzle>" or a single frame.
5. With `prefers-reduced-motion`, the pulse and the face highlight flash are off, and playback only steps. The thicker outline on the turned face stays, because it is static.

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

Cube net: a state is `6·n·n` characters over `URFDLB`, faces in that order, each face row-major. The net puts U above F, L, F, R, and B in a row, and D below F. Sticker colours: U white, R red, F green, D yellow, L orange, B blue. These colours live in `cube.js` only, and `app.js` uses them, so the table is never copied. `cube.js` loads before `app.js` and holds the sticker colours, `svg()`, `cubeNet`, and `cubeIso`.

Cube 3D view: `cubeIso(state, n, highlightFace)` draws the U face on top, F front-left, and R front-right, each as an `n × n` grid of parallelograms in the net's colours. Sticker order follows the state's reading convention ([cube.md](cube.md)): U is read from above with B at the top, so its first row is the back row, and F and R are read with U at the top, with R's first column next to F. The placement uses `READING` and `NORMAL` of `src/puzzles/cube.py` for U, F, and R as drawing geometry only. `highlightFace` draws that face's outline thicker, and a face the view does not show (D, L, B) is not outlined.

Banners: a job in state `failed` shows its last stderr line. The line comes from the log poll and the state from the snapshot poll, and either can arrive first, so each log poll that brings a stderr line redraws the banners. A job in state `budget` shows "Budget reached" and a plain note to raise the budget under Parameters and press Run. Running again posts the form, which the server accepts as `budget_updated`, and resumes. The banner notes that parallel AI models can each pass the experiment budget by one worst-case request, and that "attempts left" in the message counts one AI model's attempts.

## How to test

`tests/test_ui.py`, with temporary folders, the `fake` provider, and no network. The server is started on port 0 in a thread.

1. Keys: file modes, no backup copy, a real env var winning, an empty env var losing to a saved key, and only the last 4 characters in any `GET` body. Every secrets route needs the token.
2. The catalogue marks a model with no price, and a model with no key, as disabled, with the reasons above.
3. `POST /api/experiment` for each of `created`, `unchanged`, `budget_updated`, and 409. On 409 the file is byte-identical afterwards.
4. `updated` while `results/<id>/experiment.toml` is missing, and a config without `puzzles` comparing equal to the same choice made on the page.
5. A config the server writes loads with `load_experiment_config` and holds `puzzles`.
6. A POST without the token gets 403, whatever its `Host`. `GET /static/../secrets/anthropic.json` and `GET /secrets/anthropic.json` get 404.
   1. In the default mode, `8.8.8.8:<port>`, `10.1.2.3:<port>`, `localhost:<port>`, `[::1]:<port>`, `10.0.0.11` with no port, and `10.0.0.11:443` are accepted. `evil.example`, `localhost` with no port or a wrong port, and `aiohr.dorland.keenetic.pro` are refused without `--allow-host`. With `--allow-host`, that name is accepted with no port, with `:443`, with `:80`, in any case, and with a trailing dot, and the 403 for another name echoes the header and names the option.
   2. In the default mode, `verify_request` accepts the peers `8.8.8.8` and `172.16.0.1`, and `handle_request` does not refuse a non-loopback peer. `is_loopback("::ffff:127.0.0.1")` is true and `is_loopback("not-an-ip")` is false.
   3. The start-up text holds the "Open to every client" line and the allowed host names.
   4. With `--no-lan`, a `10.0.0.5` peer and an `evil.example` `Host` are refused, and loopback is accepted.
7. The log keeps only the newest lines at the cap, and `after` returns the newer ones.
8. A full run through the API on a one-puzzle release: records appear while the run is alive, the snapshot has no `in_progress`, and the run job ends `done`.
9. Run is refused while evaluate is alive, and evaluate while a run is.
10. Stop, and stop on server shutdown: a server given SIGTERM leaves no run alive.
11. Commit against a temporary bare remote, with `UI_GH` pointing at a stub script: the branch exists on the remote with only the two paths changed, the working tree and `HEAD` are unchanged, and a second commit with no changes gives 409. Local commits ahead of the remote with an empty diff are still pushed.
12. A failed push and a failed `gh pr create` can each be run again, and only an open pull request counts.
13. Commit is refused when the report is older than a raw file.
14. Project jobs: the argv of each job, the 409 on `main` and on a detached HEAD, the blank-note 400, mutating jobs refused while any job runs, the `/api/project` shape, and push against a temporary bare remote with a stub `gh`.
15. Replay: the frames equal successive `apply_move` calls, an impossible move stops the replay at its index, malformed output gives one frame and no moves, a missing record gives 404, a bad query field gives 400 naming it, and `/static/cube.js` is served while other unknown static paths give 404.
16. Outcome colours and the in-progress inference are in `app.js` and are not tested here. `app.js` keeps the colour table in one object.
17. The cube drawing is checked by hand with `node --check` on both scripts and a throwaway node script that loads `cube.js`, draws scrambled states from a release, and compares every sticker of `cubeIso` with `cubeNet`, and the edges where U, F, and R meet.
