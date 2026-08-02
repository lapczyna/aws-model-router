"""Template-assertion tests for `ModelRouterStack`: encryption, retention, removal
policy, IAM least-privilege scoping, and endpoint authorization — properties that
ADR-015 through ADR-018 and `docs/requirements.md` NFR-2.2 depend on, verified against
the real synthesized CloudFormation template rather than just reading the construct
code.

Every `aws_cdk` import is local to the test function that needs it (see
`tests/infra/conftest.py`'s docstring for why: it keeps the default, non-`infra`
`pytest` run from paying the `aws_cdk` import cost just to collect this module).
"""

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from tests.infra.conftest import SynthesizedStack

pytestmark = pytest.mark.infra


def test_dev_stack_synthesizes_with_expected_resource_counts(
    dev_stack: "SynthesizedStack",
) -> None:
    dev_stack.template.resource_count_is("AWS::Lambda::Function", 1)
    dev_stack.template.resource_count_is("AWS::DynamoDB::Table", 2)
    dev_stack.template.resource_count_is("AWS::ApiGateway::RestApi", 1)


def test_dynamodb_tables_use_on_demand_billing(dev_stack: "SynthesizedStack") -> None:
    dev_stack.template.has_resource_properties(
        "AWS::DynamoDB::Table", {"BillingMode": "PAY_PER_REQUEST"}
    )


def test_dynamodb_tables_are_encrypted(dev_stack: "SynthesizedStack") -> None:
    dev_stack.template.has_resource_properties(
        "AWS::DynamoDB::Table", {"SSESpecification": {"SSEEnabled": True}}
    )


def test_dynamodb_tables_have_ttl_on_expires_at(dev_stack: "SynthesizedStack") -> None:
    dev_stack.template.has_resource_properties(
        "AWS::DynamoDB::Table",
        {"TimeToLiveSpecification": {"AttributeName": "expiresAt", "Enabled": True}},
    )


def test_decisions_table_partition_key_is_decision_id(dev_stack: "SynthesizedStack") -> None:
    dev_stack.template.has_resource_properties(
        "AWS::DynamoDB::Table",
        {"KeySchema": [{"AttributeName": "decisionId", "KeyType": "HASH"}]},
    )


def test_idempotency_table_has_composite_key(dev_stack: "SynthesizedStack") -> None:
    dev_stack.template.has_resource_properties(
        "AWS::DynamoDB::Table",
        {
            "KeySchema": [
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ]
        },
    )


def test_dev_point_in_time_recovery_disabled(dev_stack: "SynthesizedStack") -> None:
    dev_stack.template.has_resource_properties(
        "AWS::DynamoDB::Table",
        {"PointInTimeRecoverySpecification": {"PointInTimeRecoveryEnabled": False}},
    )


def test_prod_point_in_time_recovery_enabled(prod_stack: "SynthesizedStack") -> None:
    prod_stack.template.has_resource_properties(
        "AWS::DynamoDB::Table",
        {"PointInTimeRecoverySpecification": {"PointInTimeRecoveryEnabled": True}},
    )


def test_dev_tables_and_log_groups_are_destroyed_on_stack_deletion(
    dev_stack: "SynthesizedStack",
) -> None:
    dev_stack.template.has_resource("AWS::DynamoDB::Table", {"DeletionPolicy": "Delete"})
    dev_stack.template.has_resource("AWS::Logs::LogGroup", {"DeletionPolicy": "Delete"})


def test_prod_tables_and_log_groups_are_retained_on_stack_deletion(
    prod_stack: "SynthesizedStack",
) -> None:
    prod_stack.template.has_resource("AWS::DynamoDB::Table", {"DeletionPolicy": "Retain"})
    prod_stack.template.has_resource("AWS::Logs::LogGroup", {"DeletionPolicy": "Retain"})


def test_lambda_function_uses_python312_with_active_tracing(
    dev_stack: "SynthesizedStack",
) -> None:
    dev_stack.template.has_resource_properties(
        "AWS::Lambda::Function",
        {"Runtime": "python3.12", "TracingConfig": {"Mode": "Active"}},
    )


def test_lambda_environment_variables_reference_tables_not_hardcoded_names(
    dev_stack: "SynthesizedStack",
) -> None:
    from aws_cdk.assertions import Match

    dev_stack.template.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "Environment": {
                "Variables": Match.object_like(
                    {
                        "POLICIES_DIR": "policies",
                        "LOG_LEVEL": "INFO",
                        "DECISIONS_TABLE_NAME": Match.any_value(),
                        "IDEMPOTENCY_TABLE_NAME": Match.any_value(),
                    }
                )
            }
        },
    )


