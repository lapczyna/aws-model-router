# Troubleshooting

Common local-development and deployment problems, and how to diagnose them. This is
about ordinary failures during development — for a suspected *security* incident, see
[`../operations/incident-response.md`](../operations/incident-response.md) instead;
for a *production alarm* firing against a deployed stack, see
[`../operations/alarm-response.md`](../operations/alarm-response.md).

## `RoutingPolicyNotFoundError: No routing policy found for application '...'`

There is no `policies/applications/<application_id>.yaml` (or `.yml`/`.json`) **and**
`policies/default_policy.yaml` doesn't exist or failed to parse. Check:

1. Does the file exist at exactly that path, named exactly `<application_id>` (case
   sensitive)? See `adapters.config.local_policy_repository.LocalFileRoutingPolicyRepository`.
2. Does `policies/default_policy.yaml` exist? If every application should have an
   explicit, dedicated policy, this is expected — see
   [`policy-authoring-guide.md`](policy-authoring-guide.md).

## `ConfigurationError: Invalid routing policy at ...` / `Invalid model catalogue at ...`

A YAML/JSON file failed Pydantic validation. The exception message includes the specific
field(s) and constraint(s) that failed — read it, it's a real Pydantic `ValidationError`,
not a generic wrapper. Common causes:

* A pricing value written as a bare number (`0.003`) instead of a quoted string
  (`"0.003"`) — see `src/domain/money.py` for why this is rejected rather than silently
  accepted as a lossy binary float.
* `preferred_model_alias` missing when `routing_strategy: preferred_model`, or set to a
  value not present in `allowed_model_aliases` — see `src/domain/policy.py`'s
  `_validate_consistency`.
* A `fallback_policy.fallback_model_aliases` entry not present in
  `allowed_model_aliases`.

## A request unexpectedly returns `NO_ELIGIBLE_MODEL` or `REQUIRED_CAPABILITY_UNAVAILABLE`

This is not a bug by default — it's the router's explicit, explainable response to a
request no eligible model satisfies (ADR-007). Run the same request through
`scripts/evaluate_route.py` and read `considered_candidates` in the output: every
candidate model lists its own `eligible` flag and `reason_codes` explaining exactly why
it was excluded (capability mismatch, cost limit, quality tier, model not allowlisted,
or — if a `ModelHealthRepository` is wired in — `MODEL_UNHEALTHY`).

## Fallback didn't happen when I expected it to

Check, in order:

1. Is `policy.fallback_policy.fallback_model_aliases` actually non-empty for this
   application? The default `FallbackPolicy()` has none configured (ADR-011).
2. Was the failure category `PERMANENT` (`NON_RETRYABLE_ERROR`)? Fallback only applies to
   `THROTTLED`/`TRANSIENT`/`TIMEOUT` — a permanent failure stops the chain immediately,
   since retrying an unfixable error wastes cost for no chance of success.
3. Is the configured fallback alias actually *eligible* for this specific request (same
   capability/cost/quality-tier checks as the primary)? An ineligible fallback alias is
   silently skipped, not force-attempted.
4. See [ADR-028](../adr/0028-fallback-chain-considers-health-excluded-candidates.md) if
   the preferred model was excluded by health tracking *before* selection, not by an
   invocation-time failure — this is a distinct path with its own history.

## `pytest -m infra` fails with a jsii/Node.js error

CDK's Python API is jsii-bridged to a Node.js runtime even for assertion-only tests like
`Template.from_stack(...)` — this requires a working system Node.js install, not just
`pip install -e ".[infra]"`. Confirm `node --version` runs successfully; if jsii itself
throws (e.g. a stale temp-directory cleanup error), the issue is usually a leftover jsii
kernel temp directory from a prior interrupted run, not your code change.

## `cdk deploy`/`cdk synth` fails after adding a model to the catalogue

`infrastructure/cdk_constructs/lambda_construct.py`'s `_load_bedrock_resource_arns`
parses `policies/model_catalogue.yaml` at synth time to scope IAM permissions — a
malformed `resolution.type`/`resolution.value` here fails at `cdk synth`, not silently at
runtime. See [`model-onboarding-guide.md`](model-onboarding-guide.md) for the exact
required shape.

## Working directory confusion with `cdk` commands

`infrastructure/` has its own `cdk.json`; `cdk` commands (`cdk synth`, `cdk deploy`,
`cdk diff`) must run from inside that directory, while most other commands in this
project's docs run from the repository root. If a `cdk` command fails with "no such app"
or similar, check `pwd` first — that's almost always the actual cause.

## Real Bedrock/DynamoDB calls print `NoCredentialsError` or similar

Only `scripts/invoke_lambda_locally.py --use-real-services`, `scripts/bedrock_live_smoke_test.py`,
and an actual deployed stack need real AWS credentials — every other script and the full
`pytest tests/` unit/contract suite runs entirely against local files and in-memory
fakes. If you didn't intend to hit AWS, you likely passed `--use-real-services` (or a
similar flag) by mistake — see `scripts/README.md`.
