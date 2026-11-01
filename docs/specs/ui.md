# ui

Files: `ui/server.py`, `ui/app.py`, `ui/gitdata.py`, `ui/bundle.py`, `ui/puzzleinfo.py`, `ui/catalogue.py`, `ui/experiments.py`, `ui/forms.py`, `ui/branches.py`, `ui/expdata.py`, `ui/pooling.py`, `ui/jobs.py`, `ui/commit.py`, `ui/project.py`, `ui/secrets.py`, `ui/common.py`, `ui/tomlw.py`, `ui/replay.py`, `ui/static/index.html`, `ui/static/router.js`, `ui/static/markdown.js`, `ui/static/cube.js`, `ui/static/progress.js`, `ui/static/progressview.js`, `ui/static/cubepanel.js`, `ui/static/expmetrics.js`, `ui/static/pages/models.js`, `ui/static/pages/puzzles.js`, `ui/static/pages/inputs.js`, `ui/static/pages/experiments.js`, `ui/static/pages/experiment.js`, `ui/static/pages/new.js`, `ui/static/pages/about.js`, `ui/static/style.css`, `ui/start.sh`.

Start: `./ui/start.sh` changes to the repo root, creates `.venv` with `python3 -m venv` (3.11 or later) and runs `pip install -e '.[test]'` only when `.venv` is missing, then runs `python -m ui.server` with its arguments, adding `--port 7991` unless they include `--port`. Before that it stops any process listening on that port: SIGTERM first, so a UI server stops its jobs, then SIGKILL for whatever still listens after 5 seconds. Later updates go through the Install button.

## Purpose

