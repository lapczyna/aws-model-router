"""The API Gateway REST API (ADR-016: one shared Lambda behind six routes).

Authorization (ADR-015): `/health` and `/ready` are intentionally public (standard
liveness/readiness convention; they expose no sensitive data). Every `/v1/*` business
route requires IAM (SigV4) authorization — fine-grained, per-application authorization
(allowlists, cost limits) is then enforced by the router's own policy engine, keyed on
the `applicationId` the caller supplies in the request body (see ADR-015 for the
layering rationale and its documented limitation).

Access logs record only request metadata (method, path, status, latency, caller
identity) — never request/response bodies (ADR-008); API Gateway access logs don't
capture body content regardless, so this is inherent to the mechanism, not an extra
precaution.
"""

from aws_cdk import aws_apigateway as apigateway
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from cdk_nag import NagSuppressions
from constructs import Construct

from config import EnvironmentConfig


class ApiConstruct(Construct):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        environment_config: EnvironmentConfig,
        lambda_alias: lambda_.Alias,
    ) -> None:
        super().__init__(scope, construct_id)

        access_log_group = logs.LogGroup(
            self,
            "ApiAccessLogGroup",
            retention=environment_config.log_retention,
            removal_policy=environment_config.removal_policy,
        )

        self.rest_api = apigateway.RestApi(
            self,
            "RestApi",
            rest_api_name=f"model-router-{environment_config.env_name}",
            endpoint_types=[apigateway.EndpointType.REGIONAL],
            deploy_options=apigateway.StageOptions(
                stage_name=environment_config.env_name,
                throttling_rate_limit=environment_config.api_throttling_rate_limit,
                throttling_burst_limit=environment_config.api_throttling_burst_limit,
                logging_level=apigateway.MethodLoggingLevel.INFO,
                data_trace_enabled=False,  # never log full request/response payloads
                metrics_enabled=True,
                tracing_enabled=True,
                access_log_destination=apigateway.LogGroupLogDestination(access_log_group),
                access_log_format=apigateway.AccessLogFormat.json_with_standard_fields(
                    caller=True,
                    http_method=True,
                    ip=True,
                    protocol=True,
                    request_time=True,
                    resource_path=True,
                    response_length=True,
                    status=True,
                    user=True,
                ),
            ),
        )

        integration = apigateway.LambdaIntegration(lambda_alias, proxy=True)

        # Gateway-level defense-in-depth (AwsSolutions-APIG2): reject a POST with no
        # body before it ever reaches (and bills) a Lambda invocation. Full shape
        # validation (required fields, types) stays in the Lambda handler via pydantic
        # (src/handlers/request_mapping.py) — a single source of truth for the request
        # schema, rather than maintaining an equivalent JSON Schema Model here too.
        body_required_validator = apigateway.RequestValidator(
            self,
            "BodyRequiredValidator",
            rest_api=self.rest_api,
            validate_request_body=True,
        )

        health = self.rest_api.root.add_resource("health")
        health_method = health.add_method(
            "GET", integration, authorization_type=apigateway.AuthorizationType.NONE
        )

        ready = self.rest_api.root.add_resource("ready")
        ready_method = ready.add_method(
            "GET", integration, authorization_type=apigateway.AuthorizationType.NONE
        )

        v1 = self.rest_api.root.add_resource("v1")

        inference = v1.add_resource("inference")
        inference.add_method(
            "POST",
            integration,
            authorization_type=apigateway.AuthorizationType.IAM,
            request_validator=body_required_validator,
        )

        routes = v1.add_resource("routes")
        evaluate = routes.add_resource("evaluate")
        evaluate.add_method(
            "POST",
            integration,
            authorization_type=apigateway.AuthorizationType.IAM,
            request_validator=body_required_validator,
        )

        models = v1.add_resource("models")
        models.add_method("GET", integration, authorization_type=apigateway.AuthorizationType.IAM)

        decisions = v1.add_resource("decisions")
        decision_by_id = decisions.add_resource("{decisionId}")
        decision_by_id.add_method(
            "GET", integration, authorization_type=apigateway.AuthorizationType.IAM
        )

        # API Gateway's hard payload ceiling (10 MB) isn't independently configurable
        # lower via CDK; the application-level guard is `MAX_REQUEST_BODY_BYTES`
        # (src/handlers/api_handler.py). Tightening the outer bound further is a WAF
        # body-size-restriction rule — see the AwsSolutions-APIG3 suppression below for
        # why WAF itself isn't adopted by default.

        NagSuppressions.add_resource_suppressions(
            self.rest_api,
            [
                {
                    "id": "AwsSolutions-APIG2",
                    "reason": (
                        "The two POST routes (the only ones with a request body) "
                        "already require validate_request_body=True "
                        "(BodyRequiredValidator, above). GET routes carry no body to "
                        "validate. Full field-level/shape validation is intentionally "
                        "centralized in the Lambda's pydantic layer "
                        "(src/handlers/request_mapping.py) as the single source of "
                        "truth for the request schema, rather than duplicated as a "
                        "second, hand-maintained JSON Schema Model here."
                    ),
                },
                {
                    "id": "AwsSolutions-APIG3",
                    "reason": (
                        "AWS WAF is optional, always-on infrastructure with its own "
                        "monthly cost, contrary to this project's pay-per-request-only "
                        "base architecture (ADR-005). A WAF body-size-restriction rule "
                        "is documented as an optional future enhancement, not adopted "
                        "by default for the base reference deployment."
                    ),
                },
                {
                    "id": "AwsSolutions-IAM4",
                    "reason": (
                        "AmazonAPIGatewayPushToCloudWatchLogs is the standard AWS-managed "
                        "policy CDK attaches to the account-level CloudWatch role API "
                        "Gateway itself requires to push access logs — narrowly scoped "
                        "to logs actions already; not a wildcard/administrative policy."
                    ),
                    "appliesTo": [
                        "Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/"
                        "AmazonAPIGatewayPushToCloudWatchLogs"
                    ],
                },
                {
                    "id": "AwsSolutions-COG4",
                    "reason": (
                        "IAM (SigV4) authorization is this project's deliberately chosen "
                        "authorization model (ADR-015), not Cognito — there is no "
                        "end-user identity to pool; callers are backend services."
                    ),
                },
            ],
            apply_to_children=True,
        )

        for method in (health_method, ready_method):
            NagSuppressions.add_resource_suppressions(
                method,
                [
                    {
                        "id": "AwsSolutions-APIG4",
                        "reason": (
                            "/health and /ready are intentionally public "
                            "(AuthorizationType.NONE) by design (ADR-015) — standard "
                            "liveness/readiness convention; neither exposes anything "
                            "sensitive."
                        ),
                    }
                ],
            )
