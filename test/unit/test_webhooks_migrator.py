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
        set(),  # already_migrated
    ]

    remapper = IDRemapper({"webhooks": 10, "accounts": 20})
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
