"""Migrator for the ``active_storage_attachments`` entity.

:description: Remaps FK columns:

    * ``id``       → ``id + offset_active_storage_attachments``
    * ``blob_id``  → ``blob_id + offset_active_storage_blobs`` (required — skip on orphan)
    * ``record_id`` → remapped based on ``record_type`` (polymorphic FK)

    Supported ``record_type`` values:
    * ``Attachment`` → remap via ``attachments`` offset
    * ``Contact``    → remap via ``contacts`` offset
    * ``User``       → remap via ``users`` offset
    * ``Inbox``      → remap via ``inboxes`` offset
    * ``AgentBot``   → remap via ``agent_bots`` offset (TODO: add migrator)
    * ``DataImport`` → remap via ``data_imports`` offset (TODO: add migrator)
    * ``ActiveStorage::VariantRecord`` → remap via ``active_storage_variant_records`` offset

    Records with unsupported ``record_type`` are skipped with warning.
"""

from __future__ import annotations

from sqlalchemy import MetaData, Table

from src.migrators.base_migrator import BaseMigrator, MigrationResult


class ActiveStorageAttachmentsMigrator(BaseMigrator):
    """Migrate all rows from ``active_storage_attachments`` source → destination.

    Handles polymorphic ``record_type`` FK remapping.

    :param source_engine: Read-only source engine.
    :type source_engine: Engine
    :param dest_engine: Read-write destination engine.
    :type dest_engine: Engine
    :param id_remapper: Session-scoped offset remapper.
    :type id_remapper: IDRemapper
    :param state_repo: Migration state control repository.
    :type state_repo: MigrationStateRepository
    :param logger: Logger with ``MaskingHandler`` attached.
    :type logger: logging.Logger
    """

    # Mapa de record_type para nome da tabela correspondente
    RECORD_TYPE_TABLE_MAP = {
        "Attachment": "attachments",
        "Contact": "contacts",
        "User": "users",
        "Inbox": "inboxes",
        "AgentBot": "agent_bots",
        "DataImport": "data_imports",
        "ActiveStorage::VariantRecord": "active_storage_variant_records",
    }

    def migrate(self) -> MigrationResult:
        """Execute active_storage_attachments migration.

        :returns: Migration result summary for ``active_storage_attachments``.
        :rtype: MigrationResult
        """
        self.logger.info("ActiveStorageAttachmentsMigrator: starting")
        src_meta = MetaData()
        src_table = Table("active_storage_attachments", src_meta, autoload_with=self.source_engine)
        dest_meta = MetaData()
        dest_table = Table("active_storage_attachments", dest_meta, autoload_with=self.dest_engine)

        with self.dest_engine.connect() as conn:
            migrated_blobs = self.state_repo.get_migrated_ids(conn, "active_storage_blobs")
            migrated_attachments = self.state_repo.get_migrated_ids(conn, "attachments")
            migrated_contacts = self.state_repo.get_migrated_ids(conn, "contacts")
            migrated_users = self.state_repo.get_migrated_ids(conn, "users")
            migrated_inboxes = self.state_repo.get_migrated_ids(conn, "inboxes")

        migrated_sets = {
            "active_storage_blobs": migrated_blobs,
            "attachments": migrated_attachments,
            "contacts": migrated_contacts,
            "users": migrated_users,
            "inboxes": migrated_inboxes,
        }

        rows = self._select_source_rows(src_table)

        self.logger.info("ActiveStorageAttachmentsMigrator: %d source rows fetched", len(rows))

        def remap_fn(row: dict) -> dict | None:
            """Remap PK and FK columns for an active_storage_attachments row.

            :param row: Source row as plain dict.
            :type row: dict
            :returns: Destination row with remapped IDs or ``None`` if FK orphan.
            :rtype: dict | None
            """
            id_origin = int(row["id"])
            blob_id_origin = int(row["blob_id"])
            record_type = row["record_type"]
            record_id_origin = int(row["record_id"])

            # Validar blob_id (FK obrigatória)
            if blob_id_origin not in migrated_blobs:
                self.logger.warning(
                    "ActiveStorageAttachmentsMigrator: id=%d skipped — orphan blob_id=%d",
                    id_origin,
                    blob_id_origin,
                )
                return None

            # Mapear record_type para nome da tabela
            table_name = self.RECORD_TYPE_TABLE_MAP.get(record_type)

            if not table_name:
                self.logger.warning(
                    "ActiveStorageAttachmentsMigrator: id=%d skipped — unsupported record_type=%s",
                    id_origin,
                    record_type,
                )
                return None

            # Verificar se a tabela correspondente foi migrada
            migrated_set = migrated_sets.get(table_name)

            if migrated_set is None:
                self.logger.warning(
                    "ActiveStorageAttachmentsMigrator: id=%d skipped — record_type=%s not yet migrated (table=%s)",
                    id_origin,
                    record_type,
                    table_name,
                )
                return None

            # Validar record_id (FK polimórfica)
            if record_id_origin not in migrated_set:
                self.logger.warning(
                    "ActiveStorageAttachmentsMigrator: id=%d skipped — orphan record_id=%d (record_type=%s, table=%s)",
                    id_origin,
                    record_id_origin,
                    record_type,
                    table_name,
                )
                return None

            # Remapear IDs
            return {
                **row,
                "id": self.id_remapper.remap(id_origin, "active_storage_attachments"),
                "blob_id": self.id_remapper.remap(blob_id_origin, "active_storage_blobs"),
                "record_id": self.id_remapper.remap(record_id_origin, table_name),
                # name, record_type, created_at copiados verbatim
            }

        result = self._run_batches(rows, "active_storage_attachments", dest_table, remap_fn)

        self.logger.info(
            "ActiveStorageAttachmentsMigrator: complete — migrated=%d skipped=%d failed=%d",
            result.migrated,
            result.skipped,
            len(result.failed_ids),
        )
        return result

    # ------------------------------------------------------------------
    # POC dry-run hooks
    # ------------------------------------------------------------------

    def _table_name(self) -> str:
        """Return canonical table name.

        :returns: ``"active_storage_attachments"``
        :rtype: str
        """
        return "active_storage_attachments"

    def _fetch_all_source_rows(self) -> list[dict]:
        """Fetch all rows from source ``active_storage_attachments``.

        :returns: All source rows as plain dicts.
        :rtype: list[dict]
        """
        src_meta = MetaData()
        src_table = Table("active_storage_attachments", src_meta, autoload_with=self.source_engine)
        return self._select_source_rows(src_table)

    def _classify_row_poc(  # type: ignore[override]
        self,
        row: dict,
        migrated_sets: dict[str, set[int]],
    ) -> tuple:
        """Classify an active_storage_attachments row for POC dry-run.

        Required FKs (skip on orphan): ``blob_id``, ``record_id`` (polymorphic).

        :param row: Source row as plain dict.
        :type row: dict
        :param migrated_sets: Dest ID sets keyed by table name.
        :type migrated_sets: dict[str, set[int]]
        :returns: ``(outcome, reason)`` tuple.
        :rtype: tuple
        """
        from src.reports.poc_reporter import Outcome

        blob_id = int(row["blob_id"])
        if blob_id not in migrated_sets.get("active_storage_blobs", set()):
            return (
                Outcome.ORPHAN_FK_SKIP,
                f"blob_id={blob_id} not in migrated blobs",
            )

        record_type = row["record_type"]
        record_id = int(row["record_id"])
        table_name = self.RECORD_TYPE_TABLE_MAP.get(record_type)

        if not table_name:
            return (
                Outcome.ORPHAN_FK_SKIP,
                f"unsupported record_type={record_type}",
            )

        if table_name not in migrated_sets:
            return (
                Outcome.ORPHAN_FK_SKIP,
                f"record_type={record_type} table={table_name} not migrated yet",
            )

        if record_id not in migrated_sets[table_name]:
            return (
                Outcome.ORPHAN_FK_SKIP,
                f"record_id={record_id} (record_type={record_type}) not in migrated {table_name}",
            )

        return (Outcome.INSERT, "all FK dependencies satisfied")
