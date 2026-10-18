# Spec: docs/specs/models.md
"""Sends one prompt to one AI model and returns a Reply. Reads the provider's API key from its
env var (ANTHROPIC_API_KEY, OPENAI_API_KEY, or GOOGLE_API_KEY). Writes nothing.
This is the only file that talks to an AI model API.
"""

import os
import time
from dataclasses import dataclass

KEY_VARIABLES = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "google": "GOOGLE_API_KEY"}
# Google finish reasons that mean the answer was withheld.
GOOGLE_REFUSALS = ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "RECITATION")

# Tests fill this list. Each fake call pops the first item: a Reply is returned and an
# InfrastructureError instance is raised.
FAKE_REPLIES: list = []


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


def _anthropic(model: dict, prompt: str, max_output_tokens: int, key: str) -> Reply:
    import anthropic

    client = anthropic.Anthropic(api_key=key, max_retries=0)
    start = time.perf_counter()
    try:
        response = client.messages.create(
            model=model["api_model_id"],
            max_tokens=max_output_tokens,
            messages=[{"role": "user", "content": prompt}],
            **model.get("params", {}),
        )
    except (anthropic.APIConnectionError, anthropic.RateLimitError, anthropic.InternalServerError) as error:
        raise InfrastructureError(f"anthropic: {error}") from error
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
            return Reply("", "refused", model["api_model_id"], 0, 0, time.perf_counter() - start)
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
    output_tokens = (usage.candidates_token_count or 0) if usage else 0
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
    return Reply(text, stop_reason, response.model_version or model["api_model_id"],
                 input_tokens, output_tokens, latency)


def _fake() -> Reply:
    if not FAKE_REPLIES:
        return Reply('{"moves": [], "mismatch": false}', "ok", "fake", 0, 0, 0.0)
    item = FAKE_REPLIES.pop(0)
    if isinstance(item, InfrastructureError):
        raise item
    return item


def call_model(model: dict, prompt: str, max_output_tokens: int) -> Reply:
    """Send the prompt to the model's provider and return the reply in the common shape."""
    provider = model["provider"]
    if provider == "fake":
        return _fake()
    variable = KEY_VARIABLES[provider]
    key = os.environ.get(variable)
    if not key:
        raise ValueError(f"missing API key: set the env var {variable}")
    functions = {"anthropic": _anthropic, "openai": _openai, "google": _google}
    return functions[provider](model, prompt, max_output_tokens, key)
