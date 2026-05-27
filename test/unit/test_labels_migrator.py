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
            with patch(
                "src.migrators.labels_migrator.ensure_public_table_exists"
            ) as mock_bootstrap:
                migrator.migrate()
                # Bootstrap should have been called
                mock_bootstrap.assert_called_once()


# ---------------------------------------------------------------------------
# T029-9 — Title field preserved during migration
# ---------------------------------------------------------------------------


def test_labels_title_preserved():
    """Title field is copied unchanged to destination."""
    title = "bug_report"
    rows = [
        {
            "id": 50,
            "account_id": 1,
            "title": title,
            "color": "#FF5733",
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
        with patch("src.migrators.labels_migrator.Table"):
            migrator.migrate()

    assert len(remapped_rows) == 1
    assert remapped_rows[0]["title"] == title


# ---------------------------------------------------------------------------
# T029-10 — Color field preserved during migration
# ---------------------------------------------------------------------------


def test_labels_color_preserved():
    """Color hex code is preserved as-is."""
    color = "#00FF00"
    rows = [
        {
            "id": 51,
            "account_id": 1,
            "title": "success",
            "color": color,
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
        with patch("src.migrators.labels_migrator.Table"):
            migrator.migrate()

    assert len(remapped_rows) == 1
    assert remapped_rows[0]["color"] == color


# ---------------------------------------------------------------------------
# T029-11 — Multiple labels multiple accounts
# ---------------------------------------------------------------------------


def test_labels_multiple_accounts_all_migrated():
    """Labels from multiple accounts all migrated successfully."""
    rows = [
        {
            "id": 52,
            "account_id": 1,
            "title": "label1",
            "color": "#AA0000",
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 53,
            "account_id": 2,
            "title": "label2",
            "color": "#00AA00",
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 54,
            "account_id": 3,
            "title": "label3",
            "color": "#0000AA",
            "created_at": None,
            "updated_at": None,
        },
    ]

    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=3, migrated=3, skipped=0)

    migrator = _make_migrator(source_rows=rows, migrated_accounts={1, 2, 3})
    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.labels_migrator.Table"):
            migrator.migrate()

    # All 3 labels should be migrated
    assert len(remapped_rows) == 3
    # Account IDs should be remapped
    assert remapped_rows[0]["account_id"] == 21
    assert remapped_rows[1]["account_id"] == 22
    assert remapped_rows[2]["account_id"] == 23


# ---------------------------------------------------------------------------
# T029-12 — Empty source no-op
# ---------------------------------------------------------------------------


def test_labels_empty_source_no_migration():
    """Empty source returns MigrationResult with 0 migrated/skipped."""
    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=0, migrated=0, skipped=0)

    migrator = _make_migrator(source_rows=[], migrated_accounts={1})
    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.labels_migrator.Table"):
            result = migrator.migrate()

    assert len(remapped_rows) == 0
    assert result.migrated == 0
    assert result.skipped == 0


# ---------------------------------------------------------------------------
# T029-13 — ID remapping with offset
# ---------------------------------------------------------------------------


def test_labels_id_remapping_offset():
    """Label ID is remapped using offset_labels."""
    rows = [
        {
            "id": 100,
            "account_id": 1,
            "title": "remote_label",
            "color": "#123456",
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
        with patch("src.migrators.labels_migrator.Table"):
            migrator.migrate()

    # ID should be remapped: 100 + 184 (offset_labels)
    assert len(remapped_rows) == 1
    assert remapped_rows[0]["id"] == 100 + 184


# ---------------------------------------------------------------------------
# T029-14 — Multiple labels same account different colors
# ---------------------------------------------------------------------------


def test_labels_multiple_same_account_different_colors():
    """Multiple labels for same account with different colors all migrated."""
    rows = [
        {
            "id": 101,
            "account_id": 1,
            "title": "urgent",
            "color": "#FF0000",
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 102,
            "account_id": 1,
            "title": "medium",
            "color": "#FFFF00",
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 103,
            "account_id": 1,
            "title": "low",
            "color": "#00FF00",
            "created_at": None,
            "updated_at": None,
        },
    ]

    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=3, migrated=3, skipped=0)

    migrator = _make_migrator(source_rows=rows, migrated_accounts={1})
    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.labels_migrator.Table"):
            migrator.migrate()

    assert len(remapped_rows) == 3
    assert remapped_rows[0]["color"] == "#FF0000"
    assert remapped_rows[1]["color"] == "#FFFF00"
    assert remapped_rows[2]["color"] == "#00FF00"


# ---------------------------------------------------------------------------
# T029-15 — Label title with special characters preserved
# ---------------------------------------------------------------------------


def test_labels_title_with_special_characters():
    """Label title with special characters (spaces, dashes, etc.) is preserved."""
    special_title = "Bug Report - High Priority!!!"
    rows = [
        {
            "id": 104,
            "account_id": 1,
            "title": special_title,
            "color": "#FF6600",
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
        with patch("src.migrators.labels_migrator.Table"):
            migrator.migrate()

    assert len(remapped_rows) == 1
    assert remapped_rows[0]["title"] == special_title


# ---------------------------------------------------------------------------
# T029-16 — Multiple orphan accounts all skipped
# ---------------------------------------------------------------------------


def test_labels_multiple_orphan_accounts_all_skipped():
    """Labels with multiple different orphan accounts are all skipped."""
    rows = [
        {
            "id": 105,
            "account_id": 999,
            "title": "orphan1",
            "color": "#AAAAAA",
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 106,
            "account_id": 888,
            "title": "orphan2",
            "color": "#BBBBBB",
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 107,
            "account_id": 777,
            "title": "orphan3",
            "color": "#CCCCCC",
            "created_at": None,
            "updated_at": None,
        },
    ]

    remapped_rows = []
    skipped_ids = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
            else:
                skipped_ids.append(row["id"])
        return MigrationResult(table=table_name, total_source=3, migrated=0, skipped=3)

    migrator = _make_migrator(source_rows=rows, migrated_accounts={1})
    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.labels_migrator.Table"):
            migrator.migrate()

    assert len(remapped_rows) == 0
    assert len(skipped_ids) == 3
    assert 105 in skipped_ids
    assert 106 in skipped_ids
    assert 107 in skipped_ids


# ---------------------------------------------------------------------------
# T029-17 — Multiple with mixed valid and orphan
# ---------------------------------------------------------------------------


def test_labels_multiple_mixed_valid_orphan():
    """Multiple labels: mix of valid and orphan accounts only valid migrated."""
    rows = [
        {
            "id": 108,
            "account_id": 1,
            "title": "valid1",
            "color": "#111111",
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 109,
            "account_id": 999,
            "title": "orphan",
            "color": "#222222",
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 110,
            "account_id": 2,
            "title": "valid2",
            "color": "#333333",
            "created_at": None,
            "updated_at": None,
        },
    ]

    remapped_rows = []
    skipped_ids = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
            else:
                skipped_ids.append(row["id"])
        return MigrationResult(table=table_name, total_source=3, migrated=2, skipped=1)

    migrator = _make_migrator(source_rows=rows, migrated_accounts={1, 2})
    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.labels_migrator.Table"):
            migrator.migrate()

    assert len(remapped_rows) == 2
    assert len(skipped_ids) == 1
    assert 109 in skipped_ids


# ---------------------------------------------------------------------------
# POC Helper Methods — _table_name, _fetch_all_source_rows, _classify_row_poc
# ---------------------------------------------------------------------------


def test_labels_table_name():
    """_table_name() returns 'labels'."""
    migrator = _make_migrator()
    assert migrator._table_name() == "labels"


def test_labels_fetch_all_source_rows():
    """_fetch_all_source_rows() fetches and reflects all rows."""
    rows = [
        {"id": 1, "account_id": 1, "title": "Urgent"},
        {"id": 2, "account_id": 1, "title": "Follow-up"},
    ]
    migrator = _make_migrator(source_rows=rows)

    with patch("src.migrators.labels_migrator.Table") as mock_table:
        mock_table_inst = MagicMock()
        mock_table.return_value = mock_table_inst
        result = migrator._fetch_all_source_rows()

    assert len(result) == 2
    assert result[0]["id"] == 1
    assert result[1]["title"] == "Follow-up"


def test_labels_classify_row_poc_clean():
    """_classify_row_poc returns WOULD_MIGRATE for clean row."""
    from src.reports.poc_reporter import Outcome

    migrator = _make_migrator()
    row = {"account_id": 1}
    migrated_sets = {"accounts": {1}}

    outcome, reason = migrator._classify_row_poc(row, migrated_sets)

    assert outcome == Outcome.WOULD_MIGRATE
    assert reason == "clean"
