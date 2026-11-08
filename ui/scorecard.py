# Spec: docs/specs/ui.md
"""The live score card behind `GET /api/scorecard/<id>`: for each AI model of an experiment, its attempts done and
planned and the point values of its headline metrics, its cost so far, and the experiment's elapsed and remaining
time. Point values only, no bootstrap, with the definitions of `src.evaluate.metrics`. Reads the experiment through
Bundles and the prices on `main`. Writes nothing. For display only.
"""

from datetime import datetime, timezone
from statistics import median

from src.evaluate.metrics import NA, attempt_cost, gave_moves, is_diagnosis, is_hit, mean, mean_of_two, share
from src.run.prompts import SETUPS
from ui import expdata, experiments
from ui.common import ApiError

OWN_LATENCY_MIN = 5  # fewer records of this model than this: use the pushed history instead


def cell(value: object) -> object:
    return None if value == NA else value


def parse_time(text: object) -> datetime | None:
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")) if isinstance(text, str) else None
    except ValueError:
        return None


def model_values(rows: list[dict], price: dict | None) -> dict:
    """The headline point values of one AI model's attempt rows. `rows` hold every attempt, infrastructure failures
    included, as `make_attempt_rows` gives them."""
    done = [r for r in rows if r["outcome"] != "infrastructure_failure"]
    classified = [r for r in done if r["answer_class"]]
    side = lambda part, label: [r for r in part if r["validity"] == label]
    precision = mean_of_two(share(side(classified, "valid"), lambda r: is_hit(r, "precision")),
                            share(side(classified, "invalid"), lambda r: is_hit(r, "precision")))
    coverage = share(done, lambda r: r["answer_class"] is not None)
    decision = bool(done) and all(r["decision"] for r in done)  # a decision model can't return an impossible move
    hallucination = NA if decision else share([r for r in done if gave_moves(r)], lambda r: r["impossible_move"])
    reasons = bool(done) and all(r["reasons"] for r in done)
    reason_hallucination = share([r for r in done if r["mismatch_reason"] is not None], lambda r: r["decoy"]) if reasons else NA
    thinking = (mean_of_two(share(side(done, "invalid"), is_diagnosis),
                            share(side(done, "valid"), lambda r: r["mismatch"]), complement=True) if reasons else NA)
    cost = sum(attempt_cost(r, price) for r in rows) if price else None
    efficiency = None
    if cost is not None and rows and isinstance(precision, float) and isinstance(coverage, float) and precision * coverage > 0:
        efficiency = cost / len(rows) / (precision * coverage)
    return {"balanced_precision": cell(precision), "coverage": cell(coverage), "hallucination_rate": cell(hallucination),
            "reason_hallucination_rate": cell(reason_hallucination), "critical_thinking": cell(thinking),
            "cost_usd": cost, "cost_efficiency": efficiency}


def priced(prices: dict, name: str) -> dict | None:
    price = prices.get(name)
    fields = ("price_input_per_mtok", "price_output_per_mtok")
    ok = isinstance(price, dict) and all(isinstance(price.get(f), (int, float)) and not isinstance(price.get(f), bool)
                                         for f in fields)
    return price if ok else None


def scorecard(bundles, experiment_id: str, live_ids: set[str], job_states: dict, parallels: dict, history,
              now: datetime | None = None) -> dict:
    """`history(remote)` gives the pushed (median latency, count) of each AI model (`LiveEstimate.medians`)."""
    now = now or datetime.now(timezone.utc)
    held = bundles.loaded_entry(experiment_id, live_ids)
    exp, config = held["exp"], held["exp"]["config"]
    if config is None:
        raise ApiError(400, exp["error"])
    release = config["release"]
    inputs = experiments.planned_inputs(bundles, config)
    manifest = bundles._manifest(release)
    every = expdata.read_inputs(bundles.git, bundles.git.main_ref(), release)
    rows = bundles._rows(held, {release: manifest}, {release: every})
    if exp["error"]:
        raise ApiError(400, exp["error"])
    prices = bundles._prices()
    planned = len(inputs) * len(SETUPS) * config["attempts"]
    running = {n for n, s in job_states.items() if s == "running" and n.startswith("run:")}
    alive = bool(running)
    times = [t for t in (parse_time(r.get("created_at")) for found in exp["records"].values() for r in found) if t]
    elapsed = None
    if times:
        elapsed = ((now if alive else max(times)) - min(times)).total_seconds()
    pushed = None
    models, left = [], []
    for model in config["models"]:
        name = model["name"]
        mine = [r for r in rows if r["model"] == name]
        done = len(mine)
        is_running = f"run:{name}" in running
        models.append({"name": name, "done": done, "planned": planned, "running": is_running,
                       **model_values(mine, priced(prices, name))})
        if is_running:
            own = [r["latency_s"] for r in mine if r["outcome"] != "infrastructure_failure"
                   and isinstance(r["latency_s"], (int, float))]
            typical = median(own) if len(own) >= OWN_LATENCY_MIN else None
            if typical is None:
                if pushed is None:
                    pushed = history(bundles.git.results_state()[2])
                typical = pushed.get(name, (None, 0))[0]
            parallel = max(1, parallels.get(name, 1))
            left.append(None if typical is None else max(0, planned - done) * typical / parallel)
    costs = [m["cost_usd"] for m in models]
    budget = config["budget"]
    return {"id": experiment_id, "live": alive, "models": models,
            "total": {"done": sum(m["done"] for m in models), "planned": planned * len(models),
                      "cost_usd": None if None in costs else sum(costs),
                      "per_model_usd": budget["per_model_usd"], "per_experiment_usd": budget["per_experiment_usd"],
                      "elapsed_s": elapsed,
                      "time_left_s": None if not left or None in left else max(left)}}
