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


def test_cloudflare_400_propagates(monkeypatch):
    import cloudflare

    _cloudflare_stub(monkeypatch, _raiser(_status_error(cloudflare.BadRequestError, 400)))
    with pytest.raises(cloudflare.BadRequestError):
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


def test_typesafe_400_propagates(monkeypatch):
    import typesafe_sdk

    _typesafe_stub(monkeypatch, _raiser(_typesafe_error(400)))
    with pytest.raises(typesafe_sdk.TypeSafeBadRequestError):
        models.call_decision(TYPESAFE_MODEL, "S", {"q": 1})


def test_missing_cloudflare_account_id_names_the_variable(monkeypatch):
    _cloudflare_stub(monkeypatch, lambda: dict(API_REPLY))
    monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID")
    with pytest.raises(ValueError, match="CLOUDFLARE_ACCOUNT_ID"):
        models.call_decision(CLOUDFLARE_MODEL, "S", {"q": 1})


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
