# Decision models implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run Jev, Clef, and Clef-flash as AI models through a per-move loop, judged by the same validator and metrics as the LLMs.

**Architecture:** A new loop driver, `src/run/decision.py`, makes one call per move to a decision-model client in `src/run/models.py` and returns every call's answers. `run` stores them as a JSON array in the raw response. The validator gets a second parse path that turns that array into moves and a mismatch flag. Question wording lives in `prompts/decision/questions.txt`, and a new manifest field versions it.

**Tech stack:** Python 3.11+, pytest, `typesafe-sdk` (Jev), `cloudflare` (Clef), vanilla JS for the UI.

**Spec:** `docs/superpowers/specs/2026-11-01-decision-models-design.md`. Read it before any task.

## Global constraints

1. Work only in the worktree `.claude/worktrees/decision-models`, branch `feat/decision-models`. Never touch the main checkout, where another session works.
2. Read `AGENTS.md`, `docs/definitions.md`, and `docs/methodology.md` first. Names in code follow `docs/definitions.md`.
3. Every script starts with a `# Spec: docs/specs/<file>.md` comment. A code change that departs from a spec changes that spec in the same commit.
4. Prose: plain Oxford English, British spelling with -ize endings, Oxford comma, no em dashes.
5. Commits: one change per commit, imperative subject like `git log --oneline`. Never add a Co-Authored-By trailer, "Generated with" line, or any mention of Claude or AI.
6. No AI model names in code. Model names come from `config/models.toml`.
7. Tests never touch the network. Run pytest only on the files named in the task, with `-p no:cacheprovider`. Never run the full suite in parallel.
8. Decision-model option ids are `move_1` to `move_N` (the position in `legal_moves()`, from 1) and `done`. Each move option's description is the move string. Ids never contain the move string, because moves contain `'`.
9. Question ids are exactly `next_move` (type `choice`) and `mismatch` (type `noul`).
10. The mismatch threshold is `0.5`: probability `>= 0.5` means on.
11. `DECISION_PROVIDERS = ("typesafe", "cloudflare", "fake_decision")` in `src/run/models.py` is the only place that says which providers are decision models.

## Review focus

1. A choice id that isn't offered (for example `move_99` or a raw move string) must give `malformed_output`, never an `IndexError`. Test in Task 2.
2. A call with `done` as the very first choice gives an empty move list, which is unsolved on a valid input and `failure`, not `malformed_output`. Test in Task 2.
3. A budget stop after some calls of an attempt must still write the record, with the completed calls kept and outcome `infrastructure_failure`, then stop. Test in Task 5.
4. An old release (1.1.1) has no `decision_prompt_versions`. LLM experiments on it must keep running, and a decision model on it must fail with a clear message naming the field. Test in Task 3.
5. The Cloudflare account id must never reach the page in full, and saving the token must not wipe a saved account id, and the reverse. Test in Task 6.

---

### Task 1: Docs, invariants, and config fields

**Files:**
- Modify: `AGENTS.md` (invariants 2, 9, 10, 13), `docs/definitions.md`, `docs/methodology.md`, `docs/specs/config.md`
- Modify: `src/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `src.config.PROVIDERS` includes `"typesafe"`, `"cloudflare"`, `"fake_decision"`. An experiment config may hold `max_moves` (int, at least 1). `src.config.max_moves(config: dict, release_config: dict) -> int` returns `config["max_moves"]` if set, else `2 * max(release_config["scramble_depths"])`.

- [ ] **Step 1: Write the failing tests** in `tests/test_config.py`, following the file's existing helpers for writing a temporary experiment config:

```python
def test_decision_providers_are_known():
    from src.config import PROVIDERS
    assert {"typesafe", "cloudflare", "fake_decision"} <= set(PROVIDERS)


def test_max_moves_default_and_override():
    from src.config import max_moves
    release = {"scramble_depths": [3, 7, 5]}
    assert max_moves({}, release) == 14
    assert max_moves({"max_moves": 9}, release) == 9


@pytest.mark.parametrize("value", [0, -1, "5", True])
def test_max_moves_must_be_positive_int(value):
    from src.config import parse_experiment_config
    text = 'release = "1.0.0"\nattempts = 1\nretry_cap = 0\nmax_output_tokens = 10\n' \
           f"max_moves = {value!r}\n".replace("'", '"').replace("True", "true") + \
           '[[models]]\nname = "m"\nprovider = "fake"\napi_model_id = "x"\n'
    with pytest.raises(ValueError, match="max_moves"):
        parse_experiment_config(text, "e", "e.toml")
```

