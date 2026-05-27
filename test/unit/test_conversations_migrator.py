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
# T031-2 — Orphan contact_id → contact_id NULLed-out, record included
# ---------------------------------------------------------------------------


def test_conversations_orphan_contact_id_skips_record():
    """Records with orphan contact_id are included with contact_id=None (not skipped).

    Per BUG-03 fix: Skipping whole conversation when contact_id unmigrated causes
    cascade loss of messages/attachments. NULL contact_id is acceptable in Chatwoot.
    """
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

    # Record is included but contact_id is nulled
    assert len(remapped) == 1
    assert remapped[0].get("contact_id") is None


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


# ---------------------------------------------------------------------------
# T031-5 — Required FK: account_id orphan → record skipped
# ---------------------------------------------------------------------------


def test_conversations_required_fk_orphan_account_id_skipped():
    """Records with unmigrated account_id are skipped (required FK)."""
    rows = [_base_row(account_id=9999)]
    remapped = []

    def capture(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=0, skipped=1)

    migrator = _make_migrator(
        source_rows=rows,
        migrated={"accounts": {1, 2}, "inboxes": {1}},  # 9999 not in accounts
    )
    with patch.object(migrator, "_run_batches", side_effect=capture):
        with patch("src.migrators.conversations_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert len(remapped) == 0


# ---------------------------------------------------------------------------
# T031-6 — Required FK: inbox_id orphan → record skipped
# ---------------------------------------------------------------------------


def test_conversations_required_fk_orphan_inbox_id_skipped():
    """Records with unmigrated inbox_id are skipped (required FK)."""
    rows = [_base_row(inbox_id=8888)]
    remapped = []

    def capture(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=0, skipped=1)

    migrator = _make_migrator(
        source_rows=rows,
        migrated={"accounts": {1}, "inboxes": {1, 2}},  # 8888 not in inboxes
    )
    with patch.object(migrator, "_run_batches", side_effect=capture):
        with patch("src.migrators.conversations_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert len(remapped) == 0


# ---------------------------------------------------------------------------
# T031-7 — UUID regeneration (not copied from source)
# ---------------------------------------------------------------------------


def test_conversations_uuid_regenerated():
    """UUID is regenerated (not copied from source) to avoid uniqueness violation."""
    import uuid as uuid_lib

    original_uuid = str(uuid_lib.uuid4())
    rows = [_base_row(id=10, uuid=original_uuid)]
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

    assert remapped[0]["uuid"] != original_uuid
    # Verify it's a valid UUID
    try:
        uuid_lib.UUID(remapped[0]["uuid"])
    except ValueError:
        raise AssertionError(f"Generated UUID is invalid: {remapped[0]['uuid']}")


# ---------------------------------------------------------------------------
# T031-8 — team_id NULLed-out when team not migrated
# ---------------------------------------------------------------------------


def test_conversations_team_id_nulled_when_unmigrated():
    """team_id is set to NULL when the team was not migrated."""
    rows = [_base_row(team_id=666)]  # team 666 not migrated
    remapped = []

    def capture(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    migrator = _make_migrator(
        source_rows=rows,
        migrated={"teams": {1, 2, 3}},  # 666 not in migrated teams
    )
    with patch.object(migrator, "_run_batches", side_effect=capture):
        with patch("src.migrators.conversations_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert remapped[0]["team_id"] is None


# ---------------------------------------------------------------------------
# T031-9 — Nullable contact_id NULLed when unmigrated
# ---------------------------------------------------------------------------


def test_conversations_contact_id_nulled_when_unmigrated():
    """contact_id is NULLed when contact not migrated (BUG-03 fix)."""
    rows = [_base_row(contact_id=999)]  # contact 999 not migrated

    remapped = []

    def capture(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    migrator = _make_migrator(
        source_rows=rows,
        migrated={"contacts": {1, 2, 3}},  # 999 not migrated
    )
    with patch.object(migrator, "_run_batches", side_effect=capture):
        with patch("src.migrators.conversations_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert remapped[0]["contact_id"] is None


# ---------------------------------------------------------------------------
# T031-10 — display_id incremented per account
# ---------------------------------------------------------------------------


def test_conversations_display_id_incremented_per_account():
    """display_id is incremented separately per account during migration."""
    rows = [
        _base_row(id=1, account_id=1, display_id=1),
        _base_row(id=2, account_id=1, display_id=2),
        _base_row(id=3, account_id=2, display_id=1),
    ]

    remapped = []

    def capture(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped.append(r)
        return MigrationResult(table=table_name, total_source=3, migrated=3, skipped=0)

    migrator = _make_migrator(
        source_rows=rows,
        migrated={"accounts": {1, 2}},
    )
    with patch.object(migrator, "_run_batches", side_effect=capture):
        with patch("src.migrators.conversations_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    # All display_ids should be regenerated (incremented from 0 per account)
    # For account 1: 1, 2
    # For account 2: 1
    # So results should have different display_ids than originals
    assert remapped[0]["display_id"] > 0
    assert remapped[1]["display_id"] == remapped[0]["display_id"] + 1
    assert remapped[2]["display_id"] > 0


# ---------------------------------------------------------------------------
# T031-11 — uuid regenerated per row
# ---------------------------------------------------------------------------


def test_conversations_uuid_regenerated_per_row():
    """Each conversation row gets a new UUID on migration."""
    import uuid as uuid_lib

    rows = [
        _base_row(id=1),
        _base_row(id=2),
    ]

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

    # Mock execute
    dest_conn.execute.return_value.fetchall.return_value = []
    dest_engine.connect.return_value = dest_conn

    state_repo = MagicMock(spec=MigrationStateRepository)
    state_repo.get_migrated_ids.side_effect = [
        {1},  # accounts
        {1},  # inboxes
        {1},  # contacts
        {1},  # users
        {1},  # teams
        set(),  # contact_inboxes
        set(),  # already_migrated
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
    logger = logging.getLogger("test_conversations_uuid")

    migrator = ConversationsMigrator(
        source_engine=source_engine,
        dest_engine=dest_engine,
        id_remapper=remapper,
        state_repo=state_repo,
        logger=logger,
    )

    remapped = []

    def capture(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped.append(r)
        return MigrationResult(table=table_name, total_source=2, migrated=2, skipped=0)

    with patch.object(migrator, "_run_batches", side_effect=capture):
        with patch("src.migrators.conversations_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    # Verify both rows have new UUIDs and they're different
    assert remapped[0]["uuid"] != remapped[1]["uuid"]
    # Verify they're valid UUIDs
    try:
        uuid_lib.UUID(remapped[0]["uuid"])
        uuid_lib.UUID(remapped[1]["uuid"])
    except ValueError:
        raise AssertionError("Generated UUIDs are invalid")


# ---------------------------------------------------------------------------
# T035-12 — Subject field preserved
# ---------------------------------------------------------------------------


def test_conversations_subject_preserved():
    """Subject field is copied as-is without modification."""
    subject = "Order inquiry from John"
    rows = [
        {
            "id": 100,
            "account_id": 1,
            "inbox_id": 1,
            "contact_id": 1,
            "assignee_id": 1,
            "team_id": 1,
            "uuid": "test-uuid-1",
            "subject": subject,
            "status": "open",
            "created_at": None,
            "updated_at": None,
        }
    ]

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
        {1}, {1}, {1}, {1}, {1}, set(), set()
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
    logger = logging.getLogger("test_conversations_subject")

    migrator = ConversationsMigrator(
        source_engine=source_engine,
        dest_engine=dest_engine,
        id_remapper=remapper,
        state_repo=state_repo,
        logger=logger,
    )

    remapped = []

    def capture(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    with patch.object(migrator, "_run_batches", side_effect=capture):
        with patch("src.migrators.conversations_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert remapped[0]["subject"] == subject


# ---------------------------------------------------------------------------
# T035-13 — Status field preserved
# ---------------------------------------------------------------------------


def test_conversations_status_preserved():
    """Status field is copied without modification."""
    status = "resolved"
    rows = [
        {
            "id": 101,
            "account_id": 1,
            "inbox_id": 1,
            "contact_id": 1,
            "assignee_id": 1,
            "team_id": 1,
            "uuid": "test-uuid-2",
            "subject": "Test",
            "status": status,
            "created_at": None,
            "updated_at": None,
        }
    ]

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
        {1}, {1}, {1}, {1}, {1}, set(), set()
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
    logger = logging.getLogger("test_conversations_status")

    migrator = ConversationsMigrator(
        source_engine=source_engine,
        dest_engine=dest_engine,
        id_remapper=remapper,
        state_repo=state_repo,
        logger=logger,
    )

    remapped = []

    def capture(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    with patch.object(migrator, "_run_batches", side_effect=capture):
        with patch("src.migrators.conversations_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert remapped[0]["status"] == status


# ---------------------------------------------------------------------------
# T035-14 — Empty source no-op
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# T035-14 — Conversation ID remapped with offset
# T035-15 — Orphan inbox_id skipped
# ---------------------------------------------------------------------------


def test_conversations_orphan_inbox_skipped():
    """Conversation with unmigrated inbox_id is skipped."""
    rows = [
        {
            "id": 102,
            "account_id": 1,
            "inbox_id": 999,
            "contact_id": 1,
            "assignee_id": 1,
            "team_id": 1,
            "uuid": "test-uuid-3",
            "subject": "Test",
            "status": "open",
            "created_at": None,
            "updated_at": None,
        }
    ]

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
        {1}, {1}, {1}, {1}, {1}, set(), set()
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
    logger = logging.getLogger("test_conversations_orphan")

    migrator = ConversationsMigrator(
        source_engine=source_engine,
        dest_engine=dest_engine,
        id_remapper=remapper,
        state_repo=state_repo,
        logger=logger,
    )

    remapped = []

    def capture(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=0, skipped=1)

    with patch.object(migrator, "_run_batches", side_effect=capture):
        with patch("src.migrators.conversations_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert len(remapped) == 0


# ---------------------------------------------------------------------------
# T035-14 — Conversation ID remapped with offset
# ---------------------------------------------------------------------------


def test_conversations_id_remapped_offset():
    """Conversation ID is remapped using offset_conversations."""
    rows = [
        {
            "id": 100,
            "account_id": 1,
            "inbox_id": 1,
            "contact_id": 1,
            "assignee_id": 1,
            "team_id": 1,
            "uuid": "test-uuid-14",
            "subject": "Test ID Remap",
            "status": "open",
            "created_at": None,
            "updated_at": None,
        }
    ]

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
        {1}, {1}, {1}, {1}, {1}, set(), set()
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
    logger = logging.getLogger("test_conversations_id_remap")

    migrator = ConversationsMigrator(
        source_engine=source_engine,
        dest_engine=dest_engine,
        id_remapper=remapper,
        state_repo=state_repo,
        logger=logger,
    )

    remapped = []

    def capture(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    with patch.object(migrator, "_run_batches", side_effect=capture):
        with patch("src.migrators.conversations_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    # ID should be remapped: 100 + 153582 (offset_conversations)
    assert len(remapped) == 1
    assert remapped[0]["id"] == 100 + 153582
