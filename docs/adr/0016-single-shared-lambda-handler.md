# ADR-016: Single shared Lambda handler

## Status
Accepted

## Context
Phase 5 exposes six HTTP routes (`/health`, `/ready`, `POST /v1/inference`,
`POST /v1/routes/evaluate`, `GET /v1/models`, `GET /v1/decisions/{decisionId}`). The
original scope allowed either "a route-evaluation Lambda" (implying per-route functions)
"or a shared handler if justified." All six routes depend on the same domain/application
layer (`RouteEvaluationService`, `InvocationOrchestrator`, the model catalogue), and
splitting them into separate Lambda functions would duplicate that wiring six times.

## Decision
One Lambda function (`src/handlers/api_handler.py`) serves all six routes. API Gateway's
proxy integration passes the full request (method, resource path, body, path/query
parameters) to the function; `dispatch()` routes internally by `(http_method, resource)`
to a thin `handle_*` function per route, each of which parses its event, calls exactly
one application service, and formats the response.

Services (the model catalogue, `RouteEvaluationService`, `InvocationOrchestrator`, the
DynamoDB decision repository) are constructed once, lazily on first invocation, and
reused by a warm execution environment across subsequent invocations
(`api_handler.handler`'s module-level `_SERVICES` cache) — avoiding re-reading the
bundled `policies/` config and re-creating boto3 clients on every request.

Every `handle_*` function takes its services as an explicit parameter
(`HandlerServices`) rather than reading module globals directly, so each is directly
unit-testable with fake adapters — the same dependency-injection pattern used throughout
`src/application/` since Phase 2 — without needing real AWS credentials or a deployed
Lambda.

## Consequences
* One execution role, one function to configure (memory/timeout/concurrency/log
  retention), one cold start path to reason about — simpler operationally than six
  separate functions with six sets of IAM permissions to keep in sync.
* All six routes share the same memory/timeout/concurrency configuration; a route with
  meaningfully different resource needs (there isn't one today — `/health` and
  `/v1/inference` are both fast relative to typical Lambda cold-start/init overhead)
  would need to be split out if that changed.
* Reserved concurrency (`config.EnvironmentConfig.lambda_reserved_concurrency`) is
  shared across all six routes — a burst of `/v1/models` traffic could, in principle,
  consume concurrency slots that `/v1/inference` needs. Acceptable at this project's
  scale; revisit if a specific route's traffic profile diverges enough to justify a
  split.
* Adding a seventh route is a matter of adding one `handle_*` function and one dispatch
  entry, plus one new API Gateway resource/method in `cdk_constructs/api_construct.py`
  — no new Lambda function, role, or bundling configuration.

## Alternatives considered
* **One Lambda function per route** — rejected: six functions means six execution
  roles (or one shared role granted to six functions — no isolation benefit either way,
  since all six need the same DynamoDB/Bedrock permissions), six sets of
  memory/timeout/concurrency knobs, and six cold-start paths, all for routes that share
  100% of their domain logic. The isolation benefit of separate functions (a bug in one
  route's handler can't affect another's execution) is real but marginal here, since the
  actual business logic lives in `src/application`/`src/domain`, shared regardless of
  how many Lambda functions call into it.
* **One function per read-only route, one for write/invoke routes** — rejected as a
  half-measure: doesn't meaningfully reduce shared-configuration complexity over a single
  function, while still duplicating the wiring code the fully-shared approach avoids
  entirely.
