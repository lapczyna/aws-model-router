"""The single stack assembling storage, the Lambda function, and the REST API.

One stack, not several independently-deployed ones — every resource here shares one
lifecycle (there is no reason to deploy the API without the Lambda it invokes, or the
Lambda without the tables it reads/writes), so splitting further would only add
cross-stack reference complexity without a corresponding benefit at this size (see
`docs/adr/0016-single-shared-lambda-handler.md`). Constructs (not nested stacks) provide
the internal separation instead.
"""

from pathlib import Path

from aws_cdk import CfnOutput, Stack
from constructs import Construct

from cdk_constructs.api_construct import ApiConstruct
from cdk_constructs.events_construct import EventsConstruct
from cdk_constructs.lambda_construct import LambdaConstruct
from cdk_constructs.observability_construct import ObservabilityConstruct
from cdk_constructs.storage_construct import StorageConstruct
from config import EnvironmentConfig

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class ModelRouterStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        environment_config: EnvironmentConfig,
        **kwargs: object,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)  # type: ignore[arg-type]

        storage = StorageConstruct(self, "Storage", environment_config=environment_config)
        events = EventsConstruct(self, "Events", environment_config=environment_config)

        compute = LambdaConstruct(
            self,
            "Compute",
            environment_config=environment_config,
            repo_root=_REPO_ROOT,
            decisions_table=storage.decisions_table,
            idempotency_table=storage.idempotency_table,
            decision_events_bus=events.decision_events_bus,
        )

        api = ApiConstruct(
            self,
            "Api",
            environment_config=environment_config,
            lambda_alias=compute.alias,
        )

        observability = ObservabilityConstruct(
            self,
            "Observability",
            environment_config=environment_config,
            function=compute.function,
            rest_api=api.rest_api,
        )

        CfnOutput(self, "ApiUrl", value=api.rest_api.url, description="Base URL of the REST API")
        CfnOutput(
            self,
            "DashboardUrl",
            value=(
                f"https://{self.region}.console.aws.amazon.com/cloudwatch/home"
                f"?region={self.region}#dashboards:name={observability.dashboard.dashboard_name}"
            ),
            description="CloudWatch dashboard URL",
        )
        CfnOutput(
            self,
            "AlarmTopicArn",
            value=observability.alarm_topic.topic_arn,
            description="SNS topic alarms publish to — subscribe your own endpoint to it",
        )
        CfnOutput(
            self,
            "ApiFunctionName",
            value=compute.function.function_name,
            description="Name of the shared API Lambda function",
        )
        CfnOutput(
            self,
            "DecisionsTableName",
            value=storage.decisions_table.table_name,
            description="DynamoDB table storing sanitized routing-decision audit records",
        )
        CfnOutput(
            self,
            "IdempotencyTableName",
            value=storage.idempotency_table.table_name,
            description="DynamoDB table backing concurrency-safe idempotency",
        )
        CfnOutput(
            self,
            "DecisionEventsBusName",
            value=events.decision_events_bus.event_bus_name,
            description=(
                "EventBridge bus sanitized RoutingDecisionCompleted events are "
                "published to (ADR-030) — add a rule targeting it to subscribe"
            ),
        )
