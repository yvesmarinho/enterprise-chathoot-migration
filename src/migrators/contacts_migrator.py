"""Migrator for the ``contacts`` entity.

:description: Remaps ``id`` (offset_contacts) and ``account_id`` (offset_accounts).
    Applies masking to ``name``, ``email``, ``phone_number``, ``identifier``,
    and ``additional_attributes`` (JSONB) **in log output only** — actual DB
    values are inserted verbatim from source.

    With 38,868 source records and batch size 500 this produces 78 batches.
"""

from __future__ import annotations

from sqlalchemy import MetaData, Table, text

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

        # ── Deduplication: contacts in merged accounts (same id+name) ─────────
        # A "merged" account is one whose src_id == dest_id (alias registered by
        # AccountsMigrator). For those accounts, a contact already in DEST with
        # the same (account_id, phone_number) or (account_id, email) must not be
        # re-inserted — we re-use the existing dest_id instead.
        #
        # Contacts in unmatched accounts (new accounts with offset IDs) cannot
        # have duplicates in DEST because those accounts don't exist there yet.
        src_account_ids = {int(r["account_id"]) for r in rows if r.get("account_id") is not None}
        merged_account_ids: set[int] = {
            acct_id
            for acct_id in src_account_ids
            if self.id_remapper.remap(acct_id, "accounts") == acct_id
        }

        if merged_account_ids:
            # Build lookup: (account_id, normalised_phone) → dest_id
            #               (account_id, normalised_email) → dest_id
            dst_phone_lkp: dict[tuple[int, str], int] = {}
            dst_email_lkp: dict[tuple[int, str], int] = {}

            with self.dest_engine.connect() as dest_conn:
                for acct_id in merged_account_ids:
                    for r in dest_conn.execute(
                        text(
                            "SELECT id, phone_number, email "
                            "FROM public.contacts WHERE account_id = :a"
                        ),
                        {"a": acct_id},
                    ).mappings():
                        if r["phone_number"]:
                            dst_phone_lkp[(acct_id, str(r["phone_number"]).strip().lower())] = int(
                                r["id"]
                            )
                        if r["email"]:
                            dst_email_lkp[(acct_id, str(r["email"]).strip().lower())] = int(r["id"])

            dedup_records: list[tuple[int, int]] = []  # (src_id, dest_id)
            for row in rows:
                acct_id = int(row["account_id"])
                if acct_id not in merged_account_ids:
                    continue
                src_id = int(row["id"])
                dest_id: int | None = None
                phone = row.get("phone_number")
                if phone:
                    dest_id = dst_phone_lkp.get((acct_id, str(phone).strip().lower()))
                if dest_id is None:
                    email = row.get("email")
                    if email:
                        dest_id = dst_email_lkp.get((acct_id, str(email).strip().lower()))
                if dest_id is not None:
                    self.id_remapper.register_alias("contacts", src_id, dest_id)
                    dedup_records.append((src_id, dest_id))

            if dedup_records:
                _DEDUP_BATCH = 500
                for i in range(0, len(dedup_records), _DEDUP_BATCH):
                    batch = dedup_records[i : i + _DEDUP_BATCH]
                    with self.dest_engine.connect() as dest_conn:
                        with dest_conn.begin():
                            self.state_repo.record_success_bulk(dest_conn, "contacts", batch)
                self.logger.info(
                    "ContactsMigrator: %d contacts matched by (account_id, phone/email)"
                    " — reusing dest_id, skipping INSERT",
                    len(dedup_records),
                )
        # ──────────────────────────────────────────────────────────────────────

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

    # ------------------------------------------------------------------
    # POC dry-run hooks
    # ------------------------------------------------------------------

    def _table_name(self) -> str:
        """Return canonical table name.

        :returns: ``"contacts"``
        :rtype: str
        """
        return "contacts"

    def _fetch_all_source_rows(self) -> list[dict]:
        """Fetch all rows from source ``contacts``.

        :returns: All source rows as plain dicts.
        :rtype: list[dict]
        """
        src_meta = MetaData()
        src_table = Table("contacts", src_meta, autoload_with=self.source_engine)
        with self.source_engine.connect() as conn:
            return [dict(r) for r in conn.execute(src_table.select()).mappings().all()]

    def _classify_row_poc(  # type: ignore[override]
        self,
        row: dict,
        migrated_sets: dict[str, set[int]],
    ) -> tuple:
        """Classify a contacts row: orphan account_id → ORPHAN_FK_SKIP.

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
