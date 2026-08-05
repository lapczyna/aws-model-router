# ADR-032: Streaming model responses

## Status
Accepted

## Context
Phase 10c (explicitly requested — "streaming," one of the unscoped Phase 10 items) asks
for streamed model output: incremental text as a model generates it, instead of waiting
for the full response. Every layer between a provider adapter and `InvocationOrchestrator`
was built around a single request in, a single `ProviderResponse` out
(`domain.ports.ModelProvider.invoke`) — streaming is a genuinely different shape, not a
parameter on the existing one.

The scope of this ADR was itself a decision, made explicitly before implementation: this
project's HTTP API (`infrastructure/cdk_constructs/api_construct.py`, ADR-016) is API
Gateway REST API with `LambdaIntegration(proxy=True)`, which buffers the Lambda's full
response before returning it to the caller — it cannot pass a chunked/streaming response
through. True end-to-end HTTP streaming needs a Lambda Function URL configured for
`InvokeWithResponseStream`, a separate invocation path with its own IAM SigV4 story,
alongside (not instead of) the existing REST API. That is a second ingress mechanism, not
an extension of this one, and was deliberately deferred rather than bundled into this
phase (see Consequences). What *is* in scope: making every layer below the HTTP boundary
— provider adapters, `CompositeModelProvider`, `InvocationOrchestrator` — genuinely
capable of streaming, fully tested, so the HTTP-layer question is the *only* thing left
when it's picked up.

## Decision
**`domain.ports.StreamingModelProvider`** is a separate, `@runtime_checkable` `Protocol`
— not a method added to `ModelProvider` itself — with one method:
`invoke_stream(request: ProviderRequest) -> Iterator[ProviderResponseChunk]`. Kept
separate so a provider adapter that cannot stream is never forced to implement a method
it would have to fake or raise `NotImplementedError` from; `@runtime_checkable` lets
`CompositeModelProvider.invoke_stream` `isinstance`-check a resolved adapter before
delegating, rather than trying and catching `AttributeError`.

**`domain.provider.ProviderResponseChunk`** is the streamed unit: intermediate chunks
carry only `delta_text` (incremental text since the previous chunk); the final chunk
(`is_final=True`) carries no further text, only `stop_reason`/`usage` — the same fields a
non-streaming `ProviderResponse` carries once the full response is known. Concatenating
every `delta_text` in order reconstructs the same text `invoke()` would have returned in
one shot.

**Both adapters implement it** (`BedrockModelProvider.invoke_stream` via Bedrock's
`ConverseStream` API, `OpenAIModelProvider.invoke_stream` via Chat Completions'
`stream=True` + `stream_options={"include_usage": True}`), mirroring each other's shape
exactly, the same discipline ADR-029 established for `invoke()`. Each is structured as an
eager outer method (resolves the model, checks capabilities, builds the request payload —
raising immediately on an invalid alias or unsupported capability, exactly like `invoke()`)
returning a lazy generator that only makes the network call once first iterated. Retries
(the existing shared `RetryPolicy`/full-jitter backoff from `adapters.common.retry`) apply
only to *establishing* the stream — once a single event/chunk has been read from it, a
failure is never retried, since a partially-sent response cannot be un-sent to whatever
already consumed the earlier chunks. Each adapter's wire-format-specific event/chunk
parsing lives in its own mapper (`iter_converse_stream_events`,
`iter_chat_completion_stream_chunks`), pure generator functions independent of the client,
mirroring the existing `parse_converse_response`/`parse_chat_completion_response` split.

