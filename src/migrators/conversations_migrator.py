"""Migrator for the ``conversations`` entity.

:description: Remaps five FK columns:

    * ``id``               → ``id + offset_conversations``
    * ``account_id``       → ``account_id + offset_accounts``  (required — skip on orphan)
    * ``inbox_id``         → ``inbox_id + offset_inboxes``     (required — skip on orphan)
    * ``contact_id``       → ``contact_id + offset_contacts``  (nullable — skip on orphan)
    * ``assignee_id``      → ``assignee_id + offset_users``    (nullable — NULL-out if unmigrated)
    * ``team_id``          → ``team_id + offset_teams``        (nullable — NULL-out if unmigrated)

    ``meta`` and ``additional_attributes`` JSONB fields are masked in log output.
"""

from __future__ import annotations

from sqlalchemy import MetaData, Table

from src.migrators.base_migrator import BaseMigrator, MigrationResult


class ConversationsMigrator(BaseMigrator):
    """Migrate all rows from ``conversations`` source → destination.

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
        """Execute conversations migration.

        :returns: Migration result summary for ``conversations``.
        :rtype: MigrationResult
        """
        self.logger.info("ConversationsMigrator: starting")
        src_meta = MetaData()
        src_table = Table("conversations", src_meta, autoload_with=self.source_engine)
        dest_meta = MetaData()
        dest_table = Table("conversations", dest_meta, autoload_with=self.dest_engine)

        with self.dest_engine.connect() as conn:
            migrated_accounts = self.state_repo.get_migrated_ids(conn, "accounts")
            migrated_inboxes = self.state_repo.get_migrated_ids(conn, "inboxes")
            migrated_contacts = self.state_repo.get_migrated_ids(conn, "contacts")
            migrated_users = self.state_repo.get_migrated_ids(conn, "users")
            migrated_teams = self.state_repo.get_migrated_ids(conn, "teams")

        with self.source_engine.connect() as conn:
            rows = [dict(r) for r in conn.execute(src_table.select()).mappings().all()]

        self.logger.info("ConversationsMigrator: %d source rows fetched", len(rows))

        def remap_fn(row: dict) -> dict | None:  # noqa: C901
            """Remap all FK columns for a conversations row.

            :param row: Source row as plain dict.
            :type row: dict
            :returns: Destination row with remapped IDs, or ``None`` if required FK orphan.
            :rtype: dict | None
            """
            id_origin = int(row["id"])
            account_id_origin = int(row["account_id"])
            inbox_id_origin = int(row["inbox_id"])

            # Required FKs — skip on orphan
            if account_id_origin not in migrated_accounts:
                self.logger.warning(
                    "ConversationsMigrator: id=%d skipped — orphan account_id=%d",
                    id_origin,
                    account_id_origin,
                )
                return None
            if inbox_id_origin not in migrated_inboxes:
                self.logger.warning(
                    "ConversationsMigrator: id=%d skipped — orphan inbox_id=%d",
                    id_origin,
                    inbox_id_origin,
                )
                return None

            new_row = dict(row)
            new_row["id"] = self.id_remapper.remap(id_origin, "conversations")
            new_row["account_id"] = self.id_remapper.remap(account_id_origin, "accounts")
            new_row["inbox_id"] = self.id_remapper.remap(inbox_id_origin, "inboxes")

            # Nullable FK: contact_id — skip record if orphan
            contact_id = row.get("contact_id")
            if contact_id is not None:
                contact_id_origin = int(contact_id)
                if contact_id_origin not in migrated_contacts:
                    self.logger.warning(
                        "ConversationsMigrator: id=%d skipped — orphan contact_id=%d",
                        id_origin,
                        contact_id_origin,
                    )
                    return None
                new_row["contact_id"] = self.id_remapper.remap(contact_id_origin, "contacts")

            # Nullable FK: assignee_id — NULL-out if unmigrated
            assignee_id = row.get("assignee_id")
            if assignee_id is not None:
                assignee_id_origin = int(assignee_id)
                if assignee_id_origin in migrated_users:
                    new_row["assignee_id"] = self.id_remapper.remap(assignee_id_origin, "users")
                else:
                    new_row["assignee_id"] = None

            # Nullable FK: team_id — NULL-out if unmigrated
            team_id = row.get("team_id")
            if team_id is not None:
                team_id_origin = int(team_id)
                if team_id_origin in migrated_teams:
                    new_row["team_id"] = self.id_remapper.remap(team_id_origin, "teams")
                else:
                    new_row["team_id"] = None

            return new_row

        result = self._run_batches(rows, "conversations", dest_table, remap_fn)

        self.logger.info(
            "ConversationsMigrator: complete — migrated=%d skipped=%d failed=%d",
            result.migrated,
            result.skipped,
            len(result.failed_ids),
        )
        return result
