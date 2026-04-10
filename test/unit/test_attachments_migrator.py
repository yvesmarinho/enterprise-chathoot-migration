"""Unit tests for AttachmentsMigrator (T033)."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

from src.migrators.attachments_migrator import AttachmentsMigrator
from src.migrators.base_migrator import MigrationResult
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
    state_repo.get_migrated_ids.side_effect = [
        migrated.get("messages", {1}),
        migrated.get("accounts", {1}),
        set(),  # already_migrated attachments
    ]

    remapper = IDRemapper(
        {
            "attachments": 73435,
            "messages": 1302949,
            "accounts": 20,
        }
    )
    logger = logging.getLogger("test_attachments")

    return AttachmentsMigrator(
        source_engine=source_engine,
        dest_engine=dest_engine,
        id_remapper=remapper,
        state_repo=state_repo,
        logger=logger,
    )


def _base_row(**overrides):
    base = {
        "id": 1,
        "message_id": 1,
        "account_id": 1,
        "file_type": "image",
        "external_url": "https://s3.example.com/file.jpg",
        "created_at": None,
        "updated_at": None,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# T033-1 — external_url is copied verbatim (no modification)
# ---------------------------------------------------------------------------


def test_attachments_external_url_copied_verbatim():
    """external_url S3 reference is passed through unchanged."""
    url = "https://s3.amazonaws.com/bucket/path/file.pdf"
    rows = [_base_row(external_url=url)]
    remapped = []

    def capture(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    migrator = _make_migrator(source_rows=rows)
    with patch.object(migrator, "_run_batches", side_effect=capture):
        with patch("src.migrators.attachments_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert remapped[0]["external_url"] == url


# ---------------------------------------------------------------------------
# T033-2 — Orphan message_id → record skipped
# ---------------------------------------------------------------------------


def test_attachments_orphan_message_id_skipped():
    """Attachments with orphan message_id are skipped."""
    rows = [_base_row(message_id=9999)]
    remapped = []

    def capture(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=0, skipped=1)

    migrator = _make_migrator(source_rows=rows, migrated={"messages": {1, 2}})
    with patch.object(migrator, "_run_batches", side_effect=capture):
        with patch("src.migrators.attachments_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert remapped == []


# ---------------------------------------------------------------------------
# T033-3 — No S3 API calls during migration
# ---------------------------------------------------------------------------


def test_attachments_no_s3_calls():
    """Attachments migration never makes external HTTP/S3 API calls."""
    rows = [_base_row()]

    migrator = _make_migrator(source_rows=rows)

    # Verify no boto3 or requests import is triggered
    with patch.dict("sys.modules", {"boto3": None, "requests": None}):
        with patch.object(
            migrator,
            "_run_batches",
            return_value=MigrationResult(
                table="attachments", total_source=1, migrated=1, skipped=0
            ),
        ):
            with patch("src.migrators.attachments_migrator.Table") as mock_table:
                mock_table.return_value = MagicMock()
                # Should complete without any ImportError or boto3 calls
                result = migrator.migrate()

    assert result.migrated == 1


# ---------------------------------------------------------------------------
# T033-4 — FK remapping verified
# ---------------------------------------------------------------------------


def test_attachments_fk_remapping():
    """id, message_id, account_id are all remapped correctly."""
    rows = [_base_row(id=5, message_id=3, account_id=1)]
    remapped = []

    def capture(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    migrator = _make_migrator(
        source_rows=rows, migrated={"messages": {3}, "accounts": {1}}
    )
    with patch.object(migrator, "_run_batches", side_effect=capture):
        with patch("src.migrators.attachments_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    r = remapped[0]
    assert r["id"] == 5 + 73435
    assert r["message_id"] == 3 + 1302949
    assert r["account_id"] == 1 + 20
