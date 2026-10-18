# models

File: `src/run/models.py`.

## Purpose

Send one prompt to one AI model and return the reply in the same shape for every provider. This is the only file that talks to an AI model API.

## Inputs

1. One `models` entry from the experiment config ([config](config.md)), including its optional `params`.
2. The prompt text.
3. `max_output_tokens` from the experiment config.
4. The provider's API key, read from its env var: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `GOOGLE_API_KEY`.

## Outputs

`call_model(model, prompt, max_output_tokens) -> Reply`, where `Reply` has `text`, `stop_reason`, `served_model`, `input_tokens`, `output_tokens`, and `latency_s`.

1. There is one short function per provider: `anthropic`, `openai`, and `google`. Each calls the official SDK with its built-in retries turned off, so that [run](run.md) controls every retry.
2. Every request has the same shape: one user message holding the prompt, no system prompt, and no provider JSON mode or output schema. The prompt alone asks for JSON, so every AI model gets the same request. `params` is passed to the SDK call unchanged.
3. `stop_reason` is `ok` for a complete answer, `truncated` when the answer hit the token limit, and `refused` for a refusal, including a content-filter refusal the API returns as an error.
4. `served_model` is the model id the API response reports. Token counts are copied from the API response as returned.
5. `latency_s` is the time from sending the request to receiving the full response.
6. A network error, timeout, HTTP 429, or HTTP 5xx raises `InfrastructureError`. The exception carries any token counts the API reported.
7. Provider `fake` makes no network call. It returns replies from a list given to it in tests, and raises `InfrastructureError` when the list says so.
8. A missing API key raises `ValueError` that names the env var, before any request is sent.

## How to test

No test calls a real API.

1. The fake provider returns each `stop_reason` and raises `InfrastructureError` when scripted to.
2. For each real provider, with the SDK client mocked:
   1. A normal reply gives `ok` and the served model id.
   2. A length stop gives `truncated`.
   3. A content-filter error gives `refused`.
   4. A 429, a 500, and a timeout each raise `InfrastructureError`.
   5. The mock receives exactly one user message, no system prompt, and every key from `params`.
3. A missing env var raises `ValueError` with the variable's name.
