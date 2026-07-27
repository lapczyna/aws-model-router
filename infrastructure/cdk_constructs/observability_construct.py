"""CloudWatch dashboard, alarms, and a single SNS notification topic (ADR-021).

Native AWS metrics (Lambda errors/throttles, API Gateway 5xx) need no application code.
The router's own custom metrics (provider failures, fallback rate, no-eligible-model,
estimated spend) are emitted as CloudWatch Embedded Metric Format log lines
(`adapters.metrics.emf_metrics_publisher`, ADR-019) and referenced here purely by
namespace/dimension/metric name — no `PutMetricData` IAM permission is needed for
either source, and no change to the Lambda's execution role was required for this
construct at all.
"""

from aws_cdk import Duration
from aws_cdk import aws_apigateway as apigateway
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_cloudwatch_actions as cloudwatch_actions
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_sns as sns
from constructs import Construct

from config import EnvironmentConfig

_NAMESPACE = "ModelRouter"
_PERIOD = Duration.minutes(5)
_SPEND_PERIOD = Duration.days(1)


class ObservabilityConstruct(Construct):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        environment_config: EnvironmentConfig,
        function: lambda_.Function,
        rest_api: apigateway.RestApi,
    ) -> None:
        super().__init__(scope, construct_id)
        self._environment_name = environment_config.env_name

        self.alarm_topic = sns.Topic(
            self,
            "AlarmTopic",
            topic_name=f"model-router-{environment_config.env_name}-alarms",
            enforce_ssl=True,
        )
        alarm_action = cloudwatch_actions.SnsAction(self.alarm_topic)

        lambda_errors = function.metric_errors(period=_PERIOD)
        lambda_throttles = function.metric_throttles(period=_PERIOD)
        api_5xx = rest_api.metric_server_error(period=_PERIOD)
        provider_failure_count = self._custom_metric("ProviderFailureCount", "Sum")
        request_count = self._custom_metric("RequestCount", "Sum")
        fallback_used_count = self._custom_metric("FallbackUsedCount", "Sum")
        no_eligible_model_count = self._custom_metric("NoEligibleModelCount", "Sum")
        estimated_cost_usd = self._custom_metric("EstimatedCostUsd", "Sum", period=_SPEND_PERIOD)

        fallback_rate_percent = cloudwatch.MathExpression(
            expression="(fallbackUsed / requests) * 100",
            using_metrics={"fallbackUsed": fallback_used_count, "requests": request_count},
            label="Fallback rate (%)",
            period=_PERIOD,
        )

        self._alarm(
            "LambdaErrorsAlarm",
            metric=lambda_errors,
            threshold=environment_config.lambda_error_alarm_threshold,
            description="The API Lambda function is raising unhandled errors.",
            action=alarm_action,
        )
        self._alarm(
            "LambdaThrottlesAlarm",
            metric=lambda_throttles,
            threshold=environment_config.lambda_throttle_alarm_threshold,
            description=(
                "The API Lambda function is being throttled (reserved concurrency "
                "exhausted or account concurrency limit reached)."
            ),
            action=alarm_action,
        )
        self._alarm(
            "Api5xxAlarm",
            metric=api_5xx,
            threshold=environment_config.api_5xx_alarm_threshold,
            description="API Gateway is returning server errors (5xx).",
            action=alarm_action,
        )
        self._alarm(
            "ProviderFailureAlarm",
            metric=provider_failure_count,
            threshold=environment_config.provider_failure_alarm_threshold,
            description="Model provider invocations are failing (throttled/transient/timeout).",
            action=alarm_action,
        )
        self._alarm(
            "FallbackRateAlarm",
            metric=fallback_rate_percent,
            threshold=environment_config.fallback_rate_alarm_threshold_percent,
            description="A high proportion of requests are falling back to a non-primary model.",
            action=alarm_action,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        self._alarm(
            "NoEligibleModelAlarm",
            metric=no_eligible_model_count,
            threshold=environment_config.no_eligible_model_alarm_threshold,
            description="Requests are finding no eligible model (policy/catalogue misconfiguration?).",
            action=alarm_action,
        )
        self._alarm(
            "EstimatedDailySpendAlarm",
            metric=estimated_cost_usd,
            threshold=environment_config.estimated_daily_spend_alarm_threshold_usd,
            description=(
                "Advisory only (ADR-019): estimated cost is never billed cost. Guidance that "
                "daily estimated Bedrock spend is trending above the configured threshold."
            ),
            action=alarm_action,
            evaluation_periods=1,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )

        self.dashboard = cloudwatch.Dashboard(
            self,
            "Dashboard",
            dashboard_name=f"model-router-{environment_config.env_name}",
            widgets=[
                [
                    cloudwatch.GraphWidget(
                        title="Lambda", left=[lambda_errors, lambda_throttles], width=12
                    ),
                    cloudwatch.GraphWidget(title="API Gateway 5xx", left=[api_5xx], width=12),
                ],
                [
                    cloudwatch.GraphWidget(
                        title="Requests / Fallback / No-eligible-model",
                        left=[request_count, fallback_used_count, no_eligible_model_count],
                        width=12,
                    ),
                    cloudwatch.GraphWidget(
                        title="Fallback rate (%)", left=[fallback_rate_percent], width=12
                    ),
                ],
                [
                    cloudwatch.GraphWidget(
                        title="Provider failures", left=[provider_failure_count], width=12
                    ),
                    cloudwatch.GraphWidget(
                        title="Estimated cost (USD/day)", left=[estimated_cost_usd], width=12
                    ),
                ],
            ],
        )

    def _custom_metric(
        self, metric_name: str, statistic: str, *, period: Duration = _PERIOD
    ) -> cloudwatch.Metric:
        return cloudwatch.Metric(
            namespace=_NAMESPACE,
            metric_name=metric_name,
            dimensions_map={"Environment": self._environment_name},
            statistic=statistic,
            period=period,
        )

    def _alarm(
        self,
        construct_id: str,
        *,
        metric: cloudwatch.IMetric,
        threshold: float,
        description: str,
        action: cloudwatch_actions.SnsAction,
        evaluation_periods: int = 3,
        treat_missing_data: cloudwatch.TreatMissingData = cloudwatch.TreatMissingData.NOT_BREACHING,
    ) -> cloudwatch.Alarm:
        alarm = cloudwatch.Alarm(
            self,
            construct_id,
            metric=metric,
            threshold=threshold,
            evaluation_periods=evaluation_periods,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            alarm_description=description,
            treat_missing_data=treat_missing_data,
        )
        alarm.add_alarm_action(action)
        return alarm
