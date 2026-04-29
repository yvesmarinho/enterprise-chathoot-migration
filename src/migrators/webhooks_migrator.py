"""Migrator for the ``webhooks`` entity.

:description: Remaps ``id`` (offset_webhooks) and ``account_id``
    (offset_accounts). Also remaps optional ``inbox_id`` when present.
    Deduplicates by ``(dest_account_id, url)`` for merged accounts.
    Records with orphaned ``account_id`` are skipped with a WARNING.

    NOTE: The SOURCE database had 0 webhook rows at diagnosis time
    (2026-04-24). This migrator is a no-op when the source is empty but
    is included for correctness and future-proofing.
"""

from __future__ import annotations

from sqlalchemy import MetaData, Table, text

from src.migrators.base_migrator import BaseMigrator, MigrationResult


class WebhooksMigrator(BaseMigrator):
    """Migrate all rows from ``webhooks`` source → destination.

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
        """Execute webhooks migration.

        :returns: Migration result summary for ``webhooks``.
        :rtype: MigrationResult
        """
        self.logger.info("WebhooksMigrator: starting")
        src_meta = MetaData()
        src_table = Table("webhooks", src_meta, autoload_with=self.source_engine)
        dest_meta = MetaData()
        dest_table = Table("webhooks", dest_meta, autoload_with=self.dest_engine)

        with self.dest_engine.connect() as conn:
            migrated_accounts = self.state_repo.get_migrated_ids(conn, "accounts")
            migrated_inboxes = self.state_repo.get_migrated_ids(conn, "inboxes")

        with self.source_engine.connect() as conn:
            rows = [dict(r) for r in conn.execute(src_table.select()).mappings().all()]

        self.logger.info("WebhooksMigrator: %d source rows fetched", len(rows))

        if not rows:
            self.logger.info("WebhooksMigrator: no rows — nothing to do")
            return MigrationResult(
                table="webhooks",
                total_source=0,
                migrated=0,
                skipped=0,
                failed_ids=[],
            )

        # ── Dedup: webhooks for merged accounts ─────────────────────────────
        merged_account_ids: set[int] = {
            acct_id
            for acct_id in migrated_accounts
            if self.id_remapper.has_alias("accounts", acct_id)
        }
        if merged_account_ids:
            dst_url_acct: dict[tuple[str, int], int] = {}
            with self.dest_engine.connect() as conn:
                for acct_id in merged_account_ids:
                    dest_acct_id = self.id_remapper.remap(acct_id, "accounts")
                    for dest_id, url, account_id in conn.execute(
                        text(
                            "SELECT id, url, account_id FROM webhooks "
                            "WHERE account_id = :acct_id"
                        ),
                        {"acct_id": dest_acct_id},
                    ).fetchall():
                        k = (str(url or ""), int(account_id))
                        dst_url_acct[k] = int(dest_id)

            hook_merged: list[tuple[int, int]] = []
            for row in rows:
                account_id_origin = int(row["account_id"])
                if account_id_origin not in merged_account_ids:
                    continue
                dest_acct = self.id_remapper.remap(account_id_origin, "accounts")
                key = (str(row.get("url") or ""), dest_acct)
                if key in dst_url_acct:
                    src_id = int(row["id"])
                    dest_id = dst_url_acct[key]
                    self.id_remapper.register_alias("webhooks", src_id, dest_id)
                    hook_merged.append((src_id, dest_id))

            if hook_merged:
                with self.dest_engine.connect() as conn:
                    with conn.begin():
                        for src_id, dest_id in hook_merged:
                            self.state_repo.record_success(conn, "webhooks", src_id, dest_id)
                self.logger.info(
                    "WebhooksMigrator: %d webhooks matched — skipping INSERT",
                    len(hook_merged),
                )
        # ──────────────────────────────────────────────────────────────────────

        def remap_fn(row: dict) -> dict | None:
            """Remap PK, account_id and inbox_id for a webhooks row.

            :param row: Source row as plain dict.
            :type row: dict
            :returns: Destination row or ``None`` if FK orphan.
            :rtype: dict | None
            """
            account_id_origin = int(row["account_id"])
            if account_id_origin not in migrated_accounts:
                self.logger.warning(
                    "WebhooksMigrator: id=%d skipped — orphan account_id=%d",
                    row["id"],
                    account_id_origin,
                )
                return None

            new_row = {
                **row,
                "id": self.id_remapper.remap(int(row["id"]), "webhooks"),
                "account_id": self.id_remapper.remap(account_id_origin, "accounts"),
            }

            # inbox_id is nullable — remap only when present
            inbox_id = row.get("inbox_id")
            if inbox_id is not None:
                src_inbox = int(inbox_id)
                if src_inbox in migrated_inboxes:
                    new_row["inbox_id"] = self.id_remapper.remap(src_inbox, "inboxes")
                else:
                    # inbox not migrated — set NULL rather than FK fail
                    new_row["inbox_id"] = None

            return new_row

        result = self._run_batches(rows, "webhooks", dest_table, remap_fn)

        self.logger.info(
            "WebhooksMigrator: complete — migrated=%d skipped=%d failed=%d",
            result.migrated,
            result.skipped,
            len(result.failed_ids),
        )
        return result

    # ------------------------------------------------------------------
    # POC dry-run hooks
    # ------------------------------------------------------------------

    def _table_name(self) -> str:
        return "webhooks"

    def _fetch_all_source_rows(self) -> list[dict]:
        src_meta = MetaData()
        src_table = Table("webhooks", src_meta, autoload_with=self.source_engine)
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
