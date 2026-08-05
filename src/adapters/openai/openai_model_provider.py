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
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING, Any

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
    build_chat_completion_stream_request,
    iter_chat_completion_stream_chunks,
    parse_chat_completion_response,
)
from adapters.openai.error_mapping import classify_provider_exception
from domain.enums import ProviderErrorCategory
from domain.errors import ProviderError
from domain.ports import ModelCatalogue
from domain.provider import ProviderRequest, ProviderResponse, ProviderResponseChunk

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

    def invoke_stream(self, request: ProviderRequest) -> Iterator[ProviderResponseChunk]:
        """`domain.ports.StreamingModelProvider.invoke_stream` via Chat Completions'
        `stream=True` (ADR-032, Phase 10c). Mirrors
        `adapters.bedrock.BedrockModelProvider.invoke_stream`'s shape exactly: eager
        resolution/capability-checking, lazy network call (nothing runs until the
        returned generator is first pulled from), retries only around establishing the
        stream -- never once a chunk has been read from it.
        """
        model = resolve_model(request.model_alias, self._model_catalogue)
        check_capabilities(request, model)
        target_model = resolve_target_model_id(model, self._model_catalogue)
        payload = build_chat_completion_stream_request(request, target_model)
        return self._stream(payload)

    def _stream(self, payload: dict[str, Any]) -> Iterator[ProviderResponseChunk]:
        attempt = 0
        while True:
            attempt += 1
            try:
                raw_stream = self._client.chat.completions.create(**payload)
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
            break

        try:
            yield from iter_chat_completion_stream_chunks(raw_stream)
        except openai.OpenAIError as exc:
            category = classify_provider_exception(exc)
            raise ProviderError(safe_message_for(category), category=category) from exc
