# Spec: docs/specs/site.md
"""The three headline metrics of the public results page, one row per puzzle and AI model, pooled over
every setup, depth, and experiment. Built on the assessment helpers in src/evaluate/metrics.py."""

from collections import defaultdict

from src.evaluate.metrics import NA, answer_class, is_diagnosis, mean_of_two, share

ALL = "all"  # the puzzle value of the rows pooled over every puzzle


def value(x: object, n: int) -> dict:
    return {"value": None if x == NA or x is None else x, "n": n}


def is_precise(row: dict) -> bool:
    return row["answer_class"] in ("tp", "tn")


def precision(rows: list[dict]) -> tuple[object, int]:
    """Balanced precision over classified rows, and how many there were."""
    classified = [r for r in rows if answer_class(r) is not None]
    both = (share([r for r in classified if r["validity"] == label], is_precise) for label in ("valid", "invalid"))
    return mean_of_two(*both), len(classified)


def hallucination(rows: list[dict]) -> dict:
    gave = [r for r in rows if r["parsed_moves"]]
    if not gave or all(r["decision"] for r in rows):
        return value(None, 0)
    return value(share(gave, lambda r: r["impossible_move"]), len(gave))


def critical(rows: list[dict]) -> dict:
    reasoned = [r for r in rows if r["reasons"]]
    valid = [r for r in reasoned if r["validity"] == "valid"]
    invalid = [r for r in reasoned if r["validity"] == "invalid"]
    diagnosis, false_mismatch = share(invalid, is_diagnosis), share(valid, lambda r: r["mismatch"])
    return value(mean_of_two(diagnosis, false_mismatch, True), len(reasoned))


def tokens(rows: list[dict]) -> int:
    """Input, output, retry input, and retry output tokens as stored in the raw records, summed."""
    return sum(r["input_tokens"] + r["output_tokens"] + r["retry_input_tokens"] + r["retry_output_tokens"]
               for r in rows)


def metric_row(puzzle: str, model: str, provider: str, everything: list[dict]) -> dict:
    rows = [r for r in everything if r["outcome"] != "infrastructure_failure"]
    balanced, classified = precision(rows)
    return {"puzzle": puzzle, "model": model, "provider": provider,
            "attempts": len(everything), "tokens": tokens(everything),
            "precision": value(balanced, classified), "hallucination": hallucination(rows),
            "critical": critical(rows)}


def metric_rows(attempt_rows: list[dict], providers: dict[str, str]) -> list[dict]:
    """One row per puzzle and AI model from re-validated attempt rows (`make_attempt_rows`), then one row per
    AI model with puzzle `all`, pooled over every puzzle."""
    groups = defaultdict(list)
    pooled = defaultdict(list)
    for r in attempt_rows:
        groups[(r["puzzle"], r["model"])].append(r)
        pooled[r["model"]].append(r)
    result = [metric_row(puzzle, model, providers.get(model, "unknown"), groups[(puzzle, model)])
              for (puzzle, model) in sorted(groups)]
    result += [metric_row(ALL, model, providers.get(model, "unknown"), pooled[model]) for model in sorted(pooled)]
    return result