**`CompositeModelProvider.invoke_stream`** dispatches exactly like `invoke` (resolve the
model, look up its provider's adapter), plus the `StreamingModelProvider` `isinstance`
check — raising `ProviderError` (category `PERMANENT`) if the resolved adapter doesn't
implement streaming. This keeps "does this specific provider support streaming" a fact
`CompositeModelProvider` alone needs to know, not something `InvocationOrchestrator` has
to detect on its own.

**`InvocationOrchestrator.invoke_stream`** evaluates a route and streams the selected
model's response, falling back across the candidate chain — but *only* while
establishing the stream, exactly mirroring the adapter-level retry boundary one layer up:
a `ProviderError` raised before any chunk has reached the caller is retried against the
next eligible candidate, the same as a synchronous `invoke()` failure; the moment a single
`ProviderResponseChunk` has been yielded, the model choice is final, and a `ProviderError`
raised while consuming the rest of that stream propagates straight to the caller instead
of silently trying a different model. Two deliberate, documented limitations, both scoped
out rather than half-built:

* **No idempotency support.** `IdempotencyStore.complete()` caches one `InferenceResult`
  with one `ProviderResponse`; there is no equivalent for a stream of chunks. A request
  with `idempotency_key` set raises `ProviderError` (category `PERMANENT`) immediately,
  before route evaluation.
* **`InferenceResult.response` is always `None`, even on success.** The full response is
  never materialized as one object here — only its constituent chunks, which the caller
  already consumed directly. Verified against real consumers, not assumed: neither
  `EmfMetricsPublisher` nor `EventBridgeDecisionEventPublisher` reads `result.response` at
  all (both only use `result.decision`/`result.invocation_attempts`), so persistence is
  unaffected by this.

Persistence (`AuditRecord` via `RoutingDecisionRepository`, `MetricsPublisher`,
`DecisionEventPublisher`) happens once per streamed request, exactly once — either when
the returned iterator is fully drained (reaches its final chunk) or when it terminally
fails. A caller that abandons the iterator early (stops consuming before either of those)
triggers no persistence for that request, the streaming equivalent of a client that
disconnects before an HTTP response finishes.

## Consequences
* No new trust boundary and no threat-model update: `invoke_stream` reuses the exact same
  Bedrock/OpenAI SDK clients, credentials, and network paths `invoke()` already uses
  (`ConverseStream`/Chat-Completions-with-`stream=True` are different API shapes on the
  same boundary, not a new one) — Boundary 6's OpenAI threats (T23/T24, ADR-029) already
  cover it. No new AWS resource or IAM permission was added, unlike Phase 10a/10b.
* Every layer below the HTTP boundary is genuinely stream-capable and independently
  tested — a real capability, not scaffolding. What's *not* built: any way for an HTTP
  caller to actually receive a streamed response. `POST /v1/inference` is unchanged and
  still fully buffered; `InvocationOrchestrator.invoke_stream` currently has no caller in
  this codebase outside its own test suite. Wiring an HTTP-reachable streaming endpoint is
  future work requiring a Lambda Function URL (`InvokeWithResponseStream`) as a second
  ingress path alongside API Gateway, with its own IAM auth design (Function URL IAM auth
  differs from SigV4-via-API-Gateway) and its own threat-model entries — deliberately not
  done in this phase (see Context).
* A caller of `invoke_stream` currently has no way to learn `decision_id` up front (only
  after the fact, via the persisted `AuditRecord` / `GET /v1/decisions/{decisionId}`, or
  the EventBridge decision event) — resolving real-time decision-ID correlation for a
  streaming caller is part of the same future HTTP-layer work above, not solved here.
* Idempotent replay of a streamed response is not supported at all (see Decision) —
  a caller that needs idempotency must use the non-streaming `invoke()`.
* An attempt's recorded `latency_ms` for a streamed request spans from the attempt
  starting to the stream being fully consumed — including however long the caller itself
  takes to pull each chunk, not just provider-side latency. This is inherent to measuring
  wall-clock time across a generator that yields control back to the caller between
  chunks, and mirrors how a real streaming HTTP response's total duration is normally
  measured (time-to-last-byte, not just time-to-first-byte).

## Alternatives considered
* **Add `invoke_stream` directly to `ModelProvider`** — rejected: would force every
  current and future adapter to implement streaming or fake it (e.g. buffering the whole
  response into one "streamed" chunk), defeating the point of `ModelProvider` describing
  only what every provider actually does.
* **Build the Lambda Function URL / `InvokeWithResponseStream` endpoint in this same
  phase** — rejected: a second ingress mechanism with its own auth model and threat
  surface is a large, independently-scopable unit of work in its own right (matching how
  ADR-016's REST API decision itself was), not something to bundle into the same phase as
  proving the domain/adapter/orchestrator layers can stream at all. Scoping it separately
  keeps this phase's DoD verifiable end-to-end without a half-finished HTTP surface.
* **Have `InvocationOrchestrator.invoke_stream` reconstruct a full `ProviderResponse` by
  concatenating chunks, to keep `InferenceResult.response` populated on success** —
  rejected after checking real consumers: neither existing `InferenceResult` consumer
  reads `.response`, so reconstructing it would be speculative work serving no current
  caller, and reopens the exact `response=None`-only-means-failure ambiguity a future
  consumer would need to be taught to ignore for the streaming case anyway.
* **Retry a mid-stream failure against a fresh call to the *same* model** (rather than
  treating any post-first-chunk failure as terminal) — rejected: even retrying the same
  model would resend the whole prompt and start the visible text over from the beginning,
  which is indistinguishable from silent duplication/corruption to a caller who already
  received and likely already displayed or forwarded the earlier chunks.
