"""Migrator for the ``custom_attribute_definitions`` entity.

:description: Remaps ``id`` (offset_custom_attribute_definitions) and
    ``account_id`` (offset_accounts). Deduplicates by
    ``(dest_account_id, attribute_key)`` for merged accounts so pre-existing
    DEST attribute definitions are reused.
    Records with orphaned ``account_id`` are skipped with a WARNING.
"""

from __future__ import annotations

from sqlalchemy import MetaData, Table, text

from src.migrators.base_migrator import BaseMigrator, MigrationResult


class CustomAttributeDefinitionsMigrator(BaseMigrator):
    """Migrate all rows from ``custom_attribute_definitions`` source → dest.

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
        """Execute custom_attribute_definitions migration.

        :returns: Migration result summary for ``custom_attribute_definitions``.
        :rtype: MigrationResult
        """
        self.logger.info("CustomAttributeDefinitionsMigrator: starting")
        src_meta = MetaData()
        src_table = Table(
            "custom_attribute_definitions",
            src_meta,
            autoload_with=self.source_engine,
        )
        dest_meta = MetaData()
        dest_table = Table(
            "custom_attribute_definitions",
            dest_meta,
            autoload_with=self.dest_engine,
        )

        with self.dest_engine.connect() as conn:
            migrated_accounts = self.state_repo.get_migrated_ids(conn, "accounts")

        with self.source_engine.connect() as conn:
            rows = [dict(r) for r in conn.execute(src_table.select()).mappings().all()]

        self.logger.info(
            "CustomAttributeDefinitionsMigrator: %d source rows fetched",
            len(rows),
        )

        # ── Dedup: attribute_definitions for merged accounts ────────────────
        merged_account_ids: set[int] = {
            acct_id
            for acct_id in migrated_accounts
            if self.id_remapper.has_alias("accounts", acct_id)
        }
        if merged_account_ids:
            dst_key_acct: dict[tuple[str, int], int] = {}
            with self.dest_engine.connect() as conn:
                for acct_id in merged_account_ids:
                    dest_acct_id = self.id_remapper.remap(acct_id, "accounts")
                    for dest_id, attr_key, account_id in conn.execute(
                        text(
                            "SELECT id, attribute_key, account_id "
                            "FROM custom_attribute_definitions "
                            "WHERE account_id = :acct_id"
                        ),
                        {"acct_id": dest_acct_id},
                    ).fetchall():
                        k = (str(attr_key), int(account_id))
                        dst_key_acct[k] = int(dest_id)

            attr_merged: list[tuple[int, int]] = []
            for row in rows:
                account_id_origin = int(row["account_id"])
                if account_id_origin not in merged_account_ids:
                    continue
                dest_acct = self.id_remapper.remap(account_id_origin, "accounts")
                key = (str(row.get("attribute_key") or ""), dest_acct)
                if key in dst_key_acct:
                    src_id = int(row["id"])
                    dest_id = dst_key_acct[key]
                    self.id_remapper.register_alias("custom_attribute_definitions", src_id, dest_id)
                    attr_merged.append((src_id, dest_id))

            if attr_merged:
                with self.dest_engine.connect() as conn:
                    with conn.begin():
                        for src_id, dest_id in attr_merged:
                            self.state_repo.record_success(
                                conn,
                                "custom_attribute_definitions",
                                src_id,
                                dest_id,
                            )
                self.logger.info(
                    "CustomAttributeDefinitionsMigrator:"
                    " %d attribute_definitions matched — skipping INSERT",
                    len(attr_merged),
                )
        # ──────────────────────────────────────────────────────────────────────

        def remap_fn(row: dict) -> dict | None:
            """Remap PK and account_id for a custom_attribute_definitions row.

            :param row: Source row as plain dict.
            :type row: dict
            :returns: Destination row or ``None`` if FK orphan.
            :rtype: dict | None
            """
            account_id_origin = int(row["account_id"])
            if account_id_origin not in migrated_accounts:
                self.logger.warning(
                    "CustomAttributeDefinitionsMigrator: id=%d skipped" " — orphan account_id=%d",
                    row["id"],
                    account_id_origin,
                )
                return None
            return {
                **row,
                "id": self.id_remapper.remap(int(row["id"]), "custom_attribute_definitions"),
                "account_id": self.id_remapper.remap(account_id_origin, "accounts"),
            }

        result = self._run_batches(
            rows,
            "custom_attribute_definitions",
            dest_table,
            remap_fn,
        )

        self.logger.info(
            "CustomAttributeDefinitionsMigrator: complete" " — migrated=%d skipped=%d failed=%d",
            result.migrated,
            result.skipped,
            len(result.failed_ids),
        )
        return result

    # ------------------------------------------------------------------
    # POC dry-run hooks
    # ------------------------------------------------------------------

    def _table_name(self) -> str:
        return "custom_attribute_definitions"

    def _fetch_all_source_rows(self) -> list[dict]:
        src_meta = MetaData()
        src_table = Table(
            "custom_attribute_definitions",
            src_meta,
            autoload_with=self.source_engine,
        )
        with self.source_engine.connect() as conn:
            return [dict(r) for r in conn.execute(src_table.select()).mappings().all()]

    def _classify_row_poc(
        self,
        row: dict,
        migrated_sets: dict[str, set[int]],
    ) -> tuple:
        from src.reports.poc_reporter import Outcome

        if int(row["account_id"]) not in migrated_sets.get("accounts", set()):
            return (
                Outcome.ORPHAN_FK_SKIP,
                f"account_id={row['account_id']} not in migrated accounts",
            )
        return Outcome.WOULD_MIGRATE, "clean"
