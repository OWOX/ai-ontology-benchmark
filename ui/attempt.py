# Spec: docs/specs/ui.md
"""One attempt's prompt and raw response, for the experiment page's terminal. The prompt is rebuilt
from the experiment's release on main (never the work tree); the record comes from the experiment's
branch, as in replay. Writes nothing.
"""

import json
import tempfile
from pathlib import Path

from src.puzzles.registry import get_engine
from src.run.models import DECISION_PROVIDERS
from src.run.prompts import decision_questions, decision_state, fill_template, load_questions
from ui import expdata
from ui.common import ApiError, check_id
from ui.replay import parse_query


def attempt(bundles, experiment_id: str, live_ids: set[str], query: dict) -> dict:
    query = {**query, "input_id": query.get("input", [])}  # this route names the field `input`
    try:
        model_name, input_id, setup, number = parse_query(query)
    except ApiError as error:
        raise ApiError(error.status, error.message.replace("'input_id'", "'input'")) from None
    exp = bundles.loaded(check_id(experiment_id), live_ids)
    config = exp["config"]
    if config is None:
        raise ApiError(400, exp["error"])
    model = next((m for m in config["models"] if m["name"] == model_name), None)
    if model is None:
        raise ApiError(404, f"model {model_name} is not in experiment {experiment_id}")
    git, release = bundles.git, config["release"]
    row = next((r for r in expdata.read_inputs(git, git.main_ref(), release) if r["input_id"] == input_id), None)
    if row is None:
        raise ApiError(404, f"input {input_id} is not in release {release}")
    folder = f"releases/{release}/prompts"
    template = git.show(git.main_ref(), f"{folder}/{setup}/{row['puzzle']}.txt")
    if template is None:
        raise ApiError(404, f"release {release} has no {setup} template for {row['puzzle']}")
    prompt = fill_template(template, row, setup)
    if model["provider"] in DECISION_PROVIDERS:
        text = git.show(git.main_ref(), f"{folder}/decision/questions.txt")
        if text is None:
            raise ApiError(404, f"release {release} has no decision questions file")
        with tempfile.TemporaryDirectory() as tmp:  # load_questions reads a folder, so lay the text out as one
            (Path(tmp) / "decision").mkdir()
            (Path(tmp) / "decision" / "questions.txt").write_text(text, encoding="utf-8")
            try:
                questions = load_questions(Path(tmp))
            except ValueError as error:
                raise ApiError(404, f"release {release}: {error}") from None
        asked = decision_questions(questions, get_engine(row["puzzle"]).legal_moves())
        prompt = f"{decision_state(prompt, [])}\n--- questions\n{json.dumps(asked, indent=2)}"
    record = next((r for r in exp["records"].get(model_name, []) if r.get("input_id") == input_id
                   and r.get("setup") == setup and r.get("attempt_number") == number), None)
    return {"prompt": prompt, "raw_response": record.get("raw_response") if record else None, "record": record}
