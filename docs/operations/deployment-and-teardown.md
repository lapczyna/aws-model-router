# Deployment and teardown

Covers deploying `ModelRouterStack` (`infrastructure/stacks/model_router_stack.py`) with
AWS CDK, and — just as importantly — what happens when you tear it down. Read the
teardown section *before* running `cdk destroy` against `prod`.

## Prerequisites

* AWS credentials resolvable by the CDK CLI's default chain (`aws configure`, environment
  variables, or SSO).
* `pip install -e ".[dev,infra]"` (see the repository README) so `aws-cdk-lib` and
  `constructs` are installed alongside the router's own dependencies.
* The AWS CDK CLI (`npm install -g aws-cdk`), matching the `aws-cdk-lib` major version
  pinned in `pyproject.toml`.
* Bootstrapped CDK assets in the target account/Region (one-time per account/Region):
  ```bash
  cdk bootstrap aws://ACCOUNT_ID/REGION
  ```
* No Docker daemon is required. Lambda packaging (`infrastructure/bundling.py`) tries a
  local, Docker-free `pip install --platform manylinux2014_x86_64` path first and only
  falls back to Docker-based bundling if that fails (ADR-017).

Deploying via GitHub Actions instead of locally? See
[`ci-cd.md`](ci-cd.md) — it requires its own one-time bootstrap
(`cdk deploy GitHubOidc`) in addition to the steps below.

## Environments

`dev` and `prod` are CDK context-selected (`-c env=...`), not separate CDK apps —
configuration lives in `infrastructure/config.py`. Defaults:

| Setting | `dev` | `prod` |
|---|---|---|
| Removal policy | `DESTROY` | `RETAIN` |
| Point-in-time recovery | off | on |
| Log retention | 1 week | 3 months |
| Lambda memory | 512 MB | 1024 MB |
| Lambda reserved concurrency | none | 10 |
| API throttling (rate/burst) | 10/20 | 50/100 |

## Deploying

```bash
cd infrastructure

# Preview the CloudFormation template without deploying anything
cdk synth -c env=dev

# Deploy — the stack name is required since the app also defines a second,
# separately-deployed stack (GitHubOidc, ADR-025) that `cdk deploy` would otherwise
# ask you to disambiguate
cdk deploy -c env=dev ModelRouter-dev
cdk deploy -c env=prod ModelRouter-prod
```

`cdk deploy` prints four outputs you'll need for the next steps: `ApiUrl`,
`ApiFunctionName`, `DecisionsTableName`, `IdempotencyTableName`.

## Verifying a deployment

Exercise the deployed Lambda directly (no need to go through API Gateway/SigV4 signing
first) with [`scripts/invoke_lambda_locally.py`](../../scripts/invoke_lambda_locally.py):

```bash
export DECISIONS_TABLE_NAME=<DecisionsTableName output>
export IDEMPOTENCY_TABLE_NAME=<IdempotencyTableName output>
export AWS_REGION=<region you deployed to>

# Never invokes a model — safe to run freely
python scripts/invoke_lambda_locally.py --method GET --resource /v1/models --use-real-services

# Makes a real, billable Bedrock call — requires --confirm-cost
python scripts/invoke_lambda_locally.py --method POST --resource /v1/inference \
    --body events/support_assistant_balanced.json \
    --use-real-services --confirm-cost
```

Or call the deployed `ApiUrl` directly with a SigV4-signing HTTP client (every `/v1/*`
route requires IAM authorization — see
[ADR-015](../adr/0015-api-authorization-model.md)); `/health` and `/ready` are
unauthenticated and reachable with plain `curl`.

## Tearing down

```bash
cdk destroy -c env=dev ModelRouter-dev
```

**`dev`**: `RemovalPolicy.DESTROY` — the DynamoDB tables and CloudWatch log groups are
deleted along with the stack. Nothing is recoverable afterward.

**`prod`**: `RemovalPolicy.RETAIN` (ADR-018) — `cdk destroy -c env=prod ModelRouter-prod` deletes the
stack's *managed* resources (Lambda function, API Gateway, IAM roles) but **the two
DynamoDB tables and both CloudWatch log groups are left behind**, orphaned from the
stack, still accruing storage cost. This is deliberate: it prevents an accidental
`cdk destroy` from silently discarding the audit trail (`DecisionsTable`) or in-flight
idempotency records. If you genuinely want to delete the retained `prod` data:

1. Confirm you no longer need the audit history — it cannot be recovered once deleted.
2. Delete the orphaned tables/log groups directly (AWS Console, or
   `aws dynamodb delete-table` / `aws logs delete-log-group`), identifying them by the
   `Project=aws-model-router` / `Environment=prod` tags CDK applies
   (`infrastructure/app.py`).

## Cost notes

Every resource in this stack is on-demand/pay-per-request (Lambda, DynamoDB
`PAY_PER_REQUEST`, API Gateway) — there is no idle cost from the compute or database
tier while undeployed traffic is zero (ADR-005). The only ongoing cost from a deployed-
but-unused stack is: CloudWatch log storage (bounded by the configured retention above),
and — for `prod` specifically — point-in-time recovery storage on the two tables. Actual
Bedrock invocation cost is separate and usage-based; see
[`docs/cost/`](../cost/) for estimation methodology.