def test_dev_lambda_has_no_reserved_concurrency(dev_stack: "SynthesizedStack") -> None:
    template_json = dev_stack.template.to_json()
    functions = [
        r for r in template_json["Resources"].values() if r["Type"] == "AWS::Lambda::Function"
    ]
    assert len(functions) == 1
    assert "ReservedConcurrentExecutions" not in functions[0]["Properties"]


def test_prod_lambda_reserved_concurrency_is_ten(prod_stack: "SynthesizedStack") -> None:
    prod_stack.template.has_resource_properties(
        "AWS::Lambda::Function", {"ReservedConcurrentExecutions": 10}
    )


def test_lambda_role_bedrock_permissions_are_scoped_not_wildcard(
    dev_stack: "SynthesizedStack",
) -> None:
    from aws_cdk.assertions import Match

    dev_stack.template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Action": Match.array_with(["bedrock:InvokeModel"]),
                                "Effect": "Allow",
                                "Resource": Match.array_with(
                                    [Match.string_like_regexp(r"^arn:aws:bedrock:.*")]
                                ),
                            }
                        )
                    ]
                )
            }
        },
    )


def test_lambda_role_bedrock_resource_is_never_a_wildcard(
    dev_stack: "SynthesizedStack",
) -> None:
    for statement in _iam_statements(dev_stack, action_prefix="bedrock:"):
        assert "*" not in _as_list(statement["Resource"])


def test_lambda_role_dynamodb_permissions_scoped_to_tables_not_wildcard(
    dev_stack: "SynthesizedStack",
) -> None:
    for statement in _iam_statements(dev_stack, action_prefix="dynamodb:"):
        assert "*" not in _as_list(statement["Resource"])


def test_bedrock_iam_resources_never_include_a_non_bedrock_catalogue_entry(
    dev_stack: "SynthesizedStack",
) -> None:
    """Regression test for a real bug found in Phase 10a: `_load_bedrock_resource_arns`
    used to iterate every catalogue entry regardless of `provider`, so adding an
    `openai` model (`policies/model_catalogue.yaml`'s `balanced-text-openai`, resolving
    to the OpenAI model name "gpt-4o") would have produced a meaningless
    `arn:aws:bedrock:...foundation-model/gpt-4o` ARN — syntactically a valid-looking
    Bedrock ARN (so `test_lambda_role_bedrock_permissions_are_scoped_not_wildcard`
    above would NOT have caught this), but a stray, incorrect IAM grant nonetheless.
    """
    for statement in _iam_statements(dev_stack, action_prefix="bedrock:"):
        resources = _as_list(statement["Resource"])
        assert not any("gpt-4o" in str(resource) for resource in resources)


def test_openai_secret_grant_is_scoped_to_the_specific_secret_not_wildcard(
    dev_stack: "SynthesizedStack",
) -> None:
    for statement in _iam_statements(dev_stack, action_prefix="secretsmanager:"):
        resources = _as_list(statement["Resource"])
        assert "*" not in resources
        assert (
            resources  # a secretsmanager statement exists at all, given an openai catalogue entry
        )


def test_decision_events_bus_is_created(dev_stack: "SynthesizedStack") -> None:
    dev_stack.template.resource_count_is("AWS::Events::EventBus", 1)
    dev_stack.template.has_resource_properties(
        "AWS::Events::EventBus", {"Name": "model-router-decisions-dev"}
    )


def test_eventbridge_put_events_grant_is_scoped_not_wildcard(
    dev_stack: "SynthesizedStack",
) -> None:
    for statement in _iam_statements(dev_stack, action_prefix="events:"):
        resources = _as_list(statement["Resource"])
        assert "*" not in resources
        assert resources  # an events statement exists at all


