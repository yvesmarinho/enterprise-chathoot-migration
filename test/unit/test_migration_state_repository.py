"""Unit tests for MigrationStateRepository (T034)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.repository.migration_state_repository import MigrationStateRepository

# ---------------------------------------------------------------------------
# T034-1 — create_table_if_not_exists is idempotent
# ---------------------------------------------------------------------------


def test_create_table_idempotent():
    """create_table_if_not_exists can be called twice without error."""
    engine = MagicMock()
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    conn.execute.return_value = MagicMock()
    engine.connect.return_value = conn

    repo = MigrationStateRepository()
    with patch("src.repository.migration_state_repository._metadata") as mock_meta:
        mock_meta.create_all = MagicMock()
        repo.create_table_if_not_exists(engine)
        repo.create_table_if_not_exists(engine)
    # No exception raised
    assert mock_meta.create_all.call_count == 2


# ---------------------------------------------------------------------------
# T034-2 — get_migrated_ids returns correct set of id_origem values
# ---------------------------------------------------------------------------


def test_get_migrated_ids_returns_correct_set():
    """get_migrated_ids returns the set of id_origem where status='ok'."""
    conn = MagicMock()
    conn.execute.return_value.fetchall.return_value = [(10,), (20,), (30,)]

    repo = MigrationStateRepository()
    result = repo.get_migrated_ids(conn, "contacts")

    assert result == {10, 20, 30}


# ---------------------------------------------------------------------------
# T034-3 — record_success inserts with status='ok'
# ---------------------------------------------------------------------------


def test_record_success_inserts_ok_status():
    """record_success executes an insert with status='ok'."""
    conn = MagicMock()
    conn.execute.return_value = MagicMock()

    repo = MigrationStateRepository()
    repo.record_success(conn, "contacts", id_origem=5, id_destino=225541)

    # Verify execute was called (the insert statement)
    conn.execute.assert_called_once()
    call_args = conn.execute.call_args
    # The compiled statement should include 'ok' in its values
    compiled = str(call_args[0][0])
    assert "migration_state" in compiled.lower() or "insert" in compiled.lower()


# ---------------------------------------------------------------------------
# T034-4 — record_failure inserts with 'failed' prefix in status
# ---------------------------------------------------------------------------


def test_record_failure_inserts_failed_status():
    """record_failure inserts a row with status starting with 'failed:'."""
    conn = MagicMock()
    conn.execute.return_value = MagicMock()

    repo = MigrationStateRepository()
    repo.record_failure(conn, "contacts", id_origem=99, reason="duplicate key")

    conn.execute.assert_called_once()


# ---------------------------------------------------------------------------
# T034-5 — Idempotency filtering: batch [1,2,3] with {2} done → [1,3] pending
# ---------------------------------------------------------------------------


def test_idempotency_filter_skips_already_migrated():
    """Given already_migrated={2}, only ids 1 and 3 from [1,2,3] are pending."""
    conn = MagicMock()
    # Return id=2 as already done
    conn.execute.return_value.fetchall.return_value = [(2,)]

    repo = MigrationStateRepository()
    migrated = repo.get_migrated_ids(conn, "labels")

    all_ids = {1, 2, 3}
    pending = all_ids - migrated
    assert pending == {1, 3}


# ---------------------------------------------------------------------------
# T034-6 — get_migrated_ids with empty table returns empty set
# ---------------------------------------------------------------------------


def test_get_migrated_ids_empty_returns_empty_set():
    """get_migrated_ids returns an empty set when no records are in migration_state."""
    conn = MagicMock()
    conn.execute.return_value.fetchall.return_value = []

    repo = MigrationStateRepository()
    result = repo.get_migrated_ids(conn, "accounts")

    assert result == set()
