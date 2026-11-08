# Spec: docs/specs/models.md
"""Tests for the AI model calls. Every client is faked, so no test uses the network."""

from types import SimpleNamespace as NS
from unittest.mock import MagicMock

import anthropic
import httpx
import httpx2
import openai
import pytest
from google import genai
from google.genai import errors, types

from src.run import models
from src.run.models import InfrastructureError, Reply, call_model

REQUEST = httpx.Request("POST", "https://example.invalid")
PARAMS = {"temperature": 0.5, "top_p": 0.9}
KEYS = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "google": "GOOGLE_API_KEY",
        "openrouter": "OPENROUTER_API_KEY"}


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
    assert reply == Reply("U", "ok", "fake", 0, 0, 0.0)


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
    """Replace the SDK client class; return the mocked create function (for Anthropic, stream).
    An Anthropic error is raised while the stream is read, as a dropped stream would."""
    client = MagicMock()
    if provider == "anthropic":
        create = client.messages.stream
        final = create.return_value.__enter__.return_value.get_final_message
        monkeypatch.setattr(anthropic, "Anthropic", MagicMock(return_value=client))
        if isinstance(result, Exception):
            final.side_effect = result
        else:
            final.return_value = result
        return create
    elif provider in ("openai", "openrouter"):
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
    "openrouter": (openai_response, "stop", "length", "content_filter"),
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
                                  "google": "gemini-served", "openrouter": "gpt-served"}[provider]
    assert (reply.input_tokens, reply.output_tokens) == (11, 7)
    assert reply.latency_s >= 0


def test_request_shape_anthropic(monkeypatch):
    create = install(monkeypatch, "anthropic", anthropic_response())
    call_model(entry("anthropic"), "prompt", 50)
    create.assert_called_once_with(model="alias-1", max_tokens=50,
                                   messages=[{"role": "user", "content": "prompt"}], **PARAMS)
    assert anthropic.Anthropic.call_args.kwargs["max_retries"] == 0


def test_anthropic_streams_and_never_calls_create(monkeypatch):
    install(monkeypatch, "anthropic", anthropic_response())
    call_model(entry("anthropic"), "prompt", 32000)
    client = anthropic.Anthropic.return_value
    assert client.messages.stream.call_args.kwargs["max_tokens"] == 32000
    client.messages.create.assert_not_called()
    client.messages.stream.return_value.__exit__.assert_called_once()


def test_anthropic_error_when_opening_the_stream_is_infrastructure(monkeypatch):
    create = install(monkeypatch, "anthropic", anthropic_response())
    create.return_value.__enter__.side_effect = anthropic.APIConnectionError(request=REQUEST)  # the request is sent here
    with pytest.raises(InfrastructureError):
        call_model(entry("anthropic"), "prompt", 50)


def sse_error(error_type):
    """What the SDK raises for an SSE error event: a status error built on the stream's 200 response."""
    body = {"type": "error", "error": {"type": error_type, "message": "x"}}
    return anthropic.APIStatusError("x", response=httpx.Response(200, request=REQUEST), body=body)


@pytest.mark.parametrize("error_type", ["overloaded_error", "api_error", "rate_limit_error"])
def test_anthropic_transient_stream_error_event_is_infrastructure(monkeypatch, error_type):
    install(monkeypatch, "anthropic", sse_error(error_type))
    with pytest.raises(InfrastructureError):
        call_model(entry("anthropic"), "prompt", 50)


def test_anthropic_other_stream_error_event_is_a_request_error(monkeypatch):
    install(monkeypatch, "anthropic", sse_error("invalid_request_error"))
    with pytest.raises(models.RequestError, match=r"^anthropic: (?!HTTP)"):
        call_model(entry("anthropic"), "prompt", 50)