- [ ] **Step 2: Run them and see them fail.** Run: `python -m pytest -q -p no:cacheprovider tests/test_config.py`. Expected: the three new tests fail.

- [ ] **Step 3: Implement** in `src/config.py`:

```python
PROVIDERS = ("anthropic", "openai", "google", "typesafe", "cloudflare", "fake", "fake_decision")
```

In `parse_experiment_config`, after `max_output_tokens`:

```python
    if "max_moves" in config:
        _check_min(path, "max_moves", _get(path, config, "max_moves", int), 1)
```

And a new function:

```python
def max_moves(config: dict, release_config: dict) -> int:
    """The move cap of a decision-model attempt: the config value, or twice the largest scramble depth."""
    return config.get("max_moves", 2 * max(release_config["scramble_depths"]))
```

- [ ] **Step 4: Run the tests and see them pass.** Same command. Expected: all pass.

- [ ] **Step 5: Update the docs** with the approved text from the spec's "Docs and invariants" section:
  1. `AGENTS.md` invariant 2: add `max moves` to the list of config parameters.
  2. Invariant 9: add "A decision model's raw response is instead the JSON array of its calls' answers, and the validator builds the moves and the mismatch flag from it."
  3. Invariant 10: add "For a decision model, the retry cap counts retries across all calls of an attempt, and the raw record keeps the calls that completed."
  4. Invariant 13: add "For a decision model, tokens and latency are summed over its calls, and the served model joins the distinct values."
  5. `docs/definitions.md`: add **Decision model** (Setups section: an AI model that returns probabilities over options defined in the request and never generates text; it answers through a per-move loop), **Call** (one request inside an attempt), and **Max moves** (Recorded values or Inputs: the cap on moves in one decision-model attempt; a config parameter, default twice the largest scramble depth). Change **Attempt** to "one or more requests", and **Raw response**, **Input tokens and output tokens**, **Latency**, **Served model**, **Stop reason**, **Malformed output**, **Infrastructure failure** (a decision-model attempt keeps its completed calls), and **Worst-case request cost** (per call; for a decision model, the state with `max_moves` moves).
  6. `docs/methodology.md`: one paragraph under "The variable" naming the four consequences in the spec's "Consequences for the results".
  7. `docs/specs/config.md`: the new providers and `max_moves`.

- [ ] **Step 6: Commit.** `git add AGENTS.md docs src/config.py tests/test_config.py && git commit -m "Add decision-model providers and max_moves to the config and the definitions"`

---

### Task 2: Validator path for decision models

**Files:**
- Modify: `src/validator.py`, `docs/specs/validator.md`
- Modify: `src/evaluate/metrics.py` (pass the flag), `src/evaluate/evaluate.py` if it builds the provider map
- Test: `tests/test_validator.py`, `tests/test_evaluate.py`

**Interfaces:**
- Consumes: `DECISION_PROVIDERS` is defined in Task 4. Until then this task defines nothing about providers. The validator takes a boolean.
- Produces: `validate(input: dict, raw_response: str, stop_reason: str, decision: bool = False) -> Verdict`. With `decision=True`, `raw_response` is the JSON array described below. `src/evaluate/metrics.make_attempt_rows(raw_records, inputs, prices, cache, decision_models: set[str] = frozenset())` passes `decision=raw["model"] in decision_models`. `evaluate` builds `decision_models` from the experiment config: `{m["name"] for m in config["models"] if m["provider"] in DECISION_PROVIDERS}`. Import `DECISION_PROVIDERS` from `src.run.models` only in `evaluate.py`, after Task 4. Until Task 4 lands, define the set with a literal tuple and leave a one-line comment that Task 4 moves it.

