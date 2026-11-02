# Spec: docs/specs/run.md
"""Budget helpers for run, including the --estimate printout. Reads prices and budgets handed
in by the caller, and the raw files results/<ID>/raw/<model name>.jsonl of one experiment.
Writes nothing to a file.
"""

import math
from pathlib import Path

from src.evaluate.metrics import attempt_cost
from src.puzzles.registry import get_engine
from src.run.models import DECISION_PROVIDERS
from src.run.prompts import build_prompt, worst_state
from src.run.raw import read_raw

TOLERANCE = 1e-9  # keeps float rounding from stopping a run that sits exactly on a limit


class BudgetError(Exception):
    """A checked error. The message names the file, model, or budget at fault."""


def worst_case_request_cost(prompt: str, max_output_tokens: int, price: dict) -> float:
    """The most one request can cost: ceil(characters / 4) input tokens, a full-length answer."""
    input_tokens = math.ceil(len(prompt) / 4)
    return (input_tokens * price["price_input_per_mtok"]
            + max_output_tokens * price["price_output_per_mtok"]) / 1e6


def check_prices(config: dict, prices: dict, prices_path: Path) -> None:
    for model in config["models"]:
        if model["name"] not in prices:
            raise BudgetError(f"{prices_path}: no prices for model {model['name']!r}")


def check_request_budget(config_path: Path, config: dict, model: dict, prompt: str, prices: dict) -> None:
    cost = worst_case_request_cost(prompt, config["max_output_tokens"], prices[model["name"]])
    limit = config["budget"]["per_request_usd"]
    if cost > limit + TOLERANCE:
        raise BudgetError(f"{config_path}: worst-case request cost ${cost:.4f} for model "
                          f"{model['name']!r} is above field 'budget.per_request_usd' ({limit})")


def spent_by_model(config: dict, prices: dict, raw_dir: Path) -> dict[str, float]:
    """Cost so far of each AI model's raw records, read fresh so other processes count."""
    spent = {}
    for model in config["models"]:
        records, _ = read_raw(raw_dir / f"{model['name']}.jsonl")
        spent[model["name"]] = sum(attempt_cost(r, prices[model["name"]]) for r in records)
    return spent


def check_spend(config: dict, prices: dict, raw_dir: Path, model_name: str,
                next_cost: float, attempts_left: int, spent: dict[str, float] | None = None) -> None:
    """Raise BudgetError if the next worst-case request could pass the model or experiment budget.
    `spent` is a reading from spent_by_model; without it the raw files are read now."""
    if spent is None:
        spent = spent_by_model(config, prices, raw_dir)
    budget = config["budget"]
    left = f"{attempts_left} attempts left"
    if spent[model_name] + next_cost > budget["per_model_usd"] + TOLERANCE:
        raise BudgetError(
            f"budget reached: per_model_usd {budget['per_model_usd']} for model {model_name} "
            f"(spent {spent[model_name]:.4f}, next request up to {next_cost:.4f}); {left}")
    total = sum(spent.values())
    if total + next_cost > budget["per_experiment_usd"] + TOLERANCE:
        raise BudgetError(
            f"budget reached: per_experiment_usd {budget['per_experiment_usd']} "
            f"(spent {total:.4f}, next request up to {next_cost:.4f}); {left}")


def print_estimate(config: dict, pending: list, prices: dict, templates: Path, raw_dir: Path,
                   cap: int = 0) -> None:
    """A decision model's attempt makes up to cap calls, each as long as the longest state."""
    spent = spent_by_model(config, prices, raw_dir)
    budget = config["budget"]
    total = 0.0
    for model in config["models"]:
        name = model["name"]
        is_decision = model["provider"] in DECISION_PROVIDERS
        calls = cap if is_decision else 1
        prompts = []
        for row, m, setup, _ in pending:
            if m["name"] == name:
                prompt = build_prompt(templates, row, setup)
                if is_decision:
                    prompt = worst_state(prompt, get_engine(row["puzzle"]).legal_moves(), cap)
                prompts.append(prompt)
        cost = calls * sum(worst_case_request_cost(p, config["max_output_tokens"], prices[name]) for p in prompts)
        tokens_in = calls * sum(math.ceil(len(p) / 4) for p in prompts)
        total += cost
        print(f"{name}: {len(prompts)} attempts, ~{tokens_in} input tokens, worst case ${cost:.4f}; "
              f"spent ${spent[name]:.4f} of per_model_usd {budget['per_model_usd']}")
    print(f"total: {len(pending)} attempts, worst case ${total:.4f}; "
          f"spent ${sum(spent.values()):.4f} of per_experiment_usd {budget['per_experiment_usd']}; "
          f"per_request_usd {budget['per_request_usd']}")
