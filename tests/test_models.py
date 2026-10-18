# Spec: docs/specs/models.md
"""Tests for the AI model calls. Every client is faked, so no test uses the network."""

from types import SimpleNamespace as NS
from unittest.mock import MagicMock

import anthropic
import httpx
import openai
import pytest
from google import genai
from google.genai import errors, types

from src.run import models
from src.run.models import InfrastructureError, Reply, call_model

REQUEST = httpx.Request("POST", "https://example.invalid")
PARAMS = {"temperature": 0.5, "top_p": 0.9}
KEYS = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "google": "GOOGLE_API_KEY"}


def entry(provider):
    return {"name": "m", "provider": provider, "api_model_id": "alias-1", "params": dict(PARAMS)}


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    for variable in KEYS.values():
        monkeypatch.setenv(variable, "secret")
    models.FAKE_REPLIES.clear()


def status_error(cls, code):
    return cls("boom", response=httpx.Response(code, request=REQUEST), body=None)


# ---- fake provider

def test_fake_returns_scripted_replies_in_order():
    first = Reply("a", "ok", "fake", 1, 2, 0.1)
    second = Reply("b", "truncated", "fake", 3, 4, 0.2)
    third = Reply("c", "refused", "fake", 0, 0, 0.0)
    models.FAKE_REPLIES.extend([first, second, third])
    got = [call_model({"provider": "fake"}, "p", 10) for _ in range(3)]
    assert got == [first, second, third]


def test_fake_raises_scripted_error_then_default():
    models.FAKE_REPLIES.append(InfrastructureError("down", 5, 0))
    with pytest.raises(InfrastructureError) as raised:
        call_model({"provider": "fake"}, "p", 10)
    assert raised.value.input_tokens == 5
    reply = call_model({"provider": "fake"}, "p", 10)
    assert reply == Reply('{"moves": [], "mismatch": false}', "ok", "fake", 0, 0, 0.0)


# ---- real providers, with the SDK client mocked

def anthropic_response(stop="end_turn"):
    return NS(content=[NS(type="text", text="hi")], stop_reason=stop, model="claude-served",
              usage=NS(input_tokens=11, output_tokens=7))


def openai_response(finish="stop"):
    return NS(choices=[NS(message=NS(content="hi"), finish_reason=finish)], model="gpt-served",
              usage=NS(prompt_tokens=11, completion_tokens=7))


def google_response(finish="STOP", block=None, thoughts=None):
    candidate = NS(finish_reason=types.FinishReason[finish],
                   content=NS(parts=[NS(text="hi", thought=None)]))
    return NS(candidates=[candidate], model_version="gemini-served",
              prompt_feedback=NS(block_reason=block) if block else None,
              usage_metadata=NS(prompt_token_count=11, candidates_token_count=7,
                                     thoughts_token_count=thoughts))


def install(monkeypatch, provider, result):
    """Replace the SDK client class; return the mocked create function."""
    client = MagicMock()
    if provider == "anthropic":
        create = client.messages.create
        monkeypatch.setattr(anthropic, "Anthropic", MagicMock(return_value=client))
    elif provider == "openai":
        create = client.chat.completions.create
        monkeypatch.setattr(openai, "OpenAI", MagicMock(return_value=client))
    else:
        create = client.models.generate_content
        monkeypatch.setattr(genai, "Client", MagicMock(return_value=client))
    if isinstance(result, Exception):
        create.side_effect = result
    else:
        create.return_value = result
    return create


RESPONSES = {
    "anthropic": (anthropic_response, "end_turn", "max_tokens", "refusal"),
    "openai": (openai_response, "stop", "length", "content_filter"),
    "google": (google_response, "STOP", "MAX_TOKENS", "SAFETY"),
}


@pytest.mark.parametrize("provider", RESPONSES)
@pytest.mark.parametrize("which,expected", [(1, "ok"), (2, "truncated"), (3, "refused")])
def test_stop_reasons(monkeypatch, provider, which, expected):
    make, *stops = RESPONSES[provider]
    install(monkeypatch, provider, make(stops[which - 1]))
    reply = call_model(entry(provider), "prompt", 50)
    assert reply.stop_reason == expected
    assert reply.text == "hi"
    assert reply.served_model == {"anthropic": "claude-served", "openai": "gpt-served",
                                  "google": "gemini-served"}[provider]
    assert (reply.input_tokens, reply.output_tokens) == (11, 7)
    assert reply.latency_s >= 0