Raw response shape (decision path): a JSON array, one element per completed call, each `{"answers": {"next_move": {"type": "choice", "choice": "move_3", ...}, "mismatch": {"type": "noul", "noul": 0.12}}, "usage": {...}, "model": "..."}`.

- [ ] **Step 1: Write the failing tests** in `tests/test_validator.py`. Build inputs the way the file already does: a valid 2x2 input one move from solved, and an invalid one. The helper below makes the array:

```python
import json

def calls(*steps, puzzle="2x2"):
    """steps: (move or 'done' or a raw id, mismatch probability). Returns the raw response."""
    from src.puzzles.registry import get_engine
    legal = get_engine(puzzle).legal_moves()
    out = []
    for choice, p in steps:
        cid = "done" if choice == "done" else (f"move_{legal.index(choice) + 1}" if choice in legal else choice)
        out.append({"answers": {"next_move": {"type": "choice", "choice": cid},
                                "mismatch": {"type": "noul", "noul": p}},
                    "usage": {"input_tokens": 10, "output_tokens": 0}, "model": "m"})
    return json.dumps(out)


def test_decision_solves(valid_one_move):          # the input solved by one move, e.g. its inverse
    v = validate(valid_one_move, calls((valid_one_move["solution"], 0.1), ("done", 0.1)), "ok", decision=True)
    assert v.outcome == "success" and v.move_count == 1 and not v.hallucination


def test_decision_done_first_is_failure(valid_one_move):
    v = validate(valid_one_move, calls(("done", 0.1)), "ok", decision=True)
    assert v.outcome == "failure" and v.parsed_moves == []


def test_decision_mismatch_in_later_call(invalid_input):
    v = validate(invalid_input, calls(("R", 0.2), ("U", 0.7)), "ok", decision=True)
    assert v.mismatch and v.outcome == "success" and v.parsed_moves == ["R", "U"]


@pytest.mark.parametrize("raw", ["not json", "{}", json.dumps([{"answers": {}}]),
                                 json.dumps([{"answers": {"next_move": {"choice": "move_99"},
                                                          "mismatch": {"noul": 0.1}}}]),
                                 json.dumps([{"answers": {"next_move": {"choice": "R"},
                                                          "mismatch": {"noul": 0.1}}}])])
def test_decision_malformed(valid_one_move, raw):
    assert validate(valid_one_move, raw, "ok", decision=True).outcome == "malformed_output"


def test_decision_cap_reached_is_infrastructure(valid_one_move):
    v = validate(valid_one_move, calls(("R", 0.1)), "infrastructure_failure", decision=True)
    assert v.outcome == "infrastructure_failure"
```

Adapt the fixture names to the file's existing input helpers. `valid_one_move["solution"]` stands for the move that solves it. Compute it from the input's scramble (the inverse of a one-move scramble) in the fixture.

- [ ] **Step 2: Run and see them fail.** `python -m pytest -q -p no:cacheprovider tests/test_validator.py`

- [ ] **Step 3: Implement** in `src/validator.py`:

```python
MISMATCH_THRESHOLD = 0.5


def _parse_decision(raw_response: str, legal: list[str]) -> tuple[list[str], bool] | None:
    """Return (moves, mismatch) from a decision model's array of calls, else None."""
    try:
        data = json.loads(raw_response)
    except ValueError:
        return None
    if not isinstance(data, list) or not data:
        return None
    moves, mismatch = [], False
    for call in data:
        try:
            choice = call["answers"]["next_move"]["choice"]
            probability = call["answers"]["mismatch"]["noul"]
        except (KeyError, TypeError):
            return None
        if not isinstance(probability, (int, float)) or isinstance(probability, bool):
            return None
        mismatch = mismatch or probability >= MISMATCH_THRESHOLD
        if choice == "done":
            break
        if not (isinstance(choice, str) and choice.startswith("move_") and choice[5:].isdigit()
                and 1 <= int(choice[5:]) <= len(legal)):
            return None
        moves.append(legal[int(choice[5:]) - 1])
    return moves, mismatch
```

In `validate`, add the `decision: bool = False` parameter. After the stop-reason checks, read `engine` and `legal` first, then `parsed = _parse_decision(raw_response, legal) if decision else _parse(raw_response)`. Everything after is unchanged.

