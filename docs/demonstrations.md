# Sample demonstrations

Thirteen concrete, reproducible demonstrations of `aws-model-router`'s behavior — the
capabilities a reviewer would most want to see working, each runnable locally without
AWS credentials (except where noted) using the exact commands below. Every command here
has been run against this repository; none is aspirational. (The first ten were the
original Phase 9 set; #11 was added in Phase 10a alongside multi-provider routing; #12
and #13 were added in Phase 10b alongside EventBridge decision events and OpenTelemetry
tracing.)

Setup, once:

```bash
pip install -e ".[dev]"
```

## 1. Basic routing decision

```bash
python scripts/evaluate_route.py --request scripts/examples/support_assistant_balanced.json
```

Evaluates a route for `support-assistant`'s `lowest_cost` strategy, no model invoked, no
AWS credentials needed. Shows the full `RoutingDecision`: selected model, reason codes,
every candidate considered and why it was (in)eligible. See
[ADR-007](adr/0007-deterministic-explainable-routing.md).

## 2. Fallback on provider failure

```bash
python scripts/run_demo_scenarios.py --scenario fallback
```

Simulates the preferred model being throttled and shows the orchestrator automatically
retrying the policy's configured fallback model, returning a successful response with
`fallback_used: true`. See [ADR-011](adr/0011-fallback-eligibility.md).

## 3. Weighted experimentation

```bash
python scripts/evaluate_route.py --request scripts/examples/experiment_routing.json
```

`experimental-app`'s weighted (70/30) experiment strategy deterministically assigns a
given `conversation_id` to one arm — the same conversation always lands in the same arm,
a pure hash of `experiment_id + application_id + conversation_id`. See
[ADR-012](adr/0012-deterministic-experimentation.md).

## 4. Idempotent duplicate request

```bash
python scripts/run_demo_scenarios.py --scenario idempotency
```

Invokes the same request (same `idempotency_key`) twice and shows the model was only
actually invoked once — the second call returns the identical cached decision. See
[ADR-013](adr/0013-idempotency-strategy.md).

## 5. Cost-limit rejection

```bash
python scripts/evaluate_route.py --request scripts/examples/cost_limit_exceeded.json
```

A client-supplied cost ceiling tighter than the policy's own limit excludes the only
otherwise-eligible candidate, returning `NO_ELIGIBLE_MODEL` rather than silently ignoring
the limit. See `docs/cost/cost-estimation-guide.md`.

## 6. Model health degradation

```bash
python scripts/run_demo_scenarios.py --scenario health-degradation
```

Repeatedly fails one model to show `HEALTHY → DEGRADED → UNAVAILABLE` transitions, and
that once a model is `UNAVAILABLE` it's skipped entirely (no wasted invocation) while
requests still succeed via the healthy fallback. See
[ADR-020](adr/0020-model-health-signal-scope.md) and
[ADR-028](adr/0028-fallback-chain-considers-health-excluded-candidates.md) — the latter
fixed a real gap this project's own Phase 9 fault-injection testing found, where a
health-excluded preferred model caused total request failure instead of falling back.

## 7. Full HTTP round trip

```bash
python scripts/invoke_lambda_locally.py --method POST --resource /v1/inference \
    --body events/support_assistant_balanced.json
```

Invokes the real Lambda handler code (`src/handlers/api_handler.py`) against a synthetic
API Gateway event — actual request parsing, routing, error mapping, and response
serialization, end to end, with a deterministic in-process `EchoModelProvider` standing
in for Bedrock. See `scripts/README.md` for the real-mode variant (`--use-real-services`)
against an actual deployed stack, if you have one.

## 8. Observability: metrics and logs for one request

```bash
python scripts/run_demo_scenarios.py --scenario observability
```

