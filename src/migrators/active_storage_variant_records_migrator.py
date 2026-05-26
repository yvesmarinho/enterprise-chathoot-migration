"""Migrator for the ``active_storage_variant_records`` entity.

:description: Remaps FK columns:

    * ``id``       → ``id + offset_active_storage_variant_records``
    * ``blob_id``  → ``blob_id + offset_active_storage_blobs`` (required — skip on orphan)

    This table stores metadata about image variants (thumbnails, resized versions).
    It depends on ``active_storage_blobs`` only.
"""

from __future__ import annotations

from sqlalchemy import MetaData, Table

from src.migrators.base_migrator import BaseMigrator, MigrationResult


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
        dest_table = Table(
            "active_storage_variant_records", dest_meta, autoload_with=self.dest_engine
        )

        with self.dest_engine.connect() as conn:
            migrated_blobs = self.state_repo.get_migrated_ids(conn, "active_storage_blobs")

        rows = self._select_source_rows(src_table)

        self.logger.info("ActiveStorageVariantRecordsMigrator: %d source rows fetched", len(rows))

        def remap_fn(row: dict) -> dict | None:
            """Remap PK and FK columns for an active_storage_variant_records row.

            :param row: Source row as plain dict.
            :type row: dict
            :returns: Destination row with remapped IDs or ``None`` if FK orphan.
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

            return {
                **row,
                "id": self.id_remapper.remap(id_origin, "active_storage_variant_records"),
                "blob_id": self.id_remapper.remap(blob_id_origin, "active_storage_blobs"),
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
