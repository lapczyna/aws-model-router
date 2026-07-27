# ADR-018: DynamoDB decision and idempotency store design

## Status
Accepted

## Context
Phase 4 built `IdempotencyStore` and `RoutingDecisionRepository` as protocols with a
single-process, in-memory reference implementation (`adapters.memory`), explicitly
deferring a multi-instance-safe implementation to Phase 5 (ADR-013). A deployed Lambda
function runs as multiple concurrent execution environments with no shared memory, so
the in-memory store's single lock provides no cross-instance safety at all once
deployed — a real, multi-instance-safe backing store is required, not optional, for
Phase 5 (unlike the model/policy configuration table, which Phase 5 explicitly chose
*not* to provision — see ADR-010's Phase 5 confirmation in `PROJECT_PLAN.md`).

## Decision
Two separate DynamoDB tables (`cdk_constructs/storage_construct.py`), not a
single-table design:

* **Decisions table** — partition key `decisionId` (string). Backs
  `GET /v1/decisions/{decisionId}`. TTL attribute `expiresAt`, platform-wide retention
  (`EnvironmentConfig`-driven, not per-application policy — audit retention is an
  operational setting, not something an individual application configures).
* **Idempotency table** — partition key `pk` (`applicationId`), sort key `sk`
  (`idempotencyKey`). Backs `DynamoDbIdempotencyStore`. TTL attribute `expiresAt`.

Both tables: on-demand billing (no idle cost, ADR-005), explicit
`TableEncryption.AWS_MANAGED` encryption, and an environment-driven removal policy and
point-in-time-recovery setting (`dev`: `DESTROY`/no PITR; `prod`: `RETAIN`/PITR on).

Atomicity for the idempotency store's `reserve()` — the operation that must guarantee
exactly one caller wins when two concurrent Lambda invocations race on the same key —
comes from a DynamoDB **conditional `put_item`**:
`ConditionExpression="attribute_not_exists(pk) OR expiresAt < :now"`. This is evaluated
server-side by DynamoDB itself, so it holds across any number of concurrent Lambda
execution environments — unlike the Phase 4 in-memory store's single-process lock, which
only ever protected against races within one process.

`complete()` mirrors the in-memory store's ADR-013 semantics exactly: if the
application's `IdempotencyPolicy.allow_response_caching` is `False` (default), the
record is deleted immediately rather than retained — a later, non-overlapping duplicate
request is treated as genuinely new. If caching is enabled, the record is overwritten
with `status=completed`, the serialized `InferenceResult`, and a `retention_seconds`-based
expiry.

## Consequences
* `InvocationOrchestrator` and every domain/application type are completely unaware
  this swap happened — both `DynamoDbIdempotencyStore` and
  `DynamoDbRoutingDecisionRepository` implement the exact same `domain.ports` protocols
  the in-memory versions do (ADR-002's dependency inversion paying off exactly as
  intended).
* `InferenceResult`/`AuditRecord` are stored as a single JSON string attribute
  (`result.model_dump_json()` / `audit_record.model_dump_json()`), not mapped into
  DynamoDB's native Map/List attribute types — simpler to implement and reason about
  than a hand-maintained attribute-by-attribute mapping, at the cost of not being able
  to query on nested fields (e.g. "all decisions for model X") without a table scan;
  acceptable since the only required access pattern is a decisionId lookup.
* A rare race — the conditional put fails (a valid record exists) but a following
  `get_item` finds nothing, because the record expired/was released in between — is
  handled with one bounded retry (`_MAX_RESERVE_ATTEMPTS = 2`) rather than an unbounded
  loop, then falls back to treating the reservation as `NEW`.
* Retention/TTL cleanup is DynamoDB's own background TTL sweep (typically within 48
  hours of expiry per AWS's documented behavior, not immediate) — `reserve()`'s
  conditional expression (`expiresAt < :now`) treats an expired-but-not-yet-swept item
  as absent regardless, so correctness doesn't depend on TTL sweep timing, only
  eventual storage reclamation does.

## Alternatives considered
* **Single-table design** (one table, item-type discriminator prefix) — rejected: the
  two access patterns (decision lookup by ID; idempotency lookup by
  application+key) don't share a natural key structure, and a reviewer reading two
  small, clearly-named tables can understand the schema faster than one table
  requiring a key-prefix convention to be understood first. Standard DynamoDB advice to
  prefer single-table design is strongest when access patterns and cost at scale
  dominate; neither does here.
* **DynamoDB Transactions (`TransactWriteItems`) for `reserve()`** — rejected: a
  transaction is for coordinating multiple items atomically; `reserve()` only needs a
  conditional write to a single item, which a plain conditional `put_item` already
  provides more simply and cheaply (transactions cost roughly double the write capacity
  of an equivalent non-transactional write).
* **Storing `InferenceResult`/`AuditRecord` as native DynamoDB Maps** — rejected for
  Phase 5: would require a hand-written, kept-in-sync-by-hand mapping for every nested
  domain model field, for a query capability (filtering on nested attributes) nothing
  in this project currently needs.