- [ ] **Step 4: Run and see them pass.** Same command.

- [ ] **Step 5: Thread the flag through `evaluate`.** In `src/evaluate/metrics.py`, `make_attempt_rows` gets `decision_models: set[str] = frozenset()` and calls `validate(source, raw["raw_response"], raw["stop_reason"], decision=raw["model"] in decision_models)`. `evaluate.py` builds the set from `config["models"]` and passes it. Add a test in `tests/test_evaluate.py` that writes one decision raw record with a solving array and checks its row outcome is `success`. Run `python -m pytest -q -p no:cacheprovider tests/test_evaluate.py tests/test_validator.py`.

- [ ] **Step 6: Update `docs/specs/validator.md`** with the decision path, the option ids, and the threshold.

- [ ] **Step 7: Commit.** `git commit -m "Validate decision-model answers from the array of their calls"` with the files above.

---

### Task 3: Questions file, decision state, and decision prompt versions

**Files:**
- Create: `prompts/decision/questions.txt`
- Modify: `src/run/prompts.py`, `src/release/release.py`, `src/run/run.py` (`load_release` only), `src/evaluate/evaluate.py` (`check_release` only), `docs/specs/prompts.md`, `docs/specs/release.md`
- Test: `tests/test_prompts.py`, `tests/test_release.py`, `tests/test_run.py`

**Interfaces:**
- Produces:
  - `load_questions(templates_dir: Path) -> dict[str, str]` returns `{"next_move": ..., "done": ..., "mismatch": ...}`. It raises `ValueError` naming the file if it is missing or lacks a key.
  - `decision_state(prompt: str, moves: list[str]) -> str` returns `prompt + "\n\nMoves so far: " + (" ".join(moves) or "none")`.
  - `decision_questions(questions: dict, legal: list[str]) -> dict` returns the request's `questions` object: `{"next_move": {"type": "choice", "instructions": questions["next_move"], "criteria": {"move_1": legal[0], ..., "done": questions["done"]}}, "mismatch": {"type": "noul", "instructions": questions["mismatch"]}}`.
  - `decision_prompt_versions(templates_dir: Path, inputs: list[dict]) -> dict[str, dict[str, str]]` returns `{setup: {puzzle: version}}`, where the version is the first 12 hex characters of sha256 over the questions file's bytes, then every prompt `build_prompt` makes for that setup and puzzle in input order, each followed by `"\n"`.
  - The manifest gets a new field, `decision_prompt_versions`. `run.load_release(folder, needs_decision: bool)` checks it only when the field is present, and raises `RunError("<manifest>: field 'decision_prompt_versions' is missing; decision models need a release cut after they were added")` when `needs_decision` is true and the field is absent.

- [ ] **Step 1: Create `prompts/decision/questions.txt`**, the approved text, one `key: text` per line:

```
next_move: Which move should be applied next to solve the puzzle, after the moves so far? Pick done when the moves so far solve it.
done: The moves so far solve the puzzle.
mismatch: Is this state impossible to reach from the solved state by legal moves?
```

- [ ] **Step 2: Write the failing tests** in `tests/test_prompts.py`:

```python
def test_decision_state():
    from src.run.prompts import decision_state
    assert decision_state("P", []) == "P\n\nMoves so far: none"
    assert decision_state("P", ["R", "U'"]) == "P\n\nMoves so far: R U'"


def test_decision_questions_ids():
    from src.run.prompts import decision_questions
    q = decision_questions({"next_move": "n", "done": "d", "mismatch": "m"}, ["R", "U'"])
    assert q["next_move"]["criteria"] == {"move_1": "R", "move_2": "U'", "done": "d"}
    assert q["mismatch"] == {"type": "noul", "instructions": "m"}


def test_load_questions_missing_key(tmp_path):
    from src.run.prompts import load_questions
    (tmp_path / "decision").mkdir()
    (tmp_path / "decision" / "questions.txt").write_text("next_move: n\ndone: d\n")
    with pytest.raises(ValueError, match="mismatch"):
        load_questions(tmp_path)


def test_decision_versions_change_with_questions(tmp_path, inputs_2x2):
    ...  # copy prompts/ to tmp_path, compute versions, edit questions.txt, versions differ;
         # prompt_versions (the LLM ones) stay equal
```

