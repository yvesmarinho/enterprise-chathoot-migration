"""Unit tests for TeamsMigrator (T028)."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

from src.migrators.base_migrator import MigrationResult
from src.migrators.teams_migrator import TeamsMigrator
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

    remapper = IDRemapper({"teams": 22, "accounts": 20})
    logger = logging.getLogger("test_teams")

    return TeamsMigrator(
        source_engine=source_engine,
        dest_engine=dest_engine,
        id_remapper=remapper,
        state_repo=state_repo,
        logger=logger,
    )


# ---------------------------------------------------------------------------
# T028-1 — account_id is remapped correctly
# ---------------------------------------------------------------------------


def test_teams_account_id_remapped():
    """account_id is remapped with offset_accounts during migration."""
    rows = [
        {
            "id": 2,
            "account_id": 1,
            "name": "Support Team",
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
        with patch("src.migrators.teams_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert remapped_rows[0]["account_id"] == 21  # 1 + 20
    assert remapped_rows[0]["id"] == 24  # 2 + 22


# ---------------------------------------------------------------------------
# T028-2 — 3 source records produce 1 batch (< 500)
# ---------------------------------------------------------------------------


def test_teams_small_volume_single_batch():
    """3 teams produce exactly 1 batch (all fit under batch size 500)."""
    rows = [
        {
            "id": i,
            "account_id": 1,
            "name": f"Team {i}",
            "created_at": None,
            "updated_at": None,
        }
        for i in range(1, 4)
    ]
    batches_processed = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        batches_processed.append(len(source_rows))
        return MigrationResult(
            table=table_name,
            total_source=len(source_rows),
            migrated=len(source_rows),
            skipped=0,
        )

    migrator = _make_migrator(source_rows=rows, migrated_accounts={1})
    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.teams_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert batches_processed == [3]  # all 3 rows passed to _run_batches at once