@pytest.mark.parametrize("error", [httpx2.ReadError("cut"), httpx2.RemoteProtocolError("closed")])
def test_anthropic_transport_error_while_reading_the_stream_is_infrastructure(monkeypatch, error):
    install(monkeypatch, "anthropic", error)
    with pytest.raises(InfrastructureError):
        call_model(entry("anthropic"), "prompt", 50)


def test_request_shape_openai(monkeypatch):
    create = install(monkeypatch, "openai", openai_response())
    call_model(entry("openai"), "prompt", 50)
    create.assert_called_once_with(model="alias-1", max_completion_tokens=50,
                                   messages=[{"role": "user", "content": "prompt"}], **PARAMS)
    assert openai.OpenAI.call_args.kwargs["max_retries"] == 0


def test_request_shape_openrouter(monkeypatch):
    create = install(monkeypatch, "openrouter", openai_response())
    call_model(entry("openrouter"), "prompt", 50)
    create.assert_called_once_with(model="alias-1", max_tokens=50,
                                   messages=[{"role": "user", "content": "prompt"}], extra_body=PARAMS)
    assert openai.OpenAI.call_args.kwargs["base_url"] == "https://openrouter.ai/api/v1"
    assert openai.OpenAI.call_args.kwargs["max_retries"] == 0


def test_openai_client_keeps_the_default_base_url(monkeypatch):
    install(monkeypatch, "openai", openai_response())
    call_model(entry("openai"), "prompt", 50)
    assert "base_url" not in openai.OpenAI.call_args.kwargs


MODERATION = {"code": 403, "message": "flagged", "metadata": {"reasons": ["violence"], "flagged_input": "p"}}


@pytest.mark.parametrize("body", [MODERATION, {"error": MODERATION}])
def test_openrouter_moderation_403_is_refused(monkeypatch, body):
    error = openai.PermissionDeniedError("flagged", response=httpx.Response(403, request=REQUEST), body=body)
    install(monkeypatch, "openrouter", error)
    reply = call_model(entry("openrouter"), "prompt", 50)
    assert (reply.stop_reason, reply.text, reply.served_model) == ("refused", "", "")


@pytest.mark.parametrize("body", [None, {"code": 403, "message": "Key limit exceeded"}])
def test_openrouter_other_403_is_a_request_error(monkeypatch, body):
    error = openai.PermissionDeniedError("x", response=httpx.Response(403, request=REQUEST), body=body)
    install(monkeypatch, "openrouter", error)
    with pytest.raises(models.RequestError, match="^openrouter: HTTP 403: "):
        call_model(entry("openrouter"), "prompt", 50)


@pytest.mark.parametrize("code", [401, 402, 404])
def test_openrouter_other_status_errors_are_request_errors(monkeypatch, code):
    install(monkeypatch, "openrouter", status_error(openai.APIStatusError, code))
    with pytest.raises(models.RequestError, match=f"^openrouter: HTTP {code}: "):
        call_model(entry("openrouter"), "prompt", 50)


def test_openrouter_upstream_error_finish_is_infrastructure_with_tokens(monkeypatch):
    install(monkeypatch, "openrouter", openai_response("error"))
    with pytest.raises(InfrastructureError) as raised:
        call_model(entry("openrouter"), "prompt", 50)
    assert (raised.value.input_tokens, raised.value.output_tokens) == (11, 7)


@pytest.mark.parametrize("response", [NS(choices=[], model="m", usage=None), NS(model="m")])
def test_openrouter_reply_without_choices_is_infrastructure(monkeypatch, response):
    install(monkeypatch, "openrouter", response)
    with pytest.raises(InfrastructureError):
        call_model(entry("openrouter"), "prompt", 50)


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


def test_openai_content_filter_reports_no_served_model(monkeypatch):
    error = status_error(openai.BadRequestError, 400)
    error.code = "content_filter"
    install(monkeypatch, "openai", error)
    assert call_model(entry("openai"), "prompt", 50).served_model == ""