Write the last test out fully using the file's existing fixtures for inputs and prompt folders.

- [ ] **Step 3: Run and see them fail**, then **implement** the four functions in `src/run/prompts.py`, and run again until they pass.

- [ ] **Step 4: Releases.** In `src/release/release.py`, compute `decision_versions = decision_prompt_versions(PROMPTS_DIR, inputs)`, add it to the manifest, add a "Decision prompt versions" table to the README, and make `check_bump_rules` treat a change in either field as a prompt change. A missing field in the old manifest counts as different. The template copy glob already includes `decision/questions.txt`. Add tests in `tests/test_release.py`: a minor bump is accepted when only `questions.txt` changed, and a patch bump is refused then.

- [ ] **Step 5: `load_release`.** Give it a `needs_decision: bool` parameter (the caller passes `any(m["provider"] in DECISION_PROVIDERS for m in config["models"])`, using the literal tuple until Task 4). When the field is present, compare it with `decision_prompt_versions(folder / "prompts", inputs)`. Add the two tests from Review focus item 4 in `tests/test_run.py`. Do the same field comparison in `evaluate.check_release` when both manifests hold it.

- [ ] **Step 6: Update `docs/specs/prompts.md` and `docs/specs/release.md`.** Run `python -m pytest -q -p no:cacheprovider tests/test_prompts.py tests/test_release.py tests/test_run.py tests/test_evaluate.py`. Commit: `git commit -m "Add the decision-model questions and version them in the release manifest"`.

---

### Task 4: Decision-model clients

**Files:**
- Modify: `src/run/models.py`, `pyproject.toml`, `docs/specs/models.md`, `docs/specs/setup.md` if it lists dependencies
- Test: `tests/test_models.py`

**Interfaces:**
- Produces:
  - `DECISION_PROVIDERS = ("typesafe", "cloudflare", "fake_decision")`
  - `KEY_VARIABLES` gains `"typesafe": "TYPESAFE_API_KEY"` and `"cloudflare": "CLOUDFLARE_API_TOKEN"`
  - `ACCOUNT_VARIABLES = {"cloudflare": "CLOUDFLARE_ACCOUNT_ID"}`
  - `@dataclass(frozen=True) class DecisionReply: call: dict; input_tokens: int; output_tokens: int; served_model: str; latency_s: float`, where `call` is `{"answers": ..., "usage": ..., "model": ...}` exactly as returned, ready for the raw response array
  - `call_decision(model: dict, state: str, questions: dict) -> DecisionReply`. It raises `InfrastructureError` on a network error, a timeout, HTTP 429, or 5xx. It raises `RefusedError` (new, subclass of `Exception`) on a content-filter refusal. It raises `ValueError` for a missing key or account id.
  - `FAKE_DECISION_REPLIES: list`. Tests fill it. Each fake call pops the first item: a `DecisionReply` is returned, an `InfrastructureError` or `RefusedError` instance is raised. When empty, the fake returns a reply whose `next_move` choice is `done` and whose `mismatch` is `0.0`.

- [ ] **Step 1: Install and read the SDKs.** `.venv/bin/python -m pip install typesafe-sdk==0.7.5 cloudflare==5.9.0`. Then read their code to get the exact calls. Don't guess:
  1. `typesafe_sdk`: find the client class, its constructor (`api_key`, a retries setting), the System One method (path `/v1/systemone`, constant `SYSTEM_ONE_PATH` in `typesafe_sdk/_core/constants.py`), its return type, and the error classes in `typesafe_sdk/_core/errors.py` (`TypeSafeRateLimitError`, `TypeSafeInternalServerError`, `TypeSafeAPIConnectionError`, `TypeSafeAPITimeoutError`). The retry policy is in `typesafe_sdk/_core/retry.py`, `max_retries` default 2. Switch it off with 0.
  2. `cloudflare`: `cloudflare.Cloudflare(api_token=..., max_retries=0)` and `client.ai.run(model_name, account_id=..., extra_body={...})` in `cloudflare/resources/ai/ai.py`. Find what it returns for an unknown task (the `result` object, already unwrapped from the envelope, or the envelope itself) and its error classes (`cloudflare.APIConnectionError`, `cloudflare.APIStatusError` with `status_code`).
  3. Add both to `pyproject.toml` `dependencies`, pinned with `>=` to these versions.

