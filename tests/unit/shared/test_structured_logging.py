import io
import json
import logging
from typing import cast

import pytest

from shared.structured_logging import JsonFormatter

pytestmark = pytest.mark.unit


def _log_and_capture(log_fn_name: str, message: str, **kwargs: object) -> dict[str, object]:
    logger = logging.getLogger("test.structured_logging")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger.handlers = [handler]

    getattr(logger, log_fn_name)(message, **kwargs)

    return cast(dict[str, object], json.loads(stream.getvalue().strip()))


def test_basic_fields_are_present_and_json_parseable() -> None:
    payload = _log_and_capture("info", "hello world")

    assert payload["message"] == "hello world"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "test.structured_logging"
    assert "timestamp" in payload


def test_whitelisted_extra_fields_are_included() -> None:
    payload = _log_and_capture(
        "info",
        "request handled",
        extra={"request_id": "req-1", "decision_id": "dec-1", "status_code": 200},
    )

    assert payload["request_id"] == "req-1"
    assert payload["decision_id"] == "dec-1"
    assert payload["status_code"] == 200


def test_non_whitelisted_extra_fields_are_silently_dropped() -> None:
    payload = _log_and_capture(
        "info",
        "request handled",
        extra={"application_id": "app-1", "raw_prompt": "sensitive user content"},
    )

    assert payload["application_id"] == "app-1"
    assert "raw_prompt" not in payload


def test_exception_info_is_included_when_present() -> None:
    logger = logging.getLogger("test.structured_logging.exc")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger.handlers = [handler]

    try:
        raise ValueError("boom")
    except ValueError:
        logger.exception("something failed")

    payload = json.loads(stream.getvalue().strip())
    assert "boom" in payload["exception"]
    assert "ValueError" in payload["exception"]
