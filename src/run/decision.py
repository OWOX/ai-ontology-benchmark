# Spec: docs/specs/run.md
"""The per-move loop of a decision model: one attempt is a series of calls, one move per call.
Reads nothing from disk. Writes nothing. The caller builds the record from the DecisionResult.
"""

from dataclasses import dataclass

from src.run.budget import BudgetError
from src.run.models import InfrastructureError, RefusedError, call_decision
from src.run.prompts import decision_questions, decision_state
from src.validator import MISMATCH_THRESHOLD, read_decision_call

@dataclass(frozen=True)
class DecisionResult:
    calls: list[dict]  # completed calls, in order; becomes the raw response array
    stop_reason: str  # ok, refused, or infrastructure_failure
    input_tokens: int  # summed over completed calls
    output_tokens: int
    retry_input_tokens: int  # summed over failed calls
    retry_output_tokens: int
    latency_s: float | None  # summed over completed calls; None with no completed call
    served_model: str  # distinct served models, first-seen order, joined with ","
    budget_stop: Exception | None  # a BudgetError raised after the first call, else None


def run_decision_attempt(model: dict, prompt: str, legal: list[str], questions: dict,
                         cap: int, retry_cap: int, can_afford) -> DecisionResult:
    """Run the loop for one attempt. `questions` is the object from load_questions(), read once
    per run. `can_afford(paid_in, paid_out)` gets every token the attempt has paid so far, retried
    and completed calls together, and raises BudgetError before a call that would pass a budget:
    raised before the first call, returned in budget_stop after."""
    asked = decision_questions(questions, legal)
    calls: list[dict] = []
    moves: list[str] = []
    tokens_in = tokens_out = retry_in = retry_out = retries = 0
    latency = 0.0
    served: list[str] = []
    stop = "ok"
    budget_stop = None
    started = False
    while True:
        try:
            can_afford(retry_in + tokens_in, retry_out + tokens_out)
        except BudgetError as error:
            if not started:
                raise
            stop, budget_stop = "infrastructure_failure", error
            break
        started = True
        try:
            reply = call_decision(model, decision_state(prompt, moves), asked)
        except InfrastructureError as error:
            retry_in += error.input_tokens
            retry_out += error.output_tokens
            retries += 1
            if retries > retry_cap:
                stop = "infrastructure_failure"
                break
            continue
        except RefusedError:
            stop = "refused"
            break
        calls.append(reply.call)
        tokens_in += reply.input_tokens
        tokens_out += reply.output_tokens
        latency += reply.latency_s
        if reply.served_model not in served:
            served.append(reply.served_model)
        read = read_decision_call(reply.call, legal)
        if read is None:
            break  # a call the validator rejects ends the attempt; it rules malformed_output
        move, probability = read
        if move == "done" or probability >= MISMATCH_THRESHOLD:
            break
        moves.append(move)
        if len(moves) >= cap:
            break
    return DecisionResult(calls, stop, tokens_in, tokens_out, retry_in, retry_out,
                          latency if calls else None, ",".join(served), budget_stop)