def test_google_reply_without_a_model_version_has_no_served_model(monkeypatch):
    response = google_response()
    response.model_version = None
    install(monkeypatch, "google", response)
    assert call_model(entry("google"), "prompt", 50).served_model == ""


def test_openai_other_bad_request_is_a_request_error(monkeypatch):
    error = status_error(openai.BadRequestError, 400)
    error.code = "invalid_request"
    install(monkeypatch, "openai", error)
    with pytest.raises(models.RequestError, match="^openai: HTTP 400: "):
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
    if provider in ("openai", "openrouter"):
        return [status_error(openai.RateLimitError, 429), status_error(openai.InternalServerError, 500),
                openai.APITimeoutError(request=REQUEST), openai.APIConnectionError(request=REQUEST)]
    return [errors.ClientError(429, {"error": {}}), errors.ServerError(500, {"error": {}}),
            httpx.ReadTimeout("slow"), httpx.ConnectError("down")]


@pytest.mark.parametrize("provider,index", [(p, i) for p in RESPONSES for i in range(6 if p == "anthropic" else 4)])
def test_infrastructure_errors(monkeypatch, provider, index):
    install(monkeypatch, provider, sdk_errors(provider)[index])
    with pytest.raises(InfrastructureError):
        call_model(entry(provider), "prompt", 50)


def test_anthropic_other_client_error_is_a_request_error(monkeypatch):
    install(monkeypatch, "anthropic", status_error(anthropic.BadRequestError, 400))
    with pytest.raises(models.RequestError, match="^anthropic: HTTP 400: "):
        call_model(entry("anthropic"), "prompt", 50)


def test_anthropic_usage_limit_names_the_api_message(monkeypatch):
    message = "You have reached your specified API usage limits. You will regain access on 2026-12-01 at 00:00 UTC."
    body = {"type": "error", "error": {"type": "invalid_request_error", "message": message}}
    error = anthropic.BadRequestError("boom", response=httpx.Response(400, request=REQUEST), body=body)
    install(monkeypatch, "anthropic", error)
    with pytest.raises(models.RequestError) as raised:
        call_model(entry("anthropic"), "prompt", 50)
    assert str(raised.value) == f"anthropic: HTTP 400: {message}"
    assert raised.value.__cause__ is error


def test_google_output_tokens_include_thoughts(monkeypatch):
    install(monkeypatch, "google", google_response(thoughts=5))
    assert call_model(entry("google"), "prompt", 50).output_tokens == 12


def test_google_other_client_error_is_a_request_error(monkeypatch):
    body = {"error": {"code": 400, "status": "INVALID_ARGUMENT", "message": "bad model"}}
    install(monkeypatch, "google", errors.ClientError(400, body))
    with pytest.raises(models.RequestError, match="^google: HTTP 400: bad model$"):
        call_model(entry("google"), "prompt", 50)


@pytest.mark.parametrize("provider", RESPONSES)
def test_missing_key_names_the_variable(monkeypatch, provider):
    monkeypatch.delenv(KEYS[provider])
    create = install(monkeypatch, provider, None)
    with pytest.raises(ValueError, match=KEYS[provider]):
        call_model(entry(provider), "prompt", 50)
    create.assert_not_called()


@pytest.mark.parametrize("provider", RESPONSES)
@pytest.mark.parametrize("value", ["", "  \t\n"])
def test_blank_key_is_missing(monkeypatch, provider, value):
    monkeypatch.setenv(KEYS[provider], value)
    create = install(monkeypatch, provider, None)
    with pytest.raises(ValueError, match=KEYS[provider]):
        call_model(entry(provider), "prompt", 50)
    create.assert_not_called()


@pytest.mark.parametrize("provider,module,name", [("anthropic", anthropic, "Anthropic"), ("openai", openai, "OpenAI"),
                                                  ("google", genai, "Client"), ("openrouter", openai, "OpenAI")])
