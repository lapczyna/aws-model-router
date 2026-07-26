# ADR-009: Converse API as the normalized Bedrock interface

## Status
Accepted

## Context
Amazon Bedrock historically exposed model-family-specific request/response shapes
(`InvokeModel` with per-provider JSON bodies for Anthropic, Meta, Amazon, etc.). Building
`BedrockModelProvider` against those per-family shapes would push provider-specific
normalization logic into the router for every model family Bedrock hosts, undermining
the provider-independent domain architecture (ADR-002) even within a single provider.

## Decision
`BedrockModelProvider` uses the Bedrock **Converse API** as its default interface for
supported models: a single, provider-agnostic request/response shape across model
families that support it (messages, inference parameters, tool configuration, stop
reasons, usage). Model-family-specific translation is Bedrock's responsibility, not the
router's.

## Consequences
* One adapter-level mapping (`ProviderRequest`/`ProviderResponse` ⇄ Converse shapes)
  covers every Converse-supported model family, instead of one mapping per family.
* Token usage, stop reasons, and tool-use results are extracted from a consistent
  response shape, simplifying `ProviderResponse` normalization and error/stop-reason
  classification (Phase 3).
* If a specific model or feature is not yet supported by Converse (e.g. a very new model
  family, or a modality Converse hasn't added), `BedrockModelProvider` cannot use it until
  Converse supports it, or would need a documented, explicit exception falling back to
  `InvokeModel` for that specific case — this is a deliberate, bounded trade-off in favor
  of normalization simplicity.
* `ModelCapabilities` (ADR-002) still must reflect real per-model variance (token limits,
  tool support) even though the wire format is unified — Converse does not make all
  models behave identically, only structurally consistent.

## Alternatives considered
* **`InvokeModel` with per-family request/response mapping** — rejected as the default:
  would require and maintain N provider-specific mappers inside `BedrockModelProvider`,
  directly working against ADR-002's goal of isolating provider-shape complexity behind
  one normalization boundary. Remains available as a documented escape hatch for a model
  or feature Converse does not yet support.
* **A third-party LLM abstraction library** — rejected: adds an external dependency and
  its own abstraction layer on top of Bedrock's own, when Bedrock already provides a
  native, provider-agnostic API (Converse) that meets the need directly.
