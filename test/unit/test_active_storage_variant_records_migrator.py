"""Minimal unit tests for ActiveStorageVariantRecordsMigrator (T048)."""

from unittest.mock import MagicMock, patch

from src.migrators.active_storage_variant_records_migrator import (
    ActiveStorageVariantRecordsMigrator,
)
from src.repository.migration_state_repository import MigrationStateRepository
from src.utils.id_remapper import IDRemapper


def _make_migrator(source_rows=None):
    """Build migrator with standard dependencies."""
    source_rows = source_rows or []
    
    source_engine = MagicMock()
    dest_engine = MagicMock()
    
    src_conn = MagicMock()
    src_conn.__enter__ = MagicMock(return_value=src_conn)
    src_conn.__exit__ = MagicMock(return_value=False)
    src_conn.execute.return_value.mappings.return_value.all.return_value = source_rows
    source_engine.connect.return_value = src_conn
    
    state_repo = MagicMock(spec=MigrationStateRepository)
    remapper = IDRemapper(
        {
            "active_storage_variant_records": 1000,
            "active_storage_blobs": 500,
        }
    )
    logger = MagicMock()

    return ActiveStorageVariantRecordsMigrator(
        source_engine=source_engine,
        dest_engine=dest_engine,
        id_remapper=remapper,
        state_repo=state_repo,
        logger=logger,
    )


def test_active_storage_variant_records_can_instantiate():
    """Migrator can be instantiated with required dependencies."""
    migrator = _make_migrator()
    assert migrator is not None
    assert migrator.source_engine is not None
    assert migrator.dest_engine is not None


def test_active_storage_variant_records_table_name():
    """Table name is correct."""
    migrator = _make_migrator()
    assert migrator._table_name() == "active_storage_variant_records"


def test_active_storage_variant_records_fetch_all_source_rows():
    """_fetch_all_source_rows() returns all source rows."""
    rows = [
        {"id": 1, "blob_id": 100, "variation_digest": "digest1"},
        {"id": 2, "blob_id": 101, "variation_digest": "digest2"},
    ]
    migrator = _make_migrator(source_rows=rows)

    with patch("src.migrators.active_storage_variant_records_migrator.Table"):
        result = migrator._fetch_all_source_rows()

    assert len(result) == 2
    assert result[0]["blob_id"] == 100
    assert result[1]["variation_digest"] == "digest2"


def test_active_storage_variant_records_classify_row_poc_orphan_blob():
    """_classify_row_poc returns ORPHAN_FK_SKIP for missing blob_id."""
    from src.reports.poc_reporter import Outcome

    migrator = _make_migrator()
    row = {"id": 1, "blob_id": 999, "variation_digest": "digest1"}
    migrated_sets = {"active_storage_blobs": {100, 101}}

    outcome, reason = migrator._classify_row_poc(row, migrated_sets)

    assert outcome == Outcome.ORPHAN_FK_SKIP
    assert "blob_id=999" in reason


def test_active_storage_variant_records_classify_row_poc_clean():
    """_classify_row_poc returns WOULD_MIGRATE for clean row."""
    from src.reports.poc_reporter import Outcome

    migrator = _make_migrator()
    row = {"id": 1, "blob_id": 100, "variation_digest": "digest1"}
    migrated_sets = {"active_storage_blobs": {100, 101}}

    outcome, reason = migrator._classify_row_poc(row, migrated_sets)

    assert outcome == Outcome.WOULD_MIGRATE
    assert "dependency satisfied" in reason