def test_padded_key_is_sent_stripped(monkeypatch, provider, module, name):
    monkeypatch.setenv(KEYS[provider], "  secret\n")
    install(monkeypatch, provider, RESPONSES[provider][0]())
    call_model(entry(provider), "prompt", 50)
    assert getattr(module, name).call_args.kwargs["api_key"] == "secret"


# Decision models.

ANSWERS = {"next_move": {"type": "choice", "choice": "done", "confidence": 1.0, "probabilities": {"done": 1.0}},
           "mismatch": {"type": "noul", "noul": 0.1}}
API_REPLY = {"model": "served", "answers": ANSWERS, "usage": {"input_tokens": 40, "output_tokens": 0}}
CLOUDFLARE_MODEL = {"provider": "cloudflare", "api_model_id": "@cf/cloudflare/clef-flash", "name": "clef-flash"}
TYPESAFE_MODEL = {"provider": "typesafe", "api_model_id": "jev-latest", "name": "jev"}


def _cloudflare_stub(monkeypatch, behaviour):
    sent = {}

    class FakeAI:
        def run(self, name, account_id, extra_body):
            sent.update(name=name, account_id=account_id, body=extra_body)
            return behaviour()

    class FakeClient:
        def __init__(self, api_token, max_retries):
            assert api_token == "t" and max_retries == 0
            self.ai = FakeAI()

    monkeypatch.setattr(models, "_cloudflare_client", FakeClient)
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "t")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "a")
    return sent


def _typesafe_stub(monkeypatch, behaviour):
    sent = {}

    class FakeClient:
        def __init__(self, api_key, retry):
            assert api_key == "k" and retry.max_retries == 0
            sent["constructed"] = True

        def system_one(self, state, questions, model, response_model):
            sent.update(state=state, questions=questions, model=model)
            return behaviour(response_model)

    monkeypatch.setattr(models, "_typesafe_client", FakeClient)
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    return sent


def _typesafe_ok(response_model):
    return response_model.model_validate(API_REPLY)


def _status_error(cls, status):
    request = httpx.Request("POST", "https://api.cloudflare.com/x")
    return cls("boom", response=httpx.Response(status, request=request), body=None)


def _typesafe_error(status):
    import httpx2
    from typesafe_sdk._core.errors import api_error

    return api_error(status, {"error": "boom"}, httpx2.Headers())


def _raiser(error):
    def behaviour(*_):
        raise error
    return behaviour


def test_cloudflare_call_shape(monkeypatch):
    sent = _cloudflare_stub(monkeypatch, lambda: dict(API_REPLY))
    reply = models.call_decision(CLOUDFLARE_MODEL, "S", {"q": 1})
    assert sent == {"name": "@cf/cloudflare/clef-flash", "account_id": "a",
                    "body": {"model": "clef-flash", "state": "S", "questions": {"q": 1}}}
    assert reply.input_tokens == 40 and reply.output_tokens == 0 and reply.served_model == "served"
    assert reply.call == API_REPLY and reply.latency_s >= 0
    assert set(reply.call) == {"answers", "usage", "model"}


def test_typesafe_call_shape_keeps_the_reply_exactly(monkeypatch):
    sent = _typesafe_stub(monkeypatch, _typesafe_ok)
    reply = models.call_decision(TYPESAFE_MODEL, "S", {"q": 1})
    assert (sent["state"], sent["questions"], sent["model"]) == ("S", {"q": 1}, "jev-latest")
    assert reply.call == API_REPLY and reply.input_tokens == 40 and reply.served_model == "served"
    assert set(reply.call) == {"answers", "usage", "model"}


def test_typesafe_unreported_usage_counts_as_zero(monkeypatch):
    _typesafe_stub(monkeypatch, lambda m: m.model_validate({"model": "j", "answers": ANSWERS}))
    reply = models.call_decision(TYPESAFE_MODEL, "S", {"q": 1})
    assert reply.input_tokens == 0 and reply.output_tokens == 0


