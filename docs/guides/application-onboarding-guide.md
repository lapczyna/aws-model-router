# Application onboarding guide

How to onboard a new client application — a new logical caller of the router's API. See
[`policy-authoring-guide.md`](policy-authoring-guide.md) for the mechanics of the
`RoutingPolicy` file this workflow centers on, and
[`../security/security-architecture.md`](../security/security-architecture.md) for how
`application_id` fits into the router's layered authorization model.

## 1. Decide: dedicated policy, or the default?

Every request carries an `applicationId`. If no file exists at
`policies/applications/<applicationId>.yaml` (or `.yml`/`.json`),
`policies/default_policy.yaml` (deliberately conservative — a single, cheap, allowlisted
model) applies instead. Start with the default while prototyping; write a dedicated file
once the application's real capability/cost/latency needs are known — using the default
long-term for a real application is a choice to actively make, not an oversight, since it
means sharing that conservative policy's limits with every other unconfigured caller.

## 2. Write the policy file

`policies/applications/<applicationId>.yaml`, named exactly to match the `applicationId`
your client will send. See [`policy-authoring-guide.md`](policy-authoring-guide.md) for
every field; at minimum, decide:

* Which capabilities and models this application may use
  (`allowed_capabilities`/`allowed_model_aliases`) — see
  [`model-onboarding-guide.md`](model-onboarding-guide.md) if the model you want isn't in
  the catalogue yet.
* A cost ceiling (`maximum_estimated_cost_usd`) appropriate to this application's expected
  volume — see `docs/cost/cost-comparison-report.md` for how much capability-tier choice
  alone affects cost.
* A routing strategy (`preferred_model`, `lowest_cost`, `quality_tier`, or `experiment`)
  and, if `preferred_model`, whether to also configure `fallback_policy` for automatic
  recovery from a transient provider failure.
* Whether to allow response caching for idempotent retries
  (`idempotency_policy.allow_response_caching`).

## 3. IAM authorization

Every `/v1/*` route requires a SigV4-signed request from an IAM principal holding
`execute-api:Invoke` on this API (ADR-015) — there is no separate per-application API key
or credential to provision. Ensure the calling application's IAM principal (a role or
user) has that permission; this is independent of the `RoutingPolicy` file above, which
governs *what* an authenticated caller may request, not *whether* it's authenticated.

**Known limitation**: IAM proves the caller's identity, not that the `applicationId` it
claims in the request body actually belongs to it — see
[ADR-015](../adr/0015-api-authorization-model.md) and `docs/security/threat-model.md`'s
T2 for the detective control in place (every request's `caller_principal_arn` is logged
next to its claimed `applicationId`) and the documented, not-yet-built preventive fix.
If this matters for your application (e.g. multi-tenant, less-trusted callers), read
that section before onboarding.

## 4. Test locally before deploying

```bash
# Evaluate a route without invoking any model:
python scripts/evaluate_route.py --request <a snake_case InferenceRequest JSON for your applicationId>

# Full HTTP round trip, including your new policy, with a fake model provider:
python scripts/invoke_lambda_locally.py --method POST --resource /v1/inference \
    --body <a camelCase HTTP request body for your applicationId>
```

Neither requires AWS credentials. See `scripts/examples/README.md` and
`events/README.md` for the exact request shapes each script expects.

## 5. Deploy

Policy files are version-controlled configuration, deployed the same way as any other
code change (ADR-010) — there is no separate, unreviewed runtime configuration path. See
[`../operations/deployment-and-teardown.md`](../operations/deployment-and-teardown.md).

## 6. Verify in production

Once deployed, confirm real requests from the new application resolve the intended
policy and land where expected — `docs/operations/observability.md` documents the
CloudWatch Logs Insights queries for this (filter by `application_id`).
