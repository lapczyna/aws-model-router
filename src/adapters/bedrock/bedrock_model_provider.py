"""`BedrockModelProvider`: the `ModelProvider` implementation for Amazon Bedrock.

Resolves a logical model alias against the `ModelCatalogue` (never accepting a raw
provider model ID from a caller — ADR-006), validates the request against that model's
declared capabilities, invokes it via the Converse API, and classifies any failure into
`domain.enums.ProviderErrorCategory` so callers never need to know about boto3/botocore
exception types.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING, Any

from botocore.exceptions import BotoCoreError, ClientError

from adapters.bedrock.converse_mapper import (
    build_converse_request,
    iter_converse_stream_events,
    parse_converse_response,
)
from adapters.bedrock.error_mapping import classify_provider_exception, safe_message_for
from adapters.common.model_resolution import (
    check_capabilities,
    resolve_model,
    resolve_target_model_id,
)
from adapters.common.retry import RetryPolicy, compute_backoff_delay
from domain.enums import ProviderErrorCategory
from domain.errors import ProviderError
from domain.ports import ModelCatalogue
from domain.provider import ProviderRequest, ProviderResponse, ProviderResponseChunk

if TYPE_CHECKING:
    from mypy_boto3_bedrock_runtime.client import BedrockRuntimeClient

_RETRYABLE_CATEGORIES = frozenset(
    {
        ProviderErrorCategory.THROTTLED,
        ProviderErrorCategory.TRANSIENT,
        ProviderErrorCategory.TIMEOUT,
    }
)


class BedrockModelProvider:
    def __init__(
        self,
        client: BedrockRuntimeClient,
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
        target_model_id = resolve_target_model_id(model, self._model_catalogue)
        payload = build_converse_request(request, target_model_id)

        attempt = 0
        while True:
            attempt += 1
            try:
                raw_response = self._client.converse(**payload)
            except (ClientError, BotoCoreError) as exc:
                category = classify_provider_exception(exc)
                if (
                    category not in _RETRYABLE_CATEGORIES
                    or attempt >= self._retry_policy.max_attempts
                ):
                    raise ProviderError(safe_message_for(category), category=category) from exc
                delay = compute_backoff_delay(attempt, self._retry_policy, self._jitter())
                self._sleep(delay)
                continue

            return parse_converse_response(raw_response, request.model_alias, model.provider)

    def invoke_stream(self, request: ProviderRequest) -> Iterator[ProviderResponseChunk]:
        """`domain.ports.StreamingModelProvider.invoke_stream` via Bedrock's
        ConverseStream API (ADR-032, Phase 10c).

        Resolution/capability-checking happen eagerly, exactly like `invoke()` -- an
        invalid model alias or unsupported capability raises immediately, before any
        network call. The `.converse_stream()` call itself, and the retry loop around
        it, only run once the returned iterator is first pulled from (a plain Python
        generator doesn't start executing until iterated), matching the lazy semantics
        `StreamingModelProvider` implies. Retries only ever apply to establishing the
        stream; once the first event has been read from it, a failure is not retried --
        see `iter_converse_stream_events`.
        """
        model = resolve_model(request.model_alias, self._model_catalogue)
        check_capabilities(request, model)
        target_model_id = resolve_target_model_id(model, self._model_catalogue)
        payload = build_converse_request(request, target_model_id)
        return self._stream(payload)

    def _stream(self, payload: dict[str, Any]) -> Iterator[ProviderResponseChunk]:
        attempt = 0
        while True:
            attempt += 1
            try:
                raw_response = self._client.converse_stream(**payload)
            except (ClientError, BotoCoreError) as exc:
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
            yield from iter_converse_stream_events(raw_response["stream"])
        except (ClientError, BotoCoreError) as exc:
            category = classify_provider_exception(exc)
            raise ProviderError(safe_message_for(category), category=category) from exc