- [ ] **Step 2: Write the failing tests** in `tests/test_models.py`. Stub each SDK by monkeypatching the client constructor the client function uses, so no request leaves the process:

```python
def test_cloudflare_call_shape(monkeypatch):
    sent = {}
    class FakeAI:
        def run(self, name, account_id, extra_body):
            sent.update(name=name, account_id=account_id, body=extra_body)
            return {"model": "clef-flash", "answers": {"next_move": {"type": "choice", "choice": "done"},
                    "mismatch": {"type": "noul", "noul": 0.1}}, "usage": {"input_tokens": 40, "output_tokens": 0}}
    class FakeClient:
        def __init__(self, api_token, max_retries):
            assert max_retries == 0
            self.ai = FakeAI()
    monkeypatch.setattr(models, "_cloudflare_client", FakeClient)  # the name the code uses
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "t"); monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "a")
    reply = models.call_decision({"provider": "cloudflare", "api_model_id": "@cf/cloudflare/clef-flash",
                                  "name": "clef-flash"}, "S", {"q": 1})
    assert sent == {"name": "@cf/cloudflare/clef-flash", "account_id": "a",
                    "body": {"model": "clef-flash", "state": "S", "questions": {"q": 1}}}
    assert reply.input_tokens == 40 and reply.served_model == "clef-flash"
    assert set(reply.call) == {"answers", "usage", "model"}
```

The Clef REST `model` field is the short name (`clef` or `clef-flash`): the part of `api_model_id` after the last `/`. Add the same shape test for `typesafe`, plus these:
  1. HTTP 429 and 503 raise `InfrastructureError` for both providers.
  2. HTTP 400 is not retried: the SDK's error propagates.
  3. A missing `CLOUDFLARE_ACCOUNT_ID` raises `ValueError` naming it.
  4. The fake pops in order.

- [ ] **Step 3: Implement.** Keep the pattern of `_anthropic`: a module-level reference to the SDK client class (`_cloudflare_client`, `_typesafe_client`) so tests can replace it, `time.perf_counter()` latency, and the error mapping. Cloudflare's response passes through `result` unwrapping only if Step 1 showed the SDK returns the envelope. Content filter: if either SDK has a distinct refusal error or code, map it to `RefusedError`. If neither has one, say so in the spec and don't invent one.

- [ ] **Step 4: Run** `python -m pytest -q -p no:cacheprovider tests/test_models.py` until it passes. **Update** `docs/specs/models.md` (both providers, the account id, the fake). **Replace** the literal provider tuples left by Tasks 2 and 3 with imports of `DECISION_PROVIDERS`. **Commit:** `git commit -m "Add the Jev and Clef decision-model clients"`.

---

### Task 5: The loop driver and run

**Files:**
- Create: `src/run/decision.py`
- Modify: `src/run/run.py` (`play`, `make_record`, the request budget check), `src/run/budget.py` (`print_estimate` if it builds prompts per attempt), `docs/specs/run.md`
- Test: `tests/test_decision.py` (new), `tests/test_run.py`

**Interfaces:**
- Consumes: `call_decision`, `DecisionReply`, `RefusedError`, `InfrastructureError`, and `FAKE_DECISION_REPLIES` (Task 4). `decision_state`, `decision_questions`, and `load_questions` (Task 3). `max_moves` (Task 1).
- Produces:

