"""Migrator for the ``accounts`` entity.

:description: Root entity — all other entities FK-reference ``account_id``.
    A batch failure here is **catastrophic**: the process exits with code 3
    immediately rather than continuing, because partial accounts migration
    would leave orphaned FK references impossible to reconstruct.
"""

from __future__ import annotations

from sqlalchemy import MetaData, Table, text

from src.migrators.base_migrator import BaseMigrator, MigrationResult


class AccountsMigrator(BaseMigrator):
    """Migrate all rows from ``accounts`` in source to destination.

    :param source_engine: Read-only source engine.
    :type source_engine: Engine
    :param dest_engine: Read-write destination engine.
    :type dest_engine: Engine
    :param id_remapper: Session-scoped offset remapper (must contain key
        ``"accounts"`` from prior ``compute_offsets`` call).
    :type id_remapper: IDRemapper
    :param state_repo: Migration state control repository.
    :type state_repo: MigrationStateRepository
    :param logger: Logger (expected to have ``MaskingHandler`` attached).
    :type logger: logging.Logger
    """

    def migrate(self) -> MigrationResult:
        """Execute accounts migration.

        :returns: Migration result summary for ``accounts``.
        :rtype: MigrationResult
        :raises SystemExit: Exits with code 3 on any batch failure (catastrophic).
        """
        self.logger.info("AccountsMigrator: starting")
        src_meta = MetaData()
        src_table = Table("accounts", src_meta, autoload_with=self.source_engine)
        dest_meta = MetaData()
        dest_table = Table("accounts", dest_meta, autoload_with=self.dest_engine)

        with self.source_engine.connect() as conn:
            rows = [dict(r) for r in conn.execute(src_table.select()).mappings().all()]

        self.logger.info("AccountsMigrator: %d source rows fetched", len(rows))

        # ── Merge rule: accounts with same id AND name already exist in DEST ──
        # These accounts are not re-inserted; their dest_id is reused as-is.
        # We register an alias so downstream migrators (contacts, conversations)
        # receive the correct dest_id when remapping account_id.
        with self.dest_engine.connect() as dest_conn:
            dst_id_name: set[tuple[int, str]] = {
                (int(r[0]), str(r[1]))
                for r in dest_conn.execute(text("SELECT id, name FROM public.accounts")).fetchall()
            }

        merged: list[tuple[int, int]] = []  # (src_id, dest_id)
        for row in rows:
            src_id = int(row["id"])
            src_name = str(row.get("name") or "")
            if (src_id, src_name) in dst_id_name:
                self.id_remapper.register_alias("accounts", src_id, src_id)
                merged.append((src_id, src_id))

        if merged:
            with self.dest_engine.connect() as dest_conn:
                with dest_conn.begin():
                    for src_id, dest_id in merged:
                        self.state_repo.record_success(dest_conn, "accounts", src_id, dest_id)
            self.logger.info(
                "AccountsMigrator: %d accounts matched by id+name — reusing dest_id, skipping INSERT",
                len(merged),
            )
        # ──────────────────────────────────────────────────────────────────────

        def remap_fn(row: dict) -> dict:
            """Remap PK for an accounts row.

            :param row: Source row as plain dict.
            :type row: dict
            :returns: Destination row with remapped ``id``.
            :rtype: dict
            """
            return {**row, "id": self.id_remapper.remap(int(row["id"]), "accounts")}

        result = self._run_batches(rows, "accounts", dest_table, remap_fn)

        if result.failed_ids:
            self.logger.critical(
                "AccountsMigrator: %d records failed — aborting (exit code 3)",
                len(result.failed_ids),
            )
            raise SystemExit(3)

        self.logger.info(
            "AccountsMigrator: complete — migrated=%d skipped=%d",
            result.migrated,
            result.skipped,
        )
        return result

    # ------------------------------------------------------------------
    # POC dry-run hooks
    # ------------------------------------------------------------------

    def _table_name(self) -> str:
        """Return canonical table name.

        :returns: ``"accounts"``
        :rtype: str
        """
        return "accounts"

    def _fetch_all_source_rows(self) -> list[dict]:
        """Fetch all rows from source ``accounts``.

        :returns: All source rows as plain dicts.
        :rtype: list[dict]
        """
        src_meta = MetaData()
        src_table = Table("accounts", src_meta, autoload_with=self.source_engine)
        with self.source_engine.connect() as conn:
            return [dict(r) for r in conn.execute(src_table.select()).mappings().all()]
