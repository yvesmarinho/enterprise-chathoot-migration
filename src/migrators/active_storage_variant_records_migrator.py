"""Migrator for the ``active_storage_variant_records`` entity.

:description: Remaps FK columns:

    * ``id``       → ``id + offset_active_storage_variant_records``
    * ``blob_id``  → ``blob_id + offset_active_storage_blobs`` (required — skip on orphan)

    This table stores metadata about image variants (thumbnails, resized versions).
    It depends on ``active_storage_blobs`` only.
"""

from __future__ import annotations

from sqlalchemy import MetaData, Table
from sqlalchemy.exc import NoSuchTableError

from src.migrators.base_migrator import BaseMigrator, MigrationResult
from src.utils.schema_bootstrap import ensure_public_table_exists


class ActiveStorageVariantRecordsMigrator(BaseMigrator):
    """Migrate all rows from ``active_storage_variant_records`` source → destination.

    Depends on ``active_storage_blobs`` (FK blob_id).

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
        """Execute active_storage_variant_records migration.

        :returns: Migration result summary for ``active_storage_variant_records``.
        :rtype: MigrationResult
        """
        self.logger.info("ActiveStorageVariantRecordsMigrator: starting")
        src_meta = MetaData()
        src_table = Table(
            "active_storage_variant_records", src_meta, autoload_with=self.source_engine
        )
        dest_meta = MetaData()
        try:
            dest_table = Table(
                "active_storage_variant_records", dest_meta, autoload_with=self.dest_engine
            )
        except NoSuchTableError:
            self.logger.warning(
                "ActiveStorageVariantRecordsMigrator: DEST public.active_storage_variant_records missing — bootstrapping from SOURCE"
            )
            ensure_public_table_exists(
                self.source_engine,
                self.dest_engine,
                "active_storage_variant_records",
            )
            dest_table = Table(
                "active_storage_variant_records", dest_meta, autoload_with=self.dest_engine
            )

        with self.dest_engine.connect() as conn:
            migrated_blobs = self.state_repo.get_migrated_ids(conn, "active_storage_blobs")

        rows = self._select_source_rows(src_table)

        self.logger.info("ActiveStorageVariantRecordsMigrator: %d source rows fetched", len(rows))

        # PRÉ-PROCESSAR duplicatas (FIX D21 — mesma lógica de active_storage_blobs)
        # Consultar registros existentes no DEST por (blob_id, variation_digest)
        existing_variants: dict[tuple[int, str], int] = {}
        with self.dest_engine.connect() as conn:
            from sqlalchemy import select

            existing_query = select(
                dest_table.c.id, dest_table.c.blob_id, dest_table.c.variation_digest
            )
            for row in conn.execute(existing_query):
                key = (row[1], row[2])  # (blob_id, variation_digest)
                existing_variants[key] = row[0]  # id

        self.logger.info(
            "ActiveStorageVariantRecordsMigrator: %d existing variants in DEST",
            len(existing_variants),
        )

        # Coletar duplicatas e registrar mappings (bulk)
        duplicate_pairs: list[tuple[int, int]] = []
        for row in rows:
            id_origin = int(row["id"])
            blob_id_origin = int(row["blob_id"])
            variation_digest = row["variation_digest"]

            # Skippar se blob_id não foi migrado
            if blob_id_origin not in migrated_blobs:
                continue

            # Calcular blob_id remapeado para comparar com DEST
            blob_id_dest = self.id_remapper.remap(blob_id_origin, "active_storage_blobs")
            key = (blob_id_dest, variation_digest)

            if key in existing_variants:
                id_destino_existente = existing_variants[key]
                duplicate_pairs.append((id_origin, id_destino_existente))

                self.logger.debug(
                    "ActiveStorageVariantRecordsMigrator: id=%d → id=%d (blob_id=%d, digest '%s' exists)",
                    id_origin,
                    id_destino_existente,
                    blob_id_dest,
                    variation_digest,
                )

        # BULK INSERT mappings + atualizar remapper
        if duplicate_pairs:
            with self.dest_engine.begin() as conn:
                self.state_repo.record_success_bulk(
                    conn, "active_storage_variant_records", duplicate_pairs
                )

            # Atualizar remapper em memória
            for src_id, dest_id in duplicate_pairs:
                self.id_remapper.register_alias("active_storage_variant_records", src_id, dest_id)

        self.logger.info(
            "ActiveStorageVariantRecordsMigrator: %d duplicate variants registered in migration_state (bulk)",
            len(duplicate_pairs),
        )

        def remap_fn(row: dict) -> dict | None:
            """Remap PK and FK columns for an active_storage_variant_records row.

            :param row: Source row as plain dict.
            :type row: dict
            :returns: Destination row with remapped IDs or ``None`` if FK orphan or duplicate.
            :rtype: dict | None
            """
            id_origin = int(row["id"])
            blob_id_origin = int(row["blob_id"])

            # Validar blob_id (FK obrigatória)
            if blob_id_origin not in migrated_blobs:
                self.logger.warning(
                    "ActiveStorageVariantRecordsMigrator: id=%d skipped — orphan blob_id=%d",
                    id_origin,
                    blob_id_origin,
                )
                return None

            # Skippar duplicatas (já registradas em migration_state)
            blob_id_dest = self.id_remapper.remap(blob_id_origin, "active_storage_blobs")
            variation_digest = row["variation_digest"]
            key = (blob_id_dest, variation_digest)

            if key in existing_variants:
                # Já existe — skippar insert
                return None

            return {
                **row,
                "id": self.id_remapper.remap(id_origin, "active_storage_variant_records"),
                "blob_id": blob_id_dest,
                # variation_digest copiado verbatim
            }

        result = self._run_batches(rows, "active_storage_variant_records", dest_table, remap_fn)

        self.logger.info(
            "ActiveStorageVariantRecordsMigrator: complete — migrated=%d skipped=%d failed=%d",
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

        :returns: ``"active_storage_variant_records"``
        :rtype: str
        """
        return "active_storage_variant_records"

    def _fetch_all_source_rows(self) -> list[dict]:
        """Fetch all rows from source ``active_storage_variant_records``.

        :returns: All source rows as plain dicts.
        :rtype: list[dict]
        """
        src_meta = MetaData()
        src_table = Table(
            "active_storage_variant_records", src_meta, autoload_with=self.source_engine
        )
        return self._select_source_rows(src_table)

    def _classify_row_poc(  # type: ignore[override]
        self,
        row: dict,
        migrated_sets: dict[str, set[int]],
    ) -> tuple:
        """Classify an active_storage_variant_records row for POC dry-run.

        Required FK (skip on orphan): ``blob_id``.

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

        return (Outcome.INSERT, "blob_id dependency satisfied")
