# Spec: docs/specs/models.md
"""Sends one prompt to one AI model and returns a Reply, or one state and its questions to one
decision model and returns a DecisionReply. Reads the provider's API key from its env var
(ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY, OPENROUTER_API_KEY, TYPESAFE_API_KEY, or
CLOUDFLARE_API_TOKEN, plus CLOUDFLARE_ACCOUNT_ID). Writes nothing.
This is the only file that talks to an AI model API.
"""

import os
import sys
import time
from dataclasses import dataclass

KEY_VARIABLES = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "google": "GOOGLE_API_KEY",
                 "typesafe": "TYPESAFE_API_KEY", "cloudflare": "CLOUDFLARE_API_TOKEN"}
# Providers the UI doesn't offer. Their key comes only from the env var, never from secrets/.
ENV_KEY_VARIABLES = {"openrouter": "OPENROUTER_API_KEY"}
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
# A second variable some providers need besides the key.
ACCOUNT_VARIABLES = {"cloudflare": "CLOUDFLARE_ACCOUNT_ID"}
# Providers of decision models, which are called with call_decision() instead of call_model().
DECISION_PROVIDERS = ("typesafe", "cloudflare", "fake_decision")
# The longest one request may take, in seconds, for the LLM providers (anthropic, openai, google, openrouter).
# A long reasoning reply can run for many minutes, so it is generous, and it is set so that no SDK
# default decides it silently. The decision providers (typesafe, cloudflare) keep their SDK defaults.
REQUEST_TIMEOUT_S = 1800
# The longest a connection may take to open, in seconds.
CONNECT_TIMEOUT_S = 30.0
# Google finish reasons that mean the answer was withheld.
GOOGLE_REFUSALS = ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "RECITATION")

# Tests fill this list. Each fake call pops the first item: a Reply is returned and an
# InfrastructureError or RequestError instance is raised.
FAKE_REPLIES: list = []
# The same for decision models: a DecisionReply is returned, an InfrastructureError or a
# RefusedError instance is raised.
FAKE_DECISION_REPLIES: list = []


@dataclass(frozen=True)
class Reply:
    text: str
    stop_reason: str  # ok, truncated, or refused
    served_model: str
    input_tokens: int
    output_tokens: int
    latency_s: float


class InfrastructureError(Exception):
    """A network error, timeout, HTTP 429, or HTTP 5xx, with any token counts the API reported."""

    def __init__(self, message: str, input_tokens: int = 0, output_tokens: int = 0):
        super().__init__(message)
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


@dataclass(frozen=True)
class DecisionReply:
    call: dict  # {"answers": ..., "usage": ..., "model": ...} exactly as the API returned them
    input_tokens: int
    output_tokens: int
    served_model: str
    latency_s: float


class RefusedError(Exception):
    """A content-filter refusal. Never retried. No decision-model SDK reports one today."""


class RequestError(Exception):
    """The API rejected the request itself, with an HTTP error that is not an infrastructure failure:
    an account usage limit, a bad key, or an unknown model. Never retried. `run` stops on it."""


def _request_error(provider: str, error: Exception, message: str | None = None) -> RequestError:
    """One line naming the provider, the HTTP status, and the message the API sent. `message` is
    the one the SDK already read from the body, when it keeps one."""
    # status_code (anthropic, openai, cloudflare), code (google, whose status is a name), status (typesafe)
    status = next((value for value in (getattr(error, name, None) for name in ("status_code", "code", "status"))
                   if isinstance(value, int) and not isinstance(value, bool)), None)
    body = getattr(error, "body", None)
    inner = body.get("error") if isinstance(body, dict) else None
    detail = inner if isinstance(inner, dict) else body
    if not message and isinstance(detail, dict):
        message = detail.get("message")
    if not message and isinstance(inner, str):  # a body like {"error": "text"}
        message = inner
    if not message and isinstance(body, dict) and isinstance(body.get("errors"), list):  # cloudflare
        message = "; ".join(item["message"] for item in body["errors"]
                            if isinstance(item, dict) and isinstance(item.get("message"), str))
    message = message or getattr(error, "message", None) or str(error)
    # An SSE error event comes with the stream's own 200, which says nothing about the error.
    prefix = f"{provider}: HTTP {status}: " if status and status != 200 else f"{provider}: "
    return RequestError(prefix + " ".join(str(message).split()))


def log_infrastructure_error(label: str, call: int, error: Exception) -> None:
    """Write why a call failed to stderr, never stdout, which carries the progress output the UI parses.
    `label` names the attempt, `call` is the number of the request in it, from 1."""
    text = str(error).replace("\r", " ").replace("\n", " ")
    # One write, so a line from another attempt never lands in the middle of this one.
    sys.stderr.write(f"infrastructure error: {label} call {call}: {text}"[:300] + "\n")
    sys.stderr.flush()


