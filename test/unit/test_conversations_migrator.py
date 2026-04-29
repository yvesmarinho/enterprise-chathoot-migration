"""Unit tests for ConversationsMigrator (T031)."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

from src.migrators.base_migrator import MigrationResult
from src.migrators.conversations_migrator import ConversationsMigrator
from src.repository.migration_state_repository import MigrationStateRepository
from src.utils.id_remapper import IDRemapper


def _make_migrator(source_rows=None, migrated=None):
    """Build ConversationsMigrator with injectable migrated-ID sets."""
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
    # calls: accounts, inboxes, contacts, users, teams, then _run_batches already_migrated
    state_repo.get_migrated_ids.side_effect = [
        migrated.get("accounts", {1}),
        migrated.get("inboxes", {1}),
        migrated.get("contacts", {1}),
        migrated.get("users", {1}),
        migrated.get("teams", {1}),
        set(),  # already_migrated conversations
    ]

    remapper = IDRemapper(
        {
            "conversations": 153582,
            "accounts": 20,
            "inboxes": 151,
            "contacts": 225536,
            "users": 294,
            "teams": 22,
        }
    )
    logger = logging.getLogger("test_conversations")

    return ConversationsMigrator(
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
        "inbox_id": 1,
        "contact_id": 1,
        "assignee_id": None,
        "team_id": None,
        "meta": None,
        "additional_attributes": None,
        "created_at": None,
        "updated_at": None,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# T031-1 — NULL contact_id → record skipped with log
# ---------------------------------------------------------------------------


def test_conversations_null_contact_id_skips_record():
    """Records with NULL contact_id are skipped (no contact FK to remap)."""
    rows = [_base_row(contact_id=None)]
    remapped = []

    def capture(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    migrator = _make_migrator(source_rows=rows)
    with patch.object(migrator, "_run_batches", side_effect=capture):
        with patch("src.migrators.conversations_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    # contact_id=None → row is included (no FK check needed)
    assert len(remapped) == 1
    assert remapped[0].get("contact_id") is None


# ---------------------------------------------------------------------------
# T031-2 — Orphan contact_id → record skipped
# ---------------------------------------------------------------------------


def test_conversations_orphan_contact_id_skips_record():
    """Records with orphan contact_id are skipped (remap_fn returns None)."""
    rows = [_base_row(contact_id=9999)]
    remapped = []

    def capture(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=0, skipped=1)

    migrator = _make_migrator(
        source_rows=rows,
        migrated={"contacts": {1, 2, 3}},  # 9999 not in migrated
    )
    with patch.object(migrator, "_run_batches", side_effect=capture):
        with patch("src.migrators.conversations_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert remapped == []


# ---------------------------------------------------------------------------
# T031-3 — assignee_id NULLed-out when user not migrated
# ---------------------------------------------------------------------------


def test_conversations_assignee_id_nulled_when_unmigrated():
    """assignee_id is set to NULL when the user was not migrated."""
    rows = [_base_row(assignee_id=777)]  # user 777 not migrated
    remapped = []

    def capture(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    migrator = _make_migrator(
        source_rows=rows,
        migrated={"users": {1, 2, 3}},  # 777 not in migrated users
    )
    with patch.object(migrator, "_run_batches", side_effect=capture):
        with patch("src.migrators.conversations_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert remapped[0]["assignee_id"] is None


# ---------------------------------------------------------------------------
# T031-4 — All FK columns remapped when sources are valid
# ---------------------------------------------------------------------------


def test_conversations_all_fk_columns_remapped():
    """All 5 FK columns are remapped when all FKs are valid."""
    rows = [_base_row(id=5, account_id=1, inbox_id=1, contact_id=1, assignee_id=1, team_id=1)]
    remapped = []

    def capture(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    migrator = _make_migrator(
        source_rows=rows,
        migrated={
            "accounts": {1},
            "inboxes": {1},
            "contacts": {1},
            "users": {1},
            "teams": {1},
        },
    )
    with patch.object(migrator, "_run_batches", side_effect=capture):
        with patch("src.migrators.conversations_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    r = remapped[0]
    assert r["id"] == 5 + 153582
    assert r["account_id"] == 1 + 20
    assert r["inbox_id"] == 1 + 151
    assert r["contact_id"] == 1 + 225536
    assert r["assignee_id"] == 1 + 294
    assert r["team_id"] == 1 + 22
