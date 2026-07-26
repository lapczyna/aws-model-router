# ADR-002: Provider-independent domain architecture

## Status
Accepted

## Context
The project starts with Amazon Bedrock as its only model provider, but the stated goal
is to remain extensible to additional providers later without rewriting the routing
domain. If domain logic (filtering, scoring, fallback, cost estimation) is written
against Bedrock-specific request/response shapes, adding a second provider would require
rewriting the core routing logic rather than adding an adapter.

## Decision
The domain and application layers (`src/domain/`, `src/application/`) depend only on
provider-independent interfaces — `ModelProvider`, `ProviderRequest`, `ProviderResponse`,
and related protocols. `src/domain/` contains no `boto3` or AWS SDK imports. Concrete
provider integrations (starting with `BedrockModelProvider`) live in `src/adapters/` and
implement these interfaces.

## Consequences
* A new provider can be added by writing a new adapter that implements `ModelProvider`,
  without touching routing strategies, cost estimation, or fallback logic.
* The entire routing engine is unit-testable without AWS credentials, a network
  connection, or a live Bedrock endpoint (Phase 2).
* Provider-specific capabilities (tool use, structured output, streaming, modalities)
  must be represented explicitly in `ModelCapabilities` rather than assumed uniform,
  which adds some upfront modeling effort but avoids silent incorrect assumptions later.
* Some Bedrock-specific nuance (e.g. Converse API-specific stop-reason values) must be
  normalized at the adapter boundary, which is extra translation code but keeps that
  complexity isolated to one layer.

## Alternatives considered
* **Bedrock-specific domain models** — rejected: fastest to build initially, but
  contradicts the stated multi-provider extensibility goal and would require a domain
  rewrite (not just a new adapter) to add a second provider.
* **A generic "prompt string" abstraction with no explicit capability modeling** —
  rejected: hides real differences between models (token limits, tool use, structured
  output) that the router is specifically responsible for reasoning about; would push
  those decisions back onto every calling application.