# Error types an SSE error event can carry that mean the service, not the request, failed.
ANTHROPIC_TRANSIENT_STREAM_ERRORS = ("overloaded_error", "api_error", "rate_limit_error")


def _stream_error_is_transient(error) -> bool:
    """An SSE error event arrives as a status error built on the stream's own 200 response, so the
    status code says nothing. Read the error type from its body instead."""
    body = error.body if isinstance(error.body, dict) else {}
    detail = body.get("error") if isinstance(body.get("error"), dict) else body
    return error.status_code == 200 and detail.get("type") in ANTHROPIC_TRANSIENT_STREAM_ERRORS


def _anthropic(model: dict, prompt: str, max_output_tokens: int, key: str, effort: str | None = None) -> Reply:
    import anthropic
    import httpx2

    client = anthropic.Anthropic(api_key=key, max_retries=0,
                                 timeout=httpx2.Timeout(REQUEST_TIMEOUT_S, connect=CONNECT_TIMEOUT_S))
    start = time.perf_counter()
    try:
        # Streamed, because the SDK refuses a non-streaming call with a large max_tokens.
        with client.messages.stream(
            model=model["api_model_id"],
            max_tokens=max_output_tokens,
            messages=[{"role": "user", "content": prompt}],
            **({"output_config": {"effort": effort}} if effort else {}),
            **model.get("params", {}),
        ) as stream:
            response = stream.get_final_message()
    except anthropic.APIConnectionError as error:
        raise InfrastructureError(f"anthropic: {error}") from error
    except httpx2.TransportError as error:  # a dropped connection while reading the stream
        raise InfrastructureError(f"anthropic: {error}") from error
    except anthropic.APIStatusError as error:
        if error.status_code == 429 or error.status_code >= 500 or _stream_error_is_transient(error):
            raise InfrastructureError(f"anthropic: {error}") from error
        raise _request_error("anthropic", error) from error
    latency = time.perf_counter() - start
    stop_reason = {"max_tokens": "truncated", "refusal": "refused"}.get(response.stop_reason, "ok")
    text = "".join(block.text for block in response.content if block.type == "text")
    return Reply(text, stop_reason, response.model, response.usage.input_tokens,
                 response.usage.output_tokens, latency)


def _openai_client(key: str, base_url: str | None = None):
    import httpx2
    import openai

    return openai.OpenAI(api_key=key, max_retries=0, timeout=httpx2.Timeout(REQUEST_TIMEOUT_S, connect=CONNECT_TIMEOUT_S),
                         **({"base_url": base_url} if base_url else {}))


def _moderation_flagged(body) -> bool:
    """True when an OpenRouter 403 body carries moderation metadata. Other 403s, such as a key over its
    credit limit, are request errors."""
    error = body.get("error", body) if isinstance(body, dict) else None
    metadata = error.get("metadata") if isinstance(error, dict) else None
    return isinstance(metadata, dict) and ("reasons" in metadata or "flagged_input" in metadata)


def _chat(provider: str, client, request: dict) -> Reply:
    """One Chat Completions call, shared by openai and openrouter, which speaks the same API."""
    import openai

    start = time.perf_counter()
    try:
        response = client.chat.completions.create(**request)
    except openai.BadRequestError as error:
        if error.code == "content_filter":
            return Reply("", "refused", "", 0, 0, time.perf_counter() - start)
        raise _request_error(provider, error) from error
    except (openai.APIConnectionError, openai.RateLimitError, openai.InternalServerError) as error:
        raise InfrastructureError(f"{provider}: {error}") from error
    except openai.APIStatusError as error:
        if error.status_code in (408, 409):  # request timeout and conflict, both worth trying again
            raise InfrastructureError(f"{provider}: {error}") from error
        if provider == "openrouter" and error.status_code == 403 and _moderation_flagged(error.body):
            return Reply("", "refused", "", 0, 0, time.perf_counter() - start)
        raise _request_error(provider, error) from error
    latency = time.perf_counter() - start
    if provider == "openrouter":
        usage = getattr(response, "usage", None)
        tokens = (usage.prompt_tokens or 0, usage.completion_tokens or 0) if usage else (0, 0)
        if not getattr(response, "choices", None):
            raise InfrastructureError("openrouter: the response has no choices", *tokens)
        if response.choices[0].finish_reason == "error":  # the upstream provider failed mid-answer
            raise InfrastructureError("openrouter: the upstream provider ended the answer with an error", *tokens)
    else:
        tokens = (response.usage.prompt_tokens, response.usage.completion_tokens)
    choice = response.choices[0]
    stop_reason = {"length": "truncated", "content_filter": "refused"}.get(choice.finish_reason, "ok")
    return Reply(choice.message.content or "", stop_reason, response.model, *tokens, latency)


