"""Migrator for the ``conversations`` entity.

:description: Remaps five FK columns:

    * ``id``               → ``id + offset_conversations``
    * ``account_id``       → ``account_id + offset_accounts``  (required — skip on orphan)
    * ``inbox_id``         → ``inbox_id + offset_inboxes``     (required — skip on orphan)
    * ``contact_id``       → ``contact_id + offset_contacts``  (nullable — NULL-out if orphan)
    * ``assignee_id``      → ``assignee_id + offset_users``    (nullable — NULL-out if unmigrated)
    * ``team_id``          → ``team_id + offset_teams``        (nullable — NULL-out if unmigrated)

    ``meta`` and ``additional_attributes`` JSONB fields are masked in log output.
"""

from __future__ import annotations

import uuid

from sqlalchemy import MetaData, Table, text

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
            # BUG-06 FIX: load migrated contact_inboxes IDs for contact_inbox_id remapping.
            migrated_contact_inboxes = self.state_repo.get_migrated_ids(conn, "contact_inboxes")
            # BUG-06 FIX: build (contact_id, inbox_id) → contact_inboxes.id fallback map
            # covering ALL contact_inboxes currently in DEST (includes both pre-existing
            # records and those just inserted by ContactInboxesMigrator in this run).
            _dest_ci_pairs: dict[tuple[int, int], int] = {
                (int(r[0]), int(r[1])): int(r[2])
                for r in conn.execute(
                    text("SELECT contact_id, inbox_id, id FROM public.contact_inboxes")
                ).fetchall()
            }
            # BUG-04 fix: pre-load MAX(display_id) per account in DEST so we can
            # resequence display_id for each migrated conversation without collisions.
            _display_id_counters: dict[int, int] = {}
            for dest_acct_id_row in conn.execute(
                text(
                    "SELECT account_id, COALESCE(MAX(display_id), 0) "
                    "FROM public.conversations GROUP BY account_id"
                )
            ).fetchall():
                _display_id_counters[int(dest_acct_id_row[0])] = int(dest_acct_id_row[1])

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

            # Nullable FK: contact_id — NULL-out if orphan (BUG-03 fix).
            # Skipping the whole conversation when contact_id is unmigrated causes
            # cascade loss of all messages and attachments for that conversation,
            # violating the 100%-migration goal.  A NULL contact_id is acceptable
            # in Chatwoot (contact can be re-linked manually later).
            contact_id = row.get("contact_id")
            if contact_id is not None:
                contact_id_origin = int(contact_id)
                if contact_id_origin not in migrated_contacts:
                    self.logger.warning(
                        "ConversationsMigrator: id=%d contact_id=%d not migrated — nulling out",
                        id_origin,
                        contact_id_origin,
                    )
                    new_row["contact_id"] = None
                else:
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

            # BUG-06 FIX: remap contact_inbox_id.
            # The source value is a SOURCE contact_inboxes.id; without remapping
            # it becomes an invalid FK in DEST, causing HTTP 404 for all migrated
            # conversations in the Chatwoot API.
            #
            # Resolution order:
            #   1. If src CI was successfully migrated → use id_remapper
            #   2. Else → look up (dest_contact_id, dest_inbox_id) pair in DEST
            #   3. Else → NULL out and log warning (conversation visible but
            #      the contact-inbox link is lost; can be repaired manually)
            ci_val = row.get("contact_inbox_id")
            if ci_val is not None:
                ci_origin = int(ci_val)
                if ci_origin in migrated_contact_inboxes:
                    new_row["contact_inbox_id"] = self.id_remapper.remap(
                        ci_origin, "contact_inboxes"
                    )
                else:
                    # Fallback: resolve by (contact_id, inbox_id) pair in DEST
                    dest_contact_id = new_row.get("contact_id")
                    dest_inbox_id = new_row.get("inbox_id")
                    if dest_contact_id and dest_inbox_id:
                        fallback_ci = _dest_ci_pairs.get((int(dest_contact_id), int(dest_inbox_id)))
                        if fallback_ci is not None:
                            new_row["contact_inbox_id"] = fallback_ci
                        else:
                            self.logger.warning(
                                "ConversationsMigrator: id=%d — contact_inbox_id=%d not "
                                "migrated and no (contact_id=%s, inbox_id=%s) pair in "
                                "DEST — nulling out",
                                id_origin,
                                ci_origin,
                                dest_contact_id,
                                dest_inbox_id,
                            )
                            new_row["contact_inbox_id"] = None
                    else:
                        new_row["contact_inbox_id"] = None

            # Regenerate uuid to avoid UniqueViolation on index_conversations_on_uuid
            new_row["uuid"] = str(uuid.uuid4())

            # BUG-04 fix: resequence display_id per account so it never collides
            # with display_ids already present in DEST for the same account.
            dest_acct_id = new_row["account_id"]
            _display_id_counters[dest_acct_id] = _display_id_counters.get(dest_acct_id, 0) + 1
            new_row["display_id"] = _display_id_counters[dest_acct_id]

            return new_row

        result = self._run_batches(rows, "conversations", dest_table, remap_fn)

        self.logger.info(
            "ConversationsMigrator: complete — migrated=%d skipped=%d failed=%d",
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

        :returns: ``"conversations"``
        :rtype: str
        """
        return "conversations"

    def _fetch_all_source_rows(self) -> list[dict]:
        """Fetch all rows from source ``conversations``.

        :returns: All source rows as plain dicts.
        :rtype: list[dict]
        """
        src_meta = MetaData()
        src_table = Table("conversations", src_meta, autoload_with=self.source_engine)
        with self.source_engine.connect() as conn:
            return [dict(r) for r in conn.execute(src_table.select()).mappings().all()]

    def _classify_row_poc(  # type: ignore[override]
        self,
        row: dict,
        migrated_sets: dict[str, set[int]],
    ) -> tuple:
        """Classify a conversations row for POC dry-run.

        Required FKs (skip on orphan): ``account_id``, ``inbox_id``,
        ``contact_id`` (treated as required per spec).
        Nullable FKs (NULL-out): ``assignee_id``, ``team_id``.

        :param row: Source row as plain dict.
        :type row: dict
        :param migrated_sets: Dest ID sets keyed by table name.
        :type migrated_sets: dict[str, set[int]]
        :returns: ``(outcome, reason)`` tuple.
        :rtype: tuple
        """
        from src.reports.poc_reporter import Outcome

        accts = migrated_sets.get("accounts", set())
        inboxes = migrated_sets.get("inboxes", set())
        contacts = migrated_sets.get("contacts", set())
        users = migrated_sets.get("users", set())
        teams = migrated_sets.get("teams", set())

        account_id = int(row["account_id"])
        if account_id not in accts:
            return (
                Outcome.ORPHAN_FK_SKIP,
                f"account_id={account_id} not in migrated accounts",
            )

        inbox_id = int(row["inbox_id"])
        if inbox_id not in inboxes:
            return (
                Outcome.ORPHAN_FK_SKIP,
                f"inbox_id={inbox_id} not in migrated inboxes",
            )

        contact_id = row.get("contact_id")
        nulled: list[str] = []
        if contact_id is not None and int(contact_id) not in contacts:
            nulled.append(f"contact_id={contact_id}")  # null-out, do not skip

        assignee_id = row.get("assignee_id")
        if assignee_id is not None and int(assignee_id) not in users:
            nulled.append(f"assignee_id={assignee_id}")
        team_id = row.get("team_id")
        if team_id is not None and int(team_id) not in teams:
            nulled.append(f"team_id={team_id}")
        if nulled:
            return (
                Outcome.WOULD_MIGRATE_MODIFIED,
                "nullable FKs NULL-outed: " + ", ".join(nulled),
            )
        return Outcome.WOULD_MIGRATE, "clean"
