# Spec: docs/specs/ui.md
"""One attempt's prompt and raw response, for the experiment page's terminal. The prompt is rebuilt
from the experiment's release on main (never the work tree); the record comes from the experiment's
branch, as in replay. Writes nothing.
"""

import json

from src.puzzles.registry import get_engine
from src.run.models import DECISION_PROVIDERS
from src.run.prompts import decision_questions, decision_state, fill_template, parse_questions
from src.validator import offered_reasons
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
    row = expdata.find_input(git, release, input_id)
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
        try:
            questions = parse_questions(text, f"releases/{release}/prompts/decision/questions.txt")
        except ValueError as error:
            raise ApiError(404, str(error)) from None
        engine = get_engine(row["puzzle"])
        manifest = json.loads(git.show(git.main_ref(), f"releases/{release}/manifest.json") or "{}")
        offered = offered_reasons(engine) if manifest.get("mismatch_reasons") else None
        asked = decision_questions(questions, engine.legal_moves(), offered)
        prompt = f"{decision_state(prompt, [])}\n--- questions\n{json.dumps(asked, indent=2)}"
    record = expdata.find_record(exp["records"].get(model_name, []), input_id, setup, number)
    return {"prompt": prompt, "raw_response": record.get("raw_response") if record else None, "record": record}