def _openai(model: dict, prompt: str, max_output_tokens: int, key: str, effort: str | None = None) -> Reply:
    return _chat("openai", _openai_client(key), {
        "model": model["api_model_id"],
        "max_completion_tokens": max_output_tokens,
        "messages": [{"role": "user", "content": prompt}],
        **({"reasoning_effort": effort} if effort else {}),
        **model.get("params", {}),
    })


def _openrouter(model: dict, prompt: str, max_output_tokens: int, key: str, effort: str | None = None) -> Reply:
    # params go in the body unchanged, so OpenRouter's own fields, such as provider routing, pass through the SDK.
    return _chat("openrouter", _openai_client(key, OPENROUTER_BASE_URL), {
        "model": model["api_model_id"],
        "max_tokens": max_output_tokens,
        "messages": [{"role": "user", "content": prompt}],
        "extra_body": {**({"reasoning": {"effort": effort}} if effort else {}), **model.get("params", {})},
    })


def _google(model: dict, prompt: str, max_output_tokens: int, key: str, effort: str | None = None) -> Reply:
    import httpx
    from google import genai
    from google.genai import errors, types

    # attempts=1 means a single try, so the SDK never retries.
    options = types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1),
                               timeout=REQUEST_TIMEOUT_S * 1000)  # milliseconds
    client = genai.Client(api_key=key, http_options=options)
    start = time.perf_counter()
    try:
        response = client.models.generate_content(
            model=model["api_model_id"],
            contents=prompt,
            config={"max_output_tokens": max_output_tokens,
                    **({"thinking_config": {"thinking_level": effort.upper()}} if effort else {}),
                    **model.get("params", {})},
        )
    except errors.APIError as error:
        if error.code == 429 or error.code >= 500:
            raise InfrastructureError(f"google: {error}") from error
        raise _request_error("google", error) from error
    except httpx.TransportError as error:  # connection errors and timeouts
        raise InfrastructureError(f"google: {error}") from error
    latency = time.perf_counter() - start
    usage = response.usage_metadata
    input_tokens = (usage.prompt_token_count or 0) if usage else 0
    # Gemini bills thoughts as output; the other providers' counts already include reasoning tokens.
    output_tokens = ((usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)) if usage else 0
    blocked = response.prompt_feedback is not None and response.prompt_feedback.block_reason is not None
    finish = ""
    if response.candidates and response.candidates[0].finish_reason is not None:
        finish = response.candidates[0].finish_reason.name
    if blocked or finish in GOOGLE_REFUSALS:
        stop_reason = "refused"
    elif finish == "MAX_TOKENS":
        stop_reason = "truncated"
    else:
        stop_reason = "ok"
    text = ""
    if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
        text = "".join(part.text for part in response.candidates[0].content.parts
                       if part.text and not part.thought)
    return Reply(text, stop_reason, response.model_version or "",
                 input_tokens, output_tokens, latency)


def _fake() -> Reply:
    if not FAKE_REPLIES:
        return Reply("U", "ok", "fake", 0, 0, 0.0)
    item = FAKE_REPLIES.pop(0)
    if isinstance(item, (InfrastructureError, RequestError)):
        raise item
    return item


def _typesafe_client(**options):
    import typesafe_sdk

    return typesafe_sdk.TypeSafeClient(**options)


def _cloudflare_client(**options):
    import cloudflare

    return cloudflare.Cloudflare(**options)


_RAW_MODEL = None


def _raw_model():
    """A fully permissive pydantic model of a System One reply, so that nothing the SDK's typed
    answers would drop or change is lost, and a reply that misses the schema still returns."""
    global _RAW_MODEL
    if _RAW_MODEL is None:
        from typing import Any

        from pydantic import BaseModel, ConfigDict

        class Raw(BaseModel):
            model_config = ConfigDict(extra="allow")
            model: Any = None
            answers: Any = None
            usage: Any = None

        _RAW_MODEL = Raw
    return _RAW_MODEL