@pytest.mark.parametrize("status", [429, 503])
def test_cloudflare_429_and_5xx_are_infrastructure_errors(monkeypatch, status):
    import cloudflare

    cls = cloudflare.RateLimitError if status == 429 else cloudflare.InternalServerError
    _cloudflare_stub(monkeypatch, _raiser(_status_error(cls, status)))
    with pytest.raises(InfrastructureError):
        models.call_decision(CLOUDFLARE_MODEL, "S", {"q": 1})


def test_cloudflare_timeout_is_an_infrastructure_error(monkeypatch):
    import cloudflare

    _cloudflare_stub(monkeypatch, _raiser(cloudflare.APITimeoutError(httpx.Request("POST", "https://x"))))
    with pytest.raises(InfrastructureError):
        models.call_decision(CLOUDFLARE_MODEL, "S", {"q": 1})


def test_cloudflare_400_names_the_envelope_message(monkeypatch):
    import cloudflare

    request = httpx.Request("POST", "https://api.cloudflare.com/x")
    body = {"errors": [{"code": 7000, "message": "No route for that URI"}], "success": False, "result": None}
    error = cloudflare.BadRequestError("boom", response=httpx.Response(400, request=request), body=body)
    _cloudflare_stub(monkeypatch, _raiser(error))
    with pytest.raises(models.RequestError, match="^cloudflare: HTTP 400: No route for that URI$"):
        models.call_decision(CLOUDFLARE_MODEL, "S", {"q": 1})


def test_cloudflare_400_is_a_request_error(monkeypatch):
    import cloudflare

    _cloudflare_stub(monkeypatch, _raiser(_status_error(cloudflare.BadRequestError, 400)))
    with pytest.raises(models.RequestError, match="^cloudflare: HTTP 400: "):
        models.call_decision(CLOUDFLARE_MODEL, "S", {"q": 1})


@pytest.mark.parametrize("status", [429, 503])
def test_typesafe_429_and_5xx_are_infrastructure_errors(monkeypatch, status):
    _typesafe_stub(monkeypatch, _raiser(_typesafe_error(status)))
    with pytest.raises(InfrastructureError):
        models.call_decision(TYPESAFE_MODEL, "S", {"q": 1})


def test_typesafe_connection_error_and_timeout_are_infrastructure_errors(monkeypatch):
    import typesafe_sdk

    for error in (typesafe_sdk.TypeSafeAPIConnectionError("down"), typesafe_sdk.TypeSafeAPITimeoutError(5.0)):
        _typesafe_stub(monkeypatch, _raiser(error))
        with pytest.raises(InfrastructureError):
            models.call_decision(TYPESAFE_MODEL, "S", {"q": 1})


def test_typesafe_422_names_the_message_the_sdk_read(monkeypatch):
    import httpx2
    from typesafe_sdk._core.errors import api_error

    body = {"detail": [{"loc": ["body", "state"], "msg": "field required"}]}
    _typesafe_stub(monkeypatch, _raiser(api_error(422, body, httpx2.Headers())))
    with pytest.raises(models.RequestError, match="^typesafe: HTTP 422: state: field required$"):
        models.call_decision(TYPESAFE_MODEL, "S", {"q": 1})


def test_typesafe_400_is_a_request_error(monkeypatch):
    _typesafe_stub(monkeypatch, _raiser(_typesafe_error(400)))
    with pytest.raises(models.RequestError, match="^typesafe: HTTP 400: boom$"):
        models.call_decision(TYPESAFE_MODEL, "S", {"q": 1})


def test_missing_cloudflare_account_id_names_the_variable(monkeypatch):
    _cloudflare_stub(monkeypatch, lambda: dict(API_REPLY))
    monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID")
    with pytest.raises(ValueError, match="CLOUDFLARE_ACCOUNT_ID"):
        models.call_decision(CLOUDFLARE_MODEL, "S", {"q": 1})


