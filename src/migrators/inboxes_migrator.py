"""Migrator for the ``inboxes`` entity.

:description: Remaps ``id`` (offset_inboxes) and ``account_id`` (offset_accounts).
    Records with an ``account_id`` that was not successfully migrated are
    skipped with a WARNING log entry.
"""

from __future__ import annotations

from sqlalchemy import MetaData, Table

from src.migrators.base_migrator import BaseMigrator, MigrationResult


class InboxesMigrator(BaseMigrator):
    """Migrate all rows from ``inboxes`` source → destination.

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
        """Execute inboxes migration.

        :returns: Migration result summary for ``inboxes``.
        :rtype: MigrationResult
        """
        self.logger.info("InboxesMigrator: starting")
        src_meta = MetaData()
        src_table = Table("inboxes", src_meta, autoload_with=self.source_engine)
        dest_meta = MetaData()
        dest_table = Table("inboxes", dest_meta, autoload_with=self.dest_engine)

        with self.dest_engine.connect() as conn:
            migrated_accounts = self.state_repo.get_migrated_ids(conn, "accounts")

        with self.source_engine.connect() as conn:
            rows = [dict(r) for r in conn.execute(src_table.select()).mappings().all()]

        self.logger.info("InboxesMigrator: %d source rows fetched", len(rows))

        def remap_fn(row: dict) -> dict | None:
            """Remap PK and FK for an inboxes row.

            :param row: Source row as plain dict.
            :type row: dict
            :returns: Destination row with remapped IDs, or ``None`` if FK orphan.
            :rtype: dict | None
            """
            account_id_origin = int(row["account_id"])
            if account_id_origin not in migrated_accounts:
                self.logger.warning(
                    "InboxesMigrator: id=%d skipped — orphan account_id=%d",
                    row["id"],
                    account_id_origin,
                )
                return None
            return {
                **row,
                "id": self.id_remapper.remap(int(row["id"]), "inboxes"),
                "account_id": self.id_remapper.remap(account_id_origin, "accounts"),
            }

        result = self._run_batches(rows, "inboxes", dest_table, remap_fn)

        self.logger.info(
            "InboxesMigrator: complete — migrated=%d skipped=%d failed=%d",
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

        :returns: ``"inboxes"``
        :rtype: str
        """
        return "inboxes"

    def _fetch_all_source_rows(self) -> list[dict]:
        """Fetch all rows from source ``inboxes``.

        :returns: All source rows as plain dicts.
        :rtype: list[dict]
        """
        src_meta = MetaData()
        src_table = Table("inboxes", src_meta, autoload_with=self.source_engine)
        with self.source_engine.connect() as conn:
            return [dict(r) for r in conn.execute(src_table.select()).mappings().all()]

    def _classify_row_poc(  # type: ignore[override]
        self,
        row: dict,
        migrated_sets: dict[str, set[int]],
    ) -> tuple:
        """Classify an inboxes row: orphan account_id → ORPHAN_FK_SKIP.

        :param row: Source row as plain dict.
        :type row: dict
        :param migrated_sets: Dest ID sets keyed by table name.
        :type migrated_sets: dict[str, set[int]]
        :returns: ``(outcome, reason)`` tuple.
        :rtype: tuple
        """
        from src.reports.poc_reporter import Outcome

        account_id = int(row["account_id"])
        if account_id not in migrated_sets.get("accounts", set()):
            return (
                Outcome.ORPHAN_FK_SKIP,
                f"account_id={account_id} not in migrated accounts",
            )
        return Outcome.WOULD_MIGRATE, "clean"
