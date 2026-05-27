"""Unit tests for WebhooksMigrator (T038)."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

from src.migrators.base_migrator import MigrationResult
from src.migrators.webhooks_migrator import WebhooksMigrator
from src.repository.migration_state_repository import MigrationStateRepository
from src.utils.id_remapper import IDRemapper


def _make_migrator(source_rows=None, migrated=None):
    """Build WebhooksMigrator with mocked engines."""
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
        migrated.get("inboxes", set()),  # already_migrated
    ]

    remapper = IDRemapper({"webhooks": 10, "accounts": 20, "inboxes": 30})
    logger = logging.getLogger("test_wh")

    return (
        WebhooksMigrator(
            source_engine=source_engine,
            dest_engine=dest_engine,
            id_remapper=remapper,
            state_repo=state_repo,
            logger=logger,
        ),
        remapper,
    )


def test_webhooks_basic_migration():
    """Basic webhook inserted with remapped account_id."""
    rows = [
        {
            "id": 1,
            "account_id": 1,
            "url": "https://example.com/webhook",
            "created_at": None,
            "updated_at": None,
        }
    ]

    migrator, _ = _make_migrator(source_rows=rows, migrated={"accounts": {1}})

    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.webhooks_migrator.Table"):
            migrator.migrate()

    assert len(remapped_rows) == 1
    assert remapped_rows[0]["account_id"] > 1


def test_webhooks_orphan_account_id_skipped():
    """Unmigrated account_id causes skip."""
    rows = [
        {
            "id": 2,
            "account_id": 999,
            "url": "https://example.com/webhook",
            "created_at": None,
            "updated_at": None,
        }
    ]

    migrator, _ = _make_migrator(source_rows=rows, migrated={"accounts": {1}})

    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=0, skipped=1)

    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.webhooks_migrator.Table"):
            migrator.migrate()

    assert len(remapped_rows) == 0


# ---------------------------------------------------------------------------
# T038-3 — inbox_id is remapped when migrated
# ---------------------------------------------------------------------------


def test_webhooks_inbox_id_remapped_when_migrated():
    """inbox_id is remapped when the inbox was migrated."""
    rows = [
        {
            "id": 3,
            "account_id": 1,
            "inbox_id": 5,
            "url": "https://example.com/webhook",
            "created_at": None,
            "updated_at": None,
        }
    ]

    def get_migrated_ids_fn(conn, table_name):
        if table_name == "accounts":
            return {1}
        elif table_name == "inboxes":
            return {5}
        return set()

    migrator, remapper = _make_migrator(source_rows=rows)
    migrator.state_repo.get_migrated_ids = MagicMock(side_effect=get_migrated_ids_fn)

    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.webhooks_migrator.Table"):
            migrator.migrate()

    assert len(remapped_rows) == 1
    assert remapped_rows[0]["inbox_id"] is not None
    assert remapped_rows[0]["inbox_id"] > 5


# ---------------------------------------------------------------------------
# T038-4 — inbox_id is nulled when inbox not migrated
# ---------------------------------------------------------------------------


def test_webhooks_inbox_id_nulled_when_not_migrated():
    """inbox_id is NULLed when the inbox was not migrated."""
    rows = [
        {
            "id": 4,
            "account_id": 1,
            "inbox_id": 999,
            "url": "https://example.com/webhook",
            "created_at": None,
            "updated_at": None,
        }
    ]

    def get_migrated_ids_fn(conn, table_name):
        if table_name == "accounts":
            return {1}
        elif table_name == "inboxes":
            return {1, 2, 3}
        return set()

    migrator, remapper = _make_migrator(source_rows=rows)
    migrator.state_repo.get_migrated_ids = MagicMock(side_effect=get_migrated_ids_fn)

    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.webhooks_migrator.Table"):
            migrator.migrate()

    assert len(remapped_rows) == 1
    assert remapped_rows[0]["inbox_id"] is None


# ---------------------------------------------------------------------------
# T038-5 — inbox_id null in source remains null
# ---------------------------------------------------------------------------


def test_webhooks_inbox_id_null_in_source_unchanged():
    """inbox_id NULL in source remains NULL (no error)."""
    rows = [
        {
            "id": 5,
            "account_id": 1,
            "inbox_id": None,
            "url": "https://example.com/webhook",
            "created_at": None,
            "updated_at": None,
        }
    ]

    migrator, _ = _make_migrator(source_rows=rows, migrated={"accounts": {1}})

    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.webhooks_migrator.Table"):
            migrator.migrate()

    assert len(remapped_rows) == 1
    assert remapped_rows[0]["inbox_id"] is None


# ---------------------------------------------------------------------------
# T038-6 — Empty source rows: no-op, returns 0 migrated
# ---------------------------------------------------------------------------


def test_webhooks_empty_source_no_op():
    """When source has no rows, migration is a no-op."""
    migrator, _ = _make_migrator(source_rows=[], migrated={"accounts": {1}})

    result = None
    with patch("src.migrators.webhooks_migrator.Table"):
        result = migrator.migrate()

    assert result.total_source == 0
    assert result.migrated == 0
    assert result.skipped == 0


# ---------------------------------------------------------------------------
# T038-7 — url field preserved through migration
# ---------------------------------------------------------------------------


def test_webhooks_url_field_preserved():
    """url field is copied as-is to destination."""
    test_url = "https://api.example.com/v1/webhook-receiver"
    rows = [
        {
            "id": 6,
            "account_id": 1,
            "url": test_url,
            "created_at": None,
            "updated_at": None,
        }
    ]

    migrator, _ = _make_migrator(source_rows=rows, migrated={"accounts": {1}})

    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.webhooks_migrator.Table"):
            migrator.migrate()

    assert len(remapped_rows) == 1
    assert remapped_rows[0]["url"] == test_url


# ---------------------------------------------------------------------------
# T038-8 — Mixed accounts: both migrated and orphan
# ---------------------------------------------------------------------------


def test_webhooks_mixed_accounts_partial_skip():
    """Some webhooks migrated, some skipped due to orphan account_id."""
    rows = [
        {
            "id": 7,
            "account_id": 1,
            "url": "https://example.com/webhook1",
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 8,
            "account_id": 999,
            "url": "https://example.com/webhook2",
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 9,
            "account_id": 1,
            "url": "https://example.com/webhook3",
            "created_at": None,
            "updated_at": None,
        },
    ]

    migrator, _ = _make_migrator(source_rows=rows, migrated={"accounts": {1}})

    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=3, migrated=2, skipped=1)

    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.webhooks_migrator.Table"):
            migrator.migrate()

    assert len(remapped_rows) == 2  # Only 2 valid rows (7 and 9)
    assert all(r["account_id"] > 1 for r in remapped_rows)


# ---------------------------------------------------------------------------
# T038-9 — Multiple inboxes: some migrated, some not
# ---------------------------------------------------------------------------


def test_webhooks_mixed_inbox_statuses():
    """Some webhooks have migrated inbox_id, some have unmigrated."""
    rows = [
        {
            "id": 10,
            "account_id": 1,
            "inbox_id": 5,
            "url": "https://example.com/webhook_inbox5",
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 11,
            "account_id": 1,
            "inbox_id": 999,
            "url": "https://example.com/webhook_inbox999",
            "created_at": None,
            "updated_at": None,
        },
    ]

    def get_migrated_ids_fn(conn, table_name):
        if table_name == "accounts":
            return {1}
        elif table_name == "inboxes":
            return {5, 10}  # Only 5 and 10 were migrated
        return set()

    migrator, _ = _make_migrator(source_rows=rows)
    migrator.state_repo.get_migrated_ids = MagicMock(side_effect=get_migrated_ids_fn)

    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=2, migrated=2, skipped=0)

    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.webhooks_migrator.Table"):
            migrator.migrate()

    # First webhook should have remapped inbox_id
    assert remapped_rows[0]["inbox_id"] is not None and remapped_rows[0]["inbox_id"] > 5
    # Second webhook should have NULL inbox_id
    assert remapped_rows[1]["inbox_id"] is None
