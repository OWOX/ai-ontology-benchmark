# Spec: docs/specs/ui.md
"""Pure builders for the bundle's `providers` and the experiment form. Reads nothing and writes nothing."""

from src.run.models import KEY_VARIABLES

PROVIDER_ORDER = ("anthropic", "openai", "google", "openrouter", "typesafe", "cloudflare", "fake", "fake_decision")
NO_PRICE = "no price in config/prices.toml"
# Providers listed even with no catalogue models, so their key can be saved before the first model is added.
ALWAYS_LISTED = ("openrouter",)


def config_form(config: dict, release_puzzles: list[str]) -> dict:
    """The experiment form (spec: HTTP API item 5) for a parsed experiment config."""
    return {"id": config["experiment_id"], "release": config["release"],
            "puzzles": list(config.get("puzzles") or release_puzzles),
            "models": [m["name"] for m in config["models"]], "attempts": config["attempts"],
            "retry_cap": config["retry_cap"], "max_output_tokens": config["max_output_tokens"],
            "reasoning_effort": config.get("reasoning_effort"),
            "budget": dict(config["budget"])}


def build_providers(catalogue: dict[str, dict], prices: dict, experiments: list[dict]) -> list[dict]:
    used: dict[tuple, list[str]] = {}
    for exp in experiments:
        for m in exp["config"]["models"] if exp["config"] else []:
            used.setdefault((m["provider"], m["api_model_id"]), []).append(exp["id"])
    names = list(PROVIDER_ORDER) + sorted({e["provider"] for e in catalogue.values()} - set(PROVIDER_ORDER))
    out = []
    for name in names:
        models = []
        for e in (e for e in catalogue.values() if e["provider"] == name):
            price = prices.get(e["name"])
            ok = isinstance(price, dict) and {"price_input_per_mtok", "price_output_per_mtok"} <= set(price)
            models.append({"name": e["name"], "api_model_id": e["api_model_id"], "kind": e.get("kind"),
                           "params": e.get("params", {}),
                           "price": {"input_per_mtok": price["price_input_per_mtok"],
                                     "output_per_mtok": price["price_output_per_mtok"]} if ok else None,
                           "disabled_reason": None if ok else NO_PRICE,
                           "experiments": sorted(set(used.get((name, e["api_model_id"]), [])))})
        if not models and name not in ALWAYS_LISTED:
            continue
        out.append({"name": name, "variable": KEY_VARIABLES.get(name), "key": None, "models": models})
    return out

