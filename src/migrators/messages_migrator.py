"""Migrator for the ``messages`` entity.

:description: Remaps three FK columns:

    * ``id``                → ``id + offset_messages``
    * ``account_id``        → ``account_id + offset_accounts``      (required — skip on orphan)
    * ``conversation_id``   → ``conversation_id + offset_conversations``
                              (nullable — skip record on orphan)
    * ``sender_id``         → ``sender_id + offset_users``
      (nullable — NULL-out if unmigrated)

    ``content`` (TEXT) and ``content_attributes`` (JSONB) are masked in log
    output automatically by the attached ``MaskingHandler``.

    This is the largest entity (~310,155 records → ~621 batches of 500).
"""

from __future__ import annotations

from sqlalchemy import MetaData, Table

from src.migrators.base_migrator import BaseMigrator, MigrationResult


class MessagesMigrator(BaseMigrator):
    """Migrate all rows from ``messages`` source → destination.

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
        """Execute messages migration.

        :returns: Migration result summary for ``messages``.
        :rtype: MigrationResult
        """
        self.logger.info("MessagesMigrator: starting")
        src_meta = MetaData()
        src_table = Table("messages", src_meta, autoload_with=self.source_engine)
        dest_meta = MetaData()
        dest_table = Table("messages", dest_meta, autoload_with=self.dest_engine)

        with self.dest_engine.connect() as conn:
            migrated_accounts = self.state_repo.get_migrated_ids(conn, "accounts")
            migrated_conversations = self.state_repo.get_migrated_ids(conn, "conversations")
            migrated_users = self.state_repo.get_migrated_ids(conn, "users")

        with self.source_engine.connect() as conn:
            rows = [dict(r) for r in conn.execute(src_table.select()).mappings().all()]

        self.logger.info("MessagesMigrator: %d source rows fetched", len(rows))

        def remap_fn(row: dict) -> dict | None:
            """Remap FK columns for a messages row.

            :param row: Source row as plain dict.
            :type row: dict
            :returns: Destination row with remapped IDs, or ``None`` if required FK orphan.
            :rtype: dict | None
            """
            id_origin = int(row["id"])
            account_id_origin = int(row["account_id"])

            # Required FK: account_id
            if account_id_origin not in migrated_accounts:
                self.logger.warning(
                    "MessagesMigrator: id=%d skipped — orphan account_id=%d",
                    id_origin,
                    account_id_origin,
                )
                return None

            new_row = dict(row)
            new_row["id"] = self.id_remapper.remap(id_origin, "messages")
            new_row["account_id"] = self.id_remapper.remap(account_id_origin, "accounts")

            # Nullable FK: conversation_id — skip record on orphan
            conv_id = row.get("conversation_id")
            if conv_id is not None:
                conv_id_origin = int(conv_id)
                if conv_id_origin not in migrated_conversations:
                    self.logger.warning(
                        "MessagesMigrator: id=%d skipped — orphan conversation_id=%d",
                        id_origin,
                        conv_id_origin,
                    )
                    return None
                new_row["conversation_id"] = self.id_remapper.remap(conv_id_origin, "conversations")

            # Nullable FK: sender_id — NULL-out if unmigrated
            sender_id = row.get("sender_id")
            if sender_id is not None:
                sender_id_origin = int(sender_id)
                if sender_id_origin in migrated_users:
                    new_row["sender_id"] = self.id_remapper.remap(sender_id_origin, "users")
                else:
                    new_row["sender_id"] = None

            return new_row

        result = self._run_batches(rows, "messages", dest_table, remap_fn)

        self.logger.info(
            "MessagesMigrator: complete — migrated=%d skipped=%d failed=%d",
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

        :returns: ``"messages"``
        :rtype: str
        """
        return "messages"

    def _fetch_all_source_rows(self) -> list[dict]:
        """Fetch all rows from source ``messages``.

        :returns: All source rows as plain dicts.
        :rtype: list[dict]
        """
        src_meta = MetaData()
        src_table = Table("messages", src_meta, autoload_with=self.source_engine)
        with self.source_engine.connect() as conn:
            return [dict(r) for r in conn.execute(src_table.select()).mappings().all()]

    def _classify_row_poc(  # type: ignore[override]
        self,
        row: dict,
        migrated_sets: dict[str, set[int]],
    ) -> tuple:
        """Classify a messages row for POC dry-run.

        Required FKs (skip on orphan): ``account_id``, ``conversation_id``.
        Nullable FK (NULL-out): ``sender_id``.

        :param row: Source row as plain dict.
        :type row: dict
        :param migrated_sets: Dest ID sets keyed by table name.
        :type migrated_sets: dict[str, set[int]]
        :returns: ``(outcome, reason)`` tuple.
        :rtype: tuple
        """
        from src.reports.poc_reporter import Outcome

        accts = migrated_sets.get("accounts", set())
        convs = migrated_sets.get("conversations", set())
        users = migrated_sets.get("users", set())

        account_id = int(row["account_id"])
        if account_id not in accts:
            return (
                Outcome.ORPHAN_FK_SKIP,
                f"account_id={account_id} not in migrated accounts",
            )

        conv_id = row.get("conversation_id")
        if conv_id is not None and int(conv_id) not in convs:
            return (
                Outcome.ORPHAN_FK_SKIP,
                f"conversation_id={conv_id} not in migrated conversations",
            )

        sender_id = row.get("sender_id")
        if sender_id is not None and int(sender_id) not in users:
            return (
                Outcome.WOULD_MIGRATE_MODIFIED,
                f"sender_id={sender_id} not migrated → will be NULL-outed",
            )
        return Outcome.WOULD_MIGRATE, "clean"
