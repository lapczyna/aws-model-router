# Contract tests

Validate request/response and provider contracts: API request/response schemas
(`docs/architecture/api-contracts.md`) and the `ModelProvider` adapter contract against
fakes and `botocore.stub.Stubber`.

`test_policy_schema_examples.py` (Phase 2) validates the repository's real, shipped
`policies/` configuration against the domain schema — a regression check pinning the
sample config to what it must satisfy, and a preview of the "policy-schema validation"
CI step planned for Phase 8. Bedrock provider contract tests are added in Phase 3.

No test in this directory requires live AWS credentials or makes a real Bedrock
invocation.
