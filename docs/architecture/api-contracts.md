# API Contracts

> **Status:** these contracts are the target design established in Phase 1. They are
> implemented as an in-process, cloud-independent routing engine in Phase 2, wired to a
> real Bedrock adapter in Phase 3, and exposed over API Gateway + Lambda starting in
> Phase 5. Until then, no HTTP endpoint actually exists — this document defines the
> contract everything else is built toward.

## Conventions

* All request/response bodies are JSON.
* All timestamps are ISO 8601, UTC (e.g. `2026-07-26T14:03:11Z`).
* All monetary values are decimal strings or numbers representing USD, always explicitly
  labeled as **estimates** (`estimatedCostUsd`), never as billed cost.
* Every response includes a `requestId`. Every executed or evaluated routing decision
  additionally includes a `decisionId`.
* Errors follow the `ErrorResponse` shape (see below) and a stable `errorCode`.
* Clients authenticate via IAM SigV4 or a JWT bearer token, depending on the deployment's
  configured authorizer (see the authorization ADR added in Phase 5). API keys, if used
  at all, only gate usage plans/throttling — they are never treated as identity.

## Endpoints

| Method | Path | Purpose | Invokes a model? |
|---|---|---|---|
| `POST` | `/v1/inference` | Route and execute an inference request | Yes |
| `POST` | `/v1/routes/evaluate` | Explain the route that would be selected | No |
| `GET` | `/v1/models` | List logical capabilities and service tiers available to the caller | No |
| `GET` | `/v1/decisions/{decisionId}` | Retrieve a sanitized, previously recorded routing decision | No |
| `GET` | `/health` | Liveness — is the process up | No |
| `GET` | `/ready` | Readiness — can required configuration be loaded | No |

---

### `POST /v1/inference`

Routes and executes an inference request against the model selected by policy.

**Request**

```json
{
  "applicationId": "support-assistant",
  "messages": [
    { "role": "user", "content": "Summarize this incident report." }
  ],
  "requirements": {
    "capability": "balanced-text",
    "qualityTier": "standard",
    "maximumEstimatedCostUsd": 0.01,
    "maximumOutputTokens": 500,
    "latencyPreference": "balanced",
    "requiresToolUse": false,
    "requiresStructuredOutput": false
  },
  "conversationId": "conv-8f21",
  "idempotencyKey": "8f8f2a41-8f1a-4e9a-9a63-3a1c2f9c9d10",
  "metadata": {
    "useCase": "incident-summary"
  }
}
```