def test_request_shape_anthropic(monkeypatch):
    create = install(monkeypatch, "anthropic", anthropic_response())
    call_model(entry("anthropic"), "prompt", 50)
    create.assert_called_once_with(model="alias-1", max_tokens=50,
                                   messages=[{"role": "user", "content": "prompt"}], **PARAMS)
    assert anthropic.Anthropic.call_args.kwargs["max_retries"] == 0


def test_request_shape_openai(monkeypatch):
    create = install(monkeypatch, "openai", openai_response())
    call_model(entry("openai"), "prompt", 50)
    create.assert_called_once_with(model="alias-1", max_completion_tokens=50,
                                   messages=[{"role": "user", "content": "prompt"}], **PARAMS)
    assert openai.OpenAI.call_args.kwargs["max_retries"] == 0


def test_request_shape_google(monkeypatch):
    create = install(monkeypatch, "google", google_response())
    call_model(entry("google"), "prompt", 50)
    create.assert_called_once_with(model="alias-1", contents="prompt",
                                   config={"max_output_tokens": 50, **PARAMS})
    retry = genai.Client.call_args.kwargs["http_options"].retry_options
    assert retry.attempts == 1


def test_openai_content_filter_error_is_refused(monkeypatch):
    error = status_error(openai.BadRequestError, 400)
    error.code = "content_filter"
    install(monkeypatch, "openai", error)
    assert call_model(entry("openai"), "prompt", 50).stop_reason == "refused"


def test_openai_other_bad_request_propagates(monkeypatch):
    error = status_error(openai.BadRequestError, 400)
    error.code = "invalid_request"
    install(monkeypatch, "openai", error)
    with pytest.raises(openai.BadRequestError):
        call_model(entry("openai"), "prompt", 50)


def test_google_blocked_prompt_is_refused(monkeypatch):
    response = NS(candidates=None, model_version="gemini-served", usage_metadata=None,
                  prompt_feedback=NS(block_reason="SAFETY"))
    install(monkeypatch, "google", response)
    reply = call_model(entry("google"), "prompt", 50)
    assert (reply.stop_reason, reply.text) == ("refused", "")


def sdk_errors(provider):
    if provider == "anthropic":
        return [status_error(anthropic.RateLimitError, 429), status_error(anthropic.InternalServerError, 500),
                status_error(anthropic.APIStatusError, 529), status_error(anthropic.APIStatusError, 503),
                anthropic.APITimeoutError(request=REQUEST), anthropic.APIConnectionError(request=REQUEST)]
    if provider == "openai":
        return [status_error(openai.RateLimitError, 429), status_error(openai.InternalServerError, 500),
                openai.APITimeoutError(request=REQUEST), openai.APIConnectionError(request=REQUEST)]
    return [errors.ClientError(429, {"error": {}}), errors.ServerError(500, {"error": {}}),
            httpx.ReadTimeout("slow"), httpx.ConnectError("down")]


@pytest.mark.parametrize("provider,index", [(p, i) for p in RESPONSES for i in range(6 if p == "anthropic" else 4)])
def test_infrastructure_errors(monkeypatch, provider, index):
    install(monkeypatch, provider, sdk_errors(provider)[index])
    with pytest.raises(InfrastructureError):
        call_model(entry(provider), "prompt", 50)


def test_anthropic_other_client_error_propagates(monkeypatch):
    install(monkeypatch, "anthropic", status_error(anthropic.BadRequestError, 400))
    with pytest.raises(anthropic.BadRequestError):
        call_model(entry("anthropic"), "prompt", 50)


def test_google_output_tokens_include_thoughts(monkeypatch):
    install(monkeypatch, "google", google_response(thoughts=5))
    assert call_model(entry("google"), "prompt", 50).output_tokens == 12


def test_google_other_client_error_propagates(monkeypatch):
    install(monkeypatch, "google", errors.ClientError(400, {"error": {}}))
    with pytest.raises(errors.ClientError):
        call_model(entry("google"), "prompt", 50)


@pytest.mark.parametrize("provider", RESPONSES)
def test_missing_key_names_the_variable(monkeypatch, provider):
    monkeypatch.delenv(KEYS[provider])
    create = install(monkeypatch, provider, None)
    with pytest.raises(ValueError, match=KEYS[provider]):
        call_model(entry(provider), "prompt", 50)
    create.assert_not_called()
