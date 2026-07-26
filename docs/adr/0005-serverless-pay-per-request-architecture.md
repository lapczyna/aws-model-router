# ADR-005: Serverless, pay-per-request architecture

## Status
Accepted

## Context
This is a reference/portfolio project without predictable, sustained production traffic.
It must cost close to nothing while idle, while still demonstrating a credible,
production-shaped architecture under load.

## Decision
The default deployment uses only pay-per-request AWS services: Lambda (compute), API
Gateway REST API (entry point), DynamoDB on-demand capacity (state), and Bedrock
on-demand inference (model calls). No always-on compute (EC2/ECS/EKS), no provisioned
database or search cluster (Aurora/OpenSearch/ElastiCache), no NAT Gateway, and no
Bedrock Provisioned Throughput are used in the base architecture.

## Consequences
* Idle cost is near zero: Lambda, API Gateway, and DynamoDB on-demand only bill for
  actual invocations/requests/reads/writes; CloudWatch Logs cost is bounded by
  configured retention.
* Cold starts and per-invocation Lambda limits (time, memory, payload size) become real
  constraints the design must respect (thin handlers, bounded retries, no long-running
  background work).
* Horizontal scaling is automatic (Lambda concurrency, DynamoDB on-demand) but must be
  bounded deliberately (reserved concurrency, API Gateway throttling) to cap worst-case
  cost during traffic spikes or retry storms — this is why bounded retries/fallback
  (ADR-007, Phase 4) and throttling (Phase 5) are explicit requirements, not
  afterthoughts.
* Some workloads that would be simpler on always-on compute (e.g. long-lived streaming
  connections) are deliberately out of scope for the base architecture, matching the
  project's non-goal of building a chatbot UI.

## Alternatives considered
* **Containers on ECS/EKS (Fargate or otherwise)** — rejected: introduces always-on or
  minimum-provisioned cost even at zero traffic, and no requirement in this project
  needs long-running processes, custom networking, or sidecars that would justify it.
* **Provisioned Bedrock Throughput** — rejected: has a significant fixed hourly cost
  regardless of usage, which directly contradicts the near-zero idle cost goal; on-demand
  inference is used throughout, with cross-Region inference profiles considered later
  purely for resilience/throughput headroom (Phase 7), not as a provisioning model.
* **Step Functions for the core request flow** — rejected: the request flow is a
  synchronous, low-latency chain of in-process steps within one Lambda invocation; a
  Step Functions state machine would add per-transition cost and latency without a
  corresponding orchestration need (no long-running waits, no human-in-the-loop steps in
  the base flow).