Runs one request through a real `EmfMetricsPublisher` and the structured JSON logging
formatter, printing exactly the log/metric lines CloudWatch would capture in a real
deployment — metadata only (decision ID, model alias, status, cost estimate), never raw
prompt/response content. See [ADR-019](adr/0019-observability-approach.md),
[ADR-008](adr/0008-metadata-only-audit-records-by-default.md), and
`docs/operations/observability.md`.

## 9. Security abuse case: no raw content ever leaks into logs or audit records

```bash
python -m pytest tests/unit/handlers/test_abuse_cases.py -v
```

Sends a request containing a distinctive sentinel string in the prompt and asserts it
never appears in the persisted `AuditRecord` or in any structured log line
(`test_sentinel_prompt_never_appears_in_the_persisted_audit_record`,
`test_sentinel_prompt_never_appears_in_structured_logs`) — an automated, adversarial
test of the same guarantee Demonstration 8 shows in the positive case. See
`docs/security/threat-model.md`.

## 10. CI/CD: IaC scanning catching a real bug

```bash
cd infrastructure
CDK_NAG_ENABLED=true cdk synth -c env=dev --quiet
pip install "cfn-lint>=1.0,<2.0"
cfn-lint --ignore-checks W3005 W3037 --template cdk.out/ModelRouter-dev.template.json
```

Reproduces the exact CI check (`.github/workflows/pr.yml`'s `iac-security-scan` job)
that, during Phase 8, caught a real deployment-breaking defect: CDK's
`Tags.of(stack).add(...)` was tagging the `AWS::CloudWatch::Dashboard` resource, but
CloudFormation's schema for that resource type doesn't accept a `Tags` property at all —
cdk-nag's construct-tree security rules never flagged this (it's a schema-conformance
issue, not a security/best-practice one), only cfn-lint's template-schema validation did.
See [ADR-027](adr/0027-iac-security-scanning-approach.md) for the full story, including
why both tools are run rather than either alone.

## 11. Cross-provider fallback (Bedrock primary, OpenAI fallback)

```bash
python scripts/run_demo_scenarios.py --scenario multi-provider-fallback
```

A single fallback chain spans two different vendors: `policies/applications/
multi-provider-demo.yaml` configures Bedrock as preferred with OpenAI as fallback.
`CompositeModelProvider` dispatches each attempt to the correct adapter based on the
catalogued model's `provider` field — proof that ADR-002's provider-independence claim
holds for a genuinely different vendor, not just a second Bedrock model family. See
[ADR-029](adr/0029-multi-provider-routing-openai.md).

## 12. EventBridge decision events

```bash
python scripts/run_demo_scenarios.py --scenario decision-events
```

One sanitized `RoutingDecisionCompleted` event is published to EventBridge per completed
request, against a fake client so the exact event `Detail` is printed to the console —
decision/policy IDs, capability, selected model, cost, never raw prompt/response content.
An external system subscribes by adding a rule to the deployed
`model-router-decisions-{env}` bus, no code change needed. See
[ADR-030](adr/0030-eventbridge-decision-events.md).

## 13. OpenTelemetry distributed tracing

```bash
python scripts/run_demo_scenarios.py --scenario tracing
```

Runs one request that throttles on its preferred model and falls back, against a real,
locally-constructed `TracerProvider` + `InMemorySpanExporter`, and prints every span
created: `model_router.evaluate_route`, `model_router.invoke`, and one
`model_router.invoke_attempt` per fallback-chain candidate, correctly nested. No OTLP
collector is deployed by this project — set `OTEL_EXPORTER_OTLP_ENDPOINT` on a real
deployment to export these spans somewhere real. See
[ADR-031](adr/0031-opentelemetry-tracing.md).

## Requirements traceability

`docs/requirements.md` is the authoritative functional/non-functional requirements list;
these thirteen demonstrations are chosen to make the most externally-visible,
differentiating behaviors concretely observable, not to enumerate every requirement
individually. See `PROJECT_PLAN.md` for the phase-by-phase history behind each
capability shown above.
