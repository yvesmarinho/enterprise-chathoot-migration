"""Minimal unit tests for ActiveStorageBlobsMigrator (T049)."""

from unittest.mock import MagicMock

from src.migrators.active_storage_blobs_migrator import ActiveStorageBlobsMigrator
from src.repository.migration_state_repository import MigrationStateRepository
from src.utils.id_remapper import IDRemapper


def test_active_storage_blobs_can_instantiate():
    """Migrator can be instantiated with required dependencies."""
    source_engine = MagicMock()
    dest_engine = MagicMock()
    state_repo = MagicMock(spec=MigrationStateRepository)
    remapper = IDRemapper({"active_storage_blobs": 500})
    logger = MagicMock()

    migrator = ActiveStorageBlobsMigrator(
        source_engine=source_engine,
        dest_engine=dest_engine,
        id_remapper=remapper,
        state_repo=state_repo,
        logger=logger,
    )

    assert migrator is not None
    assert migrator.source_engine == source_engine
    assert migrator.dest_engine == dest_engine


def test_active_storage_blobs_table_name():
    """Table name is correct."""
    source_engine = MagicMock()
    dest_engine = MagicMock()
    state_repo = MagicMock(spec=MigrationStateRepository)
    remapper = IDRemapper({"active_storage_blobs": 500})
    logger = MagicMock()

    migrator = ActiveStorageBlobsMigrator(
        source_engine=source_engine,
        dest_engine=dest_engine,
        id_remapper=remapper,
        state_repo=state_repo,
        logger=logger,
    )

    assert migrator._table_name() == "active_storage_blobs"