def _typesafe(model: dict, state: str, questions: dict, key: str) -> DecisionReply:
    import typesafe_sdk

    client = _typesafe_client(api_key=key, retry=typesafe_sdk.RetryPolicy(max_retries=0))
    start = time.perf_counter()
    try:
        response = client.system_one(state, questions, model=model["api_model_id"], response_model=_raw_model())
    except (typesafe_sdk.TypeSafeRateLimitError, typesafe_sdk.TypeSafeInternalServerError,
            typesafe_sdk.TypeSafeAPIConnectionError) as error:  # connection errors include timeouts
        raise InfrastructureError(f"typesafe: {error}") from error
    except typesafe_sdk.TypeSafeAPIResponseValidationError:
        # A 200 whose body is not a JSON object. The call stays empty, and the validator rules it malformed.
        return _decision_reply({}, time.perf_counter() - start)
    except typesafe_sdk.TypeSafeAPIError as error:
        # The SDK keeps the message it read from the body, whatever its shape, in `_message`.
        raise _request_error("typesafe", error, getattr(error, "_message", None)) from error
    latency = time.perf_counter() - start
    return _decision_reply(response.model_dump(exclude_unset=True), latency)


def _cloudflare(model: dict, state: str, questions: dict, key: str) -> DecisionReply:
    import cloudflare

    account = (os.environ.get(ACCOUNT_VARIABLES["cloudflare"]) or "").strip()
    if not account:
        raise ValueError(f"missing account id: set the env var {ACCOUNT_VARIABLES['cloudflare']}")
    client = _cloudflare_client(api_token=key, max_retries=0)
    body = {"model": model["api_model_id"].rsplit("/", 1)[-1], "state": state, "questions": questions}
    start = time.perf_counter()
    try:
        # The SDK has no typed request for decision models, so the body goes through extra_body.
        # It returns the envelope's result, already unwrapped, as a plain dict for this model.
        result = client.ai.run(model["api_model_id"], account_id=account, extra_body=body)
    except cloudflare.APIConnectionError as error:  # includes APITimeoutError
        raise InfrastructureError(f"cloudflare: {error}") from error
    except cloudflare.APIStatusError as error:
        if error.status_code == 429 or error.status_code >= 500:
            raise InfrastructureError(f"cloudflare: {error}") from error
        raise _request_error("cloudflare", error) from error
    latency = time.perf_counter() - start
    if hasattr(result, "model_dump"):
        result = result.model_dump()
    # A result that is not an object leaves the call empty, and the validator rules it malformed.
    return _decision_reply(result if isinstance(result, dict) else {}, latency)


def _decision_reply(data: dict, latency: float) -> DecisionReply:
    """Keep exactly the answers, usage, and model the API sent, and no other key."""
    call = {k: data[k] for k in ("answers", "usage", "model") if k in data}
    usage = call.get("usage") if isinstance(call.get("usage"), dict) else {}
    served = call["model"] if isinstance(call.get("model"), str) else ""
    return DecisionReply(call, _count(usage.get("input_tokens")), _count(usage.get("output_tokens")),
                         served, latency)


def _count(value) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _fake_decision() -> DecisionReply:
    if not FAKE_DECISION_REPLIES:
        call = {"answers": {"next_move": {"type": "choice", "choice": "done"}},
                "usage": {"input_tokens": 0, "output_tokens": 0}, "model": "fake"}
        return DecisionReply(call, 0, 0, "fake", 0.0)
    item = FAKE_DECISION_REPLIES.pop(0)
    if isinstance(item, (InfrastructureError, RefusedError)):
        raise item
    return item


def call_decision(model: dict, state: str, questions: dict) -> DecisionReply:
    """Send the state and questions to the decision model's provider and return one reply."""
    provider = model["provider"]
    if provider not in DECISION_PROVIDERS:
        raise ValueError(f"provider {provider} is not a decision-model provider")
    if provider == "fake_decision":
        return _fake_decision()
    variable = KEY_VARIABLES[provider]
    key = (os.environ.get(variable) or "").strip()
    if not key:
        raise ValueError(f"missing API key: set the env var {variable}")
    functions = {"typesafe": _typesafe, "cloudflare": _cloudflare}
    return functions[provider](model, state, questions, key)


def call_model(model: dict, prompt: str, max_output_tokens: int, reasoning_effort: str | None = None) -> Reply:
    """Send the prompt to the model's provider and return the reply in the common shape. The reasoning
    effort goes to the provider's own parameter, only for a system-2 model."""
    provider = model["provider"]
    if provider in DECISION_PROVIDERS:
        raise ValueError(f"provider {provider} is a decision-model provider: use call_decision")
    if provider == "fake":
        return _fake()
    variable = {**KEY_VARIABLES, **ENV_KEY_VARIABLES}[provider]
    key = (os.environ.get(variable) or "").strip()
    if not key:
        raise ValueError(f"missing API key: set the env var {variable}")
    functions = {"anthropic": _anthropic, "openai": _openai, "google": _google, "openrouter": _openrouter}
    effort = reasoning_effort if model.get("kind") == "system-2" else None
    return functions[provider](model, prompt, max_output_tokens, key, effort)
