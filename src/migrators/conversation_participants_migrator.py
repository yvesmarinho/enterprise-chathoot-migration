"""Migrator for the ``conversation_participants`` entity.

:description: Remaps three FK columns:

    * ``id``                → ``id + offset_conversation_participants``
    * ``account_id``        → ``account_id + offset_accounts`` (required — skip on orphan)
    * ``conversation_id``   → ``conversation_id + offset_conversations`` (required — skip on orphan)
    * ``user_id``           → ``user_id + offset_users`` (required — skip on orphan)

    Conversation participants represent multi-user conversations where multiple
    agents/users are involved. All three FK columns are required for a participant
    record to be meaningful, so any orphan constraint triggers a skip.
"""

from __future__ import annotations

from sqlalchemy import MetaData, Table
from sqlalchemy.exc import NoSuchTableError

from src.migrators.base_migrator import BaseMigrator, MigrationResult
from src.utils.schema_bootstrap import ensure_public_table_exists


class ConversationParticipantsMigrator(BaseMigrator):
    """Migrate all rows from ``conversation_participants`` source → destination.

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
        """Execute conversation_participants migration.

        :returns: Migration result summary for ``conversation_participants``.
        :rtype: MigrationResult
        """
        self.logger.info("ConversationParticipantsMigrator: starting")
        src_meta = MetaData()
        src_table = Table("conversation_participants", src_meta, autoload_with=self.source_engine)
        dest_meta = MetaData()
        try:
            dest_table = Table(
                "conversation_participants", dest_meta, autoload_with=self.dest_engine
            )
        except NoSuchTableError:
            self.logger.warning(
                "ConversationParticipantsMigrator: DEST public.conversation_participants missing — bootstrapping from SOURCE"
            )
            ensure_public_table_exists(
                self.source_engine, self.dest_engine, "conversation_participants"
            )
            dest_table = Table(
                "conversation_participants", dest_meta, autoload_with=self.dest_engine
            )

        with self.dest_engine.connect() as conn:
            migrated_accounts = self.state_repo.get_migrated_ids(conn, "accounts")
            migrated_conversations = self.state_repo.get_migrated_ids(conn, "conversations")
            migrated_users = self.state_repo.get_migrated_ids(conn, "users")

        rows = self._select_source_rows(src_table)

        self.logger.info("ConversationParticipantsMigrator: %d source rows fetched", len(rows))

        def remap_fn(row: dict) -> dict | None:
            """Remap FK columns for a conversation_participants row.

            :param row: Source row as plain dict.
            :type row: dict
            :returns: Destination row with remapped IDs, or ``None`` if any required FK orphan.
            :rtype: dict | None
            """
            id_origin = int(row["id"])
            account_id_origin = int(row["account_id"])
            conversation_id_origin = int(row["conversation_id"])
            user_id_origin = int(row["user_id"])

            # Required FK: account_id
            if account_id_origin not in migrated_accounts:
                self.logger.warning(
                    "ConversationParticipantsMigrator: id=%d skipped — orphan account_id=%d",
                    id_origin,
                    account_id_origin,
                )
                return None

            # Required FK: conversation_id
            if conversation_id_origin not in migrated_conversations:
                self.logger.warning(
                    "ConversationParticipantsMigrator: id=%d skipped — orphan conversation_id=%d",
                    id_origin,
                    conversation_id_origin,
                )
                return None

            # Required FK: user_id
            if user_id_origin not in migrated_users:
                self.logger.warning(
                    "ConversationParticipantsMigrator: id=%d skipped — orphan user_id=%d",
                    id_origin,
                    user_id_origin,
                )
                return None

            new_row = dict(row)
            new_row["id"] = self.id_remapper.remap(id_origin, "conversation_participants")
            new_row["account_id"] = self.id_remapper.remap(account_id_origin, "accounts")
            new_row["conversation_id"] = self.id_remapper.remap(
                conversation_id_origin, "conversations"
            )
            new_row["user_id"] = self.id_remapper.remap(user_id_origin, "users")

            return new_row

        result = self._run_batches(rows, "conversation_participants", dest_table, remap_fn)

        self.logger.info(
            "ConversationParticipantsMigrator: complete — migrated=%d skipped=%d failed=%d",
            result.migrated,
            result.skipped,
            len(result.failed_ids),
        )
        return result

    # ------------------------------------------------------------------
    # POC dry-run hooks
    # ------------------------------------------------------------------

    def _fetch_all_source_rows(self) -> list[dict]:
        """Fetch all rows from source ``conversation_participants``.

        :returns: All source rows as plain dicts.
        :rtype: list[dict]
        """
        src_meta = MetaData()
        src_table = Table("conversation_participants", src_meta, autoload_with=self.source_engine)
        return self._select_source_rows(src_table)

    def _table_name(self) -> str:
        """Return canonical table name.

        :returns: ``"conversation_participants"``
        :rtype: str
        """
        return "conversation_participants"

    def _classify_row_poc(  # type: ignore[override]
        self,
        row: dict,
        migrated_sets: dict[str, set[int]],
    ) -> tuple:
        """Classify a conversation_participants row for POC dry-run.

        :param row: Source row as plain dict.
        :type row: dict
        :param migrated_sets: Dest ID sets keyed by table name.
        :type migrated_sets: dict[str, set[int]]
        :returns: ``(outcome, reason)`` tuple.
        :rtype: tuple
        """
        from src.reports.poc_reporter import Outcome

        account_id = int(row.get("account_id", 0))
        conversation_id = int(row.get("conversation_id", 0))
        user_id = int(row.get("user_id", 0))

        if account_id not in migrated_sets.get("accounts", set()):
            return (Outcome.ORPHAN_FK_SKIP, f"account_id={account_id} not migrated")
        if conversation_id not in migrated_sets.get("conversations", set()):
            return (Outcome.ORPHAN_FK_SKIP, f"conversation_id={conversation_id} not migrated")
        if user_id not in migrated_sets.get("users", set()):
            return (Outcome.ORPHAN_FK_SKIP, f"user_id={user_id} not migrated")
        return Outcome.WOULD_MIGRATE, "clean"
