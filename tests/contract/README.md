# Contract tests

Validate request/response and provider contracts: API request/response schemas
(`docs/architecture/api-contracts.md`) and the `ModelProvider` adapter contract against
fakes and `botocore.stub.Stubber`.

Test files added starting in Phase 2 (policy/catalogue schema validation) and Phase 3
(Bedrock provider contract tests). No test in this directory requires live AWS
credentials or makes a real Bedrock invocation.
