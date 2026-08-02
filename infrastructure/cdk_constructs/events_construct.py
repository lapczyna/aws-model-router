"""A dedicated EventBridge event bus for sanitized routing-decision events (ADR-030,
Phase 10b) -- separate from the AWS account's default bus so the Lambda's
`events:PutEvents` IAM grant can be scoped to exactly this bus's ARN, not
`resources=["*"]` or the shared default bus every other AWS service also publishes to.

No `RemovalPolicy` here: unlike DynamoDB tables or CloudWatch log groups, an event bus
holds no data at rest to retain or lose on stack deletion -- it only routes events that
have already been published (and, per ADR-030, are never stored more durably than an
external subscriber's own rule/target chooses).
"""

from aws_cdk import aws_events as events
from constructs import Construct

from config import EnvironmentConfig


class EventsConstruct(Construct):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        environment_config: EnvironmentConfig,
    ) -> None:
        super().__init__(scope, construct_id)

        self.decision_events_bus = events.EventBus(
            self,
            "DecisionEventsBus",
            event_bus_name=f"model-router-decisions-{environment_config.env_name}",
        )