A local web page for finding your way around what the project holds on GitHub, and for starting new [experiments](../definitions.md#releases-and-experiments). A left menu leads to the AI models, the puzzles, the experiments with their metrics, and the README, all for one [release](../definitions.md#releases-and-experiments) at a time. A New Experiment screen picks puzzles and AI models, sets the parameters, runs the experiment while showing every attempt, scores it, and opens a pull request with the results. The page starts the existing scripts as subprocesses. It adds no logic to them, and computes metrics only with `src.evaluate.metrics`.

The architecture rules are in [AGENTS.md](../../AGENTS.md#architecture):

1. Git is the only source of persistent data. Everything the page shows is read from git refs with `git show` and `git ls-tree`, never by listing the work tree. The one exception is an experiment with a live job in this server, which is read from its local branch `results/<id>`.
2. `ui/` holds code only.
3. The UI process writes only `./secrets/`. Experiment data reaches git through `run`, `evaluate`, and the [commit](#commit) step, which write to the branch `results/<id>`. `run` and `evaluate` still write `results/<id>/` in the work tree, as their own specs say. The UI never writes `config/experiments/<id>.toml`. It starts `run --config -` and passes the config on stdin ([run.md](run.md#inputs)).
4. One experiment is one branch, `results/<id>`.

The UI may run `release` (which calls `generate` for a major bump) on a branch other than `main`, and never runs `generate` on its own. It never edits anything in `releases/`, `prompts/`, or `results/<id>/raw/`, and never writes to `main`.

## Start

```
python -m ui.server [--port 8765] [--root .] [--lan | --no-lan] [--allow-host NAME]
```

`--lan` is the default. It binds to `0.0.0.0` and serves every peer address, but only a `Host` that is an IP literal (IPv4, or IPv6 in brackets) or a name given with `--allow-host NAME` (repeatable, compared case-insensitively and without a trailing dot), each with any port or none, or `localhost` with the server's port. A router proxy may send its IP or its name with no port, or with `:443` or `:80`, so these need no port match. Any other `Host` gets 403 with a message that echoes the header (at most 100 characters) and says to add the name with `--allow-host`. On start it prints the loopback URL, one URL for this machine's primary LAN address from a UDP probe (in any range, not only private ones), and the line "Open to every client: anyone who can reach this port can run experiments on your API keys (use --no-lan for this machine only)", preceded by the allowed host names when there are any. `--no-lan` binds to `127.0.0.1`, serves only peers in `127.0.0.0/8` and `Host` headers of `localhost:<port>` or `127.x.x.x:<port>`, and prints only the loopback URL. With `--no-lan`, a peer outside `127.0.0.0/8` is dropped before its request is read. An idle connection times out after 30 seconds. `--root` is the repo root, for tests. A restart binds at once, even while old connections are closing. It exits with code 1 if another server answers on `127.0.0.1:<port>` (checked before binding, because macOS lets a `0.0.0.0` and a `127.0.0.1` server share a port), or if `--root` has no `releases/` folder.

The server uses `http.server.ThreadingHTTPServer` with `daemon_threads = True`. Shared job state sits behind one `threading.Lock`.

On Ctrl-C or SIGTERM the server stops every live job the way `POST /api/stop` does (SIGINT, wait up to 10 seconds, then SIGTERM) before it exits, so no run outlives it.

The page polls. The server has no event stream.

## Inputs

Every path below is read from a git ref, never from the work tree, except the API keys, the live experiments in item 7, and the work-tree checks of API 2 (`local_results`, `local_report`), 8, 12, and 13.

1. Refs. `ui/gitdata.py` runs `git fetch --prune origin main '+refs/heads/results/*:refs/remotes/origin/results/*'` with `GIT_TERMINAL_PROMPT=0` and a 60-second timeout, at most once every 30 seconds, when a bundle is built with `refresh=1` or none is in memory yet. A failed fetch is not an error: the server builds from the refs it already has and reports `fetch_error` and the time of the last good fetch. `main` means `origin/main`, or `HEAD` when the repo has no `origin`.
2. Releases: the folders `releases/<version>/` on `main` with a `manifest.json`, newest first. For each, `manifest.json`, `inputs.jsonl`, and `prompts/<setup>/<puzzle>.txt`. The default release is the newest.
3. The model catalogue, `config/models.toml` on `main`, read by the UI only. Each entry has the same shape as a `[[models]]` entry in an experiment config, so the UI copies it unchanged:

   ```toml
   [[models]]
   name = "example-model"
   provider = "fake"
   api_model_id = "example-model-2026-01-01"
   kind = "system-2"
   params = { temperature = 1.0 }
   ```

   `kind` is `system-1` or `system-2` (see [definitions](../definitions.md#setups)). The UI copies it into the experiment config when the catalogue entry has one.

4. Token prices, `config/prices.toml` on `main`. A catalogue model with no price there is shown disabled with the reason "no price in config/prices.toml".
5. Puzzle descriptions, `docs/puzzles/<puzzle>.md` on `main`. The page shows the first paragraph after the title. A missing file shows "no description on main" and no link.
6. Experiments: each ref `origin/results/<id>`. From its tree: `results/<id>/experiment.toml`, every `results/<id>/raw/<model>.jsonl` (read with the same rules as `src.run.raw.read_raw`), and any `results/<id>/<version>.metrics.csv` and `results/<id>/<version>.md`. A branch with no `experiment.toml` is left out.
7. Live experiments: an id with a live job in this server is read from its local branch `refs/heads/results/<id>`, which `run` commits to after every record, and is marked `pushed: false` until the remote branch equals it.
8. The README, `README.md` on `main`.
9. The GitHub base URL, from `git remote get-url origin`, as `https://github.com/<owner>/<repo>`, accepting the `https://` and `git@github.com:` forms with or without `.git`. With no `origin`, or another host, every source link is left out.
10. API keys, one provider each for `src.run.models.KEY_VARIABLES`. A key is stored in `secrets/<provider>.json` as `{"api_key": "..."}`. The folder has mode 0700 and each file 0600, written atomically (a temp file in the folder, then replace). Saving overwrites the file and keeps no copy, and clearing deletes it. The server merges the saved keys under `os.environ`, so a real env var wins and the file is then ignored. An env var that is set but empty counts as unset. The merged env goes to subprocesses only. The page gets only whether a key is set, where it comes from (`env`, `file`, or `missing`), and its last 4 characters, never a whole key. A model whose provider key is missing is shown disabled with the reason "no API key: add it under Models". The `fake` provider needs no key. There is no `.env` support. Terminal users export the variables themselves.

`run` and `evaluate` still read releases, prices, and the assessment from the work tree, as their specs say. A release that is on `main` but not in the work tree is offered by the page, and `run` then exits with its own error.

## Bundle

`ui/bundle.py` builds one JSON object per release with everything the menu pages show, so a page changes without another request:

```json
{"schema": 1, "release": "1.1.1", "releases": ["1.1.1", "1.1.0", "1.0.0"],
 "fetched_at": "2026-10-25T10:12:00Z", "fetch_error": null, "repo": "https://github.com/<owner>/<repo>",
 "main_sha": "<sha>",
 "defaults": {"attempts": 3, "retry_cap": 3, "max_output_tokens": 4096,
              "budget": {"per_request_usd": 0.5, "per_model_usd": 5.0, "per_experiment_usd": 10.0}},
 "providers": [{"name": "anthropic", "variable": "ANTHROPIC_API_KEY", "key": {"source": "file", "tail": "ab12"},
                "models": [{"name": "claude-opus-5-5", "api_model_id": "claude-opus-5-5", "kind": "system-2", "params": {},
                            "price": {"input_per_mtok": 5.0, "output_per_mtok": 25.0}, "disabled_reason": null,
                            "experiments": ["<id>"]}]}],
 "puzzles": [{"name": "2x2", "n": 2, "input_count": 60, "depths": [1, 3, 5], "valid": 40, "invalid": 20,
              "description": {"text": "...", "source": "<url>"},
              "prompts": {"no_model": {"text": "...", "version": "<12 hex>", "source": "<url>"}},
              "legal_moves": ["U", "U'"], "legal_moves_source": "<url>",
              "impossible_seen": [{"move": "u", "count": 3, "models": ["..."], "experiments": ["<id>"]}],
              "inputs_source": "<url>"}],
 "experiments": [{"id": "...", "model": "...", "provider": "...", "api_model_id": "...", "puzzle": "2x2", "validity": "all",
                  "release": "1.1.1", "attempts": 180, "infrastructure_failures": 0,
                  "success_rate": 0.41, "hallucination_rate": 0.12, "mismatch_detection_rate": 0.6,
                  "false_mismatch_rate": 0.05, "malformed_output_rate": 0.0,
                  "total_tokens": 812345, "cost_usd": 3.21, "metrics_source": "report",
                  "report_version": "1.1.1", "differs_from_catalogue": false, "served_models": ["..."],
                  "pushed": true, "running": false, "error": null, "branch": "<url>"}],
 "about": {"markdown": "...", "source": "<url>"}}
```

1. `providers` come in the order anthropic, openai, google, fake, each with its catalogue models in file order. A model's `experiments` are the ids whose config holds an entry with the same `provider` and `api_model_id`, so experiments are matched on what was called, not on the name. `defaults` is the `DEFAULTS` dict of `ui/experiments.py`, the starting values of New Experiment.
2. `puzzles` are the release's `release_config.puzzles`. `n` is the side for an `NxN` name, else `null`. `prompts` hold the template for each setup with the placeholder `{state}` left in, and the prompt version from the manifest. `legal_moves` is the engine's `legal_moves()` from the registry. The page shows it and the server never sends a second copy anywhere else. A puzzle with no engine has `legal_moves: null`. `impossible_seen` lists every parsed move of every record of that puzzle in this release's experiments that is not in `legal_moves()` (exact string match), with its count, the AI models that returned it, and the experiment ids, sorted by count. It comes from the re-validated attempt rows (`parsed_moves` from the validator, not the stored value), read one AI model file at a time, and is never written down. A model file that cannot be scored adds nothing, and the experiment's other model files still count. A stored `parsed_moves` that is not a list, or an entry that is not a string, is ignored, and an experiment that cannot be read adds nothing.
3. `experiments` has three rows per experiment, AI model, and puzzle, one for each `validity` scope: `all`, `valid`, and `invalid`, for the experiments whose release is the bundle's release or one of its mirrors. Rates leave out `infrastructure_failure` attempts, as [definitions.md](../definitions.md#metrics) says, and are `null` with an empty denominator. `total_tokens` is input, output, retry input, and retry output tokens summed. `cost_usd` uses the prices in `results/<id>/prices.toml` on the branch when there is one, else `config/prices.toml` on `main`.
   1. When the branch has `results/<id>/<version>.metrics.csv` for the newest such version, the row's rates are pooled from its rows for that AI model, puzzle, and scope (each rate's numerator over its `_n`), and `metrics_source` is `report`.
   2. Otherwise the server computes them from the raw records with `src.evaluate.metrics.compute` under the experiment's release, for display only, and `metrics_source` is `computed`. Nothing is stored.
   3. `differs_from_catalogue` is true when the experiment's entry for the AI model differs from the catalogue entry with the same name in `api_model_id`, `provider`, or `params`, or the catalogue has no such name. `kind` is not compared, because experiments committed before the field existed have none.
   4. A branch whose config does not parse, or whose raw file has a record that lacks a required field, gives one row with `error` set to the message and every metric `null`. The other rows still build. Torn lines are skipped and counted, as in `evaluate`.
4. The server keeps built bundles in memory only, keyed by the release and the shas of `main` and of every `results/*` ref it read. The same shas return the same object. A moved ref rebuilds the bundle. Nothing is written to disk. The key status in `providers` and the disabled reasons that depend on it are not cached: they are filled in on every request, so saving a key shows at once.
5. A build is synchronous: the request waits until it is done.

## Security

1. At start the server makes a token with `secrets.token_urlsafe(24)` and writes it into `index.html` as `<meta name="ui-token" content="...">`.
2. The default mode (`--lan`) has no network restriction: every peer address is accepted, so the server can sit behind a router's public name or proxy. It still checks `Host`, to stop DNS rebinding: a web page the owner visits can point its own hostname at this server and read the page and its token. A rebinding attack always uses a hostname, so IP literals and names passed with `--allow-host` (each with any port or none) and `localhost` (with the server's port) are the only accepted `Host` values.
3. Warning: in the default mode, anyone who can reach the port and sends an accepted `Host` gets the token, because the server puts it in the page it serves to every client that loads it. That client can start paid runs, use the saved API keys, and push. The traffic is plain HTTP, so anyone who can watch the network can read the token and any API key sent through the page. Use `--no-lan` to restrict the server to this machine. With `--no-lan`, every request from a peer outside `127.0.0.0/8` gets 403, and so does every request whose `Host` header is not `localhost:<port>` or `<ip>:<port>`, where `<ip>` is a literal address in `127.0.0.0/8`. An IPv4-mapped IPv6 peer counts as its IPv4 address. Hostnames are refused, which stops DNS rebinding.
4. Every `POST` without the header `X-Token: <token>` gets 403. So do `GET /api/commit/<id>` and `GET /api/bundle`, which can run `git fetch` and carry the key status, and `GET /api/secrets`.
5. Static files come from an allowlist: `/` serves `index.html`, and `/static/` serves exactly the files named under Files above. Any other path gets 404. Nothing outside `ui/static/` is ever served, so `secrets/` can't be reached.
6. A `POST` body is JSON of at most 64 KiB, or 400.

## HTTP API

Every JSON error is `{"error": "<message>"}` with a 4xx status. The message names the field at fault.

1. `GET /api/bundle?release=<version>&refresh=<0|1>` returns the [bundle](#bundle) for that release, default the newest. `refresh=1` fetches first, within the 30-second limit of Inputs 1. An unknown release gives 400 naming `release`.
2. `GET /api/experiments/<id>` returns one experiment in full, read from its branch as in Inputs 6 and 7:

   ```json
   {"id": "...", "release": "1.1.1", "config": {"...": "the form shape of item 5"},
    "model_entries": [{"name": "...", "provider": "...", "api_model_id": "...", "kind": "system-2", "params": {}}], "pushed": true, "running": false,
    "branch": "<url>", "metrics_source": "report", "local_results": true, "local_report": true, "report": {"version": "1.1.1", "markdown": "...", "source": "<url>"},
    "metric_rows": [], "summary_rows": [], "served_models": {"<model>": ["..."]}, "error": null}
   ```

   `metric_rows` and `summary_rows` are the columns of [evaluate](evaluate.md#outputs): from the newest report CSV on the branch when there is one (`summary_rows` then pooled from it by AI model, setup, and validity), else from `src.evaluate.metrics.compute`, with `metrics_source` `computed`. `report` is `null` when the branch has none. `model_entries` are the config's AI models with the `api_model_id`, `kind`, and `params` the experiment used (`kind` is `null` when the config has none), which the form leaves out. `local_results` is true when `results/<id>/experiment.toml` is in the work tree, one of two work-tree reads here (like API 12). `local_report` is true when `results/<id>/<config release>.md` is in the work tree (the report Commit requires), where `evaluate` writes it before it is committed (like API 13's age check). An unknown id gives 404.
3. `GET /api/inputs?release=<version>&puzzle=<name>` returns the release's inputs of that puzzle, in release order: `[{"input_id", "scramble_depth", "validity", "state", "scramble", "source_input_id", "corruption"}]`. An unknown release or puzzle gives 400 naming the field.
4. `GET /api/branches` returns every experiment branch, `[{"id", "release", "local": true, "remote": true}]`, sorted by id, for the New Experiment branch select. An id is listed when `results/<id>/experiment.toml` is on its local or remote branch.
5. `GET /api/experiment/<id>/config` returns the config on the experiment's branch (the local one first, else the remote one) as the form below, or 404. A config without `puzzles` returns every puzzle of its release.

   The form, which items 6 to 8 take:

   ```json
   {"id": "claude-opus-5-5-gpt-6-astra_2x2-3x3_20261025-1012", "release": "1.1.1", "puzzles": ["2x2"],
    "models": ["claude-opus-5-5"], "attempts": 3, "retry_cap": 3, "max_output_tokens": 4096,
    "budget": {"per_request_usd": 0.5, "per_model_usd": 5.0, "per_experiment_usd": 10.0}}
   ```

   `models` holds catalogue names. A disabled model, an unknown release, or a puzzle that isn't in the release gives 400.
6. `POST /api/estimate {form}` and `POST /api/dry-run {form}` start `python -u -m src.run.run --experiment <id> --config - --estimate` and `... --dry-run`.
7. `POST /api/run {form, "limit": null}` starts one run job per model, all at once: `python -u -m src.run.run --experiment <id> --config - --model <name>`, plus `--limit N` if `limit` is set. The processes can race to write `results/<id>/experiment.toml` because `run` writes it atomically ([run.md](run.md#outputs)).
8. Items 6 and 7 build the experiment config from the form as TOML text with `ui/tomlw.py`, with `puzzles` always written, check it with `parse_experiment_config`, and pass it on each job's stdin. Nothing is written to disk. Before a job starts:
   1. For Run, checked first: a run job of the id alive gives 409, "a job of experiment <id> is running; stop it first", and so does a live evaluate job. Estimate and dry-run only read, so they refuse just while the same job of the id runs (API 22).
   2. No branch for the id: the experiment is new. Status `created`.
   3. A branch holds a config equal to the new one: status `unchanged`, and the run resumes. A model's `kind` is ignored when the saved entry for it has none, because experiments saved before the field existed have none. A missing `puzzles` counts as every puzzle of its release.
   4. A branch holds a config that differs only in `[budget]`: status `budget_updated`, and `run` replaces its copy.
   5. Any other difference: 409, "experiment <id> exists with a different config; load it or pick a new id".
   6. A branch exists but `results/<id>/experiment.toml` is missing from the work tree: 409, "the results of <id> are not in this checkout; check out its branch first". `run` appends to the raw files in the work tree, so resuming without them would run attempts the branch already holds. This check, like item 12's, reads the work tree.

   The response is `{"id", "status", "jobs": [...]}`.
9. The default id names the choice: the selected AI model names joined with `-`, then `_`, the selected puzzle names joined with `-`, then `_` and the local time as `YYYYMMDD-HHMM`. Every character outside `[A-Za-z0-9_-]` becomes `-`. With more than three AI models, the model part is `<count>-models`, and with more than three puzzles, the puzzle part is `<count>-puzzles`. It is `default_id(models, puzzles, now)` in `ui/experiments.py`, and the page asks the server for it with `GET /api/default-id?models=a,b&puzzles=2x2`.
10. `GET /api/state/<id>` returns the live snapshot, read from the experiment's branch as in Inputs 6 and 7:

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

    `inputs` holds only the experiment's puzzles, in release order. `records` follows the rules of `src.run.raw.read_raw` over each model's raw file. `jobs` maps each job name of the id to its state. `report` is the report path if the branch has it, else `null`. The snapshot holds no in-progress attempt: the page works that out (see Polling). An unknown id gives 404.
11. `POST /api/stop {"id"}` sends SIGINT to every live run job of the id, waits up to 10 seconds, then sends SIGTERM to any still alive. A request that is in flight when the job stops may be paid for and never recorded, so the page says to prefer `limit` for small runs.
12. `POST /api/evaluate {"id", "release": null}` starts `python -u -m src.evaluate.evaluate --experiment <id>`, plus `--release <version>` if `release` is set (a bad version gives 400). 409 while a run job of the id is alive. `evaluate` reads `results/<id>/` from the work tree, so 409 "experiment <id> has no results in this checkout" when `results/<id>/experiment.toml` is missing there: that one check reads the work tree.
13. `GET /api/commit/<id>` returns the commit preview: `{"branch": "results/<id>", "base": "<sha>", "files": [...], "diffstat": "..."}`. 409 while any job of the id is alive, before the report exists, or when the report is older than any file in `results/<id>/raw/` (message "the report is older than the raw records; evaluate again first"). The age is the file modification times.
14. `POST /api/commit {"id"}` makes the commit and the pull request, and returns `{"branch": "...", "commit": "<sha>", "pr_url": "..."}`. The same 409 rules apply.
15. `GET /api/log?after=<seq>` returns the terminal lines newer than `seq` (default 0) and the job states:

    ```json
    {"lines": [{"seq": 41, "id": "t1", "job": "run:example-model", "stream": "stdout", "text": "..."}],
     "last": 41,
     "jobs": [{"id": "t1", "job": "run:example-model", "state": "running", "code": null}]}
    ```

    The server keeps one in-memory list of lines for all jobs, at most 5,000, dropping the oldest. `id` is the experiment id of the job that wrote the line, `""` for a project job, so two experiments that both run `run:<model>` stay apart. The page keys a failure banner by `(id, job)` and the ended-job check by `(id, job)`. `stream` is `cmd`, `stdout`, or `stderr`. The `cmd` line is the full command, logged before the process starts. `seq` counts up from 1 for the life of the server. `state` is `running`, `done`, `failed`, `budget`, or `stopped`. `budget` means the job exited 1 with a stderr line starting `error: budget reached:`. `stopped` means the UI stopped it.
16. `GET /api/secrets` returns `{"<provider>": {"variable": "ANTHROPIC_API_KEY", "configured": true, "tail": "ab12", "source": "env" | "file" | "missing", "location": "secrets/anthropic.json" | "env var ANTHROPIC_API_KEY" | null}}` for each provider. `POST /api/secrets {"provider", "action": "save" | "clear", "api_key"}` saves a stripped key or deletes the file, and returns the same listing. An empty key, or one with whitespace inside, gives 400 naming `api_key`. Both need the token.

Project jobs belong to no experiment and use the id `""`. Their names are `install`, `tests`, `release`, and `push`. Each is echoed to the terminal like the others.

17. `GET /api/project` needs no token. It returns `{"branch", "clean", "latest_release", "python", "packages": {"anthropic": true, "openai": true, "google-genai": true, "pytest": true}, "gh": true}`. `branch` is `git rev-parse --abbrev-ref HEAD`, `clean` is true when `git status --porcelain` is empty, `latest_release` is `src.release.release.latest_version`, each package is checked with `importlib.util.find_spec` and never imported, and `gh` is whether the `gh` binary is found.
18. `POST /api/install` starts `python -u -m pip install -e .[test]`, with `.[test]` as one argument.
19. `POST /api/tests` starts `python -u -m pytest -q -p no:cacheprovider`.
20. `POST /api/release {"bump", "note"}` starts `python -u -m src.release.release --bump <bump> --note <note>`. A `bump` that is not `major`, `minor`, or `patch`, or a blank `note`, gives 400.
21. `POST /api/push` runs `git push -u origin <branch>`, then `git push origin <tag>...` for the `release-*` tags reachable from the branch (`git tag --merged <branch> --list 'release-*'`; skipped when there are none), then finds the open pull request with `gh pr view` or makes one with `gh pr create --base main --head <branch> --fill`, and returns `{"branch", "pr_url"}`. It adds no attribution. It runs inline, like commit.
22. Release and push give 409 when the branch is `main` or HEAD is detached. Install, release, and push give 409 while any job of any experiment, or any project job, is running, and while one of them runs every other job gives 409. Release also gives 409, naming up to 10 paths, when `git status --porcelain` is not empty. `tests` gives 409 only while the same job is running, and `dry-run` only while a dry run of the same id is.

23. `GET /api/replay/<id>?model=<name>&input_id=<id>&setup=<setup>&attempt=<n>` needs no token, like `/api/state`. It plays one attempt's moves on its input and returns every state on the way:

    ```json
    {"input_id": "2x2-d5-001", "puzzle": "2x2", "outcome": "hallucination", "moves": ["R", "U'", "X"],
     "frames": ["<state 0>", "<after move 1>", "<after move 2>"], "stopped_at": 2, "solved": false}
    ```

    The record is the one in `results/<id>/raw/<model>.jsonl` on the experiment's branch (Inputs 6 and 7), read with the rules of `src.run.raw.read_raw`, with that `input_id`, `setup`, and `attempt_number`. `moves` is its `parsed_moves`, empty for `malformed_output` and `infrastructure_failure`. `frames[0]` is the input's state from the experiment's release on `main`. Each next frame is the engine's `apply_move` of the next move. A move that is not in `legal_moves()` (exact string match) stops the replay: `stopped_at` is its index, and it and every later move get no frame. Otherwise `stopped_at` is `null`. `solved` is `is_solved` of the last frame when the replay did not stop and at least one move was applied, else false, and is for display only: `outcome` is always the record's own. A puzzle with no engine in the registry gives one frame. A missing or malformed `model`, `input_id`, `setup`, or `attempt` gives 400 naming the query field. An unknown experiment, a model outside the experiment, an unknown input, or no matching record gives 404. The move group is never sent to the page: the page only draws the frames.

Job names are `run:<model>`, `estimate`, `dry-run`, `evaluate`, and `commit`, plus the project jobs above. Every job runs with `cwd` at the root and the merged env from Inputs 10. The registry keys a job by experiment id and name, so a job that belongs to no experiment can use the id `""`.

## Polling

1. Snapshot. The page loads `GET /api/state/<id>` on load, and again every 1.5 seconds while any job of that experiment is alive. The poll that sees the last job end is the final one. With no job alive it loads once and stops.
2. Log. The page polls `GET /api/log?after=<seq>` every second while any job is alive and every 5 seconds otherwise.
3. In-progress attempt. For each model with a running `run:<model>` job, the page marks the first attempt with no record, in the loop order of [run.md](run.md#outputs): input in release order, then setup, then attempt number. It is an inference, as `run` doesn't report the attempt it is on.

## Commit

The commit never touches the working tree, the index, or `HEAD`:

1. `git fetch origin main`, then `git fetch origin results/<id>`. The parent is `origin/results/<id>` if that fetch succeeds, else `origin/main`. [run](run.md#outputs) commits to the local branch `results/<id>` as it goes, so if that branch exists and the remote branch is missing or an ancestor of it, the parent is the local branch instead. If the local branch is an ancestor of the remote one, the preview moves it forward to the remote branch. The local branch is then "ahead" when the remote branch is missing or differs from it.
2. Before building the tree, `stale_files` from `src/run/branch.py` (see [run](run.md#outputs), Outputs 3) compares every `results/<id>/raw/*.jsonl` on the parent with the work tree. A work-tree file that does not start with the branch file's exact bytes gives 409 with the same message as `run`: `results/<id>/raw/<model>.jsonl on <ref> holds records this checkout lacks; bring the branch's results into the work tree first, after checking that no local records are uncommitted (for example: git restore --source=<ref> --worktree -- results/<id>)`. `<ref>` is the ref the files were read from: the local branch `results/<id>` when it exists, else `origin/results/<id>` (the UI names the parent it used, `origin/main` when the branch does not exist). The verb is `hold` for several files. It is `git restore`, not `git checkout`, so the real index stays untouched. Without it, the new tree would replace the branch's longer file with the shorter local one. A raw file gone from the work tree is not compared.
3. With `GIT_INDEX_FILE` set to a temporary file: `git read-tree <parent>`, then `git add -- results/<id>`, then `git write-tree`. Only that path is ever added (the config's copy is `results/<id>/experiment.toml`), with `--ignore-removal` so a file already on the branch is never dropped, and without the temporary copies `.experiment.toml.*.tmp`.
4. Preview: the files are `git diff --name-only <parent> <tree>`, and the diffstat is `git diff --stat <parent> <tree>`. No files, no branch on the remote, and no local commits ahead means 409 "nothing to commit".
5. Commit, in this order, so a failure at any step can be run again: `git commit-tree <tree> -p <parent> -m "Results: experiment <id>"`, then `git push origin <commit>:refs/heads/results/<id>`, and only after the push succeeds `git update-ref refs/heads/results/<id> <commit>`. With no files but a branch already on the remote, there is no new commit and the step goes straight to the pull request. With no files but local commits ahead, there is no new commit either: the step pushes the local branch, then goes to the pull request.
6. Pull request: if `gh pr view results/<id> --json url,state` finds one whose state is `OPEN`, return its URL. A closed or merged pull request doesn't count. With no files, nothing ahead, and an open pull request, 409 "nothing to commit". Else `gh pr create --base main --head results/<id> --title "Results: experiment <id>" --body "<body>"`. The body lists the release, puzzles, models, attempts, and a link to the report path. It carries no attribution line.
7. The `gh` binary is `$UI_GH` if set, else `gh`, so tests can stub it.

Every git and gh command is echoed to the terminal as a `commit` job.

## Page

Two parts: a left menu, fixed to the viewport height, and the page on the right. The router (`router.js`) reads the hash: `#/models`, `#/puzzles`, `#/puzzles/<puzzle>/inputs`, `#/experiments`, `#/experiments/<id>`, `#/new`, and `#/about`, each with `?release=<version>`, and any other filter, in the hash too, so a link or a reload opens the same view. An empty hash opens `#/experiments`. Each page is one file in `ui/static/pages/` with a `render(bundle, params)` function, and a page that needs more than the bundle loads it itself.

Every text taken from a file ends with a small "source" link to that file on GitHub, at the commit sha of the ref it was read from, as `https://github.com/<owner>/<repo>/blob/<sha>/<path>`. With no GitHub base URL, there is no link.

Markdown is rendered by `markdown.js`, a small renderer for headings, paragraphs, numbered and bulleted lists, links, inline code, code blocks, emphasis, and tables. It escapes all HTML in the source first and allows only `http`, `https`, and relative links, so a file can never inject markup. A relative link points at the same file on GitHub.

### Left menu

1. A release select, newest first, defaulting to the newest, with a ↻ button beside it. Changing the release loads its bundle.
2. Models, Puzzles, Experiments, and About, with the current page highlighted. Models shows ⚠️ when any provider other than `fake` has no key.
3. Beside the page title, a status dot. Its colour shows the server: grey while connecting, green when the server answers, red when it doesn't, and amber when it answers but the last GitHub fetch failed. Its tooltip, which is also its accessible label, has two lines. The first is "Server: connecting", "Server: live", or "Server: not reachable, reconnecting". The second is "Fetched from GitHub <time>", "GitHub not reached, showing data from <time>: <error>", or "Not fetched yet". The log poll sets the server state and each bundle sets the fetch state.

### Cache and refresh

1. The page keeps each bundle in `localStorage` under `bundle:<release>`, and the release of the newest answer under `bundle:last` (the instant cached render uses it when the hash names no release), inside try/catch, so a blocked storage only loses the cache. A cached bundle with another `schema` is dropped.
2. On load, and on a release change, the page renders at once from the cached bundle if there is one, then requests `GET /api/bundle` and renders again when it answers. The server's answer always replaces the cache.
3. ↻ requests the bundle with `refresh=1`, and spins until the answer. A failed request keeps the cached view and shows the error under the menu.
4. When a job ends, the page requests the bundle again, so a pushed experiment appears.

### Models

One block per provider, in bundle order.

1. The header is the provider name, with ⚠️ and "no API key" when the key is `missing` (never for `fake`).
2. The key row: with no key, a password field and Save. With a key saved in a file, `Key …abcd from secrets/anthropic.json`, with Edit and Clear (after `confirm()`). Edit shows the password field, Save, and Cancel. With a key from an env var, `Set by env var ANTHROPIC_API_KEY`, with no controls. Save and Clear reload the bundle. The field is cleared after Save and Cancel, and a key is never shown. A note says "Keys are stored in ./secrets/ (one file per provider), which is .gitignored and never committed."
3. One row per model: the name, `api_model_id`, its `kind` or "kind not set", the prices per million tokens, the disabled reason if any, and "N experiments", which links to `#/experiments?model=<name>`. A model with no key shows ⚠️.
4. The block ends with a source link to `config/models.toml`.

### Puzzles

One card per puzzle of the release:

1. A picture of the solved puzzle: `cubeIso` for an `NxN` cube, else the name in a box.
2. The description, from `docs/puzzles/<puzzle>.md`, with its source link.
3. A 2D net of the solved puzzle with every sticker named by its face letter and its index in the face, row by row from 1, for example `U1` to `U9` on the 3x3, in the state's reading order ([cube.md](cube.md)), so a reader can match the net to a state string. Cubes only.
4. The input count, the depths, and the valid and invalid counts. "Scrambled states" links to `#/puzzles/<puzzle>/inputs`. "Experiments" links to `#/experiments?puzzle=<puzzle>`.
5. "What the AI model is told": one folded section per setup with the prompt template, its prompt version, and its source link.
6. "Allowed moves": the `legal_moves` list as chips, with a source link to the engine. "No engine" when it is `null`.
7. "Not allowed moves seen": a table of `impossible_seen`, with the move in a code span, the count, and the AI models, each experiment id linking to its page. "None in pushed experiments yet" when it is empty.

The inputs page lists every input of the puzzle: the input id, the depth, the validity, the net of its state, and, for an invalid input, its source input and corruption, filtered by depth and validity, with a source link to `inputs.jsonl`.

### Experiments

1. A "New Experiment" button in the top-left corner opens `#/new`.
2. Filters: AI model, puzzle, and validity (all inputs, valid only, or invalid only; default all). The release comes from the menu. Filters are kept in the hash. Mismatch detection rate is `n/a` under valid only, and false mismatch rate under invalid only, by definition.
3. A table, one row per experiment, AI model, and puzzle in the chosen validity scope, with the columns: experiment id, AI model, puzzle, release, attempts, success rate, hallucination rate, mismatch detection rate, false mismatch rate, malformed output rate, infrastructure failures, total tokens, cost, and report. Rates show as percentages, and `n/a` when `null`. Clicking a column header sorts by it, and a second click reverses.
4. A row with `metrics_source: computed` shows `*` after each metric and in the report column, and the table ends with the note "* computed from the raw records by the UI for display. No report is committed for this experiment, so these are not official numbers." A row with a report shows its version.
5. A row with `differs_from_catalogue` shows ⚠️ after the AI model, with the tooltip "this experiment's settings for the AI model differ from config/models.toml". A row with `pushed: false` shows "running, not pushed". A row with `error` shows the message across the metric columns.
6. Each row links to `#/experiments/<id>`.

### Experiment

One experiment, from `GET /api/experiments/<id>`:

1. The header: the id, the release, a link to the branch on GitHub, "running, not pushed" when it applies, and the served models.
2. Summary, first under the header: one row per AI model and setup, split by validity label, from `summary_rows` (pooled over puzzles and depths, as in [evaluate](evaluate.md#outputs)), with success, hallucination, mismatch detection, false mismatch, and malformed output rates, each with `n` and its interval, plus attempts, total tokens, and cost per AI model. With a report CSV, which holds no summary rows, the server pools them from the CSV's rows the same way. The `*` note applies when computed.
3. The config: puzzles, AI models with their `api_model_id` and `params`, attempts, retry cap, max output tokens, and budgets.
4. The full metrics table, folded: one row per puzzle, setup, AI model, scramble depth, and validity label, with each rate, its `n`, and its interval, and the `*` note when computed.
5. The report, rendered, with its source link, when there is one.
6. Progress: the Cube panel and the per-input rings described below, from `GET /api/state/<id>`.
7. Actions while the experiment's results are in this checkout: Evaluate, with an optional "Score under release" select, and Commit, which opens a dialog with the preview's branch, files, and diffstat. Confirm calls `POST /api/commit` and shows the PR link. Commit is disabled while any job of this experiment is alive or before a report exists in this checkout.

### New Experiment

The terminal is on the right, sticky to the viewport height. The left column holds:

1. Branch: a select with "New: <default id>" first, then every branch from `GET /api/branches`. The new id is editable and follows the choices below until it is edited by hand. Picking an existing branch loads its config into the form from `GET /api/experiment/<id>/config`.
2. Puzzles: one `<button aria-pressed>` card per puzzle in the menu's release, with the puzzle name, its input count, and, for an `NxN` name, a solved net. At least one is needed.
3. AI models: grouped by provider. When a provider has no key, the header shows ⚠️ "no API key: add it under Models", linking there, and its models are disabled. Other disabled reasons show beside the model.
4. Parameters: attempts ("Attempts per input and setup: sends the same input N times"), retry cap, max output tokens, the three budgets, and "Limit per model" (optional). Buttons: Estimate, Dry run, Run, Stop. Each sends the form.
5. Progress: the Cube panel, a legend, and the rings, as on the Experiment page.

Banners: a job in state `failed` shows its last stderr line. The line comes from the log poll and the state from the snapshot poll, and either can arrive first, so each log poll that brings a stderr line redraws the banners. A job in state `budget` shows "Budget reached" and a plain note to raise the budget under Parameters and press Run, which the server accepts as `budget_updated`, and resumes. The banner notes that parallel AI models can each pass the experiment budget by one worst-case request, and that "attempts left" in the message counts one AI model's attempts.

### About

The README from `main`, rendered, with its source link. Under it, a "Project" box: the project status from `/api/project` (branch, clean tree, packages, `gh`), Install dependencies and Run tests, and the release tools: a bump select, a note field, a Release button, and "Push and open PR". Release is disabled, with the reason beside it, on `main` ("on main"), on a detached HEAD ("detached HEAD"), and with a dirty tree ("working tree has changes: commit them first"). Push is disabled on `main` and on a detached HEAD. Both are also disabled while any job runs. The server enforces all of this. When an install, release, or push job ends, the page reloads the project status and the bundle.

### Progress

One accordion per model, inside it one per puzzle, inside that one row per input. Headers show done/total and a count per outcome. Each row has a ring SVG split into `3 × attempts` arcs, in setup order then attempt order, with the input's cube net inside the ring, the input id, the depth, and the validity. Rows render when their accordion first opens. Hovering an arc shows setup, attempt, outcome, and, on invalid inputs, mismatch. A later snapshot only adds records, so open accordions stay open.

Cube panel: the first thing in Progress. The 3D view (`cubeIso`) is on the left and the net (`cubeNet`) of the same frame is on the right, always both. Below them are the move list, with the current move highlighted and an impossible move in the hallucination colour, and then the outcome, the input id, the setup, and the attempt number. The page never holds the move group: it draws the `frames` of `GET /api/replay/<id>`.

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

Cube net: a state is `6·n·n` characters over `URFDLB`, faces in that order, each face row-major. The net puts U above F, L, F, R, and B in a row, and D below F. Sticker colours: U white, R red, F green, D yellow, L orange, B blue. These colours live in `cube.js` only, and the page scripts use them, so the table is never copied. `cube.js` loads before the page scripts and holds the sticker colours, `svg()`, `cubeNet`, and `cubeIso`.

Cube 3D view: `cubeIso(state, n, highlightFace)` draws the U face on top, F front-left, and R front-right, each as an `n × n` grid of parallelograms in the net's colours. Sticker order follows the state's reading convention ([cube.md](cube.md)): U is read from above with B at the top, so its first row is the back row, and F and R are read with U at the top, with R's first column next to F. The placement uses `READING` and `NORMAL` of `src/puzzles/cube.py` for U, F, and R as drawing geometry only. `highlightFace` draws that face's outline thicker, and a face the view does not show (D, L, B) is not outlined.

## How to test

`tests/test_ui.py` and `tests/test_ui_bundle.py`, with temporary folders, a temporary repo with a bare remote as `origin`, the `fake` provider, and no network. The server is started on port 0 in a thread.

1. Keys: file modes, no backup copy, a real env var winning, an empty env var losing to a saved key, and only the last 4 characters in any `GET` body. Every secrets route needs the token.
2. The bundle marks a catalogue model with no price, and a model with no key, as disabled, with the reasons above, and reads the catalogue and prices from `main`: a change in the work tree that is not committed and pushed does not show.
3. Items 6 to 8 of the API for each of `created`, `unchanged`, `budget_updated`, and 409, with the config read from the branch. On 409 no job starts. No call writes any file under `config/experiments/`, and the config on each job's stdin loads with `parse_experiment_config` and holds `puzzles`. A config without `puzzles` compares equal to the same choice made on the page. A branch whose results are not in the work tree gives 409 and starts no job.
4. A POST, `GET /api/bundle`, or `GET /api/secrets` without the token gets 403, whatever its `Host`. `GET /static/../secrets/anthropic.json` and `GET /secrets/anthropic.json` get 404.
   1. In the default mode, `8.8.8.8:<port>`, `10.1.2.3:<port>`, `localhost:<port>`, `[::1]:<port>`, `10.0.0.11` with no port, and `10.0.0.11:443` are accepted. `evil.example`, `localhost` with no port or a wrong port, and `aiohr.dorland.keenetic.pro` are refused without `--allow-host`. With `--allow-host`, that name is accepted with no port, with `:443`, with `:80`, in any case, and with a trailing dot, and the 403 for another name echoes the header and names the option.
   2. In the default mode, `verify_request` accepts the peers `8.8.8.8` and `172.16.0.1`, and `handle_request` does not refuse a non-loopback peer. `is_loopback("::ffff:127.0.0.1")` is true and `is_loopback("not-an-ip")` is false.
   3. The start-up text holds the "Open to every client" line and the allowed host names.
   4. With `--no-lan`, a `10.0.0.5` peer and an `evil.example` `Host` are refused, and loopback is accepted.
5. The log keeps only the newest lines at the cap, and `after` returns the newer ones.
6. A full run through the API on a one-puzzle release: records appear in `/api/state` from the local branch while the run is alive, the experiment shows in the bundle as `pushed: false`, then as pushed once the run exits, the snapshot has no `in_progress`, and the run job ends `done`.
7. Run is refused while evaluate is alive, and evaluate while a run is.
8. Stop, and stop on server shutdown: a server given SIGTERM leaves no run alive.
9. Commit against a temporary bare remote, with `UI_GH` pointing at a stub script: the branch exists on the remote with only `results/<id>` changed, the working tree and `HEAD` are unchanged, and a second commit with no changes gives 409. Local commits ahead of the remote with an empty diff are still pushed.
10. A failed push and a failed `gh pr create` can each be run again, and only an open pull request counts.
11. Commit is refused when the report is older than a raw file, and with 409 when a work-tree raw file is shorter than the branch's.
12. Project jobs: the argv of each job, the 409 on `main` and on a detached HEAD, the blank-note 400, mutating jobs refused while any job runs, the `/api/project` shape, and push against a temporary bare remote with a stub `gh`.
13. Replay: the frames equal successive `apply_move` calls, an impossible move stops the replay at its index, malformed output gives one frame and no moves, a missing record gives 404, a bad query field gives 400 naming it, and every file named under Files is served from `/static/` while other unknown static paths give 404.
14. Bundle from refs only: a results folder in the work tree with no branch does not show, and a branch pushed to the bare remote shows after `refresh=1`. A branch with no `experiment.toml` is left out.
15. Bundle memory: the same ref shas return the same object without rebuilding, and a ref that moves gives a new bundle. The server writes no file anywhere while it serves every read route.
16. Rows and metrics: three rows per experiment, AI model, and puzzle, one per validity scope, and the `valid` and `invalid` rows' attempts add up to the `all` row's. `summary_rows` from a CSV equal those `compute` gives on the same records. With a report CSV on the branch, the rates equal the CSV's pooled numbers and `metrics_source` is `report`. Without one, they equal `src.evaluate.metrics.compute` on the same records and `metrics_source` is `computed`. Infrastructure failures change no rate. A branch with a broken config gives one row with `error`, and the other rows still build.
17. Model matching: an experiment whose entry has the catalogue's `provider` and `api_model_id` under another name is listed under that catalogue model, and one with the catalogue's name but another `api_model_id` gets `differs_from_catalogue`.
18. Impossible moves: fixture records with known impossible moves give the expected moves, counts, models, and experiment ids, and legal moves never appear.
19. Source links carry the sha of the ref read, for both `https://` and `git@github.com:` remotes, and there are none with no `origin`.
20. A failed fetch (the remote removed) still builds a bundle from the old refs, with `fetch_error` set.
21. `default_id`: names, the three-item cap, the character rule, and the time format, and the result passes `EXPERIMENT_ID_PATTERN`.
22. `/api/branches` lists local-only and remote-only branches, and `/api/experiment/<id>/config` reads the local branch before the remote one.
23. `/api/inputs` returns the release's inputs of one puzzle in order, and 400 for an unknown puzzle.
24. Outcome colours and the in-progress inference are in the page scripts and are not tested here. The colour table is one object, in one file.
25. The page scripts pass `node --check`. A node script, `tests/js/markdown.test.mjs`, run by a pytest test when `node` is found and skipped otherwise, checks that `markdown.js` escapes `<script>` and HTML attributes, drops `javascript:` links, and renders a table, a numbered list, and a link.
26. The cube drawing is checked by hand with `node --check` on both scripts and a throwaway node script that loads `cube.js`, draws scrambled states from a release, and compares every sticker of `cubeIso` with `cubeNet`, and the edges where U, F, and R meet.
27. `kind`: the catalogue and `model_entries` carry it (`null` when unset), the form copies it from the catalogue into the experiment config, and `differs_from_catalogue` ignores it.
