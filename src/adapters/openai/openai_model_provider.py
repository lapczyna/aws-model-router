"""`OpenAIModelProvider`: the `ModelProvider` implementation for OpenAI (ADR-029).

Resolves a logical model alias against the `ModelCatalogue` (never accepting a raw
provider model ID from a caller — ADR-006), validates the request against that model's
declared capabilities, invokes it via the Chat Completions API, and classifies any
failure into `domain.enums.ProviderErrorCategory` so callers never need to know about
`openai` SDK exception types. Mirrors `adapters.bedrock.BedrockModelProvider`'s shape
exactly — same shared retry/resolution helpers (`adapters.common`), same control flow —
so the two adapters are trivially comparable side by side.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

import openai

from adapters.common.error_messages import safe_message_for
from adapters.common.model_resolution import (
    check_capabilities,
    resolve_model,
    resolve_target_model_id,
)
from adapters.common.retry import RetryPolicy, compute_backoff_delay
from adapters.openai.chat_completions_mapper import (
    build_chat_completion_request,
    parse_chat_completion_response,
)
from adapters.openai.error_mapping import classify_provider_exception
from domain.enums import ProviderErrorCategory
from domain.errors import ProviderError
from domain.ports import ModelCatalogue
from domain.provider import ProviderRequest, ProviderResponse

if TYPE_CHECKING:
    from openai import OpenAI

_RETRYABLE_CATEGORIES = frozenset(
    {
        ProviderErrorCategory.THROTTLED,
        ProviderErrorCategory.TRANSIENT,
        ProviderErrorCategory.TIMEOUT,
    }
)


class OpenAIModelProvider:
    def __init__(
        self,
        client: OpenAI,
        model_catalogue: ModelCatalogue,
        retry_policy: RetryPolicy | None = None,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self._client = client
        self._model_catalogue = model_catalogue
        self._retry_policy = retry_policy if retry_policy is not None else RetryPolicy()
        self._sleep = sleep
        self._jitter = jitter

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        model = resolve_model(request.model_alias, self._model_catalogue)
        check_capabilities(request, model)
        target_model = resolve_target_model_id(model, self._model_catalogue)
        payload = build_chat_completion_request(request, target_model)

        attempt = 0
        while True:
            attempt += 1
            try:
                raw_response = self._client.chat.completions.create(**payload)
            except openai.OpenAIError as exc:
                category = classify_provider_exception(exc)
                if (
                    category not in _RETRYABLE_CATEGORIES
                    or attempt >= self._retry_policy.max_attempts
                ):
                    raise ProviderError(safe_message_for(category), category=category) from exc
                delay = compute_backoff_delay(attempt, self._retry_policy, self._jitter())
                self._sleep(delay)
                continue

            return parse_chat_completion_response(raw_response, request.model_alias, model.provider)
