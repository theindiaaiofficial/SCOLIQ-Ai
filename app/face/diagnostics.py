from __future__ import annotations

import json
import logging
from contextvars import ContextVar, Token
from typing import Any

logger = logging.getLogger("uvicorn.error")
_enabled = False
_request_id: ContextVar[str] = ContextVar("smartattend_face_request_id", default="-")


def configure_face_diagnostics(enabled: bool) -> None:
    """Enable metadata-only face diagnostics for local development/testing."""
    global _enabled
    _enabled = bool(enabled)


def bind_face_request_id(request_id: str) -> Token[str]:
    """Bind the HTTP request id so worker-thread face logs can be correlated."""
    return _request_id.set(request_id)


def reset_face_request_id(token: Token[str]) -> None:
    _request_id.reset(token)


def log_face_event(event: str, **metrics: Any) -> None:
    """Emit metadata-only diagnostics. Never pass image bytes or embeddings here."""
    if not _enabled:
        return
    record = {
        "request_id": _request_id.get(),
        "event": event,
        **metrics,
    }
    logger.info(
        "face_diagnostic %s",
        json.dumps(record, sort_keys=True, separators=(",", ":"), default=str),
    )
