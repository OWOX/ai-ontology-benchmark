# Spec: docs/specs/run.md
"""Tests for the per-move loop of a decision model, driven by the fake decision provider."""

import pytest

from src.run import decision, models
from src.run.budget import BudgetError
from src.run.models import DecisionReply, InfrastructureError, RefusedError
from src.run.budget import worst_state
from src.run.prompts import decision_state

LEGAL = ["R", "R'", "U"]
QUESTIONS = {"next_move": "q", "done": "d", "mismatch": "m"}
MODEL = {"name": "D", "provider": "fake_decision", "api_model_id": "x"}


def reply(choice_id, tokens=10, model="m", latency=0.5):
    call = {"answers": {"next_move": {"type": "choice", "choice": choice_id}},
            "usage": {"input_tokens": tokens, "output_tokens": 0}, "model": model}
    return DecisionReply(call, tokens, 0, model, latency)


@pytest.fixture(autouse=True)
def fake(monkeypatch):
    monkeypatch.setattr(models, "FAKE_DECISION_REPLIES", [])
    return models.FAKE_DECISION_REPLIES


def attempt(cap=5, retry_cap=2, can_afford=lambda i, o: None):
    return decision.run_decision_attempt(MODEL, "P", LEGAL, QUESTIONS, cap, retry_cap, can_afford, "label")


def test_stops_on_done_after_two_moves(fake):
    fake[:] = [reply("move_1"), reply("move_3"), reply("done")]
    result = attempt()
    assert len(result.calls) == 3 and fake == []
    assert (result.input_tokens, result.latency_s, result.stop_reason) == (30, 1.5, "ok")


def test_stops_on_mismatch_in_the_first_call(fake):
    fake[:] = [reply("mismatch"), reply("move_2")]
    result = attempt()
    assert len(result.calls) == 1 and len(fake) == 1 and result.stop_reason == "ok"


def test_stops_on_mismatch_in_the_second_call(fake):
    fake[:] = [reply("move_1"), reply("mismatch"), reply("done")]
    assert len(attempt().calls) == 2 and len(fake) == 1


def test_an_old_probability_field_is_ignored(fake):
    call = reply("move_1").call
    call["answers"]["mismatch"] = {"type": "noul", "noul": 0.9}
    fake[:] = [DecisionReply(call, 1, 0, "m", 0.1), reply("done")]
    assert len(attempt().calls) == 2 and fake == []


def test_stops_at_the_cap_without_done(fake):
    fake[:] = [reply("move_1"), reply("move_2"), reply("move_3")]
    result = attempt(cap=2)
    assert len(result.calls) == 2 and len(fake) == 1 and result.stop_reason == "ok"


def test_two_infrastructure_errors_with_cap_one_stop(fake):
    fake[:] = [reply("move_1"), InfrastructureError("x", 7, 2), InfrastructureError("x", 7, 2), reply("done")]
    result = attempt(retry_cap=1)
    assert result.stop_reason == "infrastructure_failure" and len(result.calls) == 1
    assert (result.retry_input_tokens, result.retry_output_tokens) == (14, 4)
    assert (result.input_tokens, result.latency_s) == (10, 0.5) and len(fake) == 1


def test_infrastructure_error_is_logged_with_the_request_number(fake, capsys):
    fake[:] = [reply("move_1"), InfrastructureError("boom"), reply("done")]
    decision.run_decision_attempt(MODEL, "P", LEGAL, QUESTIONS, 5, 2, lambda i, o: None, "m in-1 no_model attempt 1")
    captured = capsys.readouterr()
    assert captured.err == "infrastructure error: m in-1 no_model attempt 1 call 2: boom\n"
    assert captured.out == ""


def test_one_infrastructure_error_with_cap_one_continues(fake):
    fake[:] = [InfrastructureError("x", 3, 1), reply("move_1"), reply("done")]
    result = attempt(retry_cap=1)
    assert result.stop_reason == "ok" and len(result.calls) == 2
    assert (result.retry_input_tokens, result.retry_output_tokens) == (3, 1)


