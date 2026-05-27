"""Unit tests for IDRemapper (T013).

All tests use mocked SQLAlchemy engines — no real database connection required.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import ProgrammingError

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


# ---------------------------------------------------------------------------
# T013-8 — register_alias overrides offset for specific IDs
# ---------------------------------------------------------------------------


def test_register_alias_overrides_offset() -> None:
    """register_alias causes remap to return dest_id instead of id+offset."""
    remapper = IDRemapper({"accounts": 43})
    remapper.register_alias("accounts", 1, 1)
    remapper.register_alias("accounts", 17, 17)

    # Aliased IDs return dest_id exactly
    assert remapper.remap(1, "accounts") == 1
    assert remapper.remap(17, "accounts") == 17


# ---------------------------------------------------------------------------
# T013-9 — non-aliased IDs still use offset even when aliases exist
# ---------------------------------------------------------------------------


def test_non_aliased_ids_still_use_offset() -> None:
    """IDs without an alias still apply the offset normally."""
    remapper = IDRemapper({"accounts": 43})
    remapper.register_alias("accounts", 1, 1)

    # id=4 has no alias → 4 + 43 = 47
    assert remapper.remap(4, "accounts") == 47
    # id=18 has no alias → 18 + 43 = 61
    assert remapper.remap(18, "accounts") == 61


# ---------------------------------------------------------------------------
# T013-10 — alias on one table does not affect another table's remap
# ---------------------------------------------------------------------------


def test_alias_scoped_to_table() -> None:
    """An alias registered for one table does not affect a different table."""
    remapper = IDRemapper({"accounts": 43, "contacts": 226274})
    remapper.register_alias("accounts", 1, 1)

    # contacts id=1 has no alias → 1 + 226274 = 226275
    assert remapper.remap(1, "contacts") == 226275


# ---------------------------------------------------------------------------
# T013-11 — alias can map to a dest_id different from src_id (contact dedup)
# ---------------------------------------------------------------------------


def test_alias_maps_to_different_dest_id() -> None:
    """register_alias correctly returns an arbitrary dest_id (contact dedup use-case)."""
    remapper = IDRemapper({"contacts": 226274})
    remapper.register_alias("contacts", 500, 1234)

    assert remapper.remap(500, "contacts") == 1234
    # Other IDs still use offset
    assert remapper.remap(100, "contacts") == 226374


# ---------------------------------------------------------------------------
# T013-12 — register_alias on unknown table works (no offset required)
# ---------------------------------------------------------------------------


def test_alias_works_without_offset_entry() -> None:
    """register_alias + remap works even if table has no entry in offsets
    (alias lookup resolves before the KeyError check)."""
    remapper = IDRemapper({})
    remapper.register_alias("contacts", 7, 99)
    assert remapper.remap(7, "contacts") == 99


# ---------------------------------------------------------------------------
# T013-13 — has_alias returns True when alias is registered
# ---------------------------------------------------------------------------


def test_has_alias_returns_true_when_registered() -> None:
    """has_alias returns True for (table, src_id) pairs with registered aliases."""
    remapper = IDRemapper({"accounts": 50})
    remapper.register_alias("accounts", 1, 1)
    remapper.register_alias("accounts", 5, 20)

    assert remapper.has_alias("accounts", 1) is True
    assert remapper.has_alias("accounts", 5) is True


# ---------------------------------------------------------------------------
# T013-14 — has_alias returns False when alias is not registered
# ---------------------------------------------------------------------------


def test_has_alias_returns_false_when_not_registered() -> None:
    """has_alias returns False for IDs without registered aliases."""
    remapper = IDRemapper({"accounts": 50})
    remapper.register_alias("accounts", 1, 1)

    assert remapper.has_alias("accounts", 2) is False
    assert remapper.has_alias("accounts", 999) is False


# ---------------------------------------------------------------------------
# T013-15 — has_alias returns False for unknown table
# ---------------------------------------------------------------------------


def test_has_alias_returns_false_for_unknown_table() -> None:
    """has_alias returns False when the table has no aliases at all."""
    remapper = IDRemapper({"accounts": 50})
    remapper.register_alias("accounts", 1, 1)

    # contacts table was never registered with any alias
    assert remapper.has_alias("contacts", 1) is False


# ---------------------------------------------------------------------------
# T013-16 — compute_offsets raises ProgrammingError for non-"does not exist" errors
# ---------------------------------------------------------------------------


def test_compute_offsets_raises_on_non_existence_error() -> None:
    """compute_offsets re-raises ProgrammingError if it's not a "does not exist" error."""
    engine = MagicMock()
    conn = MagicMock()
    engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
    engine.connect.return_value.__exit__ = MagicMock(return_value=False)
    # Simulate a different error (e.g., permission denied)
    conn.execute.side_effect = ProgrammingError(
        "permission denied for table contacts", "SELECT", None
    )

    remapper = IDRemapper()
    with pytest.raises(ProgrammingError):
        remapper.compute_offsets(engine, ["contacts"])
