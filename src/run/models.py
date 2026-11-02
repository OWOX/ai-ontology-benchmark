# Spec: docs/specs/models.md
"""Sends one prompt to one AI model and returns a Reply, or one state and its questions to one
decision model and returns a DecisionReply. Reads the provider's API key from its env var
(ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY, TYPESAFE_API_KEY, or CLOUDFLARE_API_TOKEN, plus
CLOUDFLARE_ACCOUNT_ID). Writes nothing.
This is the only file that talks to an AI model API.
"""

import os
import time
from dataclasses import dataclass

KEY_VARIABLES = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "google": "GOOGLE_API_KEY",
                 "typesafe": "TYPESAFE_API_KEY", "cloudflare": "CLOUDFLARE_API_TOKEN"}
# A second variable some providers need besides the key.
ACCOUNT_VARIABLES = {"cloudflare": "CLOUDFLARE_ACCOUNT_ID"}
# Providers of decision models, which are called with call_decision() instead of call_model().
DECISION_PROVIDERS = ("typesafe", "cloudflare", "fake_decision")
# Google finish reasons that mean the answer was withheld.
GOOGLE_REFUSALS = ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "RECITATION")

# Tests fill this list. Each fake call pops the first item: a Reply is returned and an
# InfrastructureError instance is raised.
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


def _anthropic(model: dict, prompt: str, max_output_tokens: int, key: str) -> Reply:
    import anthropic

    client = anthropic.Anthropic(api_key=key, max_retries=0)
    start = time.perf_counter()
    try:
        # Streamed, because the SDK refuses a non-streaming call with a large max_tokens.
        with client.messages.stream(
            model=model["api_model_id"],
            max_tokens=max_output_tokens,
            messages=[{"role": "user", "content": prompt}],
            **model.get("params", {}),
        ) as stream:
            response = stream.get_final_message()
    except anthropic.APIConnectionError as error:
        raise InfrastructureError(f"anthropic: {error}") from error
    except anthropic.APIStatusError as error:
        if error.status_code == 429 or error.status_code >= 500:
            raise InfrastructureError(f"anthropic: {error}") from error
        raise
    latency = time.perf_counter() - start
    stop_reason = {"max_tokens": "truncated", "refusal": "refused"}.get(response.stop_reason, "ok")
    text = "".join(block.text for block in response.content if block.type == "text")
    return Reply(text, stop_reason, response.model, response.usage.input_tokens,
                 response.usage.output_tokens, latency)


def _openai(model: dict, prompt: str, max_output_tokens: int, key: str) -> Reply:
    import openai

    client = openai.OpenAI(api_key=key, max_retries=0)
    start = time.perf_counter()
    try:
        response = client.chat.completions.create(
            model=model["api_model_id"],
            max_completion_tokens=max_output_tokens,
            messages=[{"role": "user", "content": prompt}],
            **model.get("params", {}),
        )
    except openai.BadRequestError as error:
        if error.code == "content_filter":
            return Reply("", "refused", "", 0, 0, time.perf_counter() - start)
        raise
    except (openai.APIConnectionError, openai.RateLimitError, openai.InternalServerError) as error:
        raise InfrastructureError(f"openai: {error}") from error
    latency = time.perf_counter() - start
    choice = response.choices[0]
    stop_reason = {"length": "truncated", "content_filter": "refused"}.get(choice.finish_reason, "ok")
    return Reply(choice.message.content or "", stop_reason, response.model,
                 response.usage.prompt_tokens, response.usage.completion_tokens, latency)


def _google(model: dict, prompt: str, max_output_tokens: int, key: str) -> Reply:
    import httpx
    from google import genai
    from google.genai import errors, types

    # attempts=1 means a single try, so the SDK never retries.
    options = types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1))
    client = genai.Client(api_key=key, http_options=options)
    start = time.perf_counter()
    try:
        response = client.models.generate_content(
            model=model["api_model_id"],
            contents=prompt,
            config={"max_output_tokens": max_output_tokens, **model.get("params", {})},
        )
    except errors.APIError as error:
        if error.code == 429 or error.code >= 500:
            raise InfrastructureError(f"google: {error}") from error
        raise
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
    if isinstance(item, InfrastructureError):
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
    latency = time.perf_counter() - start
    return _decision_reply(response.model_dump(exclude_unset=True), latency)


def _cloudflare(model: dict, state: str, questions: dict, key: str) -> DecisionReply:
    import cloudflare

    account = os.environ.get(ACCOUNT_VARIABLES["cloudflare"])
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
        raise
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
    key = os.environ.get(variable)
    if not key:
        raise ValueError(f"missing API key: set the env var {variable}")
    functions = {"typesafe": _typesafe, "cloudflare": _cloudflare}
    return functions[provider](model, state, questions, key)


def call_model(model: dict, prompt: str, max_output_tokens: int) -> Reply:
    """Send the prompt to the model's provider and return the reply in the common shape."""
    provider = model["provider"]
    if provider in DECISION_PROVIDERS:
        raise ValueError(f"provider {provider} is a decision-model provider: use call_decision")
    if provider == "fake":
        return _fake()
    variable = KEY_VARIABLES[provider]
    key = os.environ.get(variable)
    if not key:
        raise ValueError(f"missing API key: set the env var {variable}")
    functions = {"anthropic": _anthropic, "openai": _openai, "google": _google}
    return functions[provider](model, prompt, max_output_tokens, key)
