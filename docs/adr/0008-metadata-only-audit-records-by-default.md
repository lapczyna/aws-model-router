# ADR-008: Metadata-only audit records by default

## Status
Accepted

## Context
Audit records and logs are essential for debugging routing decisions, understanding
cost, and demonstrating governance. However, prompts and model responses can contain
sensitive, regulated, or simply high-risk content (PII, secrets pasted by users,
proprietary text). Persisting raw content by default would create a large, hard-to-bound
data-sensitivity surface purely as a side effect of routing.

## Decision
Audit records, structured logs, and the routing-decision store persist sanitized
metadata only by default: request/decision/correlation IDs, application ID, policy ID
and version, logical capability, selected model alias, provider, reason codes, fallback
status, latency, token counts, and estimated cost. Raw prompt and response content is
never logged or persisted by default. If an application's policy explicitly opts into
additional content retention for a documented purpose, that is a separate, deliberate
policy decision — never the default.

## Consequences
* The router's own data footprint carries substantially lower sensitivity/compliance
  risk than a system that logs full conversations, simplifying data-handling review.
* Debugging a specific bad response requires reproducing it (e.g. via
  `/v1/routes/evaluate` or the calling application's own logs) rather than pulling raw
  content from the router's audit trail — a deliberate trade-off in favor of not holding
  sensitive data at rest.
* `AuditRecord` and structured log schemas must be designed up front to be genuinely
  useful for debugging and cost analysis using metadata alone (reason codes, token
  counts, latency, fallback status) — this shaped the reason-code system in ADR-007.
* Any future opt-in content retention capability must be explicit per-application policy,
  disabled by default, and documented with its own governance/compliance implications.

## Alternatives considered
* **Log everything by default, redact later** — rejected: redaction is failure-prone and
  after-the-fact; the safer default is to never write sensitive content in the first
  place.
* **Sampled full-content logging** — rejected as a default: even sampled, it creates an
  unbounded sensitivity surface (which sample contains the one regulated payload?) and
  contradicts the "no raw prompts/responses by default" principle. Left as a possible,
  explicitly opt-in, per-application policy rather than a platform default.