def test_blank_cloudflare_account_id_is_missing(monkeypatch):
    _cloudflare_stub(monkeypatch, lambda: dict(API_REPLY))
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "  ")
    with pytest.raises(ValueError, match="CLOUDFLARE_ACCOUNT_ID"):
        models.call_decision(CLOUDFLARE_MODEL, "S", {"q": 1})


def test_padded_cloudflare_account_id_is_sent_stripped(monkeypatch):
    sent = _cloudflare_stub(monkeypatch, lambda: dict(API_REPLY))
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", " a\n")
    models.call_decision(CLOUDFLARE_MODEL, "S", {"q": 1})
    assert sent["account_id"] == "a"


@pytest.mark.parametrize("stub,model", [(_cloudflare_stub, CLOUDFLARE_MODEL), (_typesafe_stub, TYPESAFE_MODEL)])
def test_padded_decision_key_is_sent_stripped(monkeypatch, stub, model):
    stub(monkeypatch, (lambda: dict(API_REPLY)) if model is CLOUDFLARE_MODEL else _typesafe_ok)
    monkeypatch.setenv(models.KEY_VARIABLES[model["provider"]], "  " + ("t" if model is CLOUDFLARE_MODEL else "k") + "\n")
    models.call_decision(model, "S", {"q": 1})  # the stub client asserts the stripped key


@pytest.mark.parametrize("model", [CLOUDFLARE_MODEL, TYPESAFE_MODEL])
def test_blank_decision_key_is_missing(monkeypatch, model):
    variable = models.KEY_VARIABLES[model["provider"]]
    monkeypatch.setenv(variable, " ")
    with pytest.raises(ValueError, match=variable):
        models.call_decision(model, "S", {"q": 1})


@pytest.mark.parametrize("model", [CLOUDFLARE_MODEL, TYPESAFE_MODEL])
def test_missing_decision_key_names_the_variable(monkeypatch, model):
    variable = models.KEY_VARIABLES[model["provider"]]
    monkeypatch.delenv(variable, raising=False)
    with pytest.raises(ValueError, match=variable):
        models.call_decision(model, "S", {"q": 1})


def test_fake_decision_pops_in_order_and_defaults_to_done(monkeypatch):
    first = models.DecisionReply({"answers": {}, "usage": {}, "model": "fake"}, 1, 2, "fake", 0.5)
    monkeypatch.setattr(models, "FAKE_DECISION_REPLIES",
                        [first, InfrastructureError("x"), models.RefusedError("y")])
    fake = {"provider": "fake_decision", "name": "f"}
    assert models.call_decision(fake, "S", {}) is first
    with pytest.raises(InfrastructureError):
        models.call_decision(fake, "S", {})
    with pytest.raises(models.RefusedError):
        models.call_decision(fake, "S", {})
    default = models.call_decision(fake, "S", {})
    assert default.call["answers"]["next_move"]["choice"] == "done"
    assert "mismatch" not in default.call["answers"]


def test_decision_providers_and_variables():
    assert models.DECISION_PROVIDERS == ("typesafe", "cloudflare", "fake_decision")
    assert models.KEY_VARIABLES["typesafe"] == "TYPESAFE_API_KEY"
    assert models.KEY_VARIABLES["cloudflare"] == "CLOUDFLARE_API_TOKEN"
    assert models.ACCOUNT_VARIABLES == {"cloudflare": "CLOUDFLARE_ACCOUNT_ID"}


def test_extra_top_level_keys_are_not_kept(monkeypatch):
    extra = {**API_REPLY, "future": "x"}
    _cloudflare_stub(monkeypatch, lambda: dict(extra))
    assert models.call_decision(CLOUDFLARE_MODEL, "S", {"q": 1}).call == API_REPLY
    _typesafe_stub(monkeypatch, lambda m: m.model_validate(extra))
    assert models.call_decision(TYPESAFE_MODEL, "S", {"q": 1}).call == API_REPLY


