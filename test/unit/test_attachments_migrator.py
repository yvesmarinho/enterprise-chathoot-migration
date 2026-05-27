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

    migrator = _make_migrator(source_rows=rows, migrated={"messages": {3}, "accounts": {1}})
    with patch.object(migrator, "_run_batches", side_effect=capture):
        with patch("src.migrators.attachments_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    r = remapped[0]
    assert r["id"] == 5 + 73435
    assert r["message_id"] == 3 + 1302949
    assert r["account_id"] == 1 + 20


# ---------------------------------------------------------------------------
# T033-5 — file_name preserved
# ---------------------------------------------------------------------------


def test_attachments_file_name_preserved():
    """file_name field is copied as-is without modification."""
    file_name = "document_2026.pdf"
    rows = [_base_row(id=6, message_id=1, account_id=1, file_name=file_name)]
    remapped = []

    def capture(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    migrator = _make_migrator(source_rows=rows, migrated={"messages": {1}, "accounts": {1}})
    with patch.object(migrator, "_run_batches", side_effect=capture):
        with patch("src.migrators.attachments_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert remapped[0]["file_name"] == file_name


# ---------------------------------------------------------------------------
# T033-6 — mixed accounts partial skip
# ---------------------------------------------------------------------------


def test_attachments_mixed_accounts_partial_skip():
    """Attachments from multiple accounts skip only those with orphaned FKs."""
    rows = [
        _base_row(id=7, message_id=1, account_id=1),
        _base_row(id=8, message_id=2, account_id=2),
        _base_row(id=9, message_id=999, account_id=1),
    ]
    remapped = []
    skipped = []

    def capture(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped.append(r)
            else:
                skipped.append(row["id"])
        return MigrationResult(table=table_name, total_source=3, migrated=2, skipped=1)

    migrator = _make_migrator(source_rows=rows, migrated={"messages": {1, 2}, "accounts": {1, 2}})
    with patch.object(migrator, "_run_batches", side_effect=capture):
        with patch("src.migrators.attachments_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert len(remapped) == 2
    assert len(skipped) == 1
    assert 9 in skipped


# ---------------------------------------------------------------------------
# T033-7 — Empty source no-op
# ---------------------------------------------------------------------------


def test_attachments_empty_source():
    """Empty source rows returns MigrationResult(0 migrated, 0 skipped)."""
    migrator = _make_migrator(source_rows=[], migrated={"messages": {1}, "accounts": {1}})

    result = None
    with patch("src.migrators.attachments_migrator.Table"):
        result = migrator.migrate()

    assert result.total_source == 0
    assert result.migrated == 0
    assert result.skipped == 0


# ---------------------------------------------------------------------------
# T033-8 — ID remapping with offset_attachments
# ---------------------------------------------------------------------------


def test_attachments_id_remapping_offset():
    """Attachment ID is remapped using offset_attachments."""
    rows = [_base_row(id=100, message_id=1, account_id=1)]
    remapped = []

    def capture(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    migrator = _make_migrator(source_rows=rows, migrated={"messages": {1}, "accounts": {1}})
    with patch.object(migrator, "_run_batches", side_effect=capture):
        with patch("src.migrators.attachments_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    # ID should be remapped with offset (exact offset depends on id_remapper setup)
    assert len(remapped) == 1
    assert remapped[0]["id"] > 100  # At least offset applied


# ---------------------------------------------------------------------------
# T033-9 — File type preserved
# ---------------------------------------------------------------------------


def test_attachments_file_type_preserved():
    """file_type field is copied as-is without modification."""
    file_type = "application/pdf"
    rows = [_base_row(id=10, message_id=1, account_id=1, file_type=file_type)]
    remapped = []

    def capture(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    migrator = _make_migrator(source_rows=rows, migrated={"messages": {1}, "accounts": {1}})
    with patch.object(migrator, "_run_batches", side_effect=capture):
        with patch("src.migrators.attachments_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert remapped[0]["file_type"] == file_type


# ---------------------------------------------------------------------------
# T033-10 — Orphan account_id skipped
# ---------------------------------------------------------------------------


def test_attachments_orphan_account_skipped():
    """Attachment with orphaned account_id is skipped."""
    rows = [_base_row(id=11, message_id=1, account_id=999)]
    remapped = []
    skipped = []

    def capture(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped.append(r)
            else:
                skipped.append(row["id"])
        return MigrationResult(table=table_name, total_source=1, migrated=0, skipped=1)

    migrator = _make_migrator(source_rows=rows, migrated={"messages": {1}, "accounts": {1, 2}})
    with patch.object(migrator, "_run_batches", side_effect=capture):
        with patch("src.migrators.attachments_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert len(remapped) == 0
    assert 11 in skipped


# ---------------------------------------------------------------------------
# T033-11 — Multiple attachments same message
# ---------------------------------------------------------------------------


def test_attachments_multiple_same_message():
    """Multiple attachments for same message all migrated successfully."""
    rows = [
        _base_row(id=12, message_id=1, account_id=1, file_name="doc1.pdf"),
        _base_row(id=13, message_id=1, account_id=1, file_name="doc2.pdf"),
        _base_row(id=14, message_id=1, account_id=1, file_name="doc3.pdf"),
    ]
    remapped = []

    def capture(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped.append(r)
        return MigrationResult(table=table_name, total_source=3, migrated=3, skipped=0)

    migrator = _make_migrator(source_rows=rows, migrated={"messages": {1}, "accounts": {1}})
    with patch.object(migrator, "_run_batches", side_effect=capture):
        with patch("src.migrators.attachments_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert len(remapped) == 3
    assert remapped[0]["file_name"] == "doc1.pdf"
    assert remapped[1]["file_name"] == "doc2.pdf"
    assert remapped[2]["file_name"] == "doc3.pdf"


# ---------------------------------------------------------------------------
# T033-12 — Empty source no-op
# ---------------------------------------------------------------------------


def test_attachments_empty_source_no_op():
    """Empty source returns MigrationResult with 0 migrated/skipped."""
    rows = []
    migrator = _make_migrator(source_rows=rows, migrated={"messages": {1}, "accounts": {1}})

    with patch("src.migrators.attachments_migrator.Table"):
        result = migrator.migrate()

    assert result.total_source == 0
    assert result.migrated == 0
    assert result.skipped == 0


# ---------------------------------------------------------------------------
# T033-13 — Multiple attachments different messages
# ---------------------------------------------------------------------------


def test_attachments_multiple_different_messages():
    """Multiple attachments for different messages all migrated successfully."""
    rows = [
        _base_row(id=15, message_id=1, account_id=1),
        _base_row(id=16, message_id=2, account_id=1),
        _base_row(id=17, message_id=3, account_id=1),
    ]
    remapped = []

    def capture(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped.append(r)
        return MigrationResult(table=table_name, total_source=3, migrated=3, skipped=0)

    migrator = _make_migrator(source_rows=rows, migrated={"messages": {1, 2, 3}, "accounts": {1}})
    with patch.object(migrator, "_run_batches", side_effect=capture):
        with patch("src.migrators.attachments_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert len(remapped) == 3
    # Each message_id should be remapped
    assert remapped[0]["message_id"] == 1 + 1302949
    assert remapped[1]["message_id"] == 2 + 1302949
    assert remapped[2]["message_id"] == 3 + 1302949


# ---------------------------------------------------------------------------
# T033-14 — Mixed valid and orphan messages
# ---------------------------------------------------------------------------


def test_attachments_mixed_valid_orphan_messages():
    """Multiple attachments: some with valid messages, some orphan (skipped)."""
    rows = [
        _base_row(id=18, message_id=1, account_id=1),
        _base_row(id=19, message_id=999, account_id=1),  # orphan message
        _base_row(id=20, message_id=2, account_id=1),
    ]
    remapped = []
    skipped = []

    def capture(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped.append(r)
            else:
                skipped.append(row["id"])
        return MigrationResult(table=table_name, total_source=3, migrated=2, skipped=1)

    migrator = _make_migrator(source_rows=rows, migrated={"messages": {1, 2}, "accounts": {1}})
    with patch.object(migrator, "_run_batches", side_effect=capture):
        with patch("src.migrators.attachments_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert len(remapped) == 2
    assert len(skipped) == 1
    assert 19 in skipped


# ---------------------------------------------------------------------------
# POC Helper Methods — _table_name, _fetch_all_source_rows, _classify_row_poc
# ---------------------------------------------------------------------------


def test_attachments_table_name():
    """_table_name() returns 'attachments'."""
    migrator = _make_migrator()
    assert migrator._table_name() == "attachments"


def test_attachments_fetch_all_source_rows():
    """_fetch_all_source_rows() returns all source rows."""
    rows = [
        _base_row(id=1, message_id=10, account_id=1),
        _base_row(id=2, message_id=11, account_id=1),
    ]
    migrator = _make_migrator(source_rows=rows)

    with patch("src.migrators.attachments_migrator.Table"):
        result = migrator._fetch_all_source_rows()

    assert len(result) == 2
    assert result[0]["message_id"] == 10
    assert result[1]["account_id"] == 1


def test_attachments_classify_row_poc_clean():
    """_classify_row_poc returns WOULD_MIGRATE for clean attachment row."""
    from src.reports.poc_reporter import Outcome

    migrator = _make_migrator()
    row = _base_row(id=1, message_id=1, account_id=1)
    migrated_sets = {"messages": {1}, "accounts": {1}}

    outcome, reason = migrator._classify_row_poc(row, migrated_sets)

    assert outcome == Outcome.WOULD_MIGRATE
    assert reason == "clean"
