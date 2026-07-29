# ADR-027: IaC security scanning — cdk-nag and cfn-lint

## Status
Accepted

## Context
Phase 8 requires an automated IaC security scan and a CFN lint check in the PR
workflow. Two different tool categories exist for CDK projects: **CDK-native security
rule packs** (cdk-nag, applied as a CDK Aspect directly against the construct tree
before synthesis completes) and **CloudFormation-template linters** (cfn-lint,
validating the already-synthesized template against AWS's resource schemas). They
catch different classes of problems and are not substitutes for each other.

## Decision
Both, in the PR workflow's `iac-security-scan` job:

1. **cdk-nag's `AwsSolutionsChecks`** rule pack, applied via `cdk.Aspects.of(app).add(...)`
   in `infrastructure/app.py`, gated behind `CDK_NAG_ENABLED=true` (never applied during
   a normal `cdk deploy`/`cdk synth`, so it can't accidentally block or slow down actual
   deployment — only the explicit CI check and a maintainer's own opt-in local run do).
   An un-suppressed Error-level finding fails `cdk synth` itself (CDK's own annotation
   mechanism), not a separate pass/fail check to maintain.
2. **cfn-lint**, run against the already-synthesized templates
   (`infrastructure/cdk.out/*.template.json`), catching template-schema-level issues
   cdk-nag's construct-tree-level checks don't — see Consequences for the real one this
   caught.

Every cdk-nag finding this project actually triggered was either **fixed** or
**suppressed with a written, reviewable justification** via `NagSuppressions`
(`cdk_constructs/storage_construct.py`, `lambda_construct.py`, `api_construct.py`) —
never globally disabled. One finding (AwsSolutions-APIG2, missing API Gateway request
validation) was fixed for real: a `RequestValidator` requiring a body on the two POST
routes, added in Phase 8, not merely suppressed.

## Consequences
* **cfn-lint caught a real, deployment-breaking bug cdk-nag did not**: CDK's
  `Tags.of(stack).add(...)` aspect (applied globally since Phase 5/6) was tagging every
  resource in the stack, including the `AWS::CloudWatch::Dashboard` from
  `ObservabilityConstruct` (Phase 6) — but CloudFormation's `AWS::CloudWatch::Dashboard`
  resource type does not accept a `Tags` property (confirmed against AWS's own
  CloudFormation documentation; the underlying tagging *API* exists as a recent feature,
  but the CloudFormation resource schema hasn't caught up to it yet). A real
  `cdk deploy` of this stack would very likely have been rejected by CloudFormation.
  Fixed via `exclude_resource_types=["AWS::CloudWatch::Dashboard"]` on every
  `Tags.of(...).add(...)` call (`infrastructure/app.py`,
  `tests/infra/conftest.py`) — this is exactly the value of running a second,
  independent tool against the literal synthesized output rather than trusting a single
  scanner's view of the construct tree.
* Two narrow, documented `--ignore-checks` on cfn-lint's own CLI invocation (not global
  suppressions): `W3005` (a benign, CDK-generated redundant `DependsOn` that appears on
  every CDK-synthesized stack with an IAM role + policy, not a defect) and `E3030` on
  the `GitHubOidc` template only (cfn-lint's bundled resource spec doesn't yet recognize
  the Node.js runtime version CDK's own `iam.OpenIdConnectProvider` custom-resource
  Lambda uses — a cfn-lint schema-currency gap in CDK-internal code, not a defect this
  project's own code introduced).
* Every `NagSuppressions` reason references either an ADR or a specific architectural
  constraint (X-Ray's `Resource: "*"` requirement, WAF's always-on cost profile,
  IAM/COG4 vs. this project's IAM-SigV4 choice) — a future reviewer can evaluate whether
  each suppression still holds without re-deriving the reasoning from scratch.

## Alternatives considered
* **cdk-nag only, no cfn-lint** — rejected: as demonstrated above, cdk-nag's
  construct-tree-level rule packs did not catch the Dashboard-tagging defect at all
  (it's a resource-schema-conformance issue, not a security/best-practice rule cdk-nag
  packs are designed to check) — the two tools are complementary, not redundant.
* **cfn-lint only, no cdk-nag** — rejected: cfn-lint validates template *shape*
  (does this resource type accept this property, are required properties present) but
  has no concept of "does this IAM policy grant excessive access" or "should this
  DynamoDB table have PITR" — the security/best-practice rule checks cdk-nag provides.
* **Checkov or another third-party IaC scanner instead of cdk-nag** — rejected: cdk-nag
  integrates as a CDK Aspect operating on the live construct tree (with full access to
  CDK's own type information), applied at synth time with zero extra tooling beyond a
  pip package already in this project's dependency graph; a template-scanning
  alternative would only ever see what cfn-lint already sees, without cdk-nag's
  construct-level rule packs' added value.
