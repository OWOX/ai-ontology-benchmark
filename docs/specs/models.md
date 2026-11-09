# models

File: `src/run/models.py`.

## Purpose

Send one prompt to one AI model and return the reply in the same shape for every provider, one call at a time or, in [batch mode](../definitions.md#batches), as one request among many in a provider's batch. This is the only file that talks to an AI model API.

## Inputs

1. One `models` entry from the experiment config ([config](config.md)), including its optional `params`.
2. The prompt text.
3. `max_output_tokens` and the optional `reasoning_effort` from the experiment config.
4. The provider's API key, read from its env var: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`, or `OPENROUTER_API_KEY`. For decision models: `TYPESAFE_API_KEY` for `typesafe`, and `CLOUDFLARE_API_TOKEN` plus the account id in `CLOUDFLARE_ACCOUNT_ID` for `cloudflare`.

## Outputs

`call_model(model, prompt, max_output_tokens, reasoning_effort=None) -> Reply`, where `Reply` has `text`, `stop_reason`, `served_model`, `input_tokens`, `output_tokens`, and `latency_s`. `latency_s` is a float, or `None` for a reply that came out of a batch.

1. There is one short function per provider: `anthropic`, `openai`, `google`, and `openrouter`. Each is a request builder, an SDK call, and a reply parser. The builder (`_anthropic_request`, `_openai_request`, `_google_request`, `_openrouter_request`) makes the request body, and the parser (`_anthropic_reply`, `_chat_reply`, `_google_reply`) turns the SDK's response into a `Reply`. [Batch mode](#batch-mode) uses the same builder and parser, so only the transport differs. Each calls the official SDK with its built-in retries turned off, so that [run](run.md) controls every retry. The Anthropic call streams (`messages.stream` and `get_final_message()`), because the SDK refuses a non-streaming call with a large `max_tokens`. Stream errors map like any other: a connection error, a transport error while reading the stream, HTTP 429, or HTTP 5xx is an `InfrastructureError`. An SSE `error` event arrives as a status error with code 200, so its body's `error.type` decides: `overloaded_error`, `api_error`, and `rate_limit_error` are an `InfrastructureError`, any other type is a `RequestError`.
2. Every request has the same shape: one user message holding the prompt, no system prompt, and no provider JSON mode or output schema. The prompt alone asks for the answer format (moves one per line, or `MISMATCH` and a reason), so every AI model gets the same request. `params` is passed to the SDK call unchanged.
   [Reasoning effort](../definitions.md#setups) is sent only when `reasoning_effort` is set and the model's `kind` is `system-2`, in the provider's own parameter: `output_config={"effort": effort}` for `anthropic`, `reasoning_effort=effort` for `openai`, and `thinking_config={"thinking_level": EFFORT}` in the `config` for `google`, with the level upper-cased, and `reasoning={"effort": effort}` in the body for `openrouter`. Provider `fake` ignores it, and decision models never receive it.
3. `stop_reason` is `ok` for a complete answer, `truncated` when the answer hit the token limit, and `refused` for a refusal, including a content-filter refusal the API returns as an error.
4. `served_model` is the model id the API response reports, or `""` when it reports none (a Google response without `model_version`, or an OpenAI content-filter refusal, which has no response). It is never filled in from `api_model_id`. Token counts are copied from the API response as returned. For Google, `output_tokens` is `candidates_token_count + thoughts_token_count`, both as returned, because Gemini bills thoughts as output. The other providers' counts already include reasoning tokens.
5. `latency_s` is the time from sending the request to receiving the full response. A reply read from a batch has `latency_s` `None`.
6. A network error, timeout, HTTP 429, or HTTP 5xx raises `InfrastructureError`. For `openai` and `openrouter`, HTTP 408 and 409 do too. The exception carries any token counts the API reported.
   Any other HTTP error the API returns, such as a 400 for a spent account usage limit, a 401 for a bad key, or a 404 for an unknown model, raises `RequestError`, chained to the SDK error. Its message is one line: `<provider>: HTTP <status>: <message>`, where the message is the one the API sent in its error body (`error.message`, a string `error`, or for `cloudflare` the `errors` messages joined with `; `; for `typesafe`, the message its SDK read from the body), or the SDK's text when the body has none. A stream error event, whose status is the stream's own 200, leaves out `HTTP <status>: `. It is never retried, and [run](run.md) stops on it.
7. Provider `fake` makes no network call. It returns replies from a list given to it in tests, and raises `InfrastructureError` or `RequestError` when the list says so. When the list is empty, it returns the default reply: text `U`, stop reason `ok`, served model `fake`, zero tokens, and zero latency.
8. Every request to an LLM provider (`anthropic`, `openai`, `google`, `openrouter`) has an explicit timeout, `REQUEST_TIMEOUT_S = 1800` seconds, so that no SDK default decides it: `httpx.Timeout(1800, connect=30)` for `anthropic`, `openai`, and `openrouter` (the installed SDKs take the `httpx2` class of that name), and `HttpOptions(timeout=1_800_000)` in milliseconds for `google`. The decision providers keep their SDK defaults. A timeout is a connection error, so it is an `InfrastructureError`.
9. A missing API key raises `ValueError` that names the env var, before any request is sent. The value is stripped of surrounding whitespace first, so a whitespace-only key is missing and a padded key is sent without its padding.

## Batch mode

A [batch](../definitions.md#batches) sends many requests at one provider's batch API, which answers within 24 hours at the [batch price](../definitions.md#prices). [run](run.md#batch-mode) drives it. This file holds the transport.

1. `BATCH_PROVIDERS = ("anthropic", "openai", "google", "fake")`. `openrouter` and the decision providers have no batch API. `submit_batch`, `batch_done`, and `batch_results` raise `ValueError` for a provider that is not in it.
2. `build_request(model, prompt, max_output_tokens, reasoning_effort=None) -> dict` returns the request body of one attempt in the provider's own shape, with the reasoning effort only for a system-2 model, exactly as item 2 above sends it. A direct call sends this body, and a batch line carries it, so the two requests are identical. It raises `ValueError` for a decision provider. For `fake` it returns `{"prompt", "max_output_tokens", "effort"}`.
3. `submit_batch(model, requests) -> batch id`, where `requests` is a list of `(custom id, body)` pairs. It sends them as one batch and returns the provider's id for it:
   1. `anthropic`: `client.messages.batches.create(requests=[{"custom_id", "params": body}, ...])`.
   2. `openai`: a JSONL file of `{"custom_id", "method": "POST", "url": "/v1/chat/completions", "body"}` lines, uploaded with purpose `batch`, then `client.batches.create` with `endpoint="/v1/chat/completions"` and `completion_window="24h"`.
   3. `google`: `client.batches.create(model=api_model_id, src=[...])` with one inline request per attempt, each `{"contents", "config", "metadata": {"key": custom id}}`. The batch id is the job's `name`.
4. `batch_done(model, batch id) -> bool` is true when the provider has finished with the batch, whether or not every request succeeded: `processing_status` `ended` for `anthropic`, status `completed`, `failed`, `expired`, or `cancelled` for `openai`, and `JOB_STATE_SUCCEEDED`, `JOB_STATE_PARTIALLY_SUCCEEDED`, `JOB_STATE_FAILED`, `JOB_STATE_CANCELLED`, or `JOB_STATE_EXPIRED` for `google`.
5. `batch_results(model, batch id) -> dict` returns, for a finished batch, a dict keyed by custom id. A value is a `Reply`, or an `InfrastructureError` or `RequestError` instance for a request that failed. A custom id the provider left out is left out here too, and [run](run.md#batch-mode) treats it as failed. A `Reply` has `latency_s` `None`, and the other fields come from the same parser as a direct call: a stop at the token limit is `truncated`, and a refusal is `refused`, so the validator rules both as it rules a direct reply. Results are matched by custom id only.
6. Failed requests map as follows. A `RequestError` means the request itself was rejected and retrying cannot help, as an HTTP 4xx is for a direct call.
   1. `anthropic`: result type `errored` is a `RequestError` for error type `invalid_request_error`, `authentication_error`, `billing_error`, `permission_error`, or `not_found_error`, and an `InfrastructureError` for any other type. `expired` and `canceled` are an `InfrastructureError`.
   2. `openai`: a line with status 200 is a reply, and a `content_filter` error code is a `Reply` with stop reason `refused`. A line that is not JSON or has no `custom_id` is skipped, and a line whose body can't be parsed is an `InfrastructureError` for its id alone. A line with no status, or status 408, 409, 429, or 5xx, is an `InfrastructureError`, and any other status is a `RequestError`. A batch with status `failed` and no result lines raises `RequestError` (`openai: the batch failed: <messages>`), except when its error code is `token_limit_exceeded`, which means the provider's queue was full: it returns no results, and every request is retried.
   3. `google`: a result with a `response` is a reply. One with an `error` is a `RequestError` for gRPC code 3, 5, 7, 9, or 16 (invalid argument, not found, permission denied, failed precondition, unauthenticated), and for an HTTP-style code from 400 to 499 except 408 and 429, and an `InfrastructureError` for any other code. A result with no `metadata.key` is skipped, because it can't be matched to its request: that request is retried as missing. A result that can't be parsed is an `InfrastructureError` for its key alone.
   4. The SDK calls of the batch API map errors as a direct call does: a connection error, HTTP 408, 409, 429, or 5xx is an `InfrastructureError`, and any other HTTP error is a `RequestError` with the one-line message of the direct-call error mapping above.
7. Provider `fake` makes no network call. `FAKE_BATCH_SUBMITS` records `(batch id, requests)` for each `submit_batch`, with ids `fake-batch-<n>`. `batch_results` pops the first dict of `FAKE_BATCH_RESULTS` (an empty dict when there is none), and a batch id in `FAKE_BATCH_PENDING` is not done.
8. The batch calls read the same env var for the API key as a direct call and raise the same `ValueError` when it is missing.

## OpenRouter

Provider `openrouter` sends any AI model that OpenRouter serves through its OpenAI-compatible Chat Completions API. Add a model to it with an entry in `config/models.toml` or an experiment config.

1. `api_model_id` is the OpenRouter model id, such as `<vendor>/<model>`. A price row in `config/prices.toml` is still needed under the entry's `name`.
2. It uses the `openai` SDK with `base_url="https://openrouter.ai/api/v1"`, built-in retries off, and the same timeout as `openai`. The key is read from `OPENROUTER_API_KEY`, which the [UI](ui.md#inputs) fills from `secrets/openrouter.json` like any other key.
3. The request has the same shape as for `openai`, except that the token limit is `max_tokens` and the body fields go through `extra_body`: `reasoning={"effort": effort}` for a system-2 model with a reasoning effort, then `params` unchanged. So OpenRouter's own fields, such as `provider` for routing preferences, can be set in `params`.
4. A reply maps as for `openai`. `finish_reason` `length` is `truncated` and `content_filter` is `refused`. HTTP 403 is `refused` only when its error body carries moderation metadata (`metadata.reasons` or `metadata.flagged_input`). Any other 403, such as a key over its credit limit, raises `RequestError`. A `finish_reason` of `error`, which means the upstream provider failed mid-answer, and a reply with no or empty `choices` raise `InfrastructureError` carrying the reported token counts. HTTP 402 for spent credits raises `RequestError`.
5. `served_model` is the response's `model` as returned, or `""` when the reply has none or is a moderation refusal, which has no response. Token counts are `usage.prompt_tokens` and `usage.completion_tokens`, which include reasoning tokens, or 0 when the reply has no `usage`.

## Decision models

`call_decision(model, state, questions) -> DecisionReply` sends one state and its questions to a decision model. `DECISION_PROVIDERS` lists the providers that use it: `typesafe`, `cloudflare`, and `fake_decision`. The validator and [run](run.md) read the same tuple.

1. `DecisionReply` has `call`, `input_tokens`, `output_tokens`, `served_model`, and `latency_s`. `call` holds only the keys `answers`, `usage`, and `model`, exactly as the API returned them, and a key the API did not send stays absent. It is plain and JSON-serializable, ready for the raw response array. Token counts are copied from `usage` as returned, and count as 0 when `usage` is missing. `served_model` is the reply's `model`, or `""` when the reply has none. It is never filled in from the request. A reply that misses the schema, such as a missing `model`, `answers: null`, a Cloudflare `result` that is not an object, or a Jev 200 body that is not a JSON object (the SDK's `TypeSafeAPIResponseValidationError`, which is caught), still returns an empty `call`, and the validator rules it `malformed_output`.
2. Provider `typesafe` uses `typesafe_sdk.TypeSafeClient(api_key=..., retry=RetryPolicy(max_retries=0))` and its `system_one(state, questions, model=api_model_id, response_model=...)`, which posts to `/v1/systemone`. The response model is a plain pydantic model that keeps every field as sent, so nothing the SDK's typed answers would drop or change is lost. `TypeSafeRateLimitError`, `TypeSafeInternalServerError`, and `TypeSafeAPIConnectionError`, which includes `TypeSafeAPITimeoutError`, raise `InfrastructureError`. Any other `TypeSafeAPIError`, such as the 400 `TypeSafeBadRequestError` or the 422 `TypeSafeUnprocessableEntityError`, raises `RequestError`.
3. Provider `cloudflare` uses `cloudflare.Cloudflare(api_token=..., max_retries=0)` and `client.ai.run(api_model_id, account_id=..., extra_body={"model": ..., "state": ..., "questions": ...})`. The SDK has no typed request for these models, so the body goes through `extra_body`. The body's `model` is the part of `api_model_id` after the last `/`, which is `clef` or `clef-flash`. The SDK returns the envelope's `result`, already unwrapped. `APIConnectionError`, which includes `APITimeoutError`, HTTP 429, and HTTP 5xx raise `InfrastructureError`. Any other `APIStatusError` raises `RequestError`.
4. `call_decision` raises `ValueError` for a provider that is not in `DECISION_PROVIDERS`, and `call_model` raises it for one that is. A missing key, or a missing `CLOUDFLARE_ACCOUNT_ID` (both stripped of surrounding whitespace first), raises `ValueError` that names the env var, before any request is sent.
5. `RefusedError` is for a content-filter refusal. Neither SDK has a distinct refusal error or code for these models, so no real provider raises it today. It exists for the fake and for later use. The loop driver records it as stop reason `refused`.
6. Provider `fake_decision` makes no network call. It returns the items of `FAKE_DECISION_REPLIES` in order, which tests fill: a `DecisionReply` is returned, and an `InfrastructureError` or `RefusedError` instance is raised. When the list is empty, it returns a reply whose `next_move` choice is `done`, with zero tokens and zero latency.

## How to test

No test calls a real API.

1. The fake provider returns each `stop_reason` and raises `InfrastructureError` when scripted to.
2. For each real provider, with the SDK client mocked:
   1. A normal reply gives `ok` and the served model id.
   2. A length stop gives `truncated`.
   3. A content-filter error gives `refused`.
   4. A 429, a 500, and a timeout each raise `InfrastructureError`. For `openai` and `openrouter`, a 408 and a 409 do too, and a 401 raises `RequestError`.
   5. A 400 raises `RequestError` whose message is the API's own, as in `anthropic: HTTP 400: You have reached your specified API usage limits. …`.
   6. The mock receives exactly one user message, no system prompt, and every key from `params`.
   7. The client gets the explicit timeout.
   8. For `openrouter`: the base URL, `max_tokens`, `params` and the reasoning effort in `extra_body`, a 403 with moderation metadata as `refused` and any other 403 as `RequestError`, a 401, 402, or 404 as `RequestError`, and a `finish_reason` of `error` or no choices as `InfrastructureError`.
3. A missing or whitespace-only env var raises `ValueError` with the variable's name, and a padded key or account id reaches the SDK stripped.
4. For each decision provider, with the SDK client replaced by a stub: the call shape and the reply kept exactly, HTTP 429 and 503 raising `InfrastructureError`, HTTP 400 raising `RequestError`, a missing key or account id raising `ValueError`, and the fake popping in order.
5. Replies that miss the schema: Jev with a missing `model` or `answers: null`, Jev with a body of `[1]` or text that is not JSON, and Cloudflare with a `result` that is a string, list, number, or null. Each returns normally, with the missing keys absent and `served_model` `""`.
6. Routing: `call_decision` rejects a non-decision provider and `call_model` rejects a decision provider, each with `ValueError`.
7. One test per decision provider through the real SDK client on a mock HTTP transport, asserting the request URL and JSON body and the resulting `DecisionReply`. No test uses the network.
8. An extra top-level key in the API reply never reaches `call`.
9. For each of `anthropic`, `openai`, and `google`, with the SDK client mocked, the body of a batch line equals the body of the direct call for the same prompt, with and without reasoning effort. `build_request` rejects a decision provider, and `submit_batch`, `batch_done`, and `batch_results` reject a provider with no batch API.
10. `batch_done` is true and false for each provider's states. `batch_results` with the results in shuffled order returns each reply under its custom id, for a succeeded, truncated, refused, errored, expired, and cancelled request and for a custom id missing from the results. The error mapping of Batch mode item 6 holds for each error type, including the OpenAI `token_limit_exceeded` batch and a Google result with no key.
11. The `fake` batch lists record submits, return results by custom id, and report a pending batch as not done.
