# ADR-013: Idempotency strategy

## Status
Accepted

## Context
A client may retry an inference request (e.g. after a timeout on their side) supplying
the same `idempotency_key`. Two distinct problems need solving, and they have different
correct answers:

1. **Concurrent duplicates**: two simultaneous requests with the same key must not both
   invoke a model — that would double the cost and could return two different
   responses for what the client considers one logical request.
2. **Replay after completion**: a *later*, non-overlapping request with the same key —
   should it get a freshly-invoked result, or the original response replayed? Per
   ADR-008, the router does not persist raw model responses by default; replaying one
   requires exactly the content retention ADR-008 says must be opt-in.

There is also a data-integrity concern: a client might reuse an idempotency key across
requests with genuinely different content (a bug, or a malicious replay with a modified
payload) — this must be rejected, not served a mismatched cached result.

## Decision
Idempotency is modeled as `domain.ports.IdempotencyStore`, keyed by
`(application_id, idempotency_key)`, with the request's normalized content hashed
(`domain.idempotency.compute_request_hash`) and compared on every reservation attempt:

* **Concurrency dedup always applies**, unconditionally, once a client supplies an
  idempotency key — this is a cost/correctness control, not something a policy can turn
  off. `InvocationOrchestrator` calls `store.reserve(...)` before doing any routing or
  invocation work; a concurrent in-flight duplicate gets
  `domain.errors.IdempotencyInProgressError` rather than triggering a second invocation.
* **Response replay is policy-gated**: `RoutingPolicy.idempotency_policy
  .allow_response_caching` (default `False`) controls whether a *completed* result is
  retained and replayed to a later request with the same key. When `False` (the
  default), `store.complete(...)` releases the reservation immediately rather than
  retaining the response — a subsequent, non-overlapping request with the same key is
  treated as genuinely new. When `True`, the result is retained for
  `idempotency_policy.retention_seconds` (default 300s) before expiring.
* **Key reuse with different content is a hard error**: if the stored request hash for
  a still-valid record doesn't match the incoming request's hash,
  `domain.errors.IdempotencyConflictError` is raised — never silently served the
  mismatched prior result.

The reference implementation, `adapters.memory.InMemoryIdempotencyStore`, is a
thread-safe, single-process store using one lock held for the full check-then-act
reservation sequence (necessary — releasing the lock between "check" and "set" would
reopen exactly the race condition idempotency exists to prevent). It additionally bounds
how long an abandoned "in progress" reservation is honored
(`stale_reservation_seconds`, independent of `IdempotencyPolicy.retention_seconds`) as a
safety net if a process crashes mid-request without calling `complete()`/`release()`.

## Consequences
* Concurrency-safety is guaranteed within a single process; it is **not** guaranteed
  across multiple router instances with the in-memory store — a DynamoDB-backed
  implementation using conditional writes (`ConditionExpression` on a partition key) is
  required for that and is explicitly Phase 5 scope, implementing the same
  `IdempotencyStore` protocol without any change to `InvocationOrchestrator`.
* Callers (eventually, the Phase 5 HTTP handler) must map `IdempotencyInProgressError`
  and `IdempotencyConflictError` to appropriate HTTP statuses (409 Conflict is the
  natural fit for both) — this ADR fixes the domain-level contract; the HTTP mapping is
  deferred.
* Because caching is off by default, most applications get concurrency-dedup with no
  response-retention risk at all — the common case requires no data-sensitivity review.
* `compute_request_hash` intentionally excludes `conversation_id`, `idempotency_key`
  itself, and `metadata` — only `application_id`, `messages`, and `requirements` are
  hashed, since those are what "the same logical request" means; a client sending
  different metadata alongside identical messages/requirements is still the same
  request for idempotency purposes.

## Alternatives considered
* **No dedicated idempotency layer — treat every request as independent** — rejected:
  directly contradicts the explicit Phase 1 requirement (FR-6) and leaves retried
  client requests free to double-invoke and double-bill.
* **Always cache and replay responses** — rejected: makes response-content retention
  the default, which ADR-008 explicitly forbids; would also silently serve stale
  results to a legitimately-new request past what the client intended as their retry
  window, if no expiry were enforced.
* **Reject key reuse outright regardless of content match** — rejected: this would
  break the primary use case idempotency keys exist for (a client safely retrying the
  *same* request after a timeout) — the fix is precisely a content-hash *comparison*,
  not a blanket rejection of key reuse.
