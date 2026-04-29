"""Migrator for the ``canned_responses`` entity.

:description: Remaps ``id`` (offset_canned_responses) and ``account_id``
    (offset_accounts). Deduplicates by ``(dest_account_id, short_code)``
    for merged accounts so pre-existing DEST canned responses are reused.
    Records with orphaned ``account_id`` are skipped with a WARNING.
"""

from __future__ import annotations

from sqlalchemy import MetaData, Table, text

from src.migrators.base_migrator import BaseMigrator, MigrationResult


class CannedResponsesMigrator(BaseMigrator):
    """Migrate all rows from ``canned_responses`` source → destination.

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
        """Execute canned_responses migration.

        :returns: Migration result summary for ``canned_responses``.
        :rtype: MigrationResult
        """
        self.logger.info("CannedResponsesMigrator: starting")
        src_meta = MetaData()
        src_table = Table("canned_responses", src_meta, autoload_with=self.source_engine)
        dest_meta = MetaData()
        dest_table = Table("canned_responses", dest_meta, autoload_with=self.dest_engine)

        with self.dest_engine.connect() as conn:
            migrated_accounts = self.state_repo.get_migrated_ids(conn, "accounts")

        with self.source_engine.connect() as conn:
            rows = [dict(r) for r in conn.execute(src_table.select()).mappings().all()]

        self.logger.info("CannedResponsesMigrator: %d source rows fetched", len(rows))

        # ── Dedup: canned_responses for merged accounts ────────────────────
        merged_account_ids: set[int] = {
            acct_id
            for acct_id in migrated_accounts
            if self.id_remapper.has_alias("accounts", acct_id)
        }
        if merged_account_ids:
            dst_code_acct: dict[tuple[str, int], int] = {}
            with self.dest_engine.connect() as conn:
                for acct_id in merged_account_ids:
                    dest_acct_id = self.id_remapper.remap(acct_id, "accounts")
                    for dest_id, short_code, account_id in conn.execute(
                        text(
                            "SELECT id, short_code, account_id "
                            "FROM canned_responses "
                            "WHERE account_id = :acct_id"
                        ),
                        {"acct_id": dest_acct_id},
                    ).fetchall():
                        k = (str(short_code).lower(), int(account_id))
                        dst_code_acct[k] = int(dest_id)

            canned_merged: list[tuple[int, int]] = []
            for row in rows:
                account_id_origin = int(row["account_id"])
                if account_id_origin not in merged_account_ids:
                    continue
                dest_acct = self.id_remapper.remap(account_id_origin, "accounts")
                code = str(row.get("short_code") or "").lower()
                key = (code, dest_acct)
                if key in dst_code_acct:
                    src_id = int(row["id"])
                    dest_id = dst_code_acct[key]
                    self.id_remapper.register_alias("canned_responses", src_id, dest_id)
                    canned_merged.append((src_id, dest_id))

            if canned_merged:
                with self.dest_engine.connect() as conn:
                    with conn.begin():
                        for src_id, dest_id in canned_merged:
                            self.state_repo.record_success(
                                conn, "canned_responses", src_id, dest_id
                            )
                self.logger.info(
                    "CannedResponsesMigrator: %d canned_responses matched" " — skipping INSERT",
                    len(canned_merged),
                )
        # ──────────────────────────────────────────────────────────────────────

        def remap_fn(row: dict) -> dict | None:
            """Remap PK and account_id for a canned_responses row.

            :param row: Source row as plain dict.
            :type row: dict
            :returns: Destination row or ``None`` if FK orphan.
            :rtype: dict | None
            """
            account_id_origin = int(row["account_id"])
            if account_id_origin not in migrated_accounts:
                self.logger.warning(
                    "CannedResponsesMigrator: id=%d skipped" " — orphan account_id=%d",
                    row["id"],
                    account_id_origin,
                )
                return None
            return {
                **row,
                "id": self.id_remapper.remap(int(row["id"]), "canned_responses"),
                "account_id": self.id_remapper.remap(account_id_origin, "accounts"),
            }

        result = self._run_batches(rows, "canned_responses", dest_table, remap_fn)

        self.logger.info(
            "CannedResponsesMigrator: complete" " — migrated=%d skipped=%d failed=%d",
            result.migrated,
            result.skipped,
            len(result.failed_ids),
        )
        return result

    # ------------------------------------------------------------------
    # POC dry-run hooks
    # ------------------------------------------------------------------

    def _table_name(self) -> str:
        return "canned_responses"

    def _fetch_all_source_rows(self) -> list[dict]:
        src_meta = MetaData()
        src_table = Table("canned_responses", src_meta, autoload_with=self.source_engine)
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
