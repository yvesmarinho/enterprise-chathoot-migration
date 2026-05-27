"""Minimal unit tests for ActiveStorageBlobsMigrator (T049)."""

from unittest.mock import MagicMock, patch

from src.migrators.active_storage_blobs_migrator import ActiveStorageBlobsMigrator
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
    remapper = IDRemapper({"active_storage_blobs": 500})
    logger = MagicMock()

    return ActiveStorageBlobsMigrator(
        source_engine=source_engine,
        dest_engine=dest_engine,
        id_remapper=remapper,
        state_repo=state_repo,
        logger=logger,
    )


def test_active_storage_blobs_can_instantiate():
    """Migrator can be instantiated with required dependencies."""
    migrator = _make_migrator()
    assert migrator is not None
    assert migrator.source_engine is not None
    assert migrator.dest_engine is not None


def test_active_storage_blobs_table_name():
    """Table name is correct."""
    migrator = _make_migrator()
    assert migrator._table_name() == "active_storage_blobs"


def test_active_storage_blobs_fetch_all_source_rows():
    """_fetch_all_source_rows() returns all source rows."""
    rows = [
        {"id": 1, "key": "blob1", "filename": "file.pdf", "checksum": "abc123"},
        {"id": 2, "key": "blob2", "filename": "file.jpg", "checksum": "def456"},
    ]
    migrator = _make_migrator(source_rows=rows)

    with patch("src.migrators.active_storage_blobs_migrator.Table"):
        result = migrator._fetch_all_source_rows()

    assert len(result) == 2
    assert result[0]["key"] == "blob1"
    assert result[1]["checksum"] == "def456"


def test_active_storage_blobs_classify_row_poc_clean():
    """_classify_row_poc returns WOULD_MIGRATE for clean row (no FKs)."""
    from src.reports.poc_reporter import Outcome

    migrator = _make_migrator()
    row = {"id": 1, "key": "blob1", "filename": "file.pdf", "checksum": "abc123"}
    migrated_sets = {}

    outcome, reason = migrator._classify_row_poc(row, migrated_sets)

    assert outcome == Outcome.WOULD_MIGRATE
    assert "FK dependencies" in reason