@pytest.mark.parametrize("body", [{"answers": None}, {}, {"model": None, "answers": 3, "usage": "x"}])
def test_typesafe_reply_missing_the_schema_returns_with_absent_keys(monkeypatch, body):
    _typesafe_stub(monkeypatch, lambda m: m.model_validate(body))
    reply = models.call_decision(TYPESAFE_MODEL, "S", {"q": 1})
    assert reply.call == body and reply.served_model == ""
    assert reply.input_tokens == 0 and reply.output_tokens == 0


@pytest.mark.parametrize("result", ["text", [1, 2], None, 7])
def test_cloudflare_result_that_is_not_an_object_gives_an_empty_call(monkeypatch, result):
    _cloudflare_stub(monkeypatch, lambda: result)
    reply = models.call_decision(CLOUDFLARE_MODEL, "S", {"q": 1})
    assert reply.call == {} and reply.served_model == ""


def test_provider_routing_is_checked_both_ways():
    with pytest.raises(ValueError, match="anthropic"):
        models.call_decision({"provider": "anthropic"}, "S", {})
    with pytest.raises(ValueError, match="cloudflare"):
        call_model({"provider": "cloudflare"}, "p", 10)


def test_cloudflare_through_the_real_sdk(monkeypatch):
    import json

    import cloudflare

    seen = {}

    def handler(request):
        seen.update(url=str(request.url), body=json.loads(request.content))
        return httpx.Response(200, json={"result": API_REPLY, "success": True, "errors": [], "messages": []})

    monkeypatch.setattr(models, "_cloudflare_client", lambda **o: cloudflare.Cloudflare(
        http_client=httpx.Client(transport=httpx.MockTransport(handler)), **o))
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "t")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "a")
    questions = {"q": {"type": "noul", "instructions": "x"}}
    reply = models.call_decision(CLOUDFLARE_MODEL, "S", questions)
    assert seen["url"].startswith("https://api.cloudflare.com/client/v4/accounts/a/ai/run/")
    assert "clef-flash" in seen["url"]
    assert seen["body"] == {"model": "clef-flash", "state": "S", "questions": questions}
    assert reply.call == API_REPLY and reply.input_tokens == 40 and reply.served_model == "served"


def test_typesafe_through_the_real_sdk(monkeypatch):
    import json

    import httpx2
    import typesafe_sdk

    seen = {}

    def handler(request):
        seen.update(url=str(request.url), body=json.loads(request.content))
        return httpx2.Response(200, json={**API_REPLY, "future": 1})

    monkeypatch.setattr(models, "_typesafe_client", lambda **o: typesafe_sdk.TypeSafeClient(
        transport=httpx2.MockTransport(handler), **o))
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    questions = {"q": {"type": "noul", "instructions": "x"}}
    reply = models.call_decision(TYPESAFE_MODEL, "S", questions)
    assert seen["url"] == "https://api.typesafe.ai/v1/systemone"
    assert seen["body"] == {"state": "S", "model": "jev-latest", "questions": questions}
    assert reply.call == API_REPLY and reply.input_tokens == 40 and reply.served_model == "served"


@pytest.mark.parametrize("content", [b"[1]", b"not json", b""])
def test_typesafe_body_that_is_not_a_json_object_gives_an_empty_call(monkeypatch, content):
    import httpx2
    import typesafe_sdk

    monkeypatch.setattr(models, "_typesafe_client", lambda **o: typesafe_sdk.TypeSafeClient(
        transport=httpx2.MockTransport(lambda request: httpx2.Response(200, content=content)), **o))
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    reply = models.call_decision(TYPESAFE_MODEL, "S", {"q": {"type": "noul", "instructions": "x"}})
    assert reply.call == {} and reply.served_model == ""
    assert reply.input_tokens == 0 and reply.output_tokens == 0 and reply.latency_s >= 0


