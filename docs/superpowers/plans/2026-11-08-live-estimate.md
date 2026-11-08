# Live estimate, sliders, inputs per depth, and a live score card

Spec: `docs/definitions.md`, `docs/methodology.md`, `AGENTS.md`, and `docs/specs/` (`config.md`, `run.md`, `ui.md`). Each task writes its own spec change first, in the same commit as the code, and the specs are then the authority. Decisions from the project owner, 2026-11-08:

1. The live estimate comes from a server endpoint that runs the same budget code as `run --estimate`, in process, with no subprocess.
2. The time estimate uses the median latency per attempt of each AI model over its pushed experiments.
3. Sliders: attempts per input and setup, and a new config parameter, inputs per depth, that runs a balanced sample of the release. Setups stay fixed at 3.
4. The Experiment page gets a live score card with the headline metrics and the spend and time.

## Global constraints

1. Build to the spec. If code has to differ, change the spec in the same commit and say so in the report.
2. Every script starts with a comment linking its spec. Names in code follow `docs/definitions.md`. A new term goes into `docs/definitions.md` before it is used anywhere else.
3. Do not touch the assessment files (`src/validator.py`, `src/puzzles/*.py`, `src/run/raw.py`, `src/evaluate/evaluate.py`, `src/evaluate/metrics.py`, `src/run/decision.py`, `src/run/prompts.py`). `tests/test_release.py::test_assessment_hash_matches_the_newest_release_manifest` must keep passing.
4. Do not change any invariant in `AGENTS.md`.
5. No AI model names in code. No Claude attribution anywhere, including commit trailers.
6. British spelling with -ize endings, Oxford comma. Plain, short sentences.
7. Small commits, one change each.
8. Run tests with `/Users/flakss/Projects/ai-ontology-hallucination-research/.venv/bin/python -m pytest -q -p no:cacheprovider <files>` from the worktree root. Run only the test files you touched plus `tests/test_ui*.py` when you touch `ui/`. Never more than 4 workers. Never create a venv.
9. Never edit anything under `releases/` or `results/`.
10. The UI reads releases and experiments from git (`ui/gitdata.py`), never from the work tree, except where `docs/specs/ui.md` already says so.

## Task 1: Inputs per depth

Files: `docs/definitions.md`, `docs/specs/config.md`, `docs/specs/run.md`, `src/config.py`, `src/run/run.py`, `ui/forms.py`, `ui/expdata.py` or wherever the UI filters the snapshot's inputs by `puzzles`, and their tests.

1. Definitions, under Inputs, after Valid/invalid split: **Inputs per depth.** The number of valid inputs per puzzle and scramble depth that an experiment runs, a config parameter of the experiment config. With it, `run` plays the first that many valid inputs of each puzzle and depth, in release order, and the first invalid inputs of the same group, as many as `ceil(k × invalid / valid)`, where `k` is inputs per depth and `invalid` and `valid` are the group's counts in the release. So a sample keeps the release's share of invalid inputs, rounded up, and at least one invalid input when the group has any. Without it, or when it is at least the group's valid count, `run` plays the whole group. A sample is a pilot: its results show how a run will go and are not evidence for the research question.
2. `config.md`: `inputs_per_depth`, optional, an integer of at least 1, in an experiment config. `load_experiment_config` leaves the key out when absent. Test it like `puzzles` in How to test (valid value, 0, a float, a bool, a string).
3. `run.md` and `src/run/run.py`: one function `experiment_inputs(config, inputs) -> list[dict]` that applies `puzzles` and then `inputs_per_depth`, in release order. `pending_attempts` uses it in place of its own `puzzles` filter. Every count `run` makes (attempts still to run, `--estimate`, `--dry-run`, `--limit`, budget checks, progress totals) follows from it. Tests: a group of 40 valid and 10 invalid with k = 1, 4, 5, 8, 40, and 100 gives 1+1, 4+1, 5+2, 8+2, 40+10, and 40+10; a group with no invalid inputs gives k+0; puzzles and inputs_per_depth together.
4. UI: `ui/forms.py` takes an optional `inputs_per_depth` from the form (absent or `null` means all; otherwise a whole number of at least 1, else 400 naming `inputs_per_depth`) and writes it into the config text. Loading a branch's config returns it. The snapshot (`GET /api/state/<id>`) and every place the UI counts an experiment's inputs or planned attempts use `experiment_inputs`, so the Experiment page's planned count is right. Update `ui.md` (the form shape in API 5, the snapshot's `inputs` sentence) to say so.

## Task 2: A pure estimate in budget.py

Files: `src/run/budget.py`, `docs/specs/run.md`, `tests/test_budget.py` (or the test file that covers `print_estimate`).