`requirements` is a set of *requested* constraints, not authoritative instructions — the
effective constraints applied are the intersection with the caller's `RoutingPolicy`
(see [`domain-glossary.md`](domain-glossary.md#routingpolicy)). A requirement the policy
does not permit the caller to set is ignored in favor of the policy's own limit, and this
is reflected in the decision's reason codes.

**Response — `200 OK`**

```json
{
  "decisionId": "dec_01J8X8QK9YB6T2H3XQ7R6F9Z1M",
  "response": {
    "role": "assistant",
    "content": "Normalized model response"
  },
  "route": {
    "modelAlias": "balanced-text-primary",
    "provider": "bedrock",
    "fallbackUsed": false,
    "reasonCodes": [
      "CAPABILITY_MATCH",
      "WITHIN_COST_LIMIT",
      "QUALITY_TIER_MATCH"
    ]
  },
  "usage": {
    "inputTokens": 120,
    "outputTokens": 180,
    "estimatedCostUsd": 0.0021
  },
  "requestId": "req_01J8X8QK8N5V6C1Z7Y2E4D3A9B"
}
```

**Errors**

| HTTP status | `errorCode` | Meaning | Fallback attempted? |
|---|---|---|---|
| 400 | `INVALID_REQUEST` | Request failed schema validation | No |
| 401 | `UNAUTHENTICATED` | Caller identity could not be established | No |
| 403 | `POLICY_DENIED` | Caller is not authorized for the requested capability/model | No |
| 402 | `COST_LIMIT_EXCEEDED` | All eligible routes exceed the request's or policy's cost limit | No |
| 422 | `REQUIRED_CAPABILITY_UNAVAILABLE` | No configured model provides the requested capability | No |
| 404 | `NO_ELIGIBLE_MODEL` | Candidates existed but all were filtered out (health, region, token limits) | N/A — already reflects attempted fallback |
| 429 | `THROTTLED` | Router-level throttling (API Gateway usage plan) | N/A |
| 502 | `PROVIDER_UNAVAILABLE` | Primary and all eligible fallbacks failed | Yes, exhausted |
| 500 | `INTERNAL_ERROR` | Unexpected router failure | No |

Example error body:

```json
{
  "requestId": "req_01J8X8QK8N5V6C1Z7Y2E4D3A9B",
  "errorCode": "COST_LIMIT_EXCEEDED",
  "message": "No eligible route satisfies the requested cost limit.",
  "reasonCodes": ["COST_LIMIT_EXCEEDED"]
}
```

---

### `POST /v1/routes/evaluate`

Evaluates and explains the expected route **without** invoking a model. Same request
shape as `/v1/inference`.

**Response — `200 OK`**

```json
{
  "decisionId": "dec_01J8X8R2N7S4K1D9M0P5T3W6E7",
  "route": {
    "modelAlias": "balanced-text-primary",
    "provider": "bedrock",
    "fallbackUsed": false,
    "reasonCodes": ["CAPABILITY_MATCH", "WITHIN_COST_LIMIT", "QUALITY_TIER_MATCH"]
  },
  "consideredCandidates": [
    {
      "modelAlias": "balanced-text-primary",
      "selected": true,
      "estimatedCostUsd": 0.0021,
      "reasonCodes": ["CAPABILITY_MATCH", "WITHIN_COST_LIMIT"]
    },
    {
      "modelAlias": "advanced-reasoning-primary",
      "selected": false,
      "estimatedCostUsd": 0.014,
      "reasonCodes": ["COST_LIMIT_EXCEEDED"]
    }
  ],
  "usageEstimate": {
    "inputTokens": 120,
    "outputTokens": 180,
    "estimatedCostUsd": 0.0021
  },
  "requestId": "req_01J8X8R2M9C3V5B7N1Q4W6E8T0"
}
```

---

### `GET /v1/models`

Returns the logical capabilities and quality tiers available to the authenticated
caller. Never returns raw provider model IDs, inference-profile ARNs, or pricing
internals — only the sanitized, client-facing surface.

**Response — `200 OK`**

```json
{
  "capabilities": [
    {
      "capability": "economical-text",
      "qualityTiers": ["standard"],
      "supportsToolUse": false,
      "supportsStructuredOutput": false,
      "typicalLatency": "low"
    },
    {
      "capability": "balanced-text",
      "qualityTiers": ["standard", "premium"],
      "supportsToolUse": true,
      "supportsStructuredOutput": true,
      "typicalLatency": "balanced"
    },
    {
      "capability": "advanced-reasoning",
      "qualityTiers": ["premium"],
      "supportsToolUse": true,
      "supportsStructuredOutput": true,
      "typicalLatency": "high"
    }
  ],
  "requestId": "req_01J8X8RN0T2K4M6P8Q1S3V5X7Z"
}
```

---

### `GET /v1/decisions/{decisionId}`

Returns a sanitized, previously recorded routing decision. Requires the caller's
application identity to match the decision's originating application (or an
operator/admin scope, added when administrative access is introduced).

**Response — `200 OK`**

```json
{
  "decisionId": "dec_01J8X8QK9YB6T2H3XQ7R6F9Z1M",
  "applicationId": "support-assistant",
  "createdAt": "2026-07-26T14:03:11Z",
  "policyId": "support-assistant-default",
  "policyVersion": 3,
  "capability": "balanced-text",
  "route": {
    "modelAlias": "balanced-text-primary",
    "provider": "bedrock",
    "fallbackUsed": false,
    "reasonCodes": ["CAPABILITY_MATCH", "WITHIN_COST_LIMIT", "QUALITY_TIER_MATCH"]
  },
  "usage": {
    "inputTokens": 120,
    "outputTokens": 180,
    "estimatedCostUsd": 0.0021
  },
  "invocationAttempts": [
    { "modelAlias": "balanced-text-primary", "status": "SUCCEEDED", "latencyMs": 812 }
  ],
  "requestId": "req_01J8X8QK8N5V6C1Z7Y2E4D3A9B"
}
```

**Errors**: `404 NOT_FOUND` if the decision does not exist or has expired past its
retention window; `403 POLICY_DENIED` if the caller does not own the decision.

---

### `GET /health`

Basic process liveness. No dependencies checked.

```json
{ "status": "ok" }
```

### `GET /ready`

Verifies that required configuration (routing policies, model catalogue) can be loaded.

```json
{ "status": "ready", "policyVersion": 3, "modelCatalogueVersion": 7 }
```

`503` with `{"status": "not_ready", "reason": "..."}` if configuration cannot be loaded.

---

## Explicitly out of scope for the public API

Administrative mutation of routing policies, the model catalogue, or pricing
configuration is **not** exposed through this API. Configuration changes are made through
version-controlled deployment (Phase 1–4) or a separately secured administrative
capability considered in a later phase. This keeps the blast radius of a compromised
client credential limited to inference usage within its own policy, never to changing
what any application is allowed to do.
