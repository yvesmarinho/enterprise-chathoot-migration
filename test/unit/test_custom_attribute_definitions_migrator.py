"""Unit tests for CustomAttributeDefinitionsMigrator (T023)."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

from src.migrators.base_migrator import MigrationResult
from src.migrators.custom_attribute_definitions_migrator import (
    CustomAttributeDefinitionsMigrator,
)
from src.repository.migration_state_repository import MigrationStateRepository
from src.utils.id_remapper import IDRemapper


def _make_migrator(source_rows=None, migrated_accounts=None):
    source_rows = source_rows or []
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
    state_repo.get_migrated_ids.side_effect = [migrated_accounts, set()]

    remapper = IDRemapper(
        {
            "custom_attribute_definitions": 100,
            "accounts": 20,
        }
    )
    logger = logging.getLogger("test_custom_attribute_definitions")

    return CustomAttributeDefinitionsMigrator(
        source_engine=source_engine,
        dest_engine=dest_engine,
        id_remapper=remapper,
        state_repo=state_repo,
        logger=logger,
    )


# ---------------------------------------------------------------------------
# T023-1 — account_id is remapped correctly
# ---------------------------------------------------------------------------


def test_custom_attribute_definitions_account_id_remapped():
    """account_id is remapped with offset_accounts during migration."""
    rows = [
        {
            "id": 1,
            "account_id": 1,
            "attribute_key": "customer_type",
            "attribute_display_name": "Customer Type",
            "attribute_model": "contact",
            "attribute_values": None,
            "attribute_type": "text",
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
        with patch("src.migrators.custom_attribute_definitions_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert remapped_rows[0]["account_id"] == 21  # 1 + 20
    assert remapped_rows[0]["id"] == 101  # 1 + 100


# ---------------------------------------------------------------------------
# T023-2 — Orphan account_id is skipped
# ---------------------------------------------------------------------------


def test_custom_attribute_definitions_orphan_account_id_skipped():
    """Attribute definition with unmigrated account_id is skipped."""
    rows = [
        {
            "id": 2,
            "account_id": 999,
            "attribute_key": "vip_status",
            "attribute_display_name": "VIP Status",
            "attribute_model": "contact",
            "attribute_values": None,
            "attribute_type": "text",
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
    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.custom_attribute_definitions_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert len(remapped_rows) == 0


# ---------------------------------------------------------------------------
# T023-3 — attribute_key field copied verbatim
# ---------------------------------------------------------------------------


def test_custom_attribute_definitions_key_unchanged():
    """attribute_key field is copied as-is without modification."""
    attr_key = "priority_level"
    rows = [
        {
            "id": 3,
            "account_id": 1,
            "attribute_key": attr_key,
            "attribute_display_name": "Priority Level",
            "attribute_model": "conversation",
            "attribute_values": None,
            "attribute_type": "text",
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

    migrator = _make_migrator(source_rows=rows)
    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.custom_attribute_definitions_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert remapped_rows[0]["attribute_key"] == attr_key


# ---------------------------------------------------------------------------
# T023-4 — Multiple account_ids with partial success
# ---------------------------------------------------------------------------


def test_custom_attribute_definitions_mixed_accounts_partial_skip():
    """Attribute definitions from mixed accounts skip only orphaned ones."""
    rows = [
        {
            "id": 1,
            "account_id": 1,
            "attribute_key": "field1",
            "attribute_display_name": "Field 1",
            "attribute_model": "contact",
            "attribute_values": None,
            "attribute_type": "text",
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 2,
            "account_id": 2,
            "attribute_key": "field2",
            "attribute_display_name": "Field 2",
            "attribute_model": "conversation",
            "attribute_values": None,
            "attribute_type": "text",
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 3,
            "account_id": 999,
            "attribute_key": "field3",
            "attribute_display_name": "Field 3",
            "attribute_model": "contact",
            "attribute_values": None,
            "attribute_type": "text",
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
        with patch("src.migrators.custom_attribute_definitions_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert len(remapped_rows) == 2
    assert len(skipped_rows) == 1
    assert skipped_rows == [3]
