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


# ---------------------------------------------------------------------------
# T038-10 — URL field with special characters preserved
# ---------------------------------------------------------------------------


def test_webhooks_url_with_special_characters_preserved():
    """URL with query params and special chars is preserved as-is."""
    special_url = "https://api.example.com/webhook?token=abc123&type=chat&v=2&special=%2B%3D%26"
    rows = [
        {
            "id": 12,
            "account_id": 1,
            "inbox_id": None,
            "url": special_url,
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
    assert remapped_rows[0]["url"] == special_url


# ---------------------------------------------------------------------------
# T038-11 — Multiple webhooks same account
# ---------------------------------------------------------------------------


def test_webhooks_multiple_webhooks_same_account():
    """Multiple webhooks for the same account all migrated."""
    rows = [
        {
            "id": 13,
            "account_id": 1,
            "inbox_id": None,
            "url": "https://example.com/webhook1",
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 14,
            "account_id": 1,
            "inbox_id": None,
            "url": "https://example.com/webhook2",
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 15,
            "account_id": 1,
            "inbox_id": None,
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
        return MigrationResult(table=table_name, total_source=3, migrated=3, skipped=0)

    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.webhooks_migrator.Table"):
            migrator.migrate()

    # All 3 webhooks should be migrated
    assert len(remapped_rows) == 3
    # IDs should be remapped
    assert remapped_rows[0]["id"] == 13 + 10
    assert remapped_rows[1]["id"] == 14 + 10
    assert remapped_rows[2]["id"] == 15 + 10


# ---------------------------------------------------------------------------
# T038-12 — Multiple accounts with webhooks
# ---------------------------------------------------------------------------


def test_webhooks_multiple_accounts_all_migrated():
    """Multiple accounts with webhooks: all migrated."""
    rows = [
        {
            "id": 16,
            "account_id": 1,
            "inbox_id": None,
            "url": "https://example.com/acct1_webhook",
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 17,
            "account_id": 2,
            "inbox_id": None,
            "url": "https://example.com/acct2_webhook",
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 18,
            "account_id": 3,
            "inbox_id": None,
            "url": "https://example.com/acct3_webhook",
            "created_at": None,
            "updated_at": None,
        },
    ]

    migrator, _ = _make_migrator(source_rows=rows, migrated={"accounts": {1, 2, 3}})

    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=3, migrated=3, skipped=0)

    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.webhooks_migrator.Table"):
            migrator.migrate()

    # All 3 webhooks from different accounts should be migrated
    assert len(remapped_rows) == 3
    # Account IDs should be remapped
    assert remapped_rows[0]["account_id"] == 1 + 20
    assert remapped_rows[1]["account_id"] == 2 + 20
    assert remapped_rows[2]["account_id"] == 3 + 20


# ---------------------------------------------------------------------------
# T038-13 — Webhook ID offset remapping
# ---------------------------------------------------------------------------


def test_webhooks_id_remapping_with_offset():
    """Webhook ID is remapped using offset_webhooks."""
    rows = [
        {
            "id": 100,
            "account_id": 1,
            "inbox_id": None,
            "url": "https://example.com/webhook",
            "created_at": None,
            "updated_at": None,
        }
    ]

    migrator, remapper = _make_migrator(source_rows=rows, migrated={"accounts": {1}})

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

    # ID should be remapped: 100 + 10 (offset_webhooks)
    assert len(remapped_rows) == 1
    expected_id = remapper.remap(100, "webhooks")
    assert remapped_rows[0]["id"] == expected_id


# ---------------------------------------------------------------------------
# T038-14 — Webhook orphan account_id skipped
# ---------------------------------------------------------------------------


def test_webhooks_orphan_account_skipped():
    """Webhook with orphaned account_id is skipped."""
    rows = [
        {
            "id": 200,
            "account_id": 999,
            "inbox_id": None,
            "url": "https://example.com/unknown",
            "created_at": None,
            "updated_at": None,
        }
    ]

    migrator, _ = _make_migrator(source_rows=rows, migrated={"accounts": {1, 2}})

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

    # Should be skipped due to orphan account_id
    assert len(remapped_rows) == 0


# ---------------------------------------------------------------------------
# T038-15 — Webhook inbox_id NULL preserved
# ---------------------------------------------------------------------------


def test_webhooks_inbox_id_null_preserved():
    """When inbox_id is NULL in source, it remains NULL in destination."""
    rows = [
        {
            "id": 201,
            "account_id": 1,
            "inbox_id": None,
            "url": "https://example.com/global-webhook",
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
# T038-16 — Multiple webhooks same account different urls
# ---------------------------------------------------------------------------


def test_webhooks_multiple_different_urls():
    """Multiple webhooks for same account with different URLs all migrated."""
    rows = [
        {
            "id": 202,
            "account_id": 1,
            "inbox_id": 5,
            "url": "https://example.com/webhook-1",
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 203,
            "account_id": 1,
            "inbox_id": 5,
            "url": "https://example.com/webhook-2",
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 204,
            "account_id": 1,
            "inbox_id": 6,
            "url": "https://example.com/webhook-3",
            "created_at": None,
            "updated_at": None,
        },
    ]

    migrator, remapper = _make_migrator(
        source_rows=rows,
        migrated={"accounts": {1}, "inboxes": {5, 6}},
    )

    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=3, migrated=3, skipped=0)

    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.webhooks_migrator.Table"):
            migrator.migrate()

    # All 3 should be migrated
    assert len(remapped_rows) == 3
    # URLs preserved
    assert remapped_rows[0]["url"] == "https://example.com/webhook-1"
    assert remapped_rows[1]["url"] == "https://example.com/webhook-2"
    assert remapped_rows[2]["url"] == "https://example.com/webhook-3"


# ---------------------------------------------------------------------------
# T038-17 — Webhook with migrated inbox_id remapped
# ---------------------------------------------------------------------------


def test_webhooks_inbox_id_remapped():
    """When inbox_id is provided and inbox is migrated, inbox_id is remapped."""
    rows = [
        {
            "id": 205,
            "account_id": 1,
            "inbox_id": 10,
            "url": "https://example.com/inbox-webhook",
            "created_at": None,
            "updated_at": None,
        }
    ]

    migrator, remapper = _make_migrator(
        source_rows=rows,
        migrated={"accounts": {1}, "inboxes": {10}},
    )

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
    expected_inbox_id = remapper.remap(10, "inboxes")
    assert remapped_rows[0]["inbox_id"] == expected_inbox_id


# ---------------------------------------------------------------------------
# T038-18 — Empty source returns 0 migrated/skipped
# ---------------------------------------------------------------------------


def test_webhooks_empty_source_returns_zero():
    """Empty source returns MigrationResult with 0 migrated and 0 skipped."""
    migrator, _ = _make_migrator(source_rows=[], migrated={"accounts": {1}})

    with patch("src.migrators.webhooks_migrator.Table"):
        result = migrator.migrate()

    assert result.total_source == 0
    assert result.migrated == 0
    assert result.skipped == 0


# ---------------------------------------------------------------------------
# T038-19 — Webhook events field preserved
# ---------------------------------------------------------------------------


def test_webhooks_events_field_preserved():
    """events field (webhook event subscriptions) is copied as-is."""
    rows = [
        {
            "id": 206,
            "account_id": 1,
            "inbox_id": None,
            "url": "https://example.com/webhook",
            "events": "conversation_created,conversation_updated,message_created",
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
    assert remapped_rows[0]["events"] == "conversation_created,conversation_updated,message_created"


# ---------------------------------------------------------------------------
# T038-20 — Webhook enabled field preserved
# ---------------------------------------------------------------------------


def test_webhooks_enabled_field_preserved():
    """enabled boolean field is preserved through migration."""
    rows = [
        {
            "id": 207,
            "account_id": 1,
            "inbox_id": None,
            "url": "https://example.com/webhook",
            "enabled": True,
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
    assert remapped_rows[0].get("enabled") is True


# ---------------------------------------------------------------------------
# T038-21 — Multiple webhooks with mixed enabled status
# ---------------------------------------------------------------------------


def test_webhooks_multiple_with_mixed_enabled_status():
    """Multiple webhooks with varying enabled status all migrated correctly."""
    rows = [
        {
            "id": 208,
            "account_id": 1,
            "inbox_id": None,
            "url": "https://example.com/webhook1",
            "enabled": True,
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 209,
            "account_id": 1,
            "inbox_id": None,
            "url": "https://example.com/webhook2",
            "enabled": False,
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
        return MigrationResult(table=table_name, total_source=2, migrated=2, skipped=0)

    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.webhooks_migrator.Table"):
            migrator.migrate()

    assert len(remapped_rows) == 2
    assert remapped_rows[0].get("enabled") is True
    assert remapped_rows[1].get("enabled") is False


# ---------------------------------------------------------------------------
# T038-22 — Webhook with missing optional fields
# ---------------------------------------------------------------------------


def test_webhooks_with_missing_optional_fields():
    """Webhook with minimal fields (no events, no enabled) migrates successfully."""
    rows = [
        {
            "id": 210,
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
    # ID and FKs should be present
    assert remapped_rows[0]["id"] is not None
    assert remapped_rows[0]["account_id"] is not None
    assert remapped_rows[0]["url"] is not None


# ---------------------------------------------------------------------------
# POC Helper Methods — _table_name, _fetch_all_source_rows, _classify_row_poc
# ---------------------------------------------------------------------------


def test_webhooks_table_name():
    """_table_name() returns 'webhooks'."""
    migrator, _ = _make_migrator()
    assert migrator._table_name() == "webhooks"


def test_webhooks_fetch_all_source_rows():
    """_fetch_all_source_rows() fetches and reflects all rows."""
    rows = [
        {"id": 1, "account_id": 1, "url": "https://example.com/webhook1"},
        {"id": 2, "account_id": 1, "url": "https://example.com/webhook2"},
    ]
    migrator, _ = _make_migrator(source_rows=rows)

    with patch("src.migrators.webhooks_migrator.Table") as mock_table:
        mock_table_inst = MagicMock()
        mock_table.return_value = mock_table_inst
        result = migrator._fetch_all_source_rows()

    assert len(result) == 2
    assert result[0]["id"] == 1
    assert result[1]["url"] == "https://example.com/webhook2"


def test_webhooks_classify_row_poc_clean():
    """_classify_row_poc returns WOULD_MIGRATE for clean row."""
    from src.reports.poc_reporter import Outcome

    migrator, _ = _make_migrator()
    row = {"account_id": 1}
    migrated_sets = {"accounts": {1}}

    outcome, reason = migrator._classify_row_poc(row, migrated_sets)

    assert outcome == Outcome.WOULD_MIGRATE
    assert reason == "clean"


def test_webhooks_classify_row_poc_orphan():
    """_classify_row_poc returns ORPHAN_FK_SKIP for orphan account."""
    from src.reports.poc_reporter import Outcome

    migrator, _ = _make_migrator()
    row = {"account_id": 999}
    migrated_sets = {"accounts": {1}}

    outcome, reason = migrator._classify_row_poc(row, migrated_sets)

    assert outcome == Outcome.ORPHAN_FK_SKIP
    assert "account" in reason.lower()
