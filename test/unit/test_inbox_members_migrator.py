"""Unit tests for InboxMembersMigrator (T034)."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

from src.migrators.base_migrator import MigrationResult
from src.migrators.inbox_members_migrator import InboxMembersMigrator
from src.repository.migration_state_repository import MigrationStateRepository
from src.utils.id_remapper import IDRemapper


def _make_migrator(source_rows=None, migrated=None):
    """Build InboxMembersMigrator with mocked engines."""
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
        return migrated.get(table_name, {1} if table_name in ["inboxes", "users"] else set())

    state_repo.get_migrated_ids.side_effect = get_migrated_ids_side_effect

    remapper = IDRemapper({"inbox_members": 30, "inboxes": 100, "users": 200})
    logger = logging.getLogger("test_im")

    return (
        InboxMembersMigrator(
            source_engine=source_engine,
            dest_engine=dest_engine,
            id_remapper=remapper,
            state_repo=state_repo,
            logger=logger,
        ),
        remapper,
    )


def test_inbox_members_basic_migration():
    """Basic inbox_member inserted with remapped FKs."""
    rows = [
        {
            "id": 1,
            "inbox_id": 1,
            "user_id": 1,
            "created_at": None,
            "updated_at": None,
        }
    ]

    migrator, _ = _make_migrator(
        source_rows=rows,
        migrated={"inboxes": {1}, "users": {1}},
    )

    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.inbox_members_migrator.Table"):
            migrator.migrate()

    assert len(remapped_rows) == 1
    assert remapped_rows[0]["inbox_id"] > 1  # Remapped


def test_inbox_members_orphan_inbox_id_skipped():
    """Unmigrated inbox_id causes skip."""
    rows = [
        {
            "id": 2,
            "inbox_id": 999,
            "user_id": 1,
            "created_at": None,
            "updated_at": None,
        }
    ]

    migrator, _ = _make_migrator(
        source_rows=rows,
        migrated={"inboxes": {1}, "users": {1}},
    )

    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=0, skipped=1)

    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.inbox_members_migrator.Table"):
            migrator.migrate()

    assert len(remapped_rows) == 0


def test_inbox_members_orphan_user_id_skipped():
    """Unmigrated user_id causes skip."""
    rows = [
        {
            "id": 3,
            "inbox_id": 1,
            "user_id": 999,
            "created_at": None,
            "updated_at": None,
        }
    ]

    migrator, _ = _make_migrator(
        source_rows=rows,
        migrated={"inboxes": {1}, "users": {1}},
    )

    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=0, skipped=1)

    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.inbox_members_migrator.Table"):
            migrator.migrate()

    assert len(remapped_rows) == 0


# ---------------------------------------------------------------------------
# T027-4 — id remapped
# ---------------------------------------------------------------------------


def test_inbox_members_id_remapped():
    """inbox_member id is remapped with correct offset."""
    rows = [
        {
            "id": 4,
            "inbox_id": 1,
            "user_id": 1,
            "created_at": None,
            "updated_at": None,
        }
    ]

    migrator, remapper = _make_migrator(
        source_rows=rows,
        migrated={"inboxes": {1}, "users": {1}},
    )

    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.inbox_members_migrator.Table"):
            migrator.migrate()

    assert len(remapped_rows) == 1
    assert remapped_rows[0]["id"] == 4 + 30  # offset 30


# ---------------------------------------------------------------------------
# T027-5 — mixed inbox/user with partial skip
# ---------------------------------------------------------------------------


def test_inbox_members_mixed_inboxes_users_partial_skip():
    """Inbox members from multiple inboxes/users skip only orphaned ones."""
    rows = [
        {
            "id": 5,
            "inbox_id": 1,
            "user_id": 1,
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 6,
            "inbox_id": 1,
            "user_id": 2,
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 7,
            "inbox_id": 999,
            "user_id": 1,
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 8,
            "inbox_id": 1,
            "user_id": 999,
            "created_at": None,
            "updated_at": None,
        },
    ]

    migrator, _ = _make_migrator(
        source_rows=rows,
        migrated={"inboxes": {1}, "users": {1, 2}},  # user_id 2 is migrated
    )

    remapped_rows = []
    skipped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
            else:
                skipped_rows.append(row["id"])
        return MigrationResult(table=table_name, total_source=4, migrated=2, skipped=2)

    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.inbox_members_migrator.Table"):
            migrator.migrate()

    assert len(remapped_rows) == 2
    assert len(skipped_rows) == 2
    assert 7 in skipped_rows  # orphan inbox_id
    assert 8 in skipped_rows  # orphan user_id


# ---------------------------------------------------------------------------
# T027-6 — empty source no-op
# ---------------------------------------------------------------------------


def test_inbox_members_empty_source_no_migration():
    """Empty source returns MigrationResult(0 migrated, 0 skipped)."""
    migrator, _ = _make_migrator(source_rows=[])

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        return MigrationResult(table=table_name, total_source=0, migrated=0, skipped=0)

    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.inbox_members_migrator.Table"):
            result = migrator.migrate()

    assert result.total_source == 0
    assert result.migrated == 0
    assert result.skipped == 0


# ---------------------------------------------------------------------------
# T027-7 — ID remapping with offset
# ---------------------------------------------------------------------------


def test_inbox_members_id_remapping_offset():
    """ID is remapped with offset_inbox_members."""
    rows = [
        {
            "id": 100,
            "inbox_id": 2,
            "user_id": 3,
            "created_at": None,
            "updated_at": None,
        }
    ]

    migrator, _ = _make_migrator(
        source_rows=rows,
        migrated={"inboxes": {2}, "users": {3}},
    )

    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.inbox_members_migrator.Table"):
            migrator.migrate()

    assert len(remapped_rows) == 1
    assert remapped_rows[0]["id"] == 100 + 30  # offset_inbox_members = 30
    assert remapped_rows[0]["inbox_id"] == 2 + 100  # offset_inboxes = 100
    assert remapped_rows[0]["user_id"] == 3 + 200  # offset_users = 200


# ---------------------------------------------------------------------------
# T027-8 — Multiple members same inbox
# ---------------------------------------------------------------------------


def test_inbox_members_multiple_same_inbox():
    """Multiple members in same inbox all migrated."""
    rows = [
        {
            "id": 9,
            "inbox_id": 3,
            "user_id": 4,
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 10,
            "inbox_id": 3,
            "user_id": 5,
            "created_at": None,
            "updated_at": None,
        },
    ]

    migrator, _ = _make_migrator(
        source_rows=rows,
        migrated={"inboxes": {3}, "users": {4, 5}},
    )

    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=2, migrated=2, skipped=0)

    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.inbox_members_migrator.Table"):
            migrator.migrate()

    assert len(remapped_rows) == 2


# ---------------------------------------------------------------------------
# T027-9 — Both FKs unmigrated (double orphan)
# ---------------------------------------------------------------------------


def test_inbox_members_both_fks_unmigrated_skipped():
    """Inbox member with both unmigrated FKs is skipped."""
    rows = [
        {
            "id": 11,
            "inbox_id": 999,
            "user_id": 999,
            "created_at": None,
            "updated_at": None,
        }
    ]

    migrator, _ = _make_migrator(
        source_rows=rows,
        migrated={"inboxes": {1}, "users": {1}},
    )

    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=0, skipped=1)

    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.inbox_members_migrator.Table"):
            migrator.migrate()

    assert len(remapped_rows) == 0
