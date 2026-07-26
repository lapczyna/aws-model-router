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
from collections.abc import Callable
from typing import TYPE_CHECKING

from botocore.exceptions import BotoCoreError, ClientError

from adapters.bedrock.converse_mapper import build_converse_request, parse_converse_response
from adapters.bedrock.error_mapping import classify_provider_exception, safe_message_for
from adapters.bedrock.retry import RetryPolicy, compute_backoff_delay
from domain.catalogue import ModelDefinition
from domain.enums import ModelResolutionType, ProviderErrorCategory
from domain.errors import ProviderError
from domain.ports import ModelCatalogue
from domain.provider import ProviderRequest, ProviderResponse

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
        model = self._resolve_model(request.model_alias)
        self._check_capabilities(request, model)
        target_model_id = self._resolve_target_model_id(model)
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

    def _resolve_model(self, model_alias: str) -> ModelDefinition:
        model = self._model_catalogue.get_by_alias(model_alias)
        if model is None:
            raise ProviderError(
                f"Unknown model alias: {model_alias!r}", category=ProviderErrorCategory.PERMANENT
            )
        return model

    def _resolve_target_model_id(self, model: ModelDefinition) -> str:
        if model.resolution.type is not ModelResolutionType.ROUTER_ALIAS:
            return model.resolution.value

        # A router alias is a single, bounded indirection to another catalogue entry —
        # not an arbitrary chain — so a router alias pointing at another router alias is
        # treated as a configuration error rather than followed recursively.
        target = self._model_catalogue.get_by_alias(model.resolution.value)
        if target is None or target.resolution.type is ModelResolutionType.ROUTER_ALIAS:
            raise ProviderError(
                f"Router alias {model.model_alias!r} does not resolve to an invocable model.",
                category=ProviderErrorCategory.PERMANENT,
            )
        return target.resolution.value

    def _check_capabilities(self, request: ProviderRequest, model: ModelDefinition) -> None:
        if request.requires_tool_use and not model.capabilities.supports_tool_use:
            raise ProviderError(
                f"Model alias {model.model_alias!r} does not support tool use.",
                category=ProviderErrorCategory.PERMANENT,
            )
        if request.requires_structured_output and not model.capabilities.supports_structured_output:
            raise ProviderError(
                f"Model alias {model.model_alias!r} does not support structured output.",
                category=ProviderErrorCategory.PERMANENT,
            )
