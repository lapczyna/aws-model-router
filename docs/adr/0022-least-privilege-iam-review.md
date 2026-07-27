# ADR-022: Least-privilege IAM review

## Status
Accepted

## Context
Phase 7's threat model (`docs/security/threat-model.md`) requires a documented
least-privilege IAM review, not just a general claim of "least privilege" (NFR-2.2).
The Lambda execution role's Bedrock permissions were already explicitly ARN-scoped to
the catalogue (ADR-017's `lambda_construct.py`), but the DynamoDB permissions used
`dynamodb.Table.grant_read_write_data()` — a broad convenience helper — without
verifying it against what the two DynamoDB adapters actually call.

## Decision
Reviewing `src/adapters/dynamodb/dynamodb_decision_repository.py` and
`dynamodb_idempotency_store.py` line by line shows exactly three boto3 table operations
in use, never more:

* `DynamoDbRoutingDecisionRepository`: `put_item` (`save`), `get_item` (`get`). No
  `update_item`, `delete_item`, `query`, or `scan` anywhere.
* `DynamoDbIdempotencyStore`: `put_item` (`reserve`'s conditional write, `complete`'s
  cache write), `get_item` (`reserve`'s fallback read), `delete_item` (`release`,
  `complete`'s no-cache-configured path). No `update_item`, `query`, or `scan`.

`grant_read_write_data()` grants `BatchGetItem`, `GetItem`, `Query`, `Scan`,
`ConditionCheckItem`, `BatchWriteItem`, `PutItem`, `UpdateItem`, `DeleteItem`,
`DescribeTable`, plus (via the table's stream-adjacent grant set)
`GetRecords`/`GetShardIterator` — nine-plus actions where two or three are ever
exercised. This is replaced with explicit `table.grant(function, *actions)` calls
listing only the actions each table's adapter actually performs:

```python
decisions_table.grant(self.function, "dynamodb:GetItem", "dynamodb:PutItem")
idempotency_table.grant(
    self.function, "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem"
)
```

**Reviewed and accepted as-is, not tightened**: the Lambda's X-Ray tracing permissions
(`xray:PutTraceSegments`, `xray:PutTelemetryRecords`, auto-added by
`tracing=lambda_.Tracing.ACTIVE`) carry `Resource: "*"`. This is not a wildcard
oversight — AWS's IAM policy reference does not define resource-level permissions for
either X-Ray action; `"*"` is the only valid resource value AWS supports for them.

## Consequences
* If a future adapter change needs a new DynamoDB operation (e.g. a `query` for a new
  access pattern), the CDK grant must be updated in the same change — an intentional
  coupling: a reviewer sees the exact permission surface a code change requires,
  including in a PR diff, rather than it being silently pre-authorized by a blanket
  helper.
* `tests/infra/test_model_router_stack.py::test_dynamodb_grants_are_scoped_to_the_exact_actions_each_adapter_uses`
  (Phase 7) asserts the exact action lists above and that neither `dynamodb:Scan` nor
  `dynamodb:Query` ever appears on the Lambda's role — a regression here (e.g. reverting
  to `grant_read_write_data()`) fails a CDK assertion test, not just a code review.
* No IAM change was needed for Bedrock (already ARN- and action-scoped since Phase 5) or
  for CloudWatch/SNS (Phase 6's `ObservabilityConstruct` added zero Lambda IAM
  permissions — alarms invoke SNS via CloudWatch's own service permissions).

## Alternatives considered
* **Leave `grant_read_write_data()` and rely on the tables' own resource-level ARN
  scoping as the primary control** — rejected: resource scoping (which table) and
  action scoping (which operations) are independent dimensions of least privilege; a
  compromised Lambda execution role that only needs to read/write specific items should
  not also be able to `Scan` an entire table, which `grant_read_write_data()` permits.
* **A custom IAM policy JSON file, hand-maintained outside CDK** — rejected: loses the
  compile-time construct references (`decisions_table.grant(...)`) that keep the policy
  and the actual table resource in sync automatically; a hand-maintained ARN string is
  exactly the kind of drift risk CDK's grant methods exist to avoid.
