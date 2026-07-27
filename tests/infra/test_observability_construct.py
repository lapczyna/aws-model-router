"""Template-assertion tests for `ObservabilityConstruct` (ADR-019, ADR-021): the
dashboard, all 7 alarms, and the SNS topic exist with the expected metric sources and
dimensions — and, just as importantly, that none of it required a new IAM permission on
the Lambda's execution role.
"""

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from tests.infra.conftest import SynthesizedStack

pytestmark = pytest.mark.infra

_CUSTOM_METRIC_ALARMS = (
    "ProviderFailureCount",
    "NoEligibleModelCount",
    "EstimatedCostUsd",
)


def test_seven_alarms_exist(dev_stack: "SynthesizedStack") -> None:
    dev_stack.template.resource_count_is("AWS::CloudWatch::Alarm", 7)


def test_dashboard_exists(dev_stack: "SynthesizedStack") -> None:
    dev_stack.template.resource_count_is("AWS::CloudWatch::Dashboard", 1)


def test_sns_topic_exists_with_ssl_enforced(dev_stack: "SynthesizedStack") -> None:
    dev_stack.template.resource_count_is("AWS::SNS::Topic", 1)
    dev_stack.template.has_resource_properties(
        "AWS::SNS::TopicPolicy",
        {
            "PolicyDocument": {
                "Statement": [
                    {
                        "Action": "sns:Publish",
                        "Effect": "Deny",
                        "Condition": {"Bool": {"aws:SecureTransport": "false"}},
                    }
                ]
            }
        },
    )


def test_lambda_errors_alarm_uses_native_metric(dev_stack: "SynthesizedStack") -> None:
    dev_stack.template.has_resource_properties(
        "AWS::CloudWatch::Alarm",
        {"Namespace": "AWS/Lambda", "MetricName": "Errors"},
    )


def test_lambda_throttles_alarm_uses_native_metric(dev_stack: "SynthesizedStack") -> None:
    dev_stack.template.has_resource_properties(
        "AWS::CloudWatch::Alarm",
        {"Namespace": "AWS/Lambda", "MetricName": "Throttles"},
    )


def test_api_5xx_alarm_uses_native_metric(dev_stack: "SynthesizedStack") -> None:
    dev_stack.template.has_resource_properties(
        "AWS::CloudWatch::Alarm",
        {"Namespace": "AWS/ApiGateway", "MetricName": "5XXError"},
    )


@pytest.mark.parametrize("metric_name", _CUSTOM_METRIC_ALARMS)
def test_custom_metric_alarms_declare_only_environment_dimension(
    dev_stack: "SynthesizedStack", metric_name: str
) -> None:
    dev_stack.template.has_resource_properties(
        "AWS::CloudWatch::Alarm",
        {
            "Namespace": "ModelRouter",
            "MetricName": metric_name,
            "Dimensions": [{"Name": "Environment", "Value": "dev"}],
        },
    )


def test_fallback_rate_alarm_is_a_math_expression_over_environment_dimensioned_metrics(
    dev_stack: "SynthesizedStack",
) -> None:
    from aws_cdk.assertions import Match

    dev_stack.template.has_resource_properties(
        "AWS::CloudWatch::Alarm",
        {
            "Metrics": Match.array_with(
                [
                    Match.object_like({"Expression": "(fallbackUsed / requests) * 100"}),
                    Match.object_like(
                        {
                            "Id": "fallbackUsed",
                            "MetricStat": Match.object_like(
                                {
                                    "Metric": Match.object_like(
                                        {
                                            "Namespace": "ModelRouter",
                                            "MetricName": "FallbackUsedCount",
                                            "Dimensions": [{"Name": "Environment", "Value": "dev"}],
                                        }
                                    )
                                }
                            ),
                        }
                    ),
                ]
            )
        },
    )


def test_all_alarms_notify_the_sns_topic(dev_stack: "SynthesizedStack") -> None:
    template_json = dev_stack.template.to_json()
    alarms = [
        resource
        for resource in template_json["Resources"].values()
        if resource["Type"] == "AWS::CloudWatch::Alarm"
    ]
    assert len(alarms) == 7
    for alarm in alarms:
        assert len(alarm["Properties"]["AlarmActions"]) == 1


def test_dev_and_prod_thresholds_differ_per_environment_config(
    dev_stack: "SynthesizedStack", prod_stack: "SynthesizedStack"
) -> None:
    dev_stack.template.has_resource_properties(
        "AWS::CloudWatch::Alarm", {"MetricName": "ProviderFailureCount", "Threshold": 5}
    )
    prod_stack.template.has_resource_properties(
        "AWS::CloudWatch::Alarm", {"MetricName": "ProviderFailureCount", "Threshold": 10}
    )


def test_estimated_spend_alarm_evaluates_over_one_day(dev_stack: "SynthesizedStack") -> None:
    dev_stack.template.has_resource_properties(
        "AWS::CloudWatch::Alarm",
        {"MetricName": "EstimatedCostUsd", "Period": 86400, "EvaluationPeriods": 1},
    )


def test_observability_adds_no_new_iam_permissions_to_lambda_role(
    dev_stack: "SynthesizedStack",
) -> None:
    # Exactly the one IAM::Policy the Lambda's execution role already needed
    # (DynamoDB + Bedrock, from Phase 5) — CloudWatch alarms invoke SNS via
    # CloudWatch's own service permissions, never the monitored Lambda's role.
    dev_stack.template.resource_count_is("AWS::IAM::Policy", 1)