def test_dynamodb_grants_are_scoped_to_the_exact_actions_each_adapter_uses(
    dev_stack: "SynthesizedStack",
) -> None:
    # ADR-022: grant_read_write_data() was replaced with explicit per-table action
    # lists matching exactly what DynamoDbRoutingDecisionRepository/
    # DynamoDbIdempotencyStore call — never Scan/Query/BatchGetItem/BatchWriteItem/
    # UpdateItem/DescribeTable, none of which either adapter uses.
    dynamodb_statements = _iam_statements(dev_stack, action_prefix="dynamodb:")
    action_sets = [frozenset(_as_list(statement["Action"])) for statement in dynamodb_statements]

    assert frozenset({"dynamodb:GetItem", "dynamodb:PutItem"}) in action_sets
    assert frozenset({"dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem"}) in action_sets
    never_granted = {
        "dynamodb:Scan",
        "dynamodb:Query",
        "dynamodb:BatchGetItem",
        "dynamodb:BatchWriteItem",
        "dynamodb:UpdateItem",
        "dynamodb:DescribeTable",
        "dynamodb:ConditionCheckItem",
        "dynamodb:GetRecords",
        "dynamodb:GetShardIterator",
    }
    all_granted_actions = {action for actions in action_sets for action in actions}
    assert not (never_granted & all_granted_actions)


def test_health_and_ready_routes_require_no_authorization(dev_stack: "SynthesizedStack") -> None:
    from aws_cdk.assertions import Match

    dev_stack.template.has_resource_properties(
        "AWS::ApiGateway::Method",
        Match.object_like({"HttpMethod": "GET", "AuthorizationType": "NONE"}),
    )


def test_public_routes_are_exactly_health_and_ready(dev_stack: "SynthesizedStack") -> None:
    public_methods = [m for m in _api_methods(dev_stack) if m["AuthorizationType"] == "NONE"]
    assert len(public_methods) == 2
    assert {m["HttpMethod"] for m in public_methods} == {"GET"}


def test_all_v1_routes_require_iam_authorization(dev_stack: "SynthesizedStack") -> None:
    protected_methods = [m for m in _api_methods(dev_stack) if m["AuthorizationType"] != "NONE"]
    assert len(protected_methods) == 4  # inference, routes/evaluate, models, decisions/{id}
    assert all(m["AuthorizationType"] == "AWS_IAM" for m in protected_methods)


def test_api_stage_never_traces_full_request_response_bodies(
    dev_stack: "SynthesizedStack",
) -> None:
    from aws_cdk.assertions import Match

    dev_stack.template.has_resource_properties(
        "AWS::ApiGateway::Stage",
        {
            "MethodSettings": Match.array_with(
                [Match.object_like({"DataTraceEnabled": False, "MetricsEnabled": True})]
            ),
            "TracingEnabled": True,
        },
    )


def test_dev_throttling_matches_environment_config(dev_stack: "SynthesizedStack") -> None:
    from aws_cdk.assertions import Match

    dev_stack.template.has_resource_properties(
        "AWS::ApiGateway::Stage",
        {
            "MethodSettings": Match.array_with(
                [Match.object_like({"ThrottlingRateLimit": 10, "ThrottlingBurstLimit": 20})]
            )
        },
    )


def test_prod_throttling_matches_environment_config(prod_stack: "SynthesizedStack") -> None:
    from aws_cdk.assertions import Match

    prod_stack.template.has_resource_properties(
        "AWS::ApiGateway::Stage",
        {
            "MethodSettings": Match.array_with(
                [Match.object_like({"ThrottlingRateLimit": 50, "ThrottlingBurstLimit": 100})]
            )
        },
    )


def test_stack_resources_are_tagged_for_ownership_and_environment(
    dev_stack: "SynthesizedStack",
) -> None:
    from aws_cdk.assertions import Match

    dev_stack.template.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "Tags": Match.array_with(
                [
                    {"Key": "Environment", "Value": "dev"},
                    {"Key": "ManagedBy", "Value": "cdk"},
                    {"Key": "Project", "Value": "aws-model-router"},
                ]
            )
        },
    )


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else [value]


def _iam_statements(stack: "SynthesizedStack", *, action_prefix: str) -> list[dict[str, object]]:
    template_json = stack.template.to_json()
    matching: list[dict[str, object]] = []
    for resource in template_json["Resources"].values():
        if resource["Type"] != "AWS::IAM::Policy":
            continue
        for statement in resource["Properties"]["PolicyDocument"]["Statement"]:
            actions = _as_list(statement.get("Action", []))
            if any(isinstance(a, str) and a.startswith(action_prefix) for a in actions):
                matching.append(statement)
    return matching


def _api_methods(stack: "SynthesizedStack") -> list[dict[str, object]]:
    template_json = stack.template.to_json()
    return [
        resource["Properties"]
        for resource in template_json["Resources"].values()
        if resource["Type"] == "AWS::ApiGateway::Method"
    ]