1. Split `print_estimate` into `estimate(config, pending, prices, questions, raw_dir, caps, prompts, with_reasons) -> dict` and a printer. The dict: `{"models": [{"name", "attempts", "input_tokens", "worst_case_usd", "spent_usd", "per_model_usd", "max_request_usd"}], "total": {"attempts", "worst_case_usd", "spent_usd", "per_experiment_usd"}, "per_request_usd"}`. `max_request_usd` is the largest worst-case request cost of the model's pending requests (one call for a decision model), 0 when none.
2. `spent_usd` comes from a `spent` mapping the caller can pass in, so a caller that holds records instead of a raw folder can use it: give `estimate` a `spent: dict[str, float] | None` argument; `None` reads `raw_dir` as today.
3. `print_estimate` prints exactly the same text as today, from the dict. The existing tests of the printed text pass unchanged. Add a test of the dict.
4. `run.md`: name `estimate` as the one place that computes the numbers, used by `--estimate` and the UI.

## Task 3: Live estimate endpoint

Files: new `ui/estimate.py`, `ui/app.py`, `docs/specs/ui.md`, new `tests/test_ui_estimate.py`.

1. `POST /api/estimate/live {form, "parallel": 4}`: checks the form as `POST /api/run` does (`ui/forms.py`, the same 400s), except that a model with no key is allowed (the estimate calls nothing). It reads the release's inputs, templates (`fill_template` on template text read with `git show`), and questions (`parse_questions`) from `origin/main` through `ui/gitdata.py`, applies `experiment_inputs`, removes attempts that already have a record on the experiment's branch when it exists (local branch first, then origin, as Inputs 6 and 7 say), and calls `budget.estimate` with `spent` computed from those records and `config/prices.toml` on `main`. A model with no price gives 400 naming it.
2. Cache by release and the refs read: rendered prompt lengths per input, setup, and puzzle, so a repeat call with a new attempts or sample value renders nothing. A call should answer in well under 250 ms on release 3.0.0 once warm.
3. Time. For each AI model, the median `latency_s` over the records of every pushed experiment (`origin/results/*`) whose model name matches, outcome not `infrastructure_failure`. Cache it by the refs read. The model's time is its attempts to run × median ÷ parallel. AI models run as parallel processes, so the total time is the largest model time. A model with no records gets `null` time and `latency_n` 0, and the total time is then `null`, with `"timing": "partial"`.
4. Response: the `estimate` dict, plus per model `median_latency_s`, `latency_n`, `time_s`, and `over` (true when worst case plus spent passes `per_model_usd`, or `max_request_usd` passes `per_request_usd`), plus `total.time_s`, `total.over` (worst case plus spent passes `per_experiment_usd`), `timing` (`"full"` or `"partial"`), and `counts`: `{"inputs", "models", "setups": 3, "attempts", "planned", "done", "to_run"}`, where `inputs` is the length of `experiment_inputs`, `planned` is inputs × models × setups × attempts, and `done` the planned attempts that already have a record.
5. `ui.md`: add the endpoint to the HTTP API list and explain the time source, in the spec's style.
6. Tests with the fake provider and a temporary git repo, as the other `tests/test_ui*.py` do: counts, spent from branch records, latency median, partial timing, the 400s, and that the numbers equal `run --estimate` for the same config (call `budget.estimate` both ways).

## Task 4: New Experiment sliders and live estimate

Files: `ui/static/pages/new.js`, `ui/static/style.css`, `docs/specs/ui.md` (New Experiment), and the UI tests that cover the page text or patterns.

1. Parameters column 2: "Attempts per input and setup" becomes a range slider from 1 to 10 with its value shown beside it. "Inputs per depth" is a new range slider from 1 to the release's valid inputs per puzzle and depth (the release's `scramble_count`; add it to the bundle if it is not there), whose top value reads "all" and sends `inputs_per_depth: null`. "Parallel requests" becomes a range slider from 1 to 16, default 4. Each keeps its value across a redraw as today and resets with the release.
2. A live estimate card above the buttons, always shown once at least one puzzle and one AI model are selected:
   1. The formula line: `<inputs> inputs × <models> AI models × 3 setups × <attempts> attempts = <planned> attempts`, and, for a loaded branch with records, `<done> done, <to_run> to run`.
   2. A table with one row per AI model: attempts to run, worst case, spent, model budget, median latency with its `n`, and time; and a Total row with the experiment budget and the total time. A worst case in the error colour when `over`. "no timing data yet" for a model with no latency, and the total time marked as partial.
   3. Times as `1 h 05 min`, `12 min`, or `40 s`.
   4. It requests `POST /api/estimate/live` 250 ms after the last change to any field, puzzle, or AI model, drops a response older than the newest request, and shows the server's error in the card.
