"""Migrator for the ``contacts`` entity.

:description: Remaps ``id`` (offset_contacts) and ``account_id`` (offset_accounts).
    Applies masking to ``name``, ``email``, ``phone_number``, ``identifier``,
    and ``additional_attributes`` (JSONB) **in log output only** — actual DB
    values are inserted verbatim from source.

    With 38,868 source records and batch size 500 this produces 78 batches.
"""

from __future__ import annotations

from sqlalchemy import MetaData, Table

from src.migrators.base_migrator import BaseMigrator, MigrationResult


class ContactsMigrator(BaseMigrator):
    """Migrate all rows from ``contacts`` source → destination.

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
        """Execute contacts migration.

        PII in log output is masked automatically by the attached
        ``MaskingHandler``.  Database rows are inserted with original values.

        :returns: Migration result summary for ``contacts``.
        :rtype: MigrationResult
        """
        self.logger.info("ContactsMigrator: starting")
        src_meta = MetaData()
        src_table = Table("contacts", src_meta, autoload_with=self.source_engine)
        dest_meta = MetaData()
        dest_table = Table("contacts", dest_meta, autoload_with=self.dest_engine)

        with self.dest_engine.connect() as conn:
            migrated_accounts = self.state_repo.get_migrated_ids(conn, "accounts")

        with self.source_engine.connect() as conn:
            rows = [dict(r) for r in conn.execute(src_table.select()).mappings().all()]

        self.logger.info("ContactsMigrator: %d source rows fetched", len(rows))

        def remap_fn(row: dict) -> dict | None:
            """Remap PK and account_id for a contacts row.

            :param row: Source row as plain dict.
            :type row: dict
            :returns: Destination row with remapped IDs, or ``None`` if FK orphan.
            :rtype: dict | None
            """
            account_id_origin = int(row["account_id"])
            if account_id_origin not in migrated_accounts:
                self.logger.warning(
                    "ContactsMigrator: id=%d skipped — orphan account_id=%d",
                    row["id"],
                    account_id_origin,
                )
                return None
            return {
                **row,
                "id": self.id_remapper.remap(int(row["id"]), "contacts"),
                "account_id": self.id_remapper.remap(account_id_origin, "accounts"),
            }

        result = self._run_batches(rows, "contacts", dest_table, remap_fn)

        self.logger.info(
            "ContactsMigrator: complete — migrated=%d skipped=%d failed=%d",
            result.migrated,
            result.skipped,
            len(result.failed_ids),
        )
        return result
