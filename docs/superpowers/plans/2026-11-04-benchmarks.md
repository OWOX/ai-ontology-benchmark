# Benchmarks page plan

Spec: `docs/specs/ui.md` sections "Benchmarks" (under Page), HTTP API item 25, How to test item 31; `docs/definitions.md` Metrics item 13 (paired model test). The spec is binding; read those sections in full before coding.

## Global Constraints

1. Read AGENTS.md (UI architecture rules, Writing rules) first. Data comes from git refs only via `GitData` (`git show`/`ls-tree`), never the work tree.
2. Every new file starts with a comment linking to its spec (`# Spec: docs/specs/ui.md` / `// Spec: docs/specs/ui.md (Benchmarks)`), like its neighbours.
3. Do not edit anything under `src/` (it is the assessment; changing it changes the release hash). Import `sign_test`, `holm`, `rates`, `wilson`, `consistency`, `NA` from `src.evaluate.metrics`; do not copy them.
4. No AI model names in code. No new dependencies. No external scripts in the page: SVG charts are hand-built.
5. Tests: `.venv/bin/python -m pytest -q tests/test_ui_bundle.py tests/test_ui.py tests/test_ui_js.py` from the repo root (the venv lives at `/Users/flakss/Projects/ai-ontology-hallucination-research/.venv`). Never run more than 4 workers in parallel.
6. British spelling with -ize endings in prose and UI text. No Claude attribution or `Co-Authored-By` in commits. Small commits, one change each.
7. Match surrounding code style: short docstrings, the `h = UI.el` DOM builder, comment density as in `ui/expdata.py` and `ui/static/pages/experiments.js`.

## Task 1: Backend — `ui/benchmarks.py` and `GET /api/benchmarks`

Files: create `ui/benchmarks.py`; modify `ui/bundle.py` (a `Bundles.benchmarks(query, live_ids)` method or equivalent that reuses `_load_all`, `releases`, `_manifest`, `is_mirror`, and an in-memory cache keyed like the bundle), `ui/app.py` (route `GET /api/benchmarks`, parse comma lists from the query), `tests/test_ui_bundle.py` (tests for How to test item 31).

1. Implement HTTP API item 25 exactly: response shape, defaults, 400 errors naming the field, unknown model ignored.
2. Experiments selected by own release ∈ releases or a mirror of one; each read once; scored from raw records via `expdata.attempt_rows` with the experiment's own release inputs; an experiment whose `error` is set goes into `skipped`.
3. Attach `input_set_id` (from the experiment release's manifest) to each attempt row for pairing; pair key is `(input_set_id, input_id)`.
4. Cells: rates via `src.evaluate.metrics.rates` on non-infrastructure rows, pooled per validity scope the same way `expdata.all_scope_rates` / `group_metrics` do (mismatch detection over invalid rows, false mismatch over valid rows); efficiency (successes on valid inputs, move_count/reference_length, mean; null under invalid only), consistency (`consistency`), latency per attempt (mean `latency_s` of non-infra rows), tokens per attempt (mean of input+output+retry input+retry output over all rows), cost per success (sum cost / successes, null when none). Metric keys: `success_rate`, `hallucination_rate`, `mismatch_detection_rate`, `false_mismatch_rate`, `malformed_output_rate`, `efficiency`, `consistency`, `latency_per_attempt_s`, `tokens_per_attempt`, `cost_per_success`. `n` for non-rate cells = attempts covered.
5. best/worst/tests per spec items 4–5: rank cells with non-null value by direction; tie with the next → null; for rate rows run the paired model test (per-input share of hits per model, inputs both have, sign test on discordant inputs via `sign_test(a_higher, b_higher)`), Holm over the row's distinct tests (one when two cells).
6. Tests per How to test item 31, using the existing fixtures in `tests/test_ui_bundle.py` (temporary repo with bare origin, `fake` provider).

## Task 2: Frontend — Benchmarks page

Files: create `ui/static/pages/benchmarks.js`; modify `ui/static/router.js` (MENU gets `["benchmarks", "Benchmarks"]` first), `ui/static/index.html` (script tag), `ui/server.py` (`STATIC_FILES` gets `pages/benchmarks.js`), `ui/static/style.css` (winner/loser tokens for both themes, chart grid, two-level table headers).

1. Implement the spec's "Benchmarks" section items 1–5 against the API shape in HTTP API item 25 (Task 1 builds the endpoint; code against the documented JSON).
2. The page loads `/api/benchmarks` itself via `UI.api`, keyed on the request-affecting hash params; significance and metrics changes redraw without a request. Hash params only when they differ from defaults.
3. Multi-select dropdowns reuse the `details.col-picker` pattern from `pages/experiments.js` (including the reopen-after-rerender behaviour).
4. Colours: define `--win` / `--lose` (and soft background variants) tokens in `style.css` for light and dark, following how existing tokens are themed there. Charts: inline SVG, small multiples in a wrapping grid, neutral bars except coloured winner/loser, Wilson whiskers on rates, 0–100% axis for rates, values above bars, model names below.
5. `node --check` passes (covered by `tests/test_ui_js.py`). Check by hand with Playwright screenshots in light and dark at 900 and 1500 px wide against a running server (start with `./ui/start.sh` pattern or `python -m ui.server --port 0` per `ui/server.py`); save screenshots in the repo `tmp/` folder.