3. Remove the Estimate button, its result block, and its table parsing. Dry run and Run stay as they are. `POST /api/estimate` stays on the server for the CLI path. Remove the test that kept the page's estimate patterns in step with `run --estimate` only if nothing else uses them.
4. Update `ui.md` New Experiment item 4 to match, in the spec's style.

## Task 5: Live score card on the Experiment page

Files: new `ui/scorecard.py`, `ui/app.py`, `ui/static/pages/experiment.js`, `ui/static/style.css`, `docs/specs/ui.md` (HTTP API and Experiment), new `tests/test_ui_scorecard.py`.

1. `GET /api/scorecard/<id>` reads the experiment as `GET /api/state/<id>` does and returns, for each AI model: done and planned attempts, and the point values (no intervals, so no bootstrap) of balanced precision, coverage, hallucination rate, reason hallucination rate, and critical thinking, from `src.evaluate.metrics` (`make_attempt_rows`, `answer_class`, `rates` or the helpers `ui/expdata.py` already uses); cost so far from `config/prices.toml` on `main`; and cost efficiency. Plus totals: cost so far against `per_model_usd` per model and `per_experiment_usd`, elapsed time from the first record's `created_at` to now while a run job is alive (to the last record's `created_at` otherwise), and time left: for each running model, attempts left × the median latency of this experiment's own records of that model (the pushed history from Task 3 when it has fewer than 5) ÷ its `parallel`, the largest over models. `null` where a value is n/a.
2. The page shows the card at the top, above the progress bar: one tile per headline metric per AI model (one row per AI model), then spend against each budget as a bar, elapsed, and time left. While a run job is alive it says "live" and polls the endpoint every 5 seconds; otherwise it loads once. Every value carries the `*` display-only mark and the note that it is computed by the UI from the raw records, like the computed Summary.
3. `ui.md`: the endpoint and the card, in the spec's style. Experiment item 1 becomes the card and then the progress bar.
4. Tests: values on a small fake experiment equal those of `src.evaluate.metrics` for the same records, elapsed and time left with and without a running job, and n/a values as `null`.

## Task 6: Definition tooltips on every input and metric

Owner request, 2026-11-08: "show (i) and tooltip definition next to each input and metric when available".

Files: `ui/bundle.py`, `ui/static/router.js` (or a new shared `ui/static/definitions.js` loaded before the pages), `ui/static/pages/benchmarks.js`, `ui/static/pages/new.js`, `ui/static/pages/experiment.js`, `ui/static/pages/experiments.js`, `ui/static/expmetrics.js`, `ui/static/progress.js` or wherever the score card and estimate card render, `ui/static/style.css`, `docs/specs/ui.md`, and the UI tests.

1. Bundle: add `definitions`: `{"terms": {"<term>": {"text": "...", "source": "<url>#<section anchor>"}}}`, holding every numbered bold term of every section of `docs/definitions.md` on `main`, parsed as `metric_definitions` is today (plain text, links keep their text, backticks dropped). Keep `metric_definitions` as it is, so Benchmarks keeps working, or move Benchmarks onto `definitions` and drop it, in one commit with the spec. The UI never keeps a second copy of a definition.
2. One shared helper builds the (i) icon and its tooltip, the one Benchmarks uses today (`.tip-wrap`, `.tip-fixed`, `aria-describedby`, placed below or above, closed by a click, the icon links to the term's section). Benchmarks uses the shared helper.
3. A term with no definition gets no icon. Never write a fallback text.
4. Where: every field on New Experiment (Puzzles, AI models, each budget, attempts per input and setup, inputs per depth, retry cap, max output tokens if a term exists, reasoning effort, limit if a term exists, parallel requests), every column of the live estimate table (attempts, worst case, spent, budget, latency), every metric of the score card, every rate column of the Summary and Full metrics tables, and every metric column of the Experiments list. The mapping from a UI label to a term name lives in one table in the shared helper file, keyed by the term exactly as `docs/definitions.md` writes it.
5. `ui.md`: Bundle item for `definitions`, and one paragraph saying where the icons go, in the spec's style.
6. Tests: the bundle parses terms from more than one section with the right anchors; the label-to-term table names only terms that exist in `docs/definitions.md` (a test reads the file and the JS table).

## Last step: screenshots

After the final review, start a UI server from the worktree on a free port with `--no-lan`, open New Experiment with two puzzles and two AI models selected and the live estimate filled, and an Experiment page with a score card, and save both screenshots under the project's `tmp/` at deviceScaleFactor 2. Send them to the owner. Stop that server afterwards.
