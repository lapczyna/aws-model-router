"""Provider-neutral adapter helpers shared by every `domain.ports.ModelProvider`
implementation (`adapters.bedrock`, `adapters.openai`, ...) — retry/backoff and model
catalogue resolution logic that has nothing to do with any one provider's wire format.
"""
