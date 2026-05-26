"""Migrator for the ``active_storage_blobs`` entity.

:description: Migrates ``active_storage_blobs`` (S3 metadata).
    This is the root table for ActiveStorage — no foreign keys.

    IDs are remapped using offset strategy:
    * ``id`` → ``id + offset_active_storage_blobs``

    Critical fields preserved verbatim:
    * ``key`` — S3 blob key (28 chars alfanuméricos)
    * ``filename`` — original filename
    * ``service_name`` — 'amazon' para S3
    * ``checksum`` — MD5 hash para validação
"""

from __future__ import annotations

from sqlalchemy import MetaData, Table

from src.migrators.base_migrator import BaseMigrator, MigrationResult


class ActiveStorageBlobsMigrator(BaseMigrator):
    """Migrate all rows from ``active_storage_blobs`` source → destination.

    This is the root table for ActiveStorage metadata. No FK dependencies.
    All fields copied verbatim except ``id`` (remapped).

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

    def migrate(self) -> MigrationResult:
        """Execute active_storage_blobs migration.

        :returns: Migration result summary for ``active_storage_blobs``.
        :rtype: MigrationResult
        """
        self.logger.info("ActiveStorageBlobsMigrator: starting")
        src_meta = MetaData()
        src_table = Table("active_storage_blobs", src_meta, autoload_with=self.source_engine)
        dest_meta = MetaData()
        dest_table = Table("active_storage_blobs", dest_meta, autoload_with=self.dest_engine)

        rows = self._select_source_rows(src_table)

        self.logger.info("ActiveStorageBlobsMigrator: %d source rows fetched", len(rows))

        # DEDUPLICAÇÃO: buscar key → id mapping do DEST
        existing_key_to_id = {}
        with self.dest_engine.connect() as conn:
            from sqlalchemy import select

            existing_query = select(dest_table.c.id, dest_table.c.key)
            for row in conn.execute(existing_query):
                existing_key_to_id[row[1]] = row[0]  # key → id

        self.logger.info("ActiveStorageBlobsMigrator: %d existing keys in DEST", len(existing_key_to_id))

        # PRÉ-PROCESSAR duplicates e registrar mapeamentos (FIX D21)
        duplicates_registered = 0
        with self.dest_engine.begin() as conn:
            for row in rows:
                id_origin = int(row["id"])
                key = row["key"]

                if key in existing_key_to_id:
                    # Key já existe — registrar mapeamento para downstream migrators
                    id_destino_existente = existing_key_to_id[key]

                    # Salvar na migration_state
                    self.state_repo.save_mapping(
                        conn, "active_storage_blobs", id_origin, id_destino_existente
                    )

                    self.logger.debug(
                        "ActiveStorageBlobsMigrator: id=%d → id=%d (key '%s' exists, reusing)",
                        id_origin,
                        id_destino_existente,
                        key,
                    )
                    duplicates_registered += 1

        self.logger.info(
            "ActiveStorageBlobsMigrator: %d duplicate keys registered in migration_state",
            duplicates_registered,
        )

        def remap_fn(row: dict) -> dict | None:
            """Remap PK for an active_storage_blobs row.

            :param row: Source row as plain dict.
            :type row: dict
            :returns: Destination row with remapped ID, or None if key exists.
            :rtype: dict | None
            """
            id_origin = int(row["id"])
            key = row["key"]

            # Skip se key já existe (já foi registrado no pre-processing acima)
            if key in existing_key_to_id:
                return None

            return {
                **row,
                "id": self.id_remapper.remap(id_origin, "active_storage_blobs"),
                # All other fields copied verbatim:
                # key, filename, content_type, metadata, byte_size, checksum,
                # created_at, service_name
            }

        result = self._run_batches(rows, "active_storage_blobs", dest_table, remap_fn)

        self.logger.info(
            "ActiveStorageBlobsMigrator: complete — migrated=%d skipped=%d failed=%d",
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

        :returns: ``"active_storage_blobs"``
        :rtype: str
        """
        return "active_storage_blobs"

    def _fetch_all_source_rows(self) -> list[dict]:
        """Fetch all rows from source ``active_storage_blobs``.

        :returns: All source rows as plain dicts.
        :rtype: list[dict]
        """
        src_meta = MetaData()
        src_table = Table("active_storage_blobs", src_meta, autoload_with=self.source_engine)
        return self._select_source_rows(src_table)

    def _classify_row_poc(  # type: ignore[override]
        self,
        row: dict,
        migrated_sets: dict[str, set[int]],
    ) -> tuple:
        """Classify an active_storage_blobs row for POC dry-run.

        No FK dependencies — always INSERT.

        :param row: Source row as plain dict.
        :type row: dict
        :param migrated_sets: Dest ID sets keyed by table name.
        :type migrated_sets: dict[str, set[int]]
        :returns: ``(outcome, reason)`` tuple.
        :rtype: tuple
        """
        from src.reports.poc_reporter import Outcome

        return (Outcome.INSERT, "no FK dependencies")
