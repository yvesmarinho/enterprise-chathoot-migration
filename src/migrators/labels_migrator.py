"""Migrator for the ``labels`` entity.

:description: Remaps ``id`` (offset_labels) and ``account_id`` (offset_accounts).
    Records with orphaned ``account_id`` are skipped with a WARNING.
"""

from __future__ import annotations

from sqlalchemy import MetaData, Table, text

from src.migrators.base_migrator import BaseMigrator, MigrationResult


class LabelsMigrator(BaseMigrator):
    """Migrate all rows from ``labels`` source → destination.

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
        """Execute labels migration.

        :returns: Migration result summary for ``labels``.
        :rtype: MigrationResult
        """
        self.logger.info("LabelsMigrator: starting")
        src_meta = MetaData()
        src_table = Table("labels", src_meta, autoload_with=self.source_engine)
        dest_meta = MetaData()
        dest_table = Table("labels", dest_meta, autoload_with=self.dest_engine)

        with self.dest_engine.connect() as conn:
            migrated_accounts = self.state_repo.get_migrated_ids(conn, "accounts")

        with self.source_engine.connect() as conn:
            rows = [dict(r) for r in conn.execute(src_table.select()).mappings().all()]

        self.logger.info("LabelsMigrator: %d source rows fetched", len(rows))

        # ── Dedup: labels for merged accounts (same id+name in both DBs) ─────
        # For accounts whose account_id was reused as-is (alias registered),
        # the destination already has labels with the same (title, account_id) key.
        # We register aliases and record_success so _run_batches skips the INSERT.
        merged_account_ids: set[int] = {
            acct_id
            for acct_id in migrated_accounts
            if self.id_remapper.remap(acct_id, "accounts") == acct_id
        }
        if merged_account_ids:
            dst_title_acct: dict[tuple[str, int], int] = {}
            with self.dest_engine.connect() as conn:
                for acct_id in merged_account_ids:
                    for dest_id, title, account_id in conn.execute(
                        text(
                            "SELECT id, title, account_id FROM public.labels "
                            "WHERE account_id = :acct_id"
                        ),
                        {"acct_id": acct_id},
                    ).fetchall():
                        dst_title_acct[(str(title), int(account_id))] = int(dest_id)

            label_merged: list[tuple[int, int]] = []
            for row in rows:
                account_id_origin = int(row["account_id"])
                if account_id_origin not in merged_account_ids:
                    continue
                key = (str(row.get("title") or ""), account_id_origin)
                if key in dst_title_acct:
                    src_id = int(row["id"])
                    dest_id = dst_title_acct[key]
                    self.id_remapper.register_alias("labels", src_id, dest_id)
                    label_merged.append((src_id, dest_id))

            if label_merged:
                with self.dest_engine.connect() as conn:
                    with conn.begin():
                        for src_id, dest_id in label_merged:
                            self.state_repo.record_success(conn, "labels", src_id, dest_id)
                self.logger.info(
                    "LabelsMigrator: %d labels matched in merged accounts — skipping INSERT",
                    len(label_merged),
                )
        # ──────────────────────────────────────────────────────────────────────

        def remap_fn(row: dict) -> dict | None:
            """Remap PK and account_id for a labels row.

            :param row: Source row as plain dict.
            :type row: dict
            :returns: Destination row with remapped IDs, or ``None`` if FK orphan.
            :rtype: dict | None
            """
            account_id_origin = int(row["account_id"])
            if account_id_origin not in migrated_accounts:
                self.logger.warning(
                    "LabelsMigrator: id=%d skipped — orphan account_id=%d",
                    row["id"],
                    account_id_origin,
                )
                return None
            return {
                **row,
                "id": self.id_remapper.remap(int(row["id"]), "labels"),
                "account_id": self.id_remapper.remap(account_id_origin, "accounts"),
            }

        result = self._run_batches(rows, "labels", dest_table, remap_fn)

        self.logger.info(
            "LabelsMigrator: complete — migrated=%d skipped=%d failed=%d",
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

        :returns: ``"labels"``
        :rtype: str
        """
        return "labels"

    def _fetch_all_source_rows(self) -> list[dict]:
        """Fetch all rows from source ``labels``.

        :returns: All source rows as plain dicts.
        :rtype: list[dict]
        """
        src_meta = MetaData()
        src_table = Table("labels", src_meta, autoload_with=self.source_engine)
        with self.source_engine.connect() as conn:
            return [dict(r) for r in conn.execute(src_table.select()).mappings().all()]

    def _classify_row_poc(  # type: ignore[override]
        self,
        row: dict,
        migrated_sets: dict[str, set[int]],
    ) -> tuple:
        """Classify a labels row: orphan account_id → ORPHAN_FK_SKIP.

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
