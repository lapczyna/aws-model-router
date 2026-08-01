"""The single Lambda function backing every REST API route (ADR-016), its execution
role (least-privilege — explicit, catalogue-scoped Bedrock permissions per ADR and
`docs/requirements.md` NFR-2.2), and a `live` alias (ADR: Lambda aliases exist now so a
future phase can add CodeDeploy canary/linear traffic shifting without a Function
replacement).
"""

from pathlib import Path
from typing import Any

import yaml
from aws_cdk import Duration, Stack
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_secretsmanager as secretsmanager
from cdk_nag import NagSuppressions
from constructs import Construct

from bundling import lambda_code_bundling_options
from config import EnvironmentConfig

_HANDLER_ENTRY_POINT = "handlers.api_handler.handler"
_BEDROCK_ACTIONS = ("bedrock:InvokeModel", "bedrock:Converse", "bedrock:ConverseStream")


def _load_catalogue_models(repo_root: Path) -> list[dict[str, Any]]:
    catalogue_path = repo_root / "policies" / "model_catalogue.yaml"
    with catalogue_path.open("r", encoding="utf-8") as handle:
        data: dict[str, Any] = yaml.safe_load(handle)
    models: list[dict[str, Any]] = data.get("models", [])
    return models


def _load_bedrock_resource_arns(
    models: list[dict[str, Any]], region: str, account_id: str
) -> list[str]:
    """Scope the Lambda's Bedrock IAM permissions to exactly the catalogued Bedrock
    models/inference profiles (`docs/requirements.md` NFR-2.2: "model/inference-profile
    restrictions where feasible") — rather than a blanket `resources=["*"]`.

    Non-Bedrock catalogue entries (e.g. `provider: openai`, added in Phase 10a) are
    skipped entirely — their `resolution.value` is a provider-specific identifier (an
    OpenAI model name, not a Bedrock model ID), and building a Bedrock ARN from it would
    be meaningless at best and a stray, unnecessary IAM grant at worst.
    """
    arns: set[str] = set()
    for model in models:
        if model.get("provider") != "bedrock":
            continue
        resolution = model["resolution"]
        resolution_type = resolution["type"]
        value = resolution["value"]
        if resolution_type == "direct_model_id":
            arns.add(f"arn:aws:bedrock:{region}::foundation-model/{value}")
        elif resolution_type in ("cross_region_inference_profile", "application_inference_profile"):
            arns.add(f"arn:aws:bedrock:{region}:{account_id}:inference-profile/{value}")
        # "router_alias" resolves (one bounded hop) to another catalogue entry already
        # covered by this same loop; it names no ARN itself.
    return sorted(arns)


def _catalogue_uses_openai(models: list[dict[str, Any]]) -> bool:
    return any(model.get("provider") == "openai" for model in models)


