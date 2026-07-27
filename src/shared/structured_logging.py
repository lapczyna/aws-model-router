"""Structured JSON logging (ADR-019, `docs/requirements.md` NFR-4.1): every log record
is one JSON object with a fixed, documented set of fields — never raw prompt/response
content (ADR-008).

`extra={...}` values passed to a stdlib `logging` call are only included in the emitted
JSON if their key is in `_ALLOWED_EXTRA_KEYS` below; anything else is silently dropped
rather than raising, so a call site that forgets this contract fails safe (loses one
field) instead of crashing the request. This whitelist is the "fixed, documented set" —
extend it deliberately, not by passing whatever a caller finds convenient.
"""

import json
import logging
import os
from datetime import UTC, datetime
from typing import Any, Final

_ALLOWED_EXTRA_KEYS: Final = frozenset(
    {
        "request_id",
        "decision_id",
        "application_id",
        "capability",
        "model_alias",
        "provider",
        "error_code",
        "latency_ms",
        "status_code",
        "http_method",
        "resource",
    }
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in _ALLOWED_EXTRA_KEYS:
            if key in record.__dict__:
                payload[key] = record.__dict__[key]
        if record.exc_info is not None:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging(level: str | None = None) -> None:
    """Configure the root logger for structured JSON output. Safe to call more than
    once (e.g. on every cold start) — replaces any existing handlers rather than
    stacking duplicates.
    """
    root = logging.getLogger()
    root.setLevel(level or os.environ.get("LOG_LEVEL", "INFO"))
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.handlers = [handler]
