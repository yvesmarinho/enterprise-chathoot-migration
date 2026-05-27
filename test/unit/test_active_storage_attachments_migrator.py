"""Minimal unit tests for ActiveStorageAttachmentsMigrator (T047)."""

from unittest.mock import MagicMock

from src.migrators.active_storage_attachments_migrator import ActiveStorageAttachmentsMigrator
from src.repository.migration_state_repository import MigrationStateRepository
from src.utils.id_remapper import IDRemapper


def test_active_storage_attachments_can_instantiate():
    """Migrator can be instantiated with required dependencies."""
    source_engine = MagicMock()
    dest_engine = MagicMock()
    state_repo = MagicMock(spec=MigrationStateRepository)
    remapper = IDRemapper(
        {
            "active_storage_attachments": 200000,
            "active_storage_blobs": 500,
            "attachments": 73435,
            "contacts": 225536,
        }
    )
    logger = MagicMock()

    migrator = ActiveStorageAttachmentsMigrator(
        source_engine=source_engine,
        dest_engine=dest_engine,
        id_remapper=remapper,
        state_repo=state_repo,
        logger=logger,
    )

    assert migrator is not None
    assert migrator.source_engine == source_engine
    assert migrator.dest_engine == dest_engine


def test_active_storage_attachments_table_name():
    """Table name is correct."""
    source_engine = MagicMock()
    dest_engine = MagicMock()
    state_repo = MagicMock(spec=MigrationStateRepository)
    remapper = IDRemapper(
        {
            "active_storage_attachments": 200000,
            "active_storage_blobs": 500,
            "attachments": 73435,
            "contacts": 225536,
        }
    )
    logger = MagicMock()

    migrator = ActiveStorageAttachmentsMigrator(
        source_engine=source_engine,
        dest_engine=dest_engine,
        id_remapper=remapper,
        state_repo=state_repo,
        logger=logger,
    )

    assert migrator._table_name() == "active_storage_attachments"


def test_active_storage_attachments_record_type_map():
    """Record type map has expected entries."""
    source_engine = MagicMock()
    dest_engine = MagicMock()
    state_repo = MagicMock(spec=MigrationStateRepository)
    remapper = IDRemapper(
        {
            "active_storage_attachments": 200000,
            "active_storage_blobs": 500,
            "attachments": 73435,
            "contacts": 225536,
        }
    )
    logger = MagicMock()

    migrator = ActiveStorageAttachmentsMigrator(
        source_engine=source_engine,
        dest_engine=dest_engine,
        id_remapper=remapper,
        state_repo=state_repo,
        logger=logger,
    )

    # Verify record type map
    assert "Attachment" in migrator.RECORD_TYPE_TABLE_MAP
    assert "Contact" in migrator.RECORD_TYPE_TABLE_MAP
    assert "User" in migrator.RECORD_TYPE_TABLE_MAP
    assert "Inbox" in migrator.RECORD_TYPE_TABLE_MAP
    assert migrator.RECORD_TYPE_TABLE_MAP["Attachment"] == "attachments"
    assert migrator.RECORD_TYPE_TABLE_MAP["Contact"] == "contacts"
