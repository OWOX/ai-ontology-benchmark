# run

Files: `src/run/run.py`, `src/run/decision.py`, `src/run/branch.py`, `src/run/progress.py`.

## Purpose

The [`run`](../definitions.md#workflows) workflow. Send every input of one release to the AI models in one experiment, under every setup, validate each attempt, and append one raw record per attempt. It never changes a release.

## Inputs

1. `--experiment ID`. Reads `config/experiments/<ID>.toml` with [config](config.md).

   With `--config -`, `run` reads the experiment config as TOML from stdin instead, with `parse_experiment_config(text, ID, "<stdin>")`, and never opens `config/experiments/`. This is how the [UI](ui.md) starts an experiment, because the UI writes no files. The config's only copy is then `results/<ID>/experiment.toml`, which `run` writes and commits as below. `--config` takes only `-`.
2. The release named in that config, `releases/<release>/`. Before the first call, `run` checks:
   1. Every file in the release matches its sha256 in `manifest.json`.
   2. The assessment files in the working tree hash to the release's `assessment_sha256`, so the validator that writes the raw records is the one the release pins.
   3. `prompt_versions()` over the release's inputs and templates equals the manifest's `prompt_versions`, so the engine code in the working tree renders exactly the prompts the release froze.
   4. If `results/<ID>/experiment.toml` exists, it equals the experiment config apart from the `[budget]` table. An experiment never changes once it starts, except that its budget can be raised to resume.
   5. Every AI model in the experiment has a price in `config/prices.toml`.
   6. If the config has `puzzles`, every name is in the release's `release_config.puzzles`. The error names the config path and the field `puzzles`.
   7. For every attempt still to run, the [worst-case request cost](../definitions.md#baseline-and-prices) is at most `per_request_usd`. The error names the AI model and its worst-case cost. For a decision model the request is the longest call of the attempt, the prompt with `max_moves` of the longest move after it, then the questions object as sent, `json.dumps(decision_questions(questions, legal), sort_keys=True)` (`worst_request(prompt, legal, cap, questions)`).
   8. If the manifest holds `decision_prompt_versions`, `decision_prompt_versions()` (the [decision prompt version](../definitions.md#setups)) equals it. If it lacks the field, this check is skipped, and `run` exits with code 1 naming `decision_prompt_versions` when any AI model in the experiment is a decision model (`load_release(folder, needs_decision)`). Releases cut before decision models keep working for the other AI models.

   It exits with code 1 before any call if a check fails.

   When the config has `puzzles`, `run` plays only the inputs of those puzzles. The attempts still to run, `--estimate`, `--dry-run`, `--limit`, and the budget checks all count only those inputs.
3. API keys from env vars, through [models](models.md).
4. Optional flags:
   1. `--model NAME` runs one AI model from the experiment. Separate processes can run different AI models at the same time, because each writes its own file.
   2. `--limit N` stops after N new attempts. For smoke tests.
   3. `--dry-run` prints each prompt and writes nothing. For a decision model it prints the first call's state (the prompt, then `Moves so far: none`) and the questions object.
   4. `--estimate` prints, for each AI model, the number of attempts still to run, the input tokens estimated as prompt characters divided by 4, and the worst-case cost with every answer at `max_output_tokens`, using `config/prices.toml`, and the cost spent so far against each budget. For a decision model, the worst case is per attempt: `max_moves` calls, each with the longest state plus the questions object (`worst_request`). It calls nothing and writes nothing.
   5. `--parallel N` keeps up to N attempts in flight at once, the [parallel requests](../definitions.md#workflows) of this process. An integer of at least 1, default 1. A smaller value makes `run` exit with code 1 with an error naming `--parallel`. `--dry-run` and `--estimate` ignore it. With 1, `run` behaves exactly as without the flag. See "Parallel requests" below.
   6. `--no-commit` skips the results branch described under Outputs. For tests.
   7. `--config -` reads the config from stdin, as in item 1.
   8. `--releases DIR`, `--configs DIR`, `--prices PATH`, and `--results DIR`, for tests.

## Outputs

In `results/<ID>/`:

1. `experiment.toml`: a copy of the experiment config, written on the first run, atomically: a temporary file in the same folder, then `os.replace`, so AI models run at the same time never read half a file. When a later run's config differs only in `[budget]`, `run` replaces the copy, so the report shows the budget in force.
2. `raw/<model name>.jsonl`: one file per AI model. `run` only appends to it, one JSON line per attempt, flushed after each line.

3. The branch `results/<ID>`, in `src/run/branch.py` (not an assessment file). Results always go to this branch. `run` needs a git work tree, found with `git rev-parse --show-toplevel` in the current folder, and exits with code 1 before any write or call if there is none. The config file and the results folder must be inside that work tree, so `--configs` and `--results` outside it are refused unless `--no-commit` is given. `--dry-run` and `--estimate` do no branch work. Otherwise:
   1. Before any write or call, `run` runs `git fetch origin results/<ID>`, ignoring a failure (no `origin`, or no such branch yet). If the local branch is missing, it builds on `origin/results/<ID>` when that exists. If the local branch is an ancestor of the remote one, it is moved forward to it. If the remote branch is an ancestor of the local one, or missing, the local branch stays. If they have diverged, `run` exits with code 1 naming both refs.
   2. Right after that, still before any write or call, `run` compares the raw files on the parent (the local branch, else `origin/results/<ID>`) with the work tree. For each `results/<ID>/raw/<model>.jsonl` in the parent's tree, the work-tree file must exist and start with the branch file's exact bytes, because raw files are append-only. The check is `stale_files(root, parent, results_dir, models)` in `src/run/branch.py`, which `ui/commit.py` shares. A raw file gone from the work tree counts only for an AI model this run will write (all of them, or the one named by `--model`). The other files (`experiment.toml`, reports, `prices.toml`) are not compared: a missing one stays on the branch, and `run` already checks the config copy. A failing file makes `run` exit with code 1 with `results/<ID>/raw/<model>.jsonl on <ref> holds records this checkout lacks; bring the branch's results into the work tree first, after checking that no local records are uncommitted (for example: git restore --source=<ref> --worktree -- results/<ID>)`. `<ref>` is the ref the files were read from: the local branch `results/<ID>` when it exists, else `origin/results/<ID>` (the UI names the parent it used, `origin/main` when the branch does not exist). The verb is `hold` for several files. It is `git restore`, not `git checkout`, so the real index stays untouched. Without it, `run` would pay again for attempts the branch holds, and the next commit would replace the branch's longer file. `--no-commit` skips the check.
   3. After it writes `experiment.toml`, and after every appended record, `run` commits the config file (none with `--config -`) and `results/<ID>/` to `refs/heads/results/<ID>`, with the message `Results: experiment <ID>, start` or `Results: experiment <ID>, <model> <input id> <setup> attempt <n>`. The parent is the local branch if it exists, else `origin/results/<ID>`, else `origin/main`, else `HEAD`. The tree is built in a temporary index file with `git add --ignore-removal`, so the work tree, the real index, and `HEAD` are never touched, and a file already on the branch is never dropped, even if it is gone from the work tree. The temporary copies `.experiment.toml.*.tmp` are never added. A commit that changes nothing is skipped.
   4. A commit that fails prints `warning: commit of results/<ID> failed: <reason>` to stderr and the run goes on. It never aborts the run or replaces a budget stop.
   5. Each commit runs under an exclusive `flock` on `<git common dir>/results-<ID>.lock`, so separate `--model` processes do not race on the ref.
   6. At exit, on a normal end, a budget stop, an error, Ctrl-C, or SIGTERM, `run` commits what is left and pushes the branch once. The start commit is inside the same guard, so an interrupt there is covered. SIGTERM makes `run` unwind like Ctrl-C and exit with code 143. The push runs under the lock and sends the branch tip read under the lock, with `git push origin <tip>:refs/heads/results/<ID>`. Every network command (fetch and push) runs with `GIT_TERMINAL_PROMPT=0` and a 60-second timeout, so a credential prompt or a hung network cannot block the run. There is no push per attempt. A failed push, or no remote `origin`, prints `warning: push of results/<ID> failed: <reason>` to stderr, before any error message so a budget error stays the last stderr line, and does not change the exit code.
   7. After the push, `run` runs `git gc --auto --quiet` and ignores a failure. Every record is a commit, so the local repository grows with history until git compacts it.

Loop order: for each input, for each AI model, for each setup (`no_model`, `descriptive`, `prescriptive`), for attempt number 1 to `attempts`:

1. Skip the attempt if its record already exists, keyed by input id, setup, AI model, and attempt number. That lets a stopped run start again where it left off. The raw file is read with `read_raw(path) -> (records, skipped_count)` in `src/run/raw.py`, which [evaluate](evaluate.md) also uses. `src/run/raw.py` is an assessment file, because it decides which raw lines get scored. It skips and counts every line that does not parse as a JSON object, because a stopped write leaves a torn line and a later run ends it with a newline, so it can sit anywhere in the file. A record that parses but lacks a key field is a checked error that names the file. Before it appends, `run` writes a newline if the file does not end with one, and it never rewrites a line.
2. Build the prompt with [prompts](prompts.md) from the release's templates.
3. Check the budgets. Spent cost is the [cost](../definitions.md#baseline-and-prices) of the raw records already written, computed by the same function [evaluate](evaluate.md) uses: this AI model's file for the model budget, and every raw file of the experiment for the experiment budget. `run` re-reads the other AI models' files before each call, so separate processes share the experiment budget. If spent cost plus the next worst-case request cost would pass `per_model_usd` or `per_experiment_usd`, `run` makes no call, writes nothing for that attempt, prints which budget stopped it, the cost spent, and the attempts left, and exits with code 1. The same check runs before every retry, counting the retry tokens so far in the attempt at the AI model's prices. If it stops a retry, `run` still writes the attempt's record as `infrastructure_failure` with those retry tokens, so paid spend is never hidden, and then exits with code 1. Raising the budget and running again resumes. Within one process there is no overshoot, even with `--parallel`: each in-flight attempt reserves its worst-case request cost, and the check adds the reservations of the other in-flight attempts of the process to the spent cost (see "Parallel requests"). Separate processes running at once can each pass the experiment budget by at most their own in-flight requests. For a decision model the spent cost is read once per attempt, before its first call, and each later call adds only the attempt's own paid tokens and the other attempts' reservations at that moment.
4. Call [models](models.md). On `InfrastructureError`, retry up to `retry_cap` times, adding any token counts from the failed calls to the retry token fields. Never retry for any other reason.
5. If the cap is reached, the raw response is empty and `stop_reason` is `infrastructure_failure`.
6. Run the [validator](validator.md) and write the record. The first [impossible move](../definitions.md#puzzles) in a reply makes the outcome `hallucination`: the attempt fails, the reply is stored whole, and `run` never asks again, because retries are for [infrastructure failures](../definitions.md#attempts-and-outcomes) only. The loop calls the model (with retries) and passes the reply and the retry token counts to the function that builds the record, so building a record never calls an API.

A decision model's attempt is not one call, so step 4 and 5 are replaced by `run_decision_attempt()` in `src/run/decision.py`, which returns a `DecisionResult`:

1. For call `k`, `call_decision()` gets `decision_state(prompt, moves so far)` and `decision_questions(questions, legal_moves())`. The questions come from `load_questions()` of the release's prompts.
2. `can_afford(retry_in, retry_out)` runs before every call. A `BudgetError` before the first call is raised. A later one ends the loop with stop reason `infrastructure_failure`, and `play` writes the record, commits as usual, and then raises the `BudgetError`.
3. An `InfrastructureError` adds its tokens to the retry tokens and counts one retry. Past `retry_cap` retries in the attempt, the loop stops with `infrastructure_failure`. A `RefusedError` stops it with `refused`, never retried.
4. After each completed call, the loop stops when the choice is `done` or `mismatch`, or when the choice can't be read or mapped to `move_<n>` (stop reason `ok`, and the validator rules `malformed_output`). Otherwise the move is added, and the loop stops when the moves number `max_moves`.
5. The record holds: `raw_response` is `json.dumps` of the completed calls; `input_tokens` and `output_tokens` are their sums; `latency_s` their sum; `served_model` the distinct values joined with `,`; `retry_*_tokens` the sums over failed calls; `prompt_version` is `decision_prompt_versions[setup][puzzle]`; the validator runs with `decision=True`. With `infrastructure_failure` and completed calls, the raw response, tokens, latency, and served model keep those calls. With none, the record is as for any AI model: raw response `""`, tokens 0, latency empty, served model `""`. A call whose reply has no `model` adds nothing to the served model, so the joined value can be empty.
6. `can_afford` gets every token the attempt has paid so far, failed and completed calls together, so the budget check counts the attempt's own earlier calls at the AI model's prices.
7. A call is read with `read_decision_call()` in the [validator](validator.md), the same reader the validator uses, so the loop stops on the first call the validator would rule `malformed_output`: a missing choice, or an id that is not an exact `move_<n>`, `done`, or `mismatch`. The stop reason is `ok` and the call is kept.
8. The questions are loaded once per run with `load_questions()`, and `worst_state()` and `worst_request()` live in `src/run/budget.py`.

Each record has every field in [invariant 13](../../AGENTS.md#invariants): `experiment_id`, `release_version`, `input_id`, `input_set_id`, `puzzle`, `scramble_depth`, `validity`, `setup`, `prompt_version`, `model`, `seed`, `input_seed`, `attempt_number`, `raw_response`, `parsed_moves`, `outcome`, `hallucination`, `mismatch`, `move_count`, `input_tokens`, `output_tokens`, `retry_input_tokens`, `retry_output_tokens`, `latency_s`, `stop_reason`, `served_model`, `decision`, and `requested_model`, plus `created_at`. `decision` is true when the AI model's provider is in `DECISION_PROVIDERS`, and `requested_model` is the model entry's `api_model_id`, for every outcome. Readers accept records with or without these two fields; [`is_decision_record`](../../src/run/raw.py) is the one place that reads `decision` and falls back to the config rule for a record without it. It never holds a cost or a metric.

At the end, `run` prints a count of outcomes.

## Parallel requests

With `--parallel N` above 1, `run` keeps up to N attempts in flight. With 1 it runs them one at a time, in the main thread, as before.

1. Worker split. Daemon worker threads do only the API part of an attempt: `call_with_retries()` or `run_decision_attempt()`. The main thread does everything else, in completion order: `make_record` (which runs the validator), `append_record`, the outcome count, the progress update, and the commit. So file writes, progress, and git stay single-threaded.
2. In-flight set. Attempts are submitted in loop order, and a new one starts as each finishes. The attempts in flight are always the first N attempts without a record, in loop order. The [UI](ui.md) relies on this.
3. Completion order. Records are appended as attempts finish, so with N above 1 the order of lines in a raw file can differ from loop order. Resume keys on input id, setup, AI model, and attempt number, so it does not matter.
4. Reservations. An attempt reserves its worst-case request cost from its submission until its record is appended, under a lock. Its first budget check adds the reservations of the attempts submitted before it, so attempts started together are admitted in loop order and a budget refuses the last of them. Its later checks (a retry, or the next call of a decision model) add the reservations of all other in-flight attempts.
5. Budget stop. After a `BudgetError` no new attempt starts. The attempts in flight finish and their records are written and committed as usual, and then the first `BudgetError` is raised, so the `error: budget reached:` line stays the last stderr line.
6. Interrupt. Ctrl-C or SIGTERM stops `run` at once and does not wait for in-flight calls. Their attempts get no record, and a resume runs them again. The `finally` in `run()` still commits and pushes what was written. The workers are daemon threads, so none keeps the process alive after `run()` returns.
7. An exception other than `InfrastructureError` raised in a worker (a bug, an unexpected SDK error) is raised in the main thread and ends the run.

## Progress

`src/run/progress.py` shows how the run is going, after every appended record. It is display only: nothing it computes goes into a raw record ([invariant 12](../../AGENTS.md#invariants)). `--dry-run` and `--estimate` show none. It counts the records already in the raw files of the AI models this process runs, so a resumed run shows the whole experiment. The totals are the attempts already recorded plus the attempts still to run.

1. On a terminal, it draws with `rich` (a dependency in `pyproject.toml`):
   1. A global bar: attempts done of the total, elapsed time, and the estimated time left.
   2. One bar per AI model and puzzle.
   3. A table with one row per AI model and a total row: attempts, input tokens, output tokens (retry tokens included), cost in USD from [`attempt_cost`](evaluate.md) and the prices in config, success rate, hallucination rate, malformed output rate, mismatch detection rate (invalid inputs only), false mismatch rate (valid inputs only), and the infrastructure failure count. Rates leave out attempts with outcome `infrastructure_failure`, as the [metrics](../definitions.md#metrics) say, and show `n/a` when nothing is left to divide by.
   4. The last attempt: AI model, puzzle, input id, setup, attempt number, and outcome.
2. When stdout is not a terminal, as in the UI log, it imports nothing from `rich` and prints one line per attempt: `[12/90] A 2x2 i-0003 descriptive #1 success | in 1234 out 567 | $0.0123 | success 40% hallucination 10% malformed 0%`. The counters and rates cover all AI models of the process. `rich` is imported only on the terminal path, so an old venv without it still runs from the UI.
3. The final `N new attempts: ...` line stays.

## How to test

All tests use the `fake` provider and temporary folders.

1. One run writes inputs × models × 3 setups × attempts records.
2. A second run with the same config adds no lines.
3. A run stopped with `--limit 5` and then run again ends with the same set of records as one full run, compared by input id, setup, AI model, and attempt number, apart from `created_at` and `latency_s`.
4. `--model A` writes only `raw/A.jsonl`.
5. A fake that fails 5 times in a row with `retry_cap = 3` gives one record with outcome `infrastructure_failure`, an empty raw response, and 4 calls made.
6. A fake that returns a malformed reply (a truncated stop reason) is called once, never retried.
7. Changing one byte of the release's `inputs.jsonl` makes `run` exit with code 1 before any call.
8. Changing one byte of `src/validator.py` makes `run` exit with code 1 before any call.
9. Patching the engine's `render()` makes `run` exit with code 1 before any call.
10. Changing anything but `[budget]` in the experiment config after the first run makes `run` exit with code 1.
11. Every record has every field listed above, and no other.
12. A torn line at the end of a raw file, and one in the middle (including one that ends in `}`), is skipped, and the run resumes after it.
13. `--dry-run` and `--estimate` write no file and make no call, and `--estimate` prints the attempt count the full run would make.
14. With fake replies that each cost 0.01 USD, a worst-case request cost of 0.01 USD, `per_model_usd = 0.035`, and no records yet, `run` makes 3 calls, then exits with code 1 naming the model budget. Raising the budget to 1.00 and running again finishes the experiment.
15. Two AI models with the same costs and `per_experiment_usd = 0.045` stop after 4 calls in total, naming the experiment budget.
16. A worst-case request cost above `per_request_usd` makes `run` exit with code 1 before any call, naming the model.
17. A config with no `[budget]` uses the defaults, and changing only `[budget]` after the first run is accepted and updates `results/<ID>/experiment.toml`.
18. A model missing from `config/prices.toml` makes `run` exit with code 1 before any call.
19. On a release with 2x2 and 3x3, `puzzles = ["2x2"]` writes records for 2x2 inputs only, and a config with no `puzzles` writes both.
20. A `puzzles` name that the release doesn't hold makes `run` exit with code 1 before any call, naming the config path and `puzzles`.
21. After a full run, `refs/heads/results/<ID>` holds every raw file with the same bytes as the work tree, and the work tree status, the index, and `HEAD` are unchanged.
22. The branch has one commit per new attempt plus the start commit.
23. With a temporary bare remote as `origin`, the branch is pushed at exit. Without one, `run` exits with code 0 and stderr carries the push warning.
24. A budget stop still commits and pushes, and the last stderr line starts with `error: budget reached:`.
25. `--no-commit`, `--dry-run`, and `--estimate` create no branch.
26. Outside a git work tree, `run` exits with code 1 before any call.
27. A raw file that is on the branch but gone from the work tree stays on the branch, and a `.experiment.toml.*.tmp` is never committed.
28. A local branch behind `origin` is moved forward at the start. A diverged one makes `run` exit with code 1 before any call, naming both refs.
29. A forced commit failure warns, and the `error: budget reached:` line stays the last stderr line.
30. An interrupt (`KeyboardInterrupt`) and SIGTERM, both raised mid-run, still commit and push the records written, and SIGTERM exits with code 143.
31. With fake replies in a known order and no terminal, `run` prints one progress line per new attempt with the right counters and rates, and a resumed run counts the records already written.
32. Rates leave out attempts with outcome `infrastructure_failure`, and show `n/a` for an empty denominator.
33. `--dry-run` and `--estimate` print no progress line.
34. A smoke test draws the `rich` display into a string with an injected console and checks that the AI model names appear.
35. `--config -` with a config on stdin runs like the same config in a file, writes no file under `config/experiments/`, and commits `results/<ID>/experiment.toml` to the branch. A config on stdin that breaks a check exits with code 1 and an error naming `<stdin>`, before any write or call.
36. A work-tree raw file shorter than the branch's (or missing, for an AI model in scope) makes `run` exit with code 1 before any write or call, naming the file and the `git checkout` fix, and makes no call. A work-tree file that extends the branch file runs, and `--model B` ignores a stale file of A.
37. A decision attempt of several calls reads the spent cost once, not once per call.
38. `--parallel 4` writes the same set of records as `--parallel 1`, compared by input id, setup, AI model, and attempt number, apart from `created_at` and `latency_s`.
39. The fake never sees more than N calls at once, and does see N at once when enough attempts are pending.
40. While N attempts are in flight, they are the first N pending attempts in loop order.
41. With `--parallel 4`, fake replies costing 0.01 USD, a worst-case request cost of 0.01 USD, and `per_model_usd = 0.035`, there are never more than 3 records, and `run` exits with code 1 naming the model budget.
42. A budget stop with attempts in flight writes their records before the error, and the error is the last stderr line.
43. An interrupt with attempts in flight commits the records written and returns promptly, well before the fake's blocked calls would finish.
44. `--parallel 0` exits with code 1 naming `--parallel`.
