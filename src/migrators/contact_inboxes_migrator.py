"""Migrator for the ``contact_inboxes`` entity.

:description: Remaps three FK columns:

    * ``id``          → ``id + offset_contact_inboxes``
    * ``contact_id``  → ``contact_id + offset_contacts``   (required — skip on orphan)
    * ``inbox_id``    → ``inbox_id + offset_inboxes``       (required — skip on orphan)

    Security constraints (from objetivo.yaml known_constraints):

    * ``pubsub_token`` MUST be NULL on insert — it is a globally unique UUID;
      copying the source value would cause UniqueViolation.
    * ``source_id`` MUST be regenerated via ``gen_random_uuid()`` — the source
      value would collide with tokens already present in DEST.
"""

from __future__ import annotations

import uuid

from sqlalchemy import MetaData, Table, text

from src.migrators.base_migrator import BaseMigrator, MigrationResult


class ContactInboxesMigrator(BaseMigrator):
    """Migrate all rows from ``contact_inboxes`` source → destination.

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
        """Execute contact_inboxes migration.

        :returns: Migration result summary for ``contact_inboxes``.
        :rtype: MigrationResult
        """
        self.logger.info("ContactInboxesMigrator: starting")
        src_meta = MetaData()
        src_table = Table("contact_inboxes", src_meta, autoload_with=self.source_engine)
        dest_meta = MetaData()
        dest_table = Table("contact_inboxes", dest_meta, autoload_with=self.dest_engine)

        with self.dest_engine.connect() as conn:
            migrated_contacts = self.state_repo.get_migrated_ids(conn, "contacts")
            migrated_inboxes = self.state_repo.get_migrated_ids(conn, "inboxes")

        with self.source_engine.connect() as conn:
            rows = [dict(r) for r in conn.execute(src_table.select()).mappings().all()]

        self.logger.info("ContactInboxesMigrator: %d source rows fetched", len(rows))

        # ── Dedup: contact_inboxes for already-migrated (contact_id, inbox_id) pairs ──
        # For contacts and inboxes that were merged (alias registered), the destination
        # may already contain a (contact_id, inbox_id) record.  We detect those by
        # querying the remapped pair in DEST and registering an alias so _run_batches
        # skips the INSERT instead of triggering a UniqueViolation.
        with self.dest_engine.connect() as conn:
            dst_ci_pairs: dict[tuple[int, int], int] = {
                (int(r[0]), int(r[1])): int(r[2])
                for r in conn.execute(
                    text("SELECT contact_id, inbox_id, id FROM public.contact_inboxes")
                ).fetchall()
            }

        dedup_records: list[tuple[int, int]] = []  # (src_id, dest_id)
        for row in rows:
            src_id = int(row["id"])
            contact_id_origin = int(row["contact_id"])
            inbox_id_origin = int(row["inbox_id"])

            if (
                contact_id_origin not in migrated_contacts
                or inbox_id_origin not in migrated_inboxes
            ):
                continue  # will be skipped in remap_fn anyway

            dest_contact_id = self.id_remapper.remap(contact_id_origin, "contacts")
            dest_inbox_id = self.id_remapper.remap(inbox_id_origin, "inboxes")
            existing_dest_id = dst_ci_pairs.get((dest_contact_id, dest_inbox_id))
            if existing_dest_id is not None:
                self.id_remapper.register_alias("contact_inboxes", src_id, existing_dest_id)
                dedup_records.append((src_id, existing_dest_id))

        if dedup_records:
            _DEDUP_BATCH = 500
            for i in range(0, len(dedup_records), _DEDUP_BATCH):
                batch = dedup_records[i : i + _DEDUP_BATCH]
                with self.dest_engine.connect() as dest_conn:
                    with dest_conn.begin():
                        self.state_repo.record_success_bulk(dest_conn, "contact_inboxes", batch)
            self.logger.info(
                "ContactInboxesMigrator: %d pairs already present in DEST — skipping INSERT",
                len(dedup_records),
            )
        # ─────────────────────────────────────────────────────────────────────

        def remap_fn(row: dict) -> dict | None:
            """Remap PK and FK columns for a contact_inboxes row.

            :param row: Source row as plain dict.
            :type row: dict
            :returns: Destination row with remapped IDs, or ``None`` if FK orphan.
            :rtype: dict | None
            """
            src_id = int(row["id"])
            contact_id_origin = int(row["contact_id"])
            inbox_id_origin = int(row["inbox_id"])

            if contact_id_origin not in migrated_contacts:
                self.logger.warning(
                    "ContactInboxesMigrator: id=%d skipped — orphan contact_id=%d",
                    src_id,
                    contact_id_origin,
                )
                return None

            if inbox_id_origin not in migrated_inboxes:
                self.logger.warning(
                    "ContactInboxesMigrator: id=%d skipped — orphan inbox_id=%d",
                    src_id,
                    inbox_id_origin,
                )
                return None

            new_row = dict(row)
            new_row["id"] = self.id_remapper.remap(src_id, "contact_inboxes")
            new_row["contact_id"] = self.id_remapper.remap(contact_id_origin, "contacts")
            new_row["inbox_id"] = self.id_remapper.remap(inbox_id_origin, "inboxes")

            # Security constraint (objetivo.yaml): pubsub_token MUST be NULL.
            # It is a globally unique token; copying from source would cause
            # UniqueViolation with existing tokens in DEST.
            new_row["pubsub_token"] = None

            # Security constraint: source_id MUST be regenerated.
            new_row["source_id"] = str(uuid.uuid4())

            return new_row

        result = self._run_batches(rows, "contact_inboxes", dest_table, remap_fn)

        self.logger.info(
            "ContactInboxesMigrator: complete — migrated=%d skipped=%d failed=%d",
            result.migrated,
            result.skipped,
            len(result.failed_ids),
        )
        return result

    # ------------------------------------------------------------------
    # POC dry-run hooks
    # ------------------------------------------------------------------

    def _table_name(self) -> str:
        return "contact_inboxes"

    def _fetch_all_source_rows(self) -> list[dict]:
        src_meta = MetaData()
        src_table = Table("contact_inboxes", src_meta, autoload_with=self.source_engine)
        with self.source_engine.connect() as conn:
            return [dict(r) for r in conn.execute(src_table.select()).mappings().all()]

    def _classify_row_poc(
        self,
        row: dict,
        migrated_sets: dict[str, set[int]],
    ) -> tuple:
        from src.reports.poc_reporter import Outcome

        contacts = migrated_sets.get("contacts", set())
        inboxes = migrated_sets.get("inboxes", set())

        if int(row["contact_id"]) not in contacts:
            return (
                Outcome.ORPHAN_FK_SKIP,
                f"contact_id={row['contact_id']} not in migrated contacts",
            )
        if int(row["inbox_id"]) not in inboxes:
            return (
                Outcome.ORPHAN_FK_SKIP,
                f"inbox_id={row['inbox_id']} not in migrated inboxes",
            )
        return (
            Outcome.WOULD_MIGRATE_MODIFIED,
            "pubsub_token=NULL, source_id=regenerated",
        )
