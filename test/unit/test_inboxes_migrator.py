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


# ---------------------------------------------------------------------------
# T026-9 — channel_type preserved through migration
# ---------------------------------------------------------------------------


def test_inboxes_channel_type_field_preserved():
    """channel_type field is preserved without modification during migration."""
    rows = [
        {
            "id": 100,
            "account_id": 1,
            "name": "sales",
            "channel_type": "Channel::Email",
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
    assert remapped_rows[0]["channel_type"] == "Channel::Email"


# ---------------------------------------------------------------------------
# T026-10 — _migrate_channels: multiple channel types processed
# ---------------------------------------------------------------------------


def test_inboxes_migrate_channels_basic():
    """_migrate_channels collects and migrates channel records for inbox migration."""
    rows = [
        {
            "id": 101,
            "account_id": 1,
            "name": "web",
            "channel_type": "Channel::WebWidget",
            "channel_id": 50,
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 102,
            "account_id": 1,
            "name": "telegram",
            "channel_type": "Channel::Telegram",
            "channel_id": 51,
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
        return MigrationResult(table=table_name, total_source=2, migrated=2, skipped=0)

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

    # No merged accounts, so initial fetch returns empty
    dest_conn.execute.return_value.fetchall.return_value = []
    dest_engine.connect.return_value = dest_conn

    state_repo = MagicMock(spec=MigrationStateRepository)
    state_repo.get_migrated_ids.side_effect = [
        {1},  # accounts
        set(),  # already_migrated
    ]

    remapper = IDRemapper(
        {"inboxes": 151, "accounts": 20, "channel_web_widgets": 1000, "channel_telegram": 500}
    )
    logger = logging.getLogger("test_inboxes_migrate_channels")

    migrator = InboxesMigrator(
        source_engine=source_engine,
        dest_engine=dest_engine,
        id_remapper=remapper,
        state_repo=state_repo,
        logger=logger,
    )

    # Mock _migrate_channels to return a channel_id_map
    channel_map = {
        ("Channel::WebWidget", 50): 1050,
        ("Channel::Telegram", 51): 551,
    }

    with patch.object(migrator, "_migrate_channels", return_value=channel_map):
        with patch.object(migrator, "_run_batches", side_effect=capture_batches):
            with patch("src.migrators.inboxes_migrator.Table"):
                migrator.migrate()

    # Both rows should be remapped, channel_id updated
    assert len(remapped_rows) == 2
    assert remapped_rows[0]["channel_id"] == 1050
    assert remapped_rows[1]["channel_id"] == 551


# ---------------------------------------------------------------------------
# T026-11 — Unknown channel_type: logged, channel_id kept as-is
# ---------------------------------------------------------------------------


def test_inboxes_unknown_channel_type_not_migrated():
    """Unknown channel_type is logged with warning, channel_id not remapped."""
    rows = [
        {
            "id": 103,
            "account_id": 1,
            "name": "unknown_channel",
            "channel_type": "Channel::Unsupported",  # Unknown type
            "channel_id": 52,
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
    state_repo.get_migrated_ids.side_effect = [
        {1},  # accounts
        set(),  # already_migrated
    ]

    remapper = IDRemapper({"inboxes": 151, "accounts": 20})
    logger = logging.getLogger("test_inboxes_unknown_channel")

    migrator = InboxesMigrator(
        source_engine=source_engine,
        dest_engine=dest_engine,
        id_remapper=remapper,
        state_repo=state_repo,
        logger=logger,
    )

    # _migrate_channels returns empty map for unknown channel type
    with patch.object(migrator, "_migrate_channels", return_value={}):
        with patch.object(migrator, "_run_batches", side_effect=capture_batches):
            with patch("src.migrators.inboxes_migrator.Table"):
                migrator.migrate()

    # Channel_id kept as-is (SOURCE value) since not in channel_id_map
    assert len(remapped_rows) == 1
    assert remapped_rows[0]["channel_id"] == 52  # Unchanged


# ---------------------------------------------------------------------------
# T026-12 — channel_id in map: remapped to DEST value
# ---------------------------------------------------------------------------


def test_inboxes_channel_id_remapped_from_map():
    """When channel_id is in the channel_id_map, it is remapped to DEST value."""
    rows = [
        {
            "id": 104,
            "account_id": 1,
            "name": "api_channel",
            "channel_type": "Channel::Api",
            "channel_id": 60,
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
    state_repo.get_migrated_ids.side_effect = [
        {1},  # accounts
        set(),  # already_migrated
    ]

    remapper = IDRemapper({"inboxes": 151, "accounts": 20})
    logger = logging.getLogger("test_inboxes_channel_map")

    migrator = InboxesMigrator(
        source_engine=source_engine,
        dest_engine=dest_engine,
        id_remapper=remapper,
        state_repo=state_repo,
        logger=logger,
    )

    # _migrate_channels returns map with (channel_type, src_id) → dest_id
    channel_map = {("Channel::Api", 60): 1060}

    with patch.object(migrator, "_migrate_channels", return_value=channel_map):
        with patch.object(migrator, "_run_batches", side_effect=capture_batches):
            with patch("src.migrators.inboxes_migrator.Table"):
                migrator.migrate()

    # Channel_id should be remapped to DEST value
    assert len(remapped_rows) == 1
    assert remapped_rows[0]["channel_id"] == 1060


# ---------------------------------------------------------------------------
# T026-13 — Account ID validation: multiple accounts mixed
# ---------------------------------------------------------------------------


def test_inboxes_multiple_accounts_mixed_migrated_unmigrated():
    """Multiple accounts in rows: migrated rows processed, unmigrated rows skipped."""
    rows = [
        {
            "id": 200,
            "account_id": 1,
            "name": "acct1_inbox",
            "channel_type": "Channel::Email",
            "channel_id": None,
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 201,
            "account_id": 2,
            "name": "acct2_inbox",
            "channel_type": "Channel::Api",
            "channel_id": None,
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 202,
            "account_id": 999,
            "name": "unmigrated_inbox",
            "channel_type": "Channel::Telegram",
            "channel_id": None,
            "created_at": None,
            "updated_at": None,
        },
    ]

    remapped_rows = []
    skipped_count = [0]

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
            else:
                skipped_count[0] += 1
        return MigrationResult(table=table_name, total_source=3, migrated=2, skipped=1)

    migrator = _make_migrator(source_rows=rows, migrated_accounts={1, 2})
    with patch.object(migrator, "_migrate_channels", return_value={}):
        with patch.object(migrator, "_run_batches", side_effect=capture_batches):
            with patch("src.migrators.inboxes_migrator.Table"):
                migrator.migrate()

    # 2 migrated + 1 unmigrated
    assert len(remapped_rows) == 2
    assert skipped_count[0] == 1
    assert remapped_rows[0]["account_id"] == 21  # 1 + 20
    assert remapped_rows[1]["account_id"] == 22  # 2 + 20


# ---------------------------------------------------------------------------
# T026-14 — Channel fields preserved: various channel types
# ---------------------------------------------------------------------------


def test_inboxes_channel_fields_preserved_all_types():
    """Various channel types all preserved without modification."""
    rows = [
        {
            "id": 210,
            "account_id": 1,
            "name": "web",
            "channel_type": "Channel::WebWidget",
            "channel_id": 50,
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 211,
            "account_id": 1,
            "name": "api",
            "channel_type": "Channel::Api",
            "channel_id": 51,
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 212,
            "account_id": 1,
            "name": "facebook",
            "channel_type": "Channel::FacebookPage",
            "channel_id": 52,
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

    channel_map = {
        ("Channel::WebWidget", 50): 100,
        ("Channel::Api", 51): 101,
        ("Channel::FacebookPage", 52): 102,
    }

    with patch.object(migrator, "_migrate_channels", return_value=channel_map):
        with patch.object(migrator, "_run_batches", side_effect=capture_batches):
            with patch("src.migrators.inboxes_migrator.Table"):
                migrator.migrate()

    # All 3 inboxes migrated, channel_types preserved
    assert len(remapped_rows) == 3
    assert remapped_rows[0]["channel_type"] == "Channel::WebWidget"
    assert remapped_rows[1]["channel_type"] == "Channel::Api"
    assert remapped_rows[2]["channel_type"] == "Channel::FacebookPage"
    # channel_ids remapped
    assert remapped_rows[0]["channel_id"] == 100
    assert remapped_rows[1]["channel_id"] == 101
    assert remapped_rows[2]["channel_id"] == 102


# ---------------------------------------------------------------------------
# T026-15 — Empty source rows: no-op
# ---------------------------------------------------------------------------


def test_inboxes_empty_source_no_migration():
    """Empty source rows returns MigrationResult with 0 migrated/skipped."""
    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=0, migrated=0, skipped=0)

    migrator = _make_migrator(source_rows=[], migrated_accounts={1})
    with patch.object(migrator, "_migrate_channels", return_value={}):
        with patch.object(migrator, "_run_batches", side_effect=capture_batches):
            with patch("src.migrators.inboxes_migrator.Table"):
                result = migrator.migrate()

    # No rows processed
    assert len(remapped_rows) == 0
    assert result.migrated == 0
    assert result.skipped == 0


# ---------------------------------------------------------------------------
# T026-16 — Channel_id_map lookup with compound tuple key
# ---------------------------------------------------------------------------


def test_inboxes_channel_id_map_tuple_key_lookup():
    """channel_id_map uses (channel_type, src_channel_id) as compound key."""
    rows = [
        {
            "id": 220,
            "account_id": 1,
            "name": "inbox_api",
            "channel_type": "Channel::Api",
            "channel_id": 60,
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

    # Map entry uses (channel_type, src_channel_id) tuple as key
    channel_map = {("Channel::Api", 60): 3000}

    with patch.object(migrator, "_migrate_channels", return_value=channel_map):
        with patch.object(migrator, "_run_batches", side_effect=capture_batches):
            with patch("src.migrators.inboxes_migrator.Table"):
                migrator.migrate()

    # channel_id correctly looked up using (channel_type, src_id) key
    assert len(remapped_rows) == 1
    assert remapped_rows[0]["channel_id"] == 3000


# ---------------------------------------------------------------------------
# T026-17 — Name field preserved
# ---------------------------------------------------------------------------


def test_inboxes_name_preserved():
    """Inbox name field is copied as-is without modification."""
    name = "Customer Support Channel"
    rows = [
        {
            "id": 221,
            "account_id": 1,
            "name": name,
            "channel_type": "Channel::WebWidget",
            "channel_id": 70,
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
    channel_map = {("Channel::WebWidget", 70): 3001}

    with patch.object(migrator, "_migrate_channels", return_value=channel_map):
        with patch.object(migrator, "_run_batches", side_effect=capture_batches):
            with patch("src.migrators.inboxes_migrator.Table"):
                migrator.migrate()

    assert remapped_rows[0]["name"] == name


# ---------------------------------------------------------------------------
# T026-18 — Multiple accounts with different channel types
# ---------------------------------------------------------------------------


def test_inboxes_multiple_accounts_different_channels():
    """Inboxes from multiple accounts with different channel types migrated."""
    rows = [
        {
            "id": 222,
            "account_id": 1,
            "name": "inbox_web1",
            "channel_type": "Channel::WebWidget",
            "channel_id": 71,
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 223,
            "account_id": 2,
            "name": "inbox_api1",
            "channel_type": "Channel::Api",
            "channel_id": 72,
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 224,
            "account_id": 1,
            "name": "inbox_fb1",
            "channel_type": "Channel::FacebookPage",
            "channel_id": 73,
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

    migrator = _make_migrator(source_rows=rows, migrated_accounts={1, 2})
    channel_map = {
        ("Channel::WebWidget", 71): 3002,
        ("Channel::Api", 72): 3003,
        ("Channel::FacebookPage", 73): 3004,
    }

    with patch.object(migrator, "_migrate_channels", return_value=channel_map):
        with patch.object(migrator, "_run_batches", side_effect=capture_batches):
            with patch("src.migrators.inboxes_migrator.Table"):
                migrator.migrate()

    # All 3 should be migrated with correct account remapping
    assert len(remapped_rows) == 3
    assert remapped_rows[0]["account_id"] == 21  # 1 + 20
    assert remapped_rows[1]["account_id"] == 22  # 2 + 20
    assert remapped_rows[2]["account_id"] == 21  # 1 + 20


# ---------------------------------------------------------------------------
# T026-19 — Enable polling field preserved
# ---------------------------------------------------------------------------


def test_inboxes_enable_polling_preserved():
    """enable_polling field is copied as-is (when present)."""
    rows = [
        {
            "id": 225,
            "account_id": 1,
            "name": "polling_inbox",
            "channel_type": "Channel::WebWidget",
            "channel_id": 74,
            "enable_polling": True,
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
    channel_map = {("Channel::WebWidget", 74): 3005}

    with patch.object(migrator, "_migrate_channels", return_value=channel_map):
        with patch.object(migrator, "_run_batches", side_effect=capture_batches):
            with patch("src.migrators.inboxes_migrator.Table"):
                migrator.migrate()

    assert remapped_rows[0]["enable_polling"] is True


# ---------------------------------------------------------------------------
# T026-20 — Orphan account_id skipped
# ---------------------------------------------------------------------------


def test_inboxes_orphan_account_skipped():
    """Inbox with unmigrated account_id is skipped."""
    rows = [
        {
            "id": 226,
            "account_id": 999,
            "name": "orphan_inbox",
            "channel_type": "Channel::WebWidget",
            "channel_id": 75,
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

    migrator = _make_migrator(source_rows=rows, migrated_accounts={1, 2})
    channel_map = {}

    with patch.object(migrator, "_migrate_channels", return_value=channel_map):
        with patch.object(migrator, "_run_batches", side_effect=capture_batches):
            with patch("src.migrators.inboxes_migrator.Table"):
                migrator.migrate()

    # Should be skipped due to orphan account_id
    assert len(remapped_rows) == 0


# ---------------------------------------------------------------------------
# T026-21 — ID remapping with offset_inboxes
# ---------------------------------------------------------------------------


def test_inboxes_id_remapping_offset():
    """Inbox ID is remapped using offset_inboxes (151)."""
    rows = [
        {
            "id": 300,
            "account_id": 1,
            "name": "remote_inbox",
            "channel_type": "Channel::WebWidget",
            "channel_id": 76,
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
    channel_map = {("Channel::WebWidget", 76): 3006}

    with patch.object(migrator, "_migrate_channels", return_value=channel_map):
        with patch.object(migrator, "_run_batches", side_effect=capture_batches):
            with patch("src.migrators.inboxes_migrator.Table"):
                migrator.migrate()

    # ID should be remapped: 300 + 151 (offset_inboxes)
    assert len(remapped_rows) == 1
    assert remapped_rows[0]["id"] == 300 + 151


# ---------------------------------------------------------------------------
# T026-22 — Empty source no-op
# ---------------------------------------------------------------------------


def test_inboxes_empty_source_no_migration():
    """Empty source returns MigrationResult(0 migrated, 0 skipped)."""
    rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        return MigrationResult(table=table_name, total_source=0, migrated=0, skipped=0)

    migrator = _make_migrator(source_rows=rows)
    channel_map = {}

    with patch.object(migrator, "_migrate_channels", return_value=channel_map):
        with patch.object(migrator, "_run_batches", side_effect=capture_batches):
            with patch("src.migrators.inboxes_migrator.Table"):
                result = migrator.migrate()

    assert result.total_source == 0
    assert result.migrated == 0
    assert result.skipped == 0


# ---------------------------------------------------------------------------
# T026-23 — Channel type field preserved
# ---------------------------------------------------------------------------


def test_inboxes_channel_type_preserved():
    """channel_type field is copied as-is (Channel::Email, ::WebWidget, etc)."""
    rows = [
        {
            "id": 301,
            "account_id": 1,
            "name": "email_inbox",
            "channel_type": "Channel::Email",
            "channel_id": 77,
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
    channel_map = {("Channel::Email", 77): 3007}

    with patch.object(migrator, "_migrate_channels", return_value=channel_map):
        with patch.object(migrator, "_run_batches", side_effect=capture_batches):
            with patch("src.migrators.inboxes_migrator.Table"):
                migrator.migrate()

    assert len(remapped_rows) == 1
    assert remapped_rows[0]["channel_type"] == "Channel::Email"


# ---------------------------------------------------------------------------
# T026-24 — enable_polling field preserved
# ---------------------------------------------------------------------------


def test_inboxes_enable_polling_preserved():
    """enable_polling field is copied as-is (true or false)."""
    rows = [
        {
            "id": 302,
            "account_id": 1,
            "name": "polling_inbox",
            "channel_type": "Channel::Email",
            "channel_id": 78,
            "enable_polling": True,
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
    channel_map = {("Channel::Email", 78): 3008}

    with patch.object(migrator, "_migrate_channels", return_value=channel_map):
        with patch.object(migrator, "_run_batches", side_effect=capture_batches):
            with patch("src.migrators.inboxes_migrator.Table"):
                migrator.migrate()

    assert len(remapped_rows) == 1
    assert remapped_rows[0]["enable_polling"] is True


# ---------------------------------------------------------------------------
# T026-25 — Channel ID remapping with map lookup
# ---------------------------------------------------------------------------


def test_inboxes_channel_id_remapped_from_map():
    """channel_id is remapped using _migrate_channels map with (type, src_id) key."""
    rows = [
        {
            "id": 303,
            "account_id": 1,
            "name": "mapped_inbox",
            "channel_type": "Channel::WebWidget",
            "channel_id": 79,
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
    # Simulate channel_id remapping: (Channel::WebWidget, 79) -> 9999
    channel_map = {("Channel::WebWidget", 79): 9999}

    with patch.object(migrator, "_migrate_channels", return_value=channel_map):
        with patch.object(migrator, "_run_batches", side_effect=capture_batches):
            with patch("src.migrators.inboxes_migrator.Table"):
                migrator.migrate()

    assert len(remapped_rows) == 1
    assert remapped_rows[0]["channel_id"] == 9999


# ---------------------------------------------------------------------------
# T026-26 — Multiple inboxes different accounts
# ---------------------------------------------------------------------------


def test_inboxes_multiple_different_accounts_filtered():
    """Multiple inboxes with unmigrated account_ids properly filtered."""
    rows = [
        {
            "id": 304,
            "account_id": 1,
            "name": "inbox_a1",
            "channel_type": "Channel::WebWidget",
            "channel_id": 80,
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 305,
            "account_id": 999,
            "name": "inbox_a999",
            "channel_type": "Channel::WebWidget",
            "channel_id": 81,
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 306,
            "account_id": 1,
            "name": "inbox_a1_2",
            "channel_type": "Channel::Email",
            "channel_id": 82,
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

    migrator = _make_migrator(source_rows=rows, migrated_accounts={1})
    channel_map = {
        ("Channel::WebWidget", 80): 4000,
        ("Channel::Email", 82): 4001,
    }

    with patch.object(migrator, "_migrate_channels", return_value=channel_map):
        with patch.object(migrator, "_run_batches", side_effect=capture_batches):
            with patch("src.migrators.inboxes_migrator.Table"):
                migrator.migrate()

    # Only 2 should migrate (account_id 1), 1 skipped (account_id 999)
    assert len(remapped_rows) == 2
    assert 305 in skipped_ids  # orphan account
    assert len(skipped_ids) == 1


# ---------------------------------------------------------------------------
# T026-27 — Name field preserved
# ---------------------------------------------------------------------------


def test_inboxes_name_preserved_special_chars():
    """inbox name field is copied as-is with special characters."""
    name = "Customer Support - São Paulo™ 🎯"
    rows = [
        {
            "id": 307,
            "account_id": 1,
            "name": name,
            "channel_type": "Channel::WebWidget",
            "channel_id": 83,
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
    channel_map = {("Channel::WebWidget", 83): 4002}

    with patch.object(migrator, "_migrate_channels", return_value=channel_map):
        with patch.object(migrator, "_run_batches", side_effect=capture_batches):
            with patch("src.migrators.inboxes_migrator.Table"):
                migrator.migrate()

    assert len(remapped_rows) == 1
    assert remapped_rows[0]["name"] == name


# ---------------------------------------------------------------------------
# POC Helper Methods — _table_name, _fetch_all_source_rows, _classify_row_poc
# ---------------------------------------------------------------------------


def test_inboxes_table_name():
    """_table_name() returns 'inboxes'."""
    migrator = _make_migrator()
    assert migrator._table_name() == "inboxes"


def test_inboxes_fetch_all_source_rows():
    """_fetch_all_source_rows() fetches and reflects all rows."""
    rows = [
        {"id": 1, "account_id": 5, "name": "Support", "channel_type": "Channel::Email"},
        {"id": 2, "account_id": 5, "name": "Sales", "channel_type": "Channel::Api"},
    ]
    migrator = _make_migrator(source_rows=rows)

    with patch("src.migrators.inboxes_migrator.Table") as mock_table:
        mock_table_inst = MagicMock()
        mock_table.return_value = mock_table_inst
        result = migrator._fetch_all_source_rows()

    assert len(result) == 2
    assert result[0]["id"] == 1
    assert result[1]["name"] == "Sales"


def test_inboxes_classify_row_poc_orphan_account():
    """_classify_row_poc() classifies orphan account_id as ORPHAN_FK_SKIP."""
    from src.reports.poc_reporter import Outcome

    migrator = _make_migrator()
    row = {"id": 1, "account_id": 999}
    migrated_sets = {"accounts": {1, 2, 3}}

    outcome, reason = migrator._classify_row_poc(row, migrated_sets)

    assert outcome == Outcome.ORPHAN_FK_SKIP
    assert "account_id=999" in reason


def test_inboxes_classify_row_poc_clean_account():
    """_classify_row_poc() returns WOULD_MIGRATE for clean account_id."""
    from src.reports.poc_reporter import Outcome

    migrator = _make_migrator()
    row = {"id": 1, "account_id": 2}
    migrated_sets = {"accounts": {1, 2, 3}}

    outcome, reason = migrator._classify_row_poc(row, migrated_sets)

    assert outcome == Outcome.WOULD_MIGRATE
    assert reason == "clean"


# ---------------------------------------------------------------------------
# Channel Type Configuration Coverage
# ---------------------------------------------------------------------------


def test_inboxes_channel_cfg_has_all_types():
    """All 9 channel types are configured in _CHANNEL_CFG."""
    from src.migrators.inboxes_migrator import _CHANNEL_CFG

    expected_types = [
        "Channel::WebWidget",
        "Channel::Api",
        "Channel::FacebookPage",
        "Channel::Telegram",
        "Channel::Email",
        "Channel::TwilioSms",
        "Channel::Whatsapp",
        "Channel::Line",
        "Channel::Sms",
    ]

    for channel_type in expected_types:
        assert channel_type in _CHANNEL_CFG, f"{channel_type} missing from _CHANNEL_CFG"
        table_name, seq_name, regen_fields = _CHANNEL_CFG[channel_type]
        assert table_name is not None
        assert seq_name is not None
        assert isinstance(regen_fields, dict)


def test_inboxes_token_regen_fields_callable():
    """Token fields (website_token, identifier, hmac_token) are callable."""
    from src.migrators.inboxes_migrator import _CHANNEL_CFG

    # WebWidget should have website_token
    _, _, webwidget_regen = _CHANNEL_CFG["Channel::WebWidget"]
    assert "website_token" in webwidget_regen
    assert callable(webwidget_regen["website_token"])

    # Api should have identifier and hmac_token
    _, _, api_regen = _CHANNEL_CFG["Channel::Api"]
    assert "identifier" in api_regen
    assert "hmac_token" in api_regen
    assert callable(api_regen["identifier"])
    assert callable(api_regen["hmac_token"])


def test_inboxes_token_regen_generates_unique_values():
    """Token regeneration functions produce different values each time."""
    from src.migrators.inboxes_migrator import _CHANNEL_CFG

    _, _, webwidget_regen = _CHANNEL_CFG["Channel::WebWidget"]
    gen_fn = webwidget_regen["website_token"]

    token1 = gen_fn()
    token2 = gen_fn()

    assert token1 != token2
    assert len(token1) > 0
    assert len(token2) > 0