def test_no_completed_call_leaves_latency_empty(fake):
    fake[:] = [InfrastructureError("x"), InfrastructureError("x")]
    result = attempt(retry_cap=1)
    assert result.calls == [] and result.latency_s is None and result.served_model == ""


def test_retries_count_across_all_calls(fake):
    fake[:] = [InfrastructureError("x"), reply("move_1"), InfrastructureError("x"), reply("move_1")]
    result = attempt(retry_cap=1)
    assert result.stop_reason == "infrastructure_failure" and len(result.calls) == 1


def test_budget_stop_before_the_first_call_raises(fake):
    fake[:] = [reply("done")]

    def stop(retry_in, retry_out):
        raise BudgetError("b")

    with pytest.raises(BudgetError):
        attempt(can_afford=stop)
    assert len(fake) == 1


def test_budget_stop_before_the_second_call_is_returned(fake):
    fake[:] = [reply("move_1"), reply("done")]
    seen = []

    def afford(retry_in, retry_out):
        seen.append((retry_in, retry_out))
        if len(seen) == 2:
            raise BudgetError("b")

    result = attempt(can_afford=afford)
    assert isinstance(result.budget_stop, BudgetError) and len(result.calls) == 1
    assert result.stop_reason == "infrastructure_failure" and len(fake) == 1


def test_served_models_are_joined_in_first_seen_order(fake):
    fake[:] = [reply("move_1", model="a"), reply("move_1", model="b"), reply("move_1", model="a"), reply("done", model="b")]
    assert attempt().served_model == "a,b"


def test_each_call_sends_the_prompt_and_the_moves_so_far(monkeypatch, fake):
    sent = []
    script = [reply("move_1"), reply("move_2"), reply("done")]

    def spy(model, state, questions):
        sent.append((state, questions))
        return script.pop(0)

    monkeypatch.setattr(decision, "call_decision", spy)
    attempt()
    assert [s for s, _ in sent] == [decision_state("P", m) for m in ([], ["R"], ["R", "R'"])]
    assert sent[0][1]["next_move"]["criteria"]["move_2"] == "R'"


def test_a_refusal_stops_with_refused(fake):
    fake[:] = [reply("move_1"), RefusedError("no")]
    result = attempt()
    assert result.stop_reason == "refused" and len(result.calls) == 1


@pytest.mark.parametrize("call", [{}, {"answers": {}}, {"answers": {"next_move": {"choice": "move_9"}}},
                                  {"answers": {"next_move": {"choice": 3}}}])
def test_an_unmappable_choice_stops_ok_and_keeps_the_call(fake, call):
    fake[:] = [DecisionReply(call, 1, 0, "m", 0.1), reply("done")]
    result = attempt()
    assert result.calls == [call] and result.stop_reason == "ok" and len(fake) == 1


def test_worst_state_uses_cap_of_the_longest_move():
    assert worst_state("P", ["R", "R2'", "U"], 3) == decision_state("P", ["R2'"] * 3)


def bad_call(answers):
    return DecisionReply({"answers": answers, "usage": {}, "model": "m"}, 1, 0, "m", 0.1)


@pytest.mark.parametrize("answers", [
    {"mismatch": {"noul": 0.9}},
    {"next_move": {"choice": "move_01"}},
    {"next_move": {"choice": "Mismatch"}},
])
def test_a_call_the_validator_rejects_stops_the_loop_with_ok(fake, answers):
    fake[:] = [reply("move_1"), bad_call(answers), reply("done")]
    result = attempt()
    assert len(result.calls) == 2 and result.stop_reason == "ok" and len(fake) == 1


def test_can_afford_sees_the_tokens_of_completed_calls(fake):
    fake[:] = [reply("move_1", tokens=40), reply("move_1", tokens=40), reply("done")]
    seen = []

    def afford(paid_in, paid_out):
        seen.append(paid_in)
        if paid_in >= 80:
            raise BudgetError("b")

    result = attempt(can_afford=afford)
    assert seen == [0, 40, 80] and len(result.calls) == 2 and isinstance(result.budget_stop, BudgetError)
    assert len(fake) == 1
