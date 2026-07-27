"""Per-environment CDK configuration.

Driven by CDK context (`cdk deploy -c env=dev`, or `cdk.json`'s default context) — CDK's
own convention for build-time configuration, not environment variables (those configure
the *running* Lambda, see `src/handlers/api_handler.py`).

`dev` favors fast iteration and near-zero idle cost (short retention, no PITR, full
teardown via `DESTROY`). `prod` favors safety (data `RETAIN`ed on stack deletion, PITR
on, longer log retention) — see `docs/adr/0018-dynamodb-decision-and-idempotency-store-design.md`
and `docs/operations/deployment-and-teardown.md` for the teardown implications of `RETAIN`.
"""

from dataclasses import dataclass

from aws_cdk import RemovalPolicy
from aws_cdk import aws_logs as logs


@dataclass(frozen=True)
class EnvironmentConfig:
    env_name: str
    removal_policy: RemovalPolicy
    log_retention: logs.RetentionDays
    enable_point_in_time_recovery: bool
    lambda_memory_mb: int
    lambda_timeout_seconds: int
    lambda_reserved_concurrency: int | None
    api_throttling_rate_limit: int
    api_throttling_burst_limit: int
    decisions_retention_seconds: int
    idempotency_stale_reservation_seconds: int
    max_request_body_bytes: int
    # Alarm thresholds (Phase 6, ADR-021) — evaluated over a 5-minute period unless
    # noted. "Guidance" thresholds (estimated spend) are advisory, not hard limits: the
    # underlying metric is itself an estimate, never billed cost (ADR-005).
    lambda_error_alarm_threshold: int
    lambda_throttle_alarm_threshold: int
    api_5xx_alarm_threshold: int
    provider_failure_alarm_threshold: int
    fallback_rate_alarm_threshold_percent: float
    no_eligible_model_alarm_threshold: int
    estimated_daily_spend_alarm_threshold_usd: float


_ENVIRONMENTS: dict[str, EnvironmentConfig] = {
    "dev": EnvironmentConfig(
        env_name="dev",
        removal_policy=RemovalPolicy.DESTROY,
        log_retention=logs.RetentionDays.ONE_WEEK,
        enable_point_in_time_recovery=False,
        lambda_memory_mb=512,
        lambda_timeout_seconds=30,
        lambda_reserved_concurrency=None,
        api_throttling_rate_limit=10,
        api_throttling_burst_limit=20,
        decisions_retention_seconds=7 * 24 * 60 * 60,
        idempotency_stale_reservation_seconds=300,
        max_request_body_bytes=256 * 1024,
        lambda_error_alarm_threshold=5,
        lambda_throttle_alarm_threshold=5,
        api_5xx_alarm_threshold=5,
        provider_failure_alarm_threshold=5,
        fallback_rate_alarm_threshold_percent=50.0,
        no_eligible_model_alarm_threshold=5,
        estimated_daily_spend_alarm_threshold_usd=5.0,
    ),
    "prod": EnvironmentConfig(
        env_name="prod",
        removal_policy=RemovalPolicy.RETAIN,
        log_retention=logs.RetentionDays.THREE_MONTHS,
        enable_point_in_time_recovery=True,
        lambda_memory_mb=1024,
        lambda_timeout_seconds=30,
        lambda_reserved_concurrency=10,
        api_throttling_rate_limit=50,
        api_throttling_burst_limit=100,
        decisions_retention_seconds=30 * 24 * 60 * 60,
        idempotency_stale_reservation_seconds=300,
        max_request_body_bytes=256 * 1024,
        lambda_error_alarm_threshold=10,
        lambda_throttle_alarm_threshold=10,
        api_5xx_alarm_threshold=10,
        provider_failure_alarm_threshold=10,
        fallback_rate_alarm_threshold_percent=25.0,
        no_eligible_model_alarm_threshold=10,
        estimated_daily_spend_alarm_threshold_usd=100.0,
    ),
}


def get_environment_config(env_name: str) -> EnvironmentConfig:
    try:
        return _ENVIRONMENTS[env_name]
    except KeyError as exc:
        raise ValueError(
            f"Unknown environment {env_name!r}; expected one of {sorted(_ENVIRONMENTS)}"
        ) from exc
