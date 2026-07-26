# ADR-006: Model aliases instead of client-supplied model IDs

## Status
Accepted

## Context
If clients could pass a raw provider model ID (e.g. a specific Bedrock model ID or
inference-profile ARN) in the request, the router's policy enforcement would be
cosmetic: any caller could request any model regardless of allowlists, cost tier, or
governance constraints, and every application would need to know provider-specific
identifiers that may change over time.

## Decision
Clients request logical capabilities (e.g. `economical-text`, `balanced-text`,
`advanced-reasoning`, `low-latency-text`, `structured-output`, `tool-capable`) or
optional quality tiers — never raw provider model IDs. Trusted, server-side router
configuration (the model catalogue and routing policy) maps these logical capabilities
to eligible model aliases, which in turn resolve to direct model IDs, cross-Region
inference profiles, or application inference profiles.

## Consequences
* Model allowlisting and governance are enforceable server-side; a client cannot bypass
  policy by simply naming a different model.
* Applications are insulated from provider identifier churn — when a model ID or
  inference-profile ARN changes, only router configuration changes, not every client.
* The router must maintain and version a model catalogue mapping capabilities → aliases →
  concrete identifiers (see ADR-010), which is additional configuration surface area but
  is exactly the governance control this project exists to demonstrate.
* Clients lose the ability to pin to an exact model version through the public API by
  design; if a specific application genuinely needs that, it must be expressed as a
  policy-approved capability/alias, not a bypass.

## Alternatives considered
* **Allow client-supplied model IDs with server-side allowlist validation** — rejected:
  still leaks provider-specific identifiers into every client, couples clients to
  provider/model lifecycle changes, and makes "what is this application allowed to use"
  harder to reason about than a capability-based contract.
* **Let clients specify a model family/version freely and only block disallowed ones** —
  rejected: same coupling problem, and shifts the burden of understanding model
  capabilities (token limits, tool support) onto every application instead of
  centralizing it in the router's model catalogue.
