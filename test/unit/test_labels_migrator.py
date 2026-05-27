"""Unit tests for LabelsMigrator (T029)."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

from src.migrators.base_migrator import MigrationResult
from src.migrators.labels_migrator import LabelsMigrator
from src.repository.migration_state_repository import MigrationStateRepository
from src.utils.id_remapper import IDRemapper


def _make_migrator(source_rows=None, migrated_accounts=None):
    source_rows = source_rows or []
    migrated_accounts = migrated_accounts if migrated_accounts is not None else {1}

    source_engine = MagicMock()
    dest_engine = MagicMock()

    src_conn = MagicMock()
    src_conn.__enter__ = MagicMock(return_value=src_conn)
    src_conn.__exit__ = MagicMock(return_value=False)
    src_conn.execute.return_value.mappings.return_value.all.return_value = source_rows
    source_engine.connect.return_value = src_conn

    dest_conn = MagicMock()
    dest_conn.__enter__ = MagicMock(return_value=dest_conn)
    dest_conn.__exit__ = MagicMock(return_value=False)
    dest_conn.begin.return_value.__enter__ = MagicMock(return_value=None)
    dest_conn.begin.return_value.__exit__ = MagicMock(return_value=False)
    dest_engine.connect.return_value = dest_conn

    state_repo = MagicMock(spec=MigrationStateRepository)
    state_repo.get_migrated_ids.side_effect = [migrated_accounts, set()]

    remapper = IDRemapper({"labels": 184, "accounts": 20})
    logger = logging.getLogger("test_labels")

    return LabelsMigrator(
        source_engine=source_engine,
        dest_engine=dest_engine,
        id_remapper=remapper,
        state_repo=state_repo,
        logger=logger,
    )


# ---------------------------------------------------------------------------
# T029-1 — account_id is remapped with offset_accounts
# ---------------------------------------------------------------------------


def test_labels_account_id_remapped():
    """account_id is remapped with offset_accounts during migration."""
    rows = [
        {
            "id": 5,
            "account_id": 1,
            "title": "urgent",
            "color": "#FF0000",
            "created_at": None,
            "updated_at": None,
        }
    ]
    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    migrator = _make_migrator(source_rows=rows, migrated_accounts={1})
    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.labels_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert remapped_rows[0]["account_id"] == 21  # 1 + 20
    assert remapped_rows[0]["id"] == 189  # 5 + 184


# ---------------------------------------------------------------------------
# T029-2 — 32 source records fit in 1 batch
# ---------------------------------------------------------------------------


def test_labels_32_records_single_batch():
    """32 label records produce a single call to _run_batches with all 32 rows."""
    rows = [
        {
            "id": i,
            "account_id": 1,
            "title": f"label_{i}",
            "color": "#000000",
            "created_at": None,
            "updated_at": None,
        }
        for i in range(1, 33)
    ]
    called_with_count = []

    def capture(source_rows, table_name, dest_table, remap_fn):
        called_with_count.append(len(source_rows))
        return MigrationResult(table=table_name, total_source=32, migrated=32, skipped=0)

    migrator = _make_migrator(source_rows=rows, migrated_accounts={1})
    with patch.object(migrator, "_run_batches", side_effect=capture):
        with patch("src.migrators.labels_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert called_with_count == [32]


# ---------------------------------------------------------------------------
# T029-3 — Orphan account_id is skipped
# ---------------------------------------------------------------------------


def test_labels_orphan_account_id_skipped():
    """Label with unmigrated account_id is skipped."""
    rows = [
        {
            "id": 1,
            "account_id": 999,
            "title": "Orphan",
            "color": "#FF0000",
            "created_at": None,
            "updated_at": None,
        }
    ]
    remapped = []

    def capture(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=0, skipped=1)

    migrator = _make_migrator(source_rows=rows, migrated_accounts={1, 2})
    with patch.object(migrator, "_run_batches", side_effect=capture):
        with patch("src.migrators.labels_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert len(remapped) == 0


# ---------------------------------------------------------------------------
# T029-4 — Color field copied verbatim (no normalization)
# ---------------------------------------------------------------------------


def test_labels_color_field_unchanged():
    """Color field is copied as-is without modification."""
    original_color = "#AABBCC"
    rows = [
        {
            "id": 2,
            "account_id": 1,
            "title": "TestLabel",
            "color": original_color,
            "created_at": None,
            "updated_at": None,
        }
    ]
    remapped = []

    def capture(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    migrator = _make_migrator(source_rows=rows)
    with patch.object(migrator, "_run_batches", side_effect=capture):
        with patch("src.migrators.labels_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert remapped[0]["color"] == original_color


# ---------------------------------------------------------------------------
# T029-5 — Mixed account_ids with some orphaned
# ---------------------------------------------------------------------------


def test_labels_mixed_account_ids_partial_skip():
    """Labels with mixed account_ids skip only orphaned ones."""
    rows = [
        {
            "id": i,
            "account_id": 1 if i % 2 == 0 else 999,
            "title": f"label_{i}",
            "color": "#000000",
            "created_at": None,
            "updated_at": None,
        }
        for i in range(1, 6)
    ]
    remapped = []
    skipped = []

    def capture(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped.append(r)
            else:
                skipped.append(row["id"])
        return MigrationResult(table=table_name, total_source=5, migrated=2, skipped=3)

    migrator = _make_migrator(source_rows=rows, migrated_accounts={1})
    with patch.object(migrator, "_run_batches", side_effect=capture):
        with patch("src.migrators.labels_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert len(remapped) == 2
    assert len(skipped) == 3


# ---------------------------------------------------------------------------
# T029-6 — Empty source: no-op
# ---------------------------------------------------------------------------


def test_labels_empty_source_no_op():
    """When source has no rows, migration completes with 0 migrated."""
    migrator = _make_migrator(source_rows=[], migrated_accounts={1})

    result = None
    with patch("src.migrators.labels_migrator.Table"):
        result = migrator.migrate()

    assert result.total_source == 0
    assert result.migrated == 0
    assert result.skipped == 0


# ---------------------------------------------------------------------------
# T029-7 — title field preserved
# ---------------------------------------------------------------------------


def test_labels_title_field_preserved():
    """title field is copied as-is during migration."""
    test_title = "urgent-issues"
    rows = [
        {
            "id": 20,
            "account_id": 1,
            "title": test_title,
            "color": "#FF0000",
            "created_at": None,
            "updated_at": None,
        }
    ]
    remapped = []

    def capture(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    migrator = _make_migrator(source_rows=rows, migrated_accounts={1})
    with patch.object(migrator, "_run_batches", side_effect=capture):
        with patch("src.migrators.labels_migrator.Table"):
            migrator.migrate()

    assert len(remapped) == 1
    assert remapped[0]["title"] == test_title


# ---------------------------------------------------------------------------
# T029-8 — Bootstrap missing table
# ---------------------------------------------------------------------------


def test_labels_bootstrap_missing_dest_table():
    """When DEST table missing, bootstrap is triggered."""
    rows = [
        {
            "id": 21,
            "account_id": 1,
            "title": "test_label",
            "color": "#000000",
            "created_at": None,
            "updated_at": None,
        }
    ]
    remapped = []

    def capture(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    source_engine = MagicMock()
    dest_engine = MagicMock()

    src_conn = MagicMock()
    src_conn.__enter__ = MagicMock(return_value=src_conn)
    src_conn.__exit__ = MagicMock(return_value=False)
    src_conn.execute.return_value.mappings.return_value.all.return_value = rows
    source_engine.connect.return_value = src_conn

    dest_conn = MagicMock()
    dest_conn.__enter__ = MagicMock(return_value=dest_conn)
    dest_conn.__exit__ = MagicMock(return_value=False)
    dest_conn.begin.return_value.__enter__ = MagicMock(return_value=None)
    dest_conn.begin.return_value.__exit__ = MagicMock(return_value=False)
    dest_conn.execute.return_value.fetchall.return_value = []
    dest_engine.connect.return_value = dest_conn

    state_repo = MagicMock(spec=MigrationStateRepository)
    state_repo.get_migrated_ids.return_value = {1}

    remapper = IDRemapper({"labels": 50, "accounts": 20})
    logger = logging.getLogger("test_labels_bootstrap")

    migrator = LabelsMigrator(
        source_engine=source_engine,
        dest_engine=dest_engine,
        id_remapper=remapper,
        state_repo=state_repo,
        logger=logger,
    )

    with patch.object(migrator, "_run_batches", side_effect=capture):
        # Mock Table to raise NoSuchTableError on first call (dest), success on second
        call_count = [0]
        def table_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:  # src table
                return MagicMock()
            elif call_count[0] == 2:  # dest table — raise error
                from sqlalchemy.exc import NoSuchTableError
                raise NoSuchTableError("labels", "labels")
            else:  # after bootstrap
                return MagicMock()

        with patch("src.migrators.labels_migrator.Table", side_effect=table_side_effect):
            with patch("src.migrators.labels_migrator.ensure_public_table_exists") as mock_bootstrap:
                migrator.migrate()
                # Bootstrap should have been called
                mock_bootstrap.assert_called_once()