```python
@dataclass(frozen=True)
class DecisionResult:
    calls: list[dict]           # completed calls, in order; becomes the raw response array
    stop_reason: str            # ok, refused, or infrastructure_failure
    input_tokens: int           # summed over completed calls
    output_tokens: int
    retry_input_tokens: int     # summed over failed calls
    retry_output_tokens: int
    latency_s: float | None     # summed over completed calls; None with no completed call
    served_model: str           # distinct served models, first-seen order, joined with ","
    budget_stop: Exception | None  # a BudgetError raised after the first call, else None


def run_decision_attempt(model: dict, prompt: str, legal: list[str], questions: dict,
                         cap: int, retry_cap: int, can_afford) -> DecisionResult: ...


def worst_state(prompt: str, legal: list[str], cap: int) -> str:
    """The longest state any call of the attempt can send: the prompt with `cap` of the longest move."""
    return decision_state(prompt, [max(legal, key=len)] * cap)
```

Loop rules, from the spec:
1. `can_afford(retry_in, retry_out)` runs before every call. A `BudgetError` before the first call of the attempt is raised. A later one ends the loop with `stop_reason="infrastructure_failure"` and `budget_stop` set.
2. An `InfrastructureError` adds its tokens to the retry tokens and counts one retry. When the retries in this attempt pass `retry_cap`, stop with `stop_reason="infrastructure_failure"`.
3. A `RefusedError` stops with `stop_reason="refused"`.
4. After each completed call, stop if `noul >= 0.5` or the choice is `done`. Otherwise append the move. Stop when the moves number `cap`.
5. The choice id maps back to the move with `legal[int(id[5:]) - 1]`. An id the loop can't map stops the loop with `stop_reason="ok"`, and the validator then rules `malformed_output`.

- [ ] **Step 1: Write the failing tests** in `tests/test_decision.py`, driving the fake through `models.FAKE_DECISION_REPLIES`. Build each reply with a helper `reply(choice_id, p, tokens=10, model="m", latency=0.5)`. Cover:
  1. Stop on `done` after two moves: 3 calls, tokens 30, latency 1.5.
  2. Stop on mismatch in call 1, and in call 2.
  3. Stop at `cap=2` without `done`: exactly 2 calls.
  4. Two infrastructure errors with `retry_cap=1`: stop, keeping the completed calls. The retry tokens hold the failed calls' tokens.
  5. One infrastructure error with `retry_cap=1`, then success: the loop continues.
  6. A budget stop before call 1 raises. A budget stop before call 2 returns `budget_stop`.
  7. Served models `a`, `b`, `a` give `"a,b"`.
  8. Each call's `state` is `decision_state(prompt, moves so far)`. Capture it with a fake that records its arguments.

- [ ] **Step 2: Run, see them fail, implement `src/run/decision.py`, run until they pass.** `python -m pytest -q -p no:cacheprovider tests/test_decision.py`

- [ ] **Step 3: Wire into `run`.**
  1. In `play`, when `model["provider"] in DECISION_PROVIDERS`, call `run_decision_attempt` with `build_prompt(...)`, the engine's `legal_moves()`, `load_questions(folder / "prompts")`, `max_moves(config, manifest["release_config"])`, `config["retry_cap"]`, and `can_afford`. `worst` is `worst_case_request_cost(worst_state(prompt, legal, cap), config["max_output_tokens"], price)`.
  2. `make_record` gets an optional `decision: DecisionResult | None`. When set, the record uses `raw_response=json.dumps(result.calls)`, the sums, `latency_s`, `stop_reason`, `served_model`, and `validate(row, raw, stop, decision=True)`.
  3. Write the record, then raise `budget_stop` if set.
  4. `check_request_budget` uses `worst_state` for decision models. `print_estimate` does the same, and multiplies the worst case per call by `cap + 1` calls per attempt.
  5. `--dry-run` prints the first call's state and the questions.
  6. `prompt_version` in the record is `manifest["decision_prompt_versions"][setup][puzzle]` for a decision model.

- [ ] **Step 4: End-to-end test** in `tests/test_run.py`, using the file's `exp` fixture with a model `{"name": "d", "provider": "fake_decision", "api_model_id": "x"}` and a release that has `decision_prompt_versions`. Fill `FAKE_DECISION_REPLIES` so one attempt solves, one is malformed, and one reaches the retry cap. Run `run`, then `evaluate`. Check the three outcomes in the raw records and in the report CSV's counts. Also add Review focus item 3 (a budget stop mid-attempt writes the record, then stops).

