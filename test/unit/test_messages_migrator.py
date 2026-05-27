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
    
    def get_migrated_ids_side_effect(conn, table_name):
        return migrated.get(table_name, {1} if table_name != "contacts" else {1})
    
    state_repo.get_migrated_ids.side_effect = get_migrated_ids_side_effect

    remapper = IDRemapper(
        {
            "messages": 1302949,
            "accounts": 20,
            "conversations": 153582,
            "users": 294,
            "contacts": 225536,
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


# ---------------------------------------------------------------------------
# T032-4 — sender_type='Contact' with migrated contact
# ---------------------------------------------------------------------------


def test_messages_sender_type_contact_remapped():
    """Message with sender_type='Contact' and valid contact remaps via contacts offset."""
    rows = [_base_row(id=11, sender_id=1, sender_type="Contact")]
    remapped = []

    def capture(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    migrator = _make_migrator(
        source_rows=rows,
        migrated={"accounts": {1}, "conversations": {1}, "contacts": {1}},
    )
    with patch.object(migrator, "_run_batches", side_effect=capture):
        with patch("src.migrators.messages_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    # sender_id should be remapped via contacts offset (not users)
    assert remapped[0]["sender_id"] != 1 + 294  # not users offset


# ---------------------------------------------------------------------------
# T032-5 — sender_type='User' with unmigrated user → NULL-out
# ---------------------------------------------------------------------------


def test_messages_sender_type_user_unmigrated_nulled():
    """Message with sender_type='User' but unmigrated user sets sender_id=NULL."""
    rows = [_base_row(id=12, sender_id=999, sender_type="User")]
    remapped = []

    def capture(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    migrator = _make_migrator(
        source_rows=rows,
        migrated={"accounts": {1}, "conversations": {1}, "users": {1, 2, 3}},
    )
    with patch.object(migrator, "_run_batches", side_effect=capture):
        with patch("src.migrators.messages_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert remapped[0]["sender_id"] is None


# ---------------------------------------------------------------------------
# T032-6 — sender_type='AgentBot' (unknown) → NULL-out
# ---------------------------------------------------------------------------


def test_messages_sender_type_agentbot_nulled():
    """Message with sender_type='AgentBot' (unknown type) sets sender_id=NULL."""
    rows = [_base_row(id=13, sender_id=999, sender_type="AgentBot")]
    remapped = []

    def capture(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    migrator = _make_migrator(
        source_rows=rows,
        migrated={"accounts": {1}, "conversations": {1}, "users": {1}},
    )
    with patch.object(migrator, "_run_batches", side_effect=capture):
        with patch("src.migrators.messages_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert remapped[0]["sender_id"] is None


# ---------------------------------------------------------------------------
# T032-7 — NULL sender_id (no remapping needed)
# ---------------------------------------------------------------------------


def test_messages_null_sender_id_unchanged():
    """Message with NULL sender_id passes through unchanged (no FK check)."""
    rows = [_base_row(id=14, sender_id=None, sender_type="User")]
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

    assert remapped[0]["sender_id"] is None


# ---------------------------------------------------------------------------
# T032-8 — Orphan account_id (required FK) → skipped
# ---------------------------------------------------------------------------


def test_messages_orphan_account_id_skipped():
    """Message with unmigrated account_id is skipped (required FK)."""
    rows = [_base_row(id=15, account_id=999)]
    remapped = []

    def capture(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=0, skipped=1)

    migrator = _make_migrator(
        source_rows=rows,
        migrated={"accounts": {1, 2}, "conversations": {1}},
    )
    with patch.object(migrator, "_run_batches", side_effect=capture):
        with patch("src.migrators.messages_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert len(remapped) == 0
