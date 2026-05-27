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


# ---------------------------------------------------------------------------
# T016-3 — name field preserved
# ---------------------------------------------------------------------------


def test_inboxes_name_preserved():
    """name field is copied as-is without modification."""
    inbox_name = "support_emails"
    rows = [
        {
            "id": 6,
            "account_id": 1,
            "name": inbox_name,
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
        with patch("src.migrators.inboxes_migrator.Table"):
            migrator.migrate()

    assert remapped_rows[0]["name"] == inbox_name


# ---------------------------------------------------------------------------
# T016-4 — channel_type preserved (polymorphic channels)
# ---------------------------------------------------------------------------


def test_inboxes_channel_type_preserved():
    """channel_type string is copied as-is (polymorphic: Email, Api, WebWidget, etc)."""
    channel_type = "Channel::Api"
    rows = [
        {
            "id": 7,
            "account_id": 2,
            "name": "api_inbox",
            "channel_type": channel_type,
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

    migrator = _make_migrator(source_rows=rows, migrated_accounts={1, 2})
    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.inboxes_migrator.Table"):
            migrator.migrate()

    assert remapped_rows[0]["channel_type"] == channel_type


# ---------------------------------------------------------------------------
# T016-5 — Mixed accounts with partial skip
# ---------------------------------------------------------------------------


def test_inboxes_mixed_accounts_partial_skip():
    """Inboxes from multiple accounts skip only orphaned ones."""
    rows = [
        {
            "id": 8,
            "account_id": 1,
            "name": "acct1_inbox",
            "channel_type": "Channel::Email",
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 9,
            "account_id": 2,
            "name": "acct2_inbox",
            "channel_type": "Channel::WebWidget",
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 10,
            "account_id": 999,
            "name": "orphan_inbox",
            "channel_type": "Channel::Email",
            "created_at": None,
            "updated_at": None,
        },
    ]
    remapped_rows = []
    skipped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
            else:
                skipped_rows.append(row["id"])
        return MigrationResult(table=table_name, total_source=3, migrated=2, skipped=1)

    migrator = _make_migrator(source_rows=rows, migrated_accounts={1, 2})
    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.inboxes_migrator.Table"):
            migrator.migrate()

    assert len(remapped_rows) == 2
    assert len(skipped_rows) == 1
    assert 10 in skipped_rows


# ---------------------------------------------------------------------------
# T026-6 — channel_id remapped and preserved when in channel_id_map
# ---------------------------------------------------------------------------


def test_inboxes_channel_id_remapped():
    """channel_id is remapped when present in channel_id_map."""
    rows = [
        {
            "id": 11,
            "account_id": 1,
            "name": "inbox_with_channel",
            "channel_type": "Channel::WebWidget",
            "channel_id": 5,
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
    
    # Mock _migrate_channels to return a channel_id_map
    channel_id_map = {("Channel::WebWidget", 5): 100}
    
    with patch.object(migrator, "_migrate_channels", return_value=channel_id_map):
        with patch.object(migrator, "_run_batches", side_effect=capture_batches):
            with patch("src.migrators.inboxes_migrator.Table"):
                migrator.migrate()

    assert len(remapped_rows) == 1
    assert remapped_rows[0]["channel_id"] == 100


# ---------------------------------------------------------------------------
# T026-7 — channel_id preserved as SOURCE when not in channel_id_map
# ---------------------------------------------------------------------------


def test_inboxes_channel_id_kept_when_unmapped():
    """channel_id is kept as SOURCE value when not found in channel_id_map."""
    rows = [
        {
            "id": 12,
            "account_id": 1,
            "name": "inbox_unmapped_channel",
            "channel_type": "Channel::Api",
            "channel_id": 999,
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
    
    # Empty channel_id_map — channel_id 999 not present
    channel_id_map = {("Channel::Api", 1): 50}  # different id
    
    with patch.object(migrator, "_migrate_channels", return_value=channel_id_map):
        with patch.object(migrator, "_run_batches", side_effect=capture_batches):
            with patch("src.migrators.inboxes_migrator.Table"):
                migrator.migrate()

    assert len(remapped_rows) == 1
    # channel_id kept as SOURCE value (999)
    assert remapped_rows[0]["channel_id"] == 999


# ---------------------------------------------------------------------------
# T026-8 — channel_id None or missing (no channel)
# ---------------------------------------------------------------------------


def test_inboxes_channel_id_none_unchanged():
    """Inbox with no channel (channel_id=None) is migrated as-is."""
    rows = [
        {
            "id": 13,
            "account_id": 1,
            "name": "no_channel_inbox",
            "channel_type": None,
            "channel_id": None,
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
    
    with patch.object(migrator, "_migrate_channels", return_value={}):
        with patch.object(migrator, "_run_batches", side_effect=capture_batches):
            with patch("src.migrators.inboxes_migrator.Table"):
                migrator.migrate()

    assert len(remapped_rows) == 1
    assert remapped_rows[0]["channel_id"] is None