- [ ] **Step 5: Run** `python -m pytest -q -p no:cacheprovider tests/test_decision.py tests/test_run.py tests/test_evaluate.py tests/test_pipeline.py`. **Update** `docs/specs/run.md`. **Commit:** `git commit -m "Run decision models through a per-move loop"`.

---

### Task 6: UI: the Cloudflare account id and the provider list

**Files:**
- Modify: `ui/secrets.py`, `ui/catalogue.py`, `ui/server.py` or `ui/app.py` (wherever `POST /api/secrets` is handled), `ui/static/pages/models.js`, `ui/static/style.css` if needed, `docs/specs/ui.md`
- Test: `tests/test_ui.py`, `tests/test_ui_bundle.py`

**Interfaces:**
- Consumes: `KEY_VARIABLES`, `ACCOUNT_VARIABLES` (Task 4).
- Produces:
  1. `secrets/cloudflare.json` holds `{"api_key": ..., "account_id": ...}`.
  2. `POST /api/secrets` accepts an optional `account_id` for `cloudflare` only. Saving one field keeps the other.
  3. `inspect` adds `"account": {"source": "env"|"file"|"missing"}` for providers in `ACCOUNT_VARIABLES`, never the value.
  4. `env(root)` also returns `CLOUDFLARE_ACCOUNT_ID` from the file when the env var is unset.
  5. `configured` is true only when both are set.
  6. `PROVIDER_ORDER = ("anthropic", "openai", "google", "typesafe", "cloudflare", "fake", "fake_decision")`, and `build_providers` leaves out a provider with no catalogue models, so the empty Fake block disappears.

- [ ] **Step 1: Write the failing tests:**
  1. Saving token then account id keeps both.
  2. Clearing deletes the file.
  3. `inspect` never contains the account id string.
  4. A provider with no models is absent from the bundle.
  5. `POST` with `account_id` for `anthropic` gives 400 naming `account_id`.

  Follow the existing secrets tests in `tests/test_ui.py`.

- [ ] **Step 2: Implement, run, pass.** `python -m pytest -q -p no:cacheprovider tests/test_ui.py tests/test_ui_bundle.py` (about 4 minutes).

- [ ] **Step 3: `models.js`.** For a provider with `key.account`, the edit row shows a second password field, placeholder `CLOUDFLARE_ACCOUNT_ID` (or 12 dots if saved), in the same row before Save. Save sends both fields, and an empty field means keep the saved value. The badge says `configured` only when both are set, and its tooltip names what is missing. `node --check ui/static/pages/models.js`.

- [ ] **Step 4: Update `docs/specs/ui.md`** (Models, HTTP API item 16, and the provider order). **Commit:** `git commit -m "Store the Cloudflare account id with its token and hide empty providers"`.

---

### Task 7: Catalogue and prices

**Files:**
- Modify: `config/models.toml`, `config/prices.toml`
- Test: `tests/test_config.py` (the catalogue and prices load and every catalogue model has a price)

- [ ] **Step 1: Add the three catalogue entries** from the spec's table, each `kind = "system-1"` and `params = {}`. Jev's `api_model_id` is `jev-latest`, the alias TypeSafe's own API reference uses. The served model in every raw record shows the version behind the alias. Put a comment above the entry saying so.

- [ ] **Step 2: Add the prices** with a comment naming the sources and dates: clef 0.24/0, clef-flash 0.038/0 (Cloudflare model pages and changelog, 2026-10-09), jev 0.042/0 (OpenRouter and Requesty listings, 2026-09-19; TypeSafe's own pricing page was not found).

- [ ] **Step 3: Test.** If `tests/test_config.py` has no test that loads `config/models.toml` and `config/prices.toml` and checks every catalogue name has a price, add one. Run it.

- [ ] **Step 4: Commit.** `git commit -m "Add Jev, Clef, and Clef-flash to the catalogue and prices"`

---

## After the tasks

1. An Opus review of the whole branch.
2. The project owner merges `feat/experiment-ui` and this branch, then cuts minor release 1.2.0 with `release`. The validator change alters the assessment hash, and `questions.txt` adds decision prompt versions, so `run` refuses 1.1.1 for decision models and asks for the new release.