def test_reasoning_effort_reaches_each_providers_own_parameter(monkeypatch):
    model = lambda provider: {**entry(provider), "kind": "system-2"}
    create = install(monkeypatch, "anthropic", anthropic_response())
    call_model(model("anthropic"), "p", 50, "medium")
    assert create.call_args.kwargs["output_config"] == {"effort": "medium"}
    create = install(monkeypatch, "openai", openai_response())
    call_model(model("openai"), "p", 50, "medium")
    assert create.call_args.kwargs["reasoning_effort"] == "medium"
    create = install(monkeypatch, "google", google_response())
    call_model(model("google"), "p", 50, "medium")
    assert create.call_args.kwargs["config"]["thinking_config"] == {"thinking_level": "MEDIUM"}
    create = install(monkeypatch, "openrouter", openai_response())
    call_model(model("openrouter"), "p", 50, "medium")
    assert create.call_args.kwargs["extra_body"]["reasoning"] == {"effort": "medium"}


@pytest.mark.parametrize("provider", ["anthropic", "openai", "google", "openrouter"])
@pytest.mark.parametrize("kind, effort", [("system-2", None), ("system-1", "high"), (None, "high")])
def test_no_effort_is_sent_without_one_or_for_a_system_1_model(monkeypatch, provider, kind, effort):
    create = install(monkeypatch, provider, {"anthropic": anthropic_response, "openai": openai_response,
                                             "google": google_response, "openrouter": openai_response}[provider]())
    model = {**entry(provider), **({"kind": kind} if kind else {})}
    call_model(model, "p", 50, effort)
    sent = create.call_args.kwargs
    sent = {**sent, **sent.get("config", {}), **sent.get("extra_body", {})}
    assert not {"output_config", "reasoning_effort", "thinking_config", "reasoning"} & set(sent)


# ---- timeouts and 408/409

@pytest.mark.parametrize("provider", ["anthropic", "openai", "openrouter"])
def test_client_gets_an_explicit_timeout(monkeypatch, provider):
    install(monkeypatch, provider, {"anthropic": anthropic_response, "openai": openai_response,
                                    "openrouter": openai_response}[provider]())
    call_model(entry(provider), "prompt", 50)
    cls = {"anthropic": anthropic.Anthropic, "openai": openai.OpenAI, "openrouter": openai.OpenAI}[provider]
    timeout = cls.call_args.kwargs["timeout"]
    assert models.REQUEST_TIMEOUT_S == 1800
    assert (timeout.read, timeout.connect) == (1800, 30.0)


def test_google_gets_an_explicit_timeout_in_milliseconds(monkeypatch):
    install(monkeypatch, "google", google_response())
    call_model(entry("google"), "prompt", 50)
    assert genai.Client.call_args.kwargs["http_options"].timeout == 1_800_000


@pytest.mark.parametrize("provider", ["openai", "openrouter"])
@pytest.mark.parametrize("code", [408, 409])
def test_openai_408_and_409_are_infrastructure(monkeypatch, provider, code):
    error = openai.APIStatusError("x", response=httpx2.Response(code, request=httpx2.Request("POST", "https://example.invalid")), body=None)
    install(monkeypatch, provider, error)
    with pytest.raises(InfrastructureError):
        call_model(entry(provider), "prompt", 50)


def test_openai_other_status_errors_are_request_errors(monkeypatch):
    error = openai.APIStatusError("x", response=httpx2.Response(401, request=httpx2.Request("POST", "https://example.invalid")), body=None)
    install(monkeypatch, "openai", error)
    with pytest.raises(models.RequestError, match="^openai: HTTP 401: x$"):
        call_model(entry("openai"), "prompt", 50)


def test_openrouter_key_variable():
    assert models.KEY_VARIABLES["openrouter"] == "OPENROUTER_API_KEY"


def test_openrouter_reply_without_a_model_has_no_served_model(monkeypatch):
    response = openai_response()
    response.model = None
    install(monkeypatch, "openrouter", response)
    assert call_model(entry("openrouter"), "prompt", 50).served_model == ""
