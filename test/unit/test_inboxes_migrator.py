"""Unit tests for InboxesMigrator (T026)."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

from src.migrators.base_migrator import MigrationResult
from src.migrators.inboxes_migrator import InboxesMigrator
from src.repository.migration_state_repository import MigrationStateRepository
from src.utils.id_remapper import IDRemapper


def _make_migrator(source_rows=None, already_migrated=None, migrated_accounts=None):
    source_rows = source_rows or []
    already_migrated = already_migrated or set()
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
    # First call returns migrated_accounts, second returns already_migrated (for _run_batches)
    state_repo.get_migrated_ids.side_effect = [migrated_accounts, already_migrated]

    remapper = IDRemapper({"inboxes": 151, "accounts": 20})
    logger = logging.getLogger("test_inboxes")

    return InboxesMigrator(
        source_engine=source_engine,
        dest_engine=dest_engine,
        id_remapper=remapper,
        state_repo=state_repo,
        logger=logger,
    )


# ---------------------------------------------------------------------------
# T026-1 — account_id is remapped with offset_accounts
# ---------------------------------------------------------------------------


def test_inboxes_account_id_remapped():
    """account_id is remapped with offset_accounts (20) during migration."""
    rows = [
        {
            "id": 3,
            "account_id": 1,
            "name": "Inbox A",
            "channel_type": "Channel::Email",
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
        with patch("src.migrators.inboxes_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert len(remapped_rows) == 1
    assert remapped_rows[0]["account_id"] == 21  # 1 + 20
    assert remapped_rows[0]["id"] == 154  # 3 + 151


# ---------------------------------------------------------------------------
# T026-2 — Orphan account_id → record skipped, not inserted
# ---------------------------------------------------------------------------


def test_inboxes_orphan_account_id_skipped():
    """Records with unmigrated account_id are skipped (remap_fn returns None)."""
    rows = [
        {
            "id": 5,
            "account_id": 999,
            "name": "Orphan Inbox",
            "channel_type": "Channel::Email",
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
        return MigrationResult(table=table_name, total_source=1, migrated=0, skipped=1)

    migrator = _make_migrator(source_rows=rows, migrated_accounts={1, 2, 3})
    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.inboxes_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert remapped_rows == []
