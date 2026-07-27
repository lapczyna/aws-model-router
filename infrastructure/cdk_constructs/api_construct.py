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

        health = self.rest_api.root.add_resource("health")
        health.add_method("GET", integration, authorization_type=apigateway.AuthorizationType.NONE)

        ready = self.rest_api.root.add_resource("ready")
        ready.add_method("GET", integration, authorization_type=apigateway.AuthorizationType.NONE)

        v1 = self.rest_api.root.add_resource("v1")

        inference = v1.add_resource("inference")
        inference.add_method(
            "POST", integration, authorization_type=apigateway.AuthorizationType.IAM
        )

        routes = v1.add_resource("routes")
        evaluate = routes.add_resource("evaluate")
        evaluate.add_method(
            "POST", integration, authorization_type=apigateway.AuthorizationType.IAM
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
        # body-size-restriction rule, documented as optional in Phase 7.
