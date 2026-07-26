# ADR-003: Amazon Bedrock as initial provider

## Status
Accepted

## Context
The router needs a real model provider to integrate against for the first, concrete
implementation. The project is explicitly an AWS-centric reference implementation, and
the team's primary cloud is AWS.

## Decision
Amazon Bedrock is the initial and only model provider implemented in this project.
Bedrock is accessed through its Converse API (see ADR-009) via a `BedrockModelProvider`
adapter that implements the provider-independent `ModelProvider` interface (ADR-002).

## Consequences
* The project can use a single, provider-agnostic invocation interface (Converse) across
  multiple model families available through Bedrock, rather than integrating with each
  model family's native API.
* IAM-based access control and AWS-native observability (CloudWatch, X-Ray) apply
  directly, with no separate credential system to manage.
* The project inherits Bedrock's regional availability and per-model feature variance
  (not every model supports every Converse feature) — this is why `ModelCapabilities` is
  explicit per model (ADR-002) rather than assumed uniform.
* Multi-provider support is deferred; it is architecturally possible (ADR-002) but not
  built or tested in this project unless a later phase explicitly adds it.

## Alternatives considered
* **Multiple providers from day one** (e.g. Bedrock + a direct OpenAI/Anthropic API
  integration) — rejected for the initial scope: doubles the adapter and testing surface
  before the core routing domain is proven, and the portfolio goal is to demonstrate
  depth in one AWS-native integration first, with extensibility demonstrated
  architecturally rather than by shipping a second, thinner integration.
* **Provisioned Throughput or a custom-hosted model endpoint** — rejected: contradicts
  the pay-per-request cost requirement (NFR-1) and is unnecessary for a reference
  implementation; on-demand Bedrock inference is used throughout.
