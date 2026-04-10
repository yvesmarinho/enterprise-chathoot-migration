"""Automatic PII masking for all log output.

:description: Provides :class:`MaskingHandler` — a Python logging handler that
    intercepts every log record and redacts sensitive values (e-mails, phone
    numbers, and column-targeted string values) before forwarding to the real
    handler.

    >>> import logging
    >>> import io
    >>> stream = io.StringIO()
    >>> inner = logging.StreamHandler(stream)
    >>> handler = MaskingHandler(inner)
    >>> logger = logging.getLogger("test_masker")
    >>> logger.addHandler(handler)
    >>> logger.setLevel(logging.DEBUG)
    >>> logger.info("contact email=user@example.com phone=+55 11 91234-5678")
    >>> "example.com" in stream.getvalue()
    False
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

# ---------------------------------------------------------------------------
# Sensitive column registry  (per entity)
# ---------------------------------------------------------------------------

SENSITIVE_COLUMNS: dict[str, list[str]] = {
    "contacts": [
        "name",
        "email",
        "phone_number",
        "identifier",
        "additional_attributes",
    ],
    "users": ["name", "email", "phone_number"],
    "conversations": ["additional_attributes", "meta"],
    "messages": ["content", "content_attributes"],
    "accounts": ["name"],
}

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
    re.IGNORECASE,
)

_BR_PHONE_RE = re.compile(
    r"(\+55)?\s*\(?\d{2}\)?\s*\d{4,5}[\-\s]?\d{4}",
)


def _mask_jsonb(value: Any) -> Any:  # noqa: ANN401
    """Recursively mask sensitive values inside a JSONB-like structure.

    Strings matching e-mail or phone patterns are replaced with ``***``.
    Dict keys are preserved; values are recursively processed.

    :param value: Any JSON-compatible value (dict, list, str, int, etc.).
    :type value: Any
    :returns: The structure with sensitive string values redacted.
    :rtype: Any

    >>> _mask_jsonb({"email": "a@b.com", "count": 5})
    {'email': '***', 'count': 5}
    >>> _mask_jsonb(["hello@world.com", 42])
    ['***', 42]
    """
    if isinstance(value, dict):
        return {k: _mask_jsonb(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask_jsonb(item) for item in value]
    if isinstance(value, str):
        return _mask_string(value)
    return value


def _mask_string(text: str) -> str:
    """Apply PII regex redaction to a plain string.

    :param text: Input string potentially containing PII.
    :type text: str
    :returns: String with e-mail addresses and phone numbers replaced by ``***``.
    :rtype: str

    >>> _mask_string("contact user@example.com or +55 11 99999-1234")
    'contact *** or ***'
    >>> _mask_string("record id=42 offset=100")
    'record id=42 offset=100'
    """
    result = _EMAIL_RE.sub("***", text)
    result = _BR_PHONE_RE.sub("***", result)
    return result


def mask_message(message: str) -> str:
    """Mask PII in a log message string.

    Tries to parse as JSON first; if successful applies :func:`_mask_jsonb`.
    Otherwise falls back to :func:`_mask_string`.

    :param message: Raw log message.
    :type message: str
    :returns: Redacted message.
    :rtype: str

    >>> mask_message('{"email": "x@y.com"}')
    '{"email": "***"}'
    >>> mask_message("plain text user@host.com")
    'plain text ***'
    """
    # Attempt JSON parse for JSONB column values logged as serialised dicts
    stripped = message.strip()
    if stripped.startswith(("{", "[")):
        try:
            obj = json.loads(stripped)
            return json.dumps(_mask_jsonb(obj), ensure_ascii=False)
        except json.JSONDecodeError:
            pass
    return _mask_string(message)


class MaskingHandler(logging.Handler):
    """Logging handler that masks PII before delegating to an inner handler.

    All records pass through :func:`mask_message` applied to the formatted
    log message before the inner handler emits anything.

    :param inner: The downstream handler that actually writes output
        (e.g., ``StreamHandler`` or ``FileHandler``).
    :type inner: logging.Handler

    >>> import io, logging
    >>> buf = io.StringIO()
    >>> h = MaskingHandler(logging.StreamHandler(buf))
    >>> h.setLevel(logging.DEBUG)
    >>> rec = logging.LogRecord("n","","",0,"test@email.com",(),None)
    >>> h.emit(rec)
    >>> "email.com" in buf.getvalue()
    False
    """

    def __init__(self, inner: logging.Handler) -> None:
        """Initialise with an inner handler.

        :param inner: Downstream logging handler.
        :type inner: logging.Handler
        """
        super().__init__()
        self._inner = inner
        # Propagate level and formatter from inner handler
        self.setLevel(inner.level)
        if inner.formatter:
            self.setFormatter(inner.formatter)

    def emit(self, record: logging.LogRecord) -> None:
        """Mask PII in *record* then forward to the inner handler.

        :param record: The original log record.
        :type record: logging.LogRecord
        """
        try:
            original = self.format(record)
            masked = mask_message(original)
            # Patch the record message so inner handler emits the masked version
            new_record = logging.makeLogRecord(record.__dict__)
            new_record.msg = masked
            new_record.args = None
            self._inner.handle(new_record)
        except Exception:  # noqa: BLE001
            self.handleError(record)
