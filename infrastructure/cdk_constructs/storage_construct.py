"""DynamoDB tables: routing decisions (audit) and idempotency (ADR-018).

Two separate tables, not a single-table design — favoring straightforward, reviewable
schemas for a portfolio reference implementation over DynamoDB single-table cleverness.
Both use on-demand billing (no idle cost — ADR-005), explicit AWS-managed encryption,
and item TTL for automatic expiry; point-in-time recovery and the removal policy are
environment-driven (`config.EnvironmentConfig`).
"""

from aws_cdk import aws_dynamodb as dynamodb
from constructs import Construct

from config import EnvironmentConfig


class StorageConstruct(Construct):
    def __init__(
        self, scope: Construct, construct_id: str, *, environment_config: EnvironmentConfig
    ) -> None:
        super().__init__(scope, construct_id)

        self.decisions_table = dynamodb.Table(
            self,
            "DecisionsTable",
            partition_key=dynamodb.Attribute(name="decisionId", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            encryption=dynamodb.TableEncryption.AWS_MANAGED,
            time_to_live_attribute="expiresAt",
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=environment_config.enable_point_in_time_recovery
            ),
            removal_policy=environment_config.removal_policy,
        )

        self.idempotency_table = dynamodb.Table(
            self,
            "IdempotencyTable",
            partition_key=dynamodb.Attribute(name="pk", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="sk", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            encryption=dynamodb.TableEncryption.AWS_MANAGED,
            time_to_live_attribute="expiresAt",
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=environment_config.enable_point_in_time_recovery
            ),
            removal_policy=environment_config.removal_policy,
        )