class LambdaConstruct(Construct):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        environment_config: EnvironmentConfig,
        repo_root: Path,
        decisions_table: dynamodb.Table,
        idempotency_table: dynamodb.Table,
    ) -> None:
        super().__init__(scope, construct_id)

        stack = Stack.of(self)
        catalogue_models = _load_catalogue_models(repo_root)
        uses_openai = _catalogue_uses_openai(catalogue_models)

        openai_secret: secretsmanager.Secret | None = None
        if uses_openai:
            # Provisioned only if the catalogue actually declares an `openai` model
            # (ADR-029) — a Secrets Manager secret has a flat monthly cost regardless of
            # use, so a Bedrock-only deployment never pays for one it doesn't need
            # (the same "no unnecessary always-on cost" discipline as ADR-005). CDK
            # generates a random placeholder value at creation time; a real key must be
            # set post-deploy (`aws secretsmanager put-secret-value`), the same
            # "provision the resource, the real credential is a manual step" pattern
            # already used for the Phase 6 SNS topic subscription.
            openai_secret = secretsmanager.Secret(
                self,
                "OpenAiApiKeySecret",
                description=(
                    "OpenAI API key for OpenAIModelProvider (ADR-029). Placeholder value "
                    "at creation; set the real key with "
                    "`aws secretsmanager put-secret-value` after deploying."
                ),
                removal_policy=environment_config.removal_policy,
            )
            NagSuppressions.add_resource_suppressions(
                openai_secret,
                [
                    {
                        "id": "AwsSolutions-SMG4",
                        "reason": (
                            "Secrets Manager's native automatic rotation is built for "
                            "AWS-managed services (RDS, Redshift, DocumentDB) that expose "
                            "a rotation API Secrets Manager's Lambda rotation functions "
                            "call. An OpenAI API key has no equivalent rotate-in-place "
                            "API — rotating it means generating a new key in the OpenAI "
                            "dashboard and revoking the old one, an inherently external, "
                            "manual action a custom rotation Lambda couldn't automate "
                            "away. Manual rotation is documented in "
                            "docs/operations/release-process.md; this is a scope "
                            "limitation of the third-party credential, not an oversight."
                        ),
                    },
                ],
            )

        log_group = logs.LogGroup(
            self,
            "ApiFunctionLogGroup",
            retention=environment_config.log_retention,
            removal_policy=environment_config.removal_policy,
        )

        self.function = lambda_.Function(
            self,
            "ApiFunction",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.X86_64,
            handler=_HANDLER_ENTRY_POINT,
            code=lambda_.Code.from_asset(
                str(repo_root),
                bundling=lambda_code_bundling_options(repo_root),
                exclude=[
                    ".git",
                    ".github",
                    ".idea",
                    ".mypy_cache",
                    ".pytest_cache",
                    ".ruff_cache",
                    ".venv",
                    "docs",
                    "infrastructure",
                    "scripts",
                    "tests",
                    "**/__pycache__",
                    "**/*.pyc",
                ],
            ),
            memory_size=environment_config.lambda_memory_mb,
            timeout=Duration.seconds(environment_config.lambda_timeout_seconds),
            reserved_concurrent_executions=environment_config.lambda_reserved_concurrency,
            log_group=log_group,
            environment={
                "POLICIES_DIR": "policies",
                "DECISIONS_TABLE_NAME": decisions_table.table_name,
                "IDEMPOTENCY_TABLE_NAME": idempotency_table.table_name,
                "MAX_REQUEST_BODY_BYTES": str(environment_config.max_request_body_bytes),
                "LOG_LEVEL": "INFO",
                "ENVIRONMENT_NAME": environment_config.env_name,
                **(
                    {"OPENAI_API_KEY_SECRET_ARN": openai_secret.secret_arn}
                    if openai_secret is not None
                    else {}
                ),
            },
            tracing=lambda_.Tracing.ACTIVE,
        )

        if openai_secret is not None:
            openai_secret.grant_read(self.function)

        # Explicit, minimal action grants (ADR-022) rather than `grant_read_write_data()`
        # — that helper grants Scan/Query/BatchGetItem/BatchWriteItem/
        # ConditionCheckItem/UpdateItem/DescribeTable/GetRecords/GetShardIterator, none
        # of which either adapter actually calls
        # (`adapters/dynamodb/dynamodb_decision_repository.py`,
        # `dynamodb_idempotency_store.py`: only GetItem/PutItem/DeleteItem, verified by
        # reading both adapters' actual boto3 calls).
        decisions_table.grant(self.function, "dynamodb:GetItem", "dynamodb:PutItem")
        idempotency_table.grant(
            self.function, "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem"
        )

        bedrock_resource_arns = _load_bedrock_resource_arns(
            catalogue_models, region=stack.region, account_id=stack.account
        )
        self.function.add_to_role_policy(
            iam.PolicyStatement(
                actions=list(_BEDROCK_ACTIONS),
                resources=bedrock_resource_arns,
            )
        )

        self.alias = lambda_.Alias(
            self,
            "ApiFunctionLiveAlias",
            alias_name="live",
            version=self.function.current_version,
        )

        NagSuppressions.add_resource_suppressions(
            self.function,
            [
                {
                    "id": "AwsSolutions-L1",
                    "reason": (
                        "The Python runtime is intentionally pinned to 3.12, matching "
                        "pyproject.toml's requires-python constraint — bumping it is a "
                        "deliberate, tested version-support decision, not an oversight."
                    ),
                },
                {
                    "id": "AwsSolutions-IAM4",
                    "reason": (
                        "AWSLambdaBasicExecutionRole is the standard AWS-managed policy "
                        "for exactly this purpose (this function's own CloudWatch Logs "
                        "write access) — narrowly scoped to logs actions already; a "
                        "hand-rolled equivalent would duplicate what AWS maintains for "
                        "this common pattern with no real security benefit."
                    ),
                    "appliesTo": [
                        "Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/"
                        "AWSLambdaBasicExecutionRole"
                    ],
                },
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": (
                        "The only Resource::* statement here is X-Ray's "
                        "PutTraceSegments/PutTelemetryRecords, reviewed and accepted in "
                        "ADR-022: AWS defines no resource-level permission for either "
                        "action, so '*' is the only valid value, not a wildcard "
                        "oversight. Every other permission on this role (DynamoDB, "
                        "Bedrock) is scoped to specific resource ARNs, not wildcarded."
                    ),
                    "appliesTo": ["Resource::*"],
                },
            ],
            apply_to_children=True,
        )
