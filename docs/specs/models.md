# models

File: `src/run/models.py`.

## Purpose

Send one prompt to one AI model and return the reply in the same shape for every provider. This is the only file that talks to an AI model API.

## Inputs

1. One `models` entry from the experiment config ([config](config.md)), including its optional `params`.
2. The prompt text.
3. `max_output_tokens` from the experiment config.
4. The provider's API key, read from its env var: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `GOOGLE_API_KEY`. For decision models: `TYPESAFE_API_KEY` for `typesafe`, and `CLOUDFLARE_API_TOKEN` plus the account id in `CLOUDFLARE_ACCOUNT_ID` for `cloudflare`.

## Outputs

`call_model(model, prompt, max_output_tokens) -> Reply`, where `Reply` has `text`, `stop_reason`, `served_model`, `input_tokens`, `output_tokens`, and `latency_s`.

1. There is one short function per provider: `anthropic`, `openai`, and `google`. Each calls the official SDK with its built-in retries turned off, so that [run](run.md) controls every retry.
2. Every request has the same shape: one user message holding the prompt, no system prompt, and no provider JSON mode or output schema. The prompt alone asks for JSON, so every AI model gets the same request. `params` is passed to the SDK call unchanged.
3. `stop_reason` is `ok` for a complete answer, `truncated` when the answer hit the token limit, and `refused` for a refusal, including a content-filter refusal the API returns as an error.
4. `served_model` is the model id the API response reports, or `""` when it reports none (a Google response without `model_version`, or an OpenAI content-filter refusal, which has no response). It is never filled in from `api_model_id`. Token counts are copied from the API response as returned. For Google, `output_tokens` is `candidates_token_count + thoughts_token_count`, both as returned, because Gemini bills thoughts as output. The other providers' counts already include reasoning tokens.
5. `latency_s` is the time from sending the request to receiving the full response.
6. A network error, timeout, HTTP 429, or HTTP 5xx raises `InfrastructureError`. The exception carries any token counts the API reported.
7. Provider `fake` makes no network call. It returns replies from a list given to it in tests, and raises `InfrastructureError` when the list says so. When the list is empty, it returns the default reply: text `{"moves": [], "mismatch": false}`, stop reason `ok`, served model `fake`, zero tokens, and zero latency.
8. A missing API key raises `ValueError` that names the env var, before any request is sent.

## Decision models

`call_decision(model, state, questions) -> DecisionReply` sends one state and its questions to a decision model. `DECISION_PROVIDERS` lists the providers that use it: `typesafe`, `cloudflare`, and `fake_decision`. The validator and [run](run.md) read the same tuple.

1. `DecisionReply` has `call`, `input_tokens`, `output_tokens`, `served_model`, and `latency_s`. `call` holds only the keys `answers`, `usage`, and `model`, exactly as the API returned them, and a key the API did not send stays absent. It is plain and JSON-serializable, ready for the raw response array. Token counts are copied from `usage` as returned, and count as 0 when `usage` is missing. `served_model` is the reply's `model`, or `""` when the reply has none. It is never filled in from the request. A reply that misses the schema, such as a missing `model`, `answers: null`, a Cloudflare `result` that is not an object, or a Jev 200 body that is not a JSON object (the SDK's `TypeSafeAPIResponseValidationError`, which is caught), still returns an empty `call`, and the validator rules it `malformed_output`.
2. Provider `typesafe` uses `typesafe_sdk.TypeSafeClient(api_key=..., retry=RetryPolicy(max_retries=0))` and its `system_one(state, questions, model=api_model_id, response_model=...)`, which posts to `/v1/systemone`. The response model is a plain pydantic model that keeps every field as sent, so nothing the SDK's typed answers would drop or change is lost. `TypeSafeRateLimitError`, `TypeSafeInternalServerError`, and `TypeSafeAPIConnectionError`, which includes `TypeSafeAPITimeoutError`, raise `InfrastructureError`. Any other error, such as the 400 `TypeSafeBadRequestError` or the 422 `TypeSafeUnprocessableEntityError`, propagates.
3. Provider `cloudflare` uses `cloudflare.Cloudflare(api_token=..., max_retries=0)` and `client.ai.run(api_model_id, account_id=..., extra_body={"model": ..., "state": ..., "questions": ...})`. The SDK has no typed request for these models, so the body goes through `extra_body`. The body's `model` is the part of `api_model_id` after the last `/`, which is `clef` or `clef-flash`. The SDK returns the envelope's `result`, already unwrapped. `APIConnectionError`, which includes `APITimeoutError`, HTTP 429, and HTTP 5xx raise `InfrastructureError`. Any other `APIStatusError` propagates.
4. `call_decision` raises `ValueError` for a provider that is not in `DECISION_PROVIDERS`, and `call_model` raises it for one that is. A missing key, or a missing `CLOUDFLARE_ACCOUNT_ID`, raises `ValueError` that names the env var, before any request is sent.
5. `RefusedError` is for a content-filter refusal. Neither SDK has a distinct refusal error or code for these models, so no real provider raises it today. It exists for the fake and for later use. The loop driver records it as stop reason `refused`.
6. Provider `fake_decision` makes no network call. It returns the items of `FAKE_DECISION_REPLIES` in order, which tests fill: a `DecisionReply` is returned, and an `InfrastructureError` or `RefusedError` instance is raised. When the list is empty, it returns a reply whose `next_move` choice is `done` and with zero tokens and zero latency.

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
4. For each decision provider, with the SDK client replaced by a stub: the call shape and the reply kept exactly, HTTP 429 and 503 raising `InfrastructureError`, HTTP 400 propagating, a missing key or account id raising `ValueError`, and the fake popping in order.
5. Replies that miss the schema: Jev with a missing `model` or `answers: null`, Jev with a body of `[1]` or text that is not JSON, and Cloudflare with a `result` that is a string, list, number, or null. Each returns normally, with the missing keys absent and `served_model` `""`.
6. Routing: `call_decision` rejects a non-decision provider and `call_model` rejects a decision provider, each with `ValueError`.
7. One test per decision provider through the real SDK client on a mock HTTP transport, asserting the request URL and JSON body and the resulting `DecisionReply`. No test uses the network.
8. An extra top-level key in the API reply never reaches `call`.
