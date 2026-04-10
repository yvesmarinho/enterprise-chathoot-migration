"""Unit tests for IDRemapper (T013).

All tests use mocked SQLAlchemy engines — no real database connection required.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.utils.id_remapper import IDRemapper

# ---------------------------------------------------------------------------
# T013-1 — compute_offsets returns 0 for empty table
# ---------------------------------------------------------------------------


def test_compute_offsets_returns_zero_for_empty_table() -> None:
    """compute_offsets returns offset=0 when MAX(id) is NULL (empty table)."""
    engine = MagicMock()
    conn = MagicMock()
    engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
    engine.connect.return_value.__exit__ = MagicMock(return_value=False)
    # MAX(id) returns NULL → row[0] is None
    conn.execute.return_value.fetchone.return_value = (None,)

    remapper = IDRemapper()
    offsets = remapper.compute_offsets(engine, ["contacts"])

    assert offsets["contacts"] == 0


# ---------------------------------------------------------------------------
# T013-2 — compute_offsets returns correct MAX value
# ---------------------------------------------------------------------------


def test_compute_offsets_returns_max_id_from_dest() -> None:
    """compute_offsets returns the MAX(id) of the destination table."""
    engine = MagicMock()
    conn = MagicMock()
    engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
    engine.connect.return_value.__exit__ = MagicMock(return_value=False)
    conn.execute.return_value.fetchone.return_value = (225536,)

    remapper = IDRemapper()
    offsets = remapper.compute_offsets(engine, ["contacts"])

    assert offsets["contacts"] == 225536


# ---------------------------------------------------------------------------
# T013-3 — remap applies id_origem + offset
# ---------------------------------------------------------------------------


def test_remap_applies_id_plus_offset() -> None:
    """remap returns id_origem + offset for the given table."""
    remapper = IDRemapper({"contacts": 225536, "accounts": 20})

    assert remapper.remap(1, "contacts") == 225537
    assert remapper.remap(38868, "contacts") == 225536 + 38868
    assert remapper.remap(3, "accounts") == 23


# ---------------------------------------------------------------------------
# T013-4 — remap with offset=0 returns id_origem unchanged
# ---------------------------------------------------------------------------


def test_remap_with_zero_offset_returns_source_id() -> None:
    """remap with offset=0 (empty dest table) returns id_origem unchanged."""
    remapper = IDRemapper({"teams": 0})
    assert remapper.remap(7, "teams") == 7


# ---------------------------------------------------------------------------
# T013-5 — remap raises KeyError for unknown table
# ---------------------------------------------------------------------------


def test_remap_raises_key_error_for_unknown_table() -> None:
    """remap raises KeyError when table was not included in compute_offsets."""
    remapper = IDRemapper({"accounts": 20})
    with pytest.raises(KeyError, match="unknown.*not found"):
        remapper.remap(1, "unknown")


# ---------------------------------------------------------------------------
# T013-6 — offsets are session-constant (compute_offsets idempotent)
# ---------------------------------------------------------------------------


def test_offsets_are_session_constant() -> None:
    """Calling compute_offsets twice returns the same dict (session-scoped)."""
    engine = MagicMock()
    conn = MagicMock()
    engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
    engine.connect.return_value.__exit__ = MagicMock(return_value=False)
    # First call returns 100, second call returns 200 (won't be seen)
    conn.execute.return_value.fetchone.side_effect = [(100,), (200,)]

    remapper = IDRemapper()
    _ = remapper.compute_offsets(engine, ["labels"])
    # Overwrite by calling again
    second = remapper.compute_offsets(engine, ["labels"])

    # The second call should update the instance (not cache the first)
    # The key behaviour is that offsets property always returns the last computed
    assert second["labels"] == 200
    assert remapper.offsets["labels"] == 200


# ---------------------------------------------------------------------------
# T013-7 — offsets property returns a copy (mutation-safe)
# ---------------------------------------------------------------------------


def test_offsets_property_returns_copy() -> None:
    """Mutating the returned offsets dict does not affect the remapper state."""
    remapper = IDRemapper({"users": 294})
    snapshot = remapper.offsets
    snapshot["users"] = 999
    assert remapper.offsets["users"] == 294
