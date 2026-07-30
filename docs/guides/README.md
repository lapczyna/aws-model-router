# Guides

Task-oriented guides for working with `aws-model-router` (Phase 9), as distinct from the
reference documentation elsewhere in `docs/` (architecture, security, cost, operations).

* [`developer-guide.md`](developer-guide.md) — repository layout, local setup, running
  tests/lint/type-checks, and where new code belongs.
* [`troubleshooting.md`](troubleshooting.md) — common local-development and deployment
  problems and how to diagnose them. See
  [`../operations/incident-response.md`](../operations/incident-response.md) instead for
  a *security* incident, and
  [`../operations/alarm-response.md`](../operations/alarm-response.md) for a *production
  alarm*.
* [`policy-authoring-guide.md`](policy-authoring-guide.md) — how to write or modify a
  `RoutingPolicy` YAML file.
* [`model-onboarding-guide.md`](model-onboarding-guide.md) — how to add a new model to
  `policies/model_catalogue.yaml`.
* [`application-onboarding-guide.md`](application-onboarding-guide.md) — how to onboard a
  new client application.

See [`../demonstrations.md`](../demonstrations.md) for ten concrete, reproducible
demonstrations of the router's behavior, and
[`../../PROJECT_PLAN.md`](../../PROJECT_PLAN.md) for the phase-by-phase project history.
