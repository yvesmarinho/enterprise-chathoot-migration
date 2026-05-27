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
from sqlalchemy.exc import NoSuchTableError

from src.migrators.base_migrator import BaseMigrator, MigrationResult
from src.utils.schema_bootstrap import ensure_public_table_exists


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
        try:
            dest_table = Table(
                "active_storage_attachments", dest_meta, autoload_with=self.dest_engine
            )
        except NoSuchTableError:
            self.logger.warning(
                "ActiveStorageAttachmentsMigrator: DEST public.active_storage_attachments missing — bootstrapping from SOURCE"
            )
            ensure_public_table_exists(
                self.source_engine,
                self.dest_engine,
                "active_storage_attachments",
            )
            dest_table = Table(
                "active_storage_attachments", dest_meta, autoload_with=self.dest_engine
            )

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

        # DEDUPLICACAO: buscar chave unica -> id no DEST
        # UNIQUE(record_type, record_id, name, blob_id)
        existing_attachments: dict[tuple[str, int, str, int], int] = {}
        with self.dest_engine.connect() as conn:
            from sqlalchemy import select

            existing_query = select(
                dest_table.c.id,
                dest_table.c.record_type,
                dest_table.c.record_id,
                dest_table.c.name,
                dest_table.c.blob_id,
            )
            for row in conn.execute(existing_query):
                key = (str(row[1]), int(row[2]), str(row[3]), int(row[4]))
                existing_attachments[key] = int(row[0])

        self.logger.info(
            "ActiveStorageAttachmentsMigrator: %d existing attachment keys in DEST",
            len(existing_attachments),
        )

        # PRE-PROCESSAR duplicatas no DEST e registrar mapeamentos (bulk)
        duplicate_pairs: list[tuple[int, int]] = []
        for row in rows:
            id_origin = int(row["id"])
            blob_id_origin = int(row["blob_id"])
            record_type = str(row["record_type"])
            record_id_origin = int(row["record_id"])
            name = str(row["name"])

            if blob_id_origin not in migrated_blobs:
                continue

            table_name = self.RECORD_TYPE_TABLE_MAP.get(record_type)
            if not table_name:
                continue

            migrated_set = migrated_sets.get(table_name)
            if migrated_set is None or record_id_origin not in migrated_set:
                continue

            blob_id_dest = self.id_remapper.remap(blob_id_origin, "active_storage_blobs")
            record_id_dest = self.id_remapper.remap(record_id_origin, table_name)
            unique_key = (record_type, record_id_dest, name, blob_id_dest)

            if unique_key in existing_attachments:
                duplicate_pairs.append((id_origin, existing_attachments[unique_key]))

        if duplicate_pairs:
            with self.dest_engine.begin() as conn:
                self.state_repo.record_success_bulk(
                    conn, "active_storage_attachments", duplicate_pairs
                )

            for src_id, dest_id in duplicate_pairs:
                self.id_remapper.register_alias("active_storage_attachments", src_id, dest_id)

        self.logger.info(
            "ActiveStorageAttachmentsMigrator: %d duplicate attachment keys registered in migration_state (bulk)",
            len(duplicate_pairs),
        )

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

            blob_id_dest = self.id_remapper.remap(blob_id_origin, "active_storage_blobs")
            record_id_dest = self.id_remapper.remap(record_id_origin, table_name)
            unique_key = (record_type, record_id_dest, str(row["name"]), blob_id_dest)

            # Skip se ja existe no DEST (ja registrado no pre-processing acima)
            if unique_key in existing_attachments:
                return None

            # Remapear IDs
            return {
                **row,
                "id": self.id_remapper.remap(id_origin, "active_storage_attachments"),
                "blob_id": blob_id_dest,
                "record_id": record_id_dest,
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

        return (Outcome.WOULD_MIGRATE, "all FK dependencies satisfied")
