"""Unit tests for MentionsMigrator (T030)."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

from src.migrators.base_migrator import MigrationResult
from src.migrators.mentions_migrator import MentionsMigrator
from src.repository.migration_state_repository import MigrationStateRepository
from src.utils.id_remapper import IDRemapper


def _make_migrator(
    source_rows=None, migrated_accounts=None, migrated_conversations=None, migrated_users=None
):
    source_rows = source_rows or []
    migrated_accounts = migrated_accounts if migrated_accounts is not None else {1}
    migrated_conversations = migrated_conversations if migrated_conversations is not None else {100}
    migrated_users = migrated_users if migrated_users is not None else {42}

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
    state_repo.get_migrated_ids.side_effect = [
        migrated_accounts,
        migrated_conversations,
        migrated_users,
    ]

    remapper = IDRemapper({"mentions": 500, "accounts": 20, "conversations": 100, "users": 50})
    logger = logging.getLogger("test_mentions")

    return MentionsMigrator(
        source_engine=source_engine,
        dest_engine=dest_engine,
        id_remapper=remapper,
        state_repo=state_repo,
        logger=logger,
    )


# ---------------------------------------------------------------------------
# T030-1 — Mentions with valid FKs are migrated
# ---------------------------------------------------------------------------


def test_mentions_valid_fks_migrated():
    """Mentions with valid account_id, conversation_id, user_id are migrated."""
    rows = [
        {
            "id": 1,
            "account_id": 1,
            "conversation_id": 100,
            "user_id": 42,
            "mentioned_at": "2026-05-28 10:00:00",
            "created_at": "2026-05-28 10:00:00",
            "updated_at": "2026-05-28 10:00:00",
        }
    ]
    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    migrator = _make_migrator(
        source_rows=rows,
        migrated_accounts={1},
        migrated_conversations={100},
        migrated_users={42},
    )
    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.mentions_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert len(remapped_rows) == 1
    assert remapped_rows[0]["id"] == 501  # 1 + offset 500
    assert remapped_rows[0]["account_id"] == 21  # 1 + offset 20
    assert remapped_rows[0]["conversation_id"] == 200  # 100 + offset 100
    assert remapped_rows[0]["user_id"] == 92  # 42 + offset 50


# ---------------------------------------------------------------------------
# T030-2 — Mention with orphan account_id is skipped
# ---------------------------------------------------------------------------


def test_mentions_orphan_account_id_skipped():
    """Mention with unmigrated account_id is skipped (returns None)."""
    rows = [
        {
            "id": 1,
            "account_id": 999,  # unmigrated
            "conversation_id": 100,
            "user_id": 42,
            "mentioned_at": "2026-05-28 10:00:00",
            "created_at": "2026-05-28 10:00:00",
            "updated_at": "2026-05-28 10:00:00",
        }
    ]
    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=0, skipped=1)

    migrator = _make_migrator(
        source_rows=rows,
        migrated_accounts={1},
        migrated_conversations={100},
        migrated_users={42},
    )
    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.mentions_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert len(remapped_rows) == 0


# ---------------------------------------------------------------------------
# T030-3 — Mention with orphan conversation_id is skipped
# ---------------------------------------------------------------------------


def test_mentions_orphan_conversation_id_skipped():
    """Mention with unmigrated conversation_id is skipped (returns None)."""
    rows = [
        {
            "id": 1,
            "account_id": 1,
            "conversation_id": 999,  # unmigrated
            "user_id": 42,
            "mentioned_at": "2026-05-28 10:00:00",
            "created_at": "2026-05-28 10:00:00",
            "updated_at": "2026-05-28 10:00:00",
        }
    ]
    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=0, skipped=1)

    migrator = _make_migrator(
        source_rows=rows,
        migrated_accounts={1},
        migrated_conversations={100},
        migrated_users={42},
    )
    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.mentions_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert len(remapped_rows) == 0


# ---------------------------------------------------------------------------
# T030-4 — Mention with orphan user_id is skipped
# ---------------------------------------------------------------------------


def test_mentions_orphan_user_id_skipped():
    """Mention with unmigrated user_id is skipped (returns None)."""
    rows = [
        {
            "id": 1,
            "account_id": 1,
            "conversation_id": 100,
            "user_id": 999,  # unmigrated
            "mentioned_at": "2026-05-28 10:00:00",
            "created_at": "2026-05-28 10:00:00",
            "updated_at": "2026-05-28 10:00:00",
        }
    ]
    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=0, skipped=1)

    migrator = _make_migrator(
        source_rows=rows,
        migrated_accounts={1},
        migrated_conversations={100},
        migrated_users={42},
    )
    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.mentions_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert len(remapped_rows) == 0
