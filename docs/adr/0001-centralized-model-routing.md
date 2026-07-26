# ADR-001: Centralized model routing

## Status
Accepted

## Context
Multiple applications need to call foundation models. If each application integrates
directly with a model provider, model choice, cost limits, allowlists, and fallback
behavior are duplicated (and inevitably diverge) across every codebase that needs an
LLM. There is no single place to enforce which models are approved, cap spend, observe
usage, or swap/upgrade a model without touching every consumer.

## Decision
All inference requests are routed through a centralized Model Router. Applications never
call Amazon Bedrock (or any other model provider) directly; they submit a normalized
request to the router, which resolves policy, selects a model, invokes it, and returns a
normalized response.

## Consequences
* Model governance (allowlists, cost limits, quality tiers, fallback) is enforced in one
  place and can evolve without changing application code.
* The router becomes a critical-path dependency and a single point of enforcement — its
  availability and correctness matter to every consuming application. This is mitigated
  by keeping it serverless, stateless where possible, and by bounding retries/fallback
  (see ADR-007 and the Phase 4 fallback ADR).
* Every application gets consistent observability, audit, and cost telemetry for free,
  rather than reimplementing it.
* Adding or upgrading a model, or migrating between providers, becomes a configuration
  and router change instead of an N-application migration.

## Alternatives considered
* **Direct per-application Bedrock integration** — rejected: no central enforcement
  point, duplicated policy logic, inconsistent observability, and no ability to swap
  providers without touching every application.
* **A shared client library instead of a network service** — rejected: a library can be
  bypassed, cannot enforce spend limits server-side, and ships policy logic into every
  application's deploy artifact, so a policy change requires redeploying every consumer
  rather than the router alone.
