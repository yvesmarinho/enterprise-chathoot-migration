"""Unit tests for MessagesMigrator (T032)."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

from src.migrators.base_migrator import MigrationResult
from src.migrators.messages_migrator import MessagesMigrator
from src.repository.migration_state_repository import MigrationStateRepository
from src.utils.id_remapper import IDRemapper


def _make_migrator(source_rows=None, migrated=None):
    source_rows = source_rows or []
    migrated = migrated or {}

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
        migrated.get("accounts", {1}),
        migrated.get("conversations", {1}),
        migrated.get("users", {1}),
        set(),  # already_migrated messages
    ]

    remapper = IDRemapper(
        {
            "messages": 1302949,
            "accounts": 20,
            "conversations": 153582,
            "users": 294,
        }
    )
    logger = logging.getLogger("test_messages")

    return MessagesMigrator(
        source_engine=source_engine,
        dest_engine=dest_engine,
        id_remapper=remapper,
        state_repo=state_repo,
        logger=logger,
    )


def _base_row(**overrides):
    base = {
        "id": 1,
        "account_id": 1,
        "conversation_id": 1,
        "sender_id": None,
        "content": "Hello",
        "content_attributes": None,
        "created_at": None,
        "updated_at": None,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# T032-1 — Orphan conversation_id → record skipped
# ---------------------------------------------------------------------------


def test_messages_orphan_conversation_id_skips():
    """Messages with orphan conversation_id are skipped."""
    rows = [_base_row(conversation_id=9999)]
    remapped = []

    def capture(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=0, skipped=1)

    migrator = _make_migrator(source_rows=rows, migrated={"conversations": {1, 2}})
    with patch.object(migrator, "_run_batches", side_effect=capture):
        with patch("src.migrators.messages_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert remapped == []


# ---------------------------------------------------------------------------
# T032-2 — sender_id NULLed-out when user not migrated
# ---------------------------------------------------------------------------


def test_messages_sender_id_nulled_when_unmigrated():
    """sender_id is set to NULL when the user was not migrated."""
    rows = [_base_row(sender_id=888)]  # user 888 not migrated
    remapped = []

    def capture(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    migrator = _make_migrator(source_rows=rows, migrated={"users": {1, 2}})
    with patch.object(migrator, "_run_batches", side_effect=capture):
        with patch("src.migrators.messages_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert remapped[0]["sender_id"] is None


# ---------------------------------------------------------------------------
# T032-3 — FK remapping for all columns
# ---------------------------------------------------------------------------


def test_messages_fk_remapping():
    """id, account_id, conversation_id, sender_id all remapped correctly."""
    rows = [_base_row(id=10, account_id=1, conversation_id=1, sender_id=1)]
    remapped = []

    def capture(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    migrator = _make_migrator(source_rows=rows)
    with patch.object(migrator, "_run_batches", side_effect=capture):
        with patch("src.migrators.messages_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    r = remapped[0]
    assert r["id"] == 10 + 1302949
    assert r["account_id"] == 1 + 20
    assert r["conversation_id"] == 1 + 153582
    assert r["sender_id"] == 1 + 294
