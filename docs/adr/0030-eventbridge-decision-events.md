# ADR-030: EventBridge decision events

## Status
Accepted

## Context
Phase 10b's "operational depth" scope (explicitly requested — see
`PROJECT_PLAN.md`) asked for a way external systems can react to routing decisions
without polling `GET /v1/decisions/{decisionId}` or scraping CloudWatch Logs Insights.
The existing observability surface (structured logs, EMF metrics, `AuditRecord`
persistence — ADR-008, ADR-019) is all pull-based or aggregate; nothing lets a
downstream consumer (an analytics pipeline, a governance/compliance system, a
cost-alerting Lambda) subscribe to individual decisions as they happen.

## Decision
`InvocationOrchestrator` gains an optional `decision_event_publisher:
domain.ports.DecisionEventPublisher | None` collaborator, called (best-effort, after
metrics publishing) at both existing "a request finished" points — the same
`InferenceResult`-shaped input `MetricsPublisher` already takes, for the same reason:
the publisher decides what to extract, not every caller.

`EventBridgeDecisionEventPublisher` (`src/adapters/events/`) is the real implementation:
one `events:PutEvents` call per completed request, `DetailType: "RoutingDecisionCompleted"`,
`Detail` containing only sanitized `RoutingDecision` fields — decision/policy IDs,
capability, selected model, provider, fallback flag, reason codes, estimated cost.
**Never** `result.response` (where real model output lives) — the same metadata-only
discipline as `AuditRecord`/`EmfMetricsPublisher` (ADR-008), verified by a dedicated test
that plants a secret in the response and confirms it never appears in the published
detail.

A dedicated `EventsConstruct` provisions a **custom** EventBridge event bus (not the
AWS account's shared default bus) unconditionally in every deployment — unlike the
OpenAI API key secret (ADR-029), an EventBridge bus has no idle cost (billed per event
published, not per bus provisioned), so there's no "only if actually used" cost
discipline to apply here. `Secret.grant_read()`'s pattern is mirrored by
`EventBus.grant_put_events_to()`: scoped to this one bus's ARN, never a wildcard.

A publish failure is caught and logged inside `EventBridgeDecisionEventPublisher.publish()`
itself, never re-raised — `domain.ports.DecisionEventPublisher`'s contract states this
explicitly. Telemetry emission must never fail the underlying `/v1/inference` request,
the same principle `EmfMetricsPublisher` already follows structurally (it can't fail
loudly since it just prints).

## Consequences
* An external system subscribes by adding an EventBridge rule targeting
  `model-router-decisions-{env}` — no code change in this project, no new IAM grant on
  this project's own Lambda (the subscriber's own infrastructure owns that).
* `CfnOutput` `DecisionEventsBusName` on the stack surfaces the bus name a rule author
  needs, the same pattern as `DashboardUrl`/`AlarmTopicArn` already established (Phase 6).
* No new persisted data store — EventBridge doesn't retain events past delivery to
  matched targets, so this is a real-time notification mechanism, not a queryable
  history (that's still `GET /v1/decisions/{decisionId}` / DynamoDB's job).
* Tested with a hand-rolled fake EventBridge client (mirrors this project's established
  pattern for every other AWS SDK boundary — Bedrock, DynamoDB), plus a CDK assertion
  test (`test_decision_events_bus_is_created`,
  `test_eventbridge_put_events_grant_is_scoped_not_wildcard`) proving the real
  synthesized template matches these claims.

## Alternatives considered
* **The account's default event bus, not a dedicated one** — rejected: the IAM
  `events:PutEvents` grant would then need to name the default bus's ARN, which is
  shared with every other AWS service in the account already publishing to it — a
  dedicated bus keeps the grant (and the mental model of "what publishes here") scoped
  to exactly this project.
* **Publishing failures re-raised, failing the request** — rejected: would make an
  operator's downstream analytics outage able to take down the actual inference API,
  turning an optional observability feature into an availability dependency. Best-effort,
  contained inside the adapter, matches this project's existing stance that telemetry is
  never allowed to be a single point of failure for the primary request path.
* **Including `considered_candidates` in the event detail** (the full per-model
  eligibility breakdown `RoutingDecision` already carries) — rejected: verbose, mostly
  redundant with what `GET /v1/decisions/{decisionId}` already exposes to anyone who
  needs that level of detail, and every additional field is one more thing to keep
  sanitized as the domain model evolves. The event is a notification, not a full record.
