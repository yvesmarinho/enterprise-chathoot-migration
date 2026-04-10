"""Unit tests for MaskingHandler and masking utilities (T014).

All tests run in-process — no database, no file system access.
"""

from __future__ import annotations

import io
import logging

import pytest

from src.utils.log_masker import MaskingHandler, _mask_jsonb, _mask_string, mask_message

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_logger_with_buffer() -> tuple[logging.Logger, io.StringIO]:
    """Return (logger, buffer) where the logger has a MaskingHandler attached."""
    buf = io.StringIO()
    inner = logging.StreamHandler(buf)
    inner.setLevel(logging.DEBUG)
    handler = MaskingHandler(inner)
    handler.setLevel(logging.DEBUG)
    logger = logging.getLogger(f"test_masker_{id(buf)}")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    return logger, buf


# ---------------------------------------------------------------------------
# T014-1 — Email address is replaced with *** in log output
# ---------------------------------------------------------------------------


def test_email_masked_in_log() -> None:
    """Email address in log message is replaced with ***."""
    logger, buf = _make_logger_with_buffer()
    logger.info("contact email=user@example.com phone=none")
    output = buf.getvalue()
    assert "example.com" not in output
    assert "***" in output


# ---------------------------------------------------------------------------
# T014-2 — Brazilian phone number is replaced with *** in log output
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "phone",
    [
        "+55 11 91234-5678",
        "(11) 99999-1234",
        "+5511987654321",
        "11 9876-5432",
    ],
)
def test_phone_number_masked_in_log(phone: str) -> None:
    """BR phone number patterns are replaced with *** in log output."""
    logger, buf = _make_logger_with_buffer()
    logger.info("contact phone=%s", phone)
    output = buf.getvalue()
    # The original phone digits should not appear in output
    # We check the last 4 digits of the phone are gone
    assert phone[-4:] not in output


# ---------------------------------------------------------------------------
# T014-3 — JSONB value containing email is masked recursively
# ---------------------------------------------------------------------------


def test_jsonb_email_masked_recursively() -> None:
    """Email nested inside a JSON object is masked."""
    result = mask_message('{"email": "nested@domain.com", "count": 5}')
    assert "nested@domain.com" not in result
    assert "***" in result
    # Non-sensitive integer values are preserved
    assert "5" in result


def test_jsonb_list_with_email_masked() -> None:
    """Email inside a JSON list is masked."""
    result = _mask_jsonb(["hello@world.com", 42, {"x": "no-pii"}])
    assert result[0] == "***"
    assert result[1] == 42
    assert result[2]["x"] == "no-pii"


# ---------------------------------------------------------------------------
# T014-4 — Integer record ID is NOT masked
# ---------------------------------------------------------------------------


def test_integer_id_not_masked() -> None:
    """Plain integer IDs are never replaced by the masker."""
    result = _mask_string("record id=42 offset=100 status=ok")
    # No email or phone in this string — should pass through unchanged
    assert "42" in result
    assert "100" in result


def test_jsonb_integer_values_not_masked() -> None:
    """Integer values inside a JSONB dict are preserved."""
    result = _mask_jsonb({"id": 99999, "status": "ok"})
    assert result["id"] == 99999


# ---------------------------------------------------------------------------
# T014-5 — Masking applies to both StreamHandler and conceptually FileHandler
# ---------------------------------------------------------------------------


def test_masking_applies_through_stream_handler() -> None:
    """MaskingHandler intercepts the record before StreamHandler emits it."""
    buf = io.StringIO()
    inner = logging.StreamHandler(buf)
    inner.setLevel(logging.DEBUG)
    handler = MaskingHandler(inner)
    handler.setLevel(logging.DEBUG)

    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="sensitive email=admin@corp.com",
        args=(),
        exc_info=None,
    )
    handler.emit(record)
    output = buf.getvalue()
    assert "admin@corp.com" not in output
    assert "***" in output


def test_masking_handler_with_file_handler_equivalent(tmp_path) -> None:
    """MaskingHandler wrapping a FileHandler masks PII before writing to disk."""
    log_file = tmp_path / "test_output.log"
    file_handler = logging.FileHandler(str(log_file))
    file_handler.setLevel(logging.DEBUG)
    handler = MaskingHandler(file_handler)

    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="user@secret.org called",
        args=(),
        exc_info=None,
    )
    handler.emit(record)
    file_handler.close()

    content = log_file.read_text()
    assert "user@secret.org" not in content
    assert "***" in content


# ---------------------------------------------------------------------------
# T014-6 — Non-PII strings are passed through unchanged
# ---------------------------------------------------------------------------


def test_non_pii_string_passes_through_unchanged() -> None:
    """Strings with no email or phone are returned identical by mask_message."""
    msg = "migrating table contacts batch 1/78"
    assert mask_message(msg) == msg


# ---------------------------------------------------------------------------
# T014-7 — mask_message handles plain text fallback (non-JSON)
# ---------------------------------------------------------------------------


def test_mask_message_plain_text_fallback() -> None:
    """mask_message uses string masking when input is not valid JSON."""
    result = mask_message("plain text user@host.com end")
    assert "user@host.com" not in result
    assert "***" in result
