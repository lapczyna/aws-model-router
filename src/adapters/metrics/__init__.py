"""Custom application metrics via the CloudWatch Embedded Metric Format (EMF, ADR-019):
one structured JSON line per metric point, written to stdout and auto-extracted into
CloudWatch Metrics by the Lambda's own log group — no extra `PutMetricData` API calls,
no extra IAM permissions beyond the `logs:PutLogEvents` every Lambda already has.
"""
