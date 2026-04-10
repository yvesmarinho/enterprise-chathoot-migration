"""Migrator for the ``users`` and ``account_users`` entities.

:description: Remaps ``id`` (offset_users).  Because ``email`` has a UNIQUE
    constraint across the entire destination database, this migrator pre-detects
    collisions and appends a ``+migrated`` suffix to the local-part of any
    colliding email address before insert
    (e.g., ``user@x.com`` → ``user+migrated@x.com``).

    The ``account_users`` join-table is migrated immediately after ``users``
    within the same database session block so that FK integrity is maintained.
"""

from __future__ import annotations

from sqlalchemy import MetaData, Table, text

from src.migrators.base_migrator import BaseMigrator, MigrationResult


class UsersMigrator(BaseMigrator):
    """Migrate ``users`` and ``account_users`` source → destination.

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
        """Execute users + account_users migration.

        :returns: Migration result summary for ``users``.
        :rtype: MigrationResult
        """
        self.logger.info("UsersMigrator: starting")

        # Reflect tables
        src_meta = MetaData()
        src_users = Table("users", src_meta, autoload_with=self.source_engine)
        src_au = Table("account_users", src_meta, autoload_with=self.source_engine)
        dest_meta = MetaData()
        dest_users = Table("users", dest_meta, autoload_with=self.dest_engine)
        dest_au = Table("account_users", dest_meta, autoload_with=self.dest_engine)

        # Load existing emails in destination for collision detection
        with self.dest_engine.connect() as conn:
            existing_emails: set[str] = {
                str(row[0]).lower()
                for row in conn.execute(
                    text("SELECT email FROM users WHERE email IS NOT NULL")
                ).fetchall()
            }
            migrated_accounts = self.state_repo.get_migrated_ids(conn, "accounts")

        # Fetch all source users
        with self.source_engine.connect() as conn:
            rows = [dict(r) for r in conn.execute(src_users.select()).mappings().all()]
            au_rows = [dict(r) for r in conn.execute(src_au.select()).mappings().all()]

        self.logger.info(
            "UsersMigrator: %d users, %d account_users fetched from source",
            len(rows),
            len(au_rows),
        )

        # Track which source user IDs are successfully migrated (for account_users)
        migrated_user_ids: set[int] = set()

        def remap_fn(row: dict) -> dict | None:
            """Remap PK and deduplicate email for a users row.

            :param row: Source row as plain dict.
            :type row: dict
            :returns: Destination row, or ``None`` to skip.
            :rtype: dict | None
            """
            new_row = dict(row)
            new_row["id"] = self.id_remapper.remap(int(row["id"]), "users")

            # Handle email collision
            email = (new_row.get("email") or "").strip()
            if email and email.lower() in existing_emails:
                local, _, domain = email.partition("@")
                new_email = f"{local}+migrated@{domain}"
                self.logger.warning(
                    "UsersMigrator: email collision for user id_origem=%d — "
                    "rewriting email (masked)",
                    row["id"],
                )
                new_row["email"] = new_email
                # Register new email to prevent further collisions within batch
                existing_emails.add(new_email.lower())
            elif email:
                existing_emails.add(email.lower())

            migrated_user_ids.add(int(row["id"]))
            return new_row

        result = self._run_batches(rows, "users", dest_users, remap_fn)

        # --- Migrate account_users join table ---
        self.logger.info("UsersMigrator: migrating account_users (%d rows)", len(au_rows))
        au_migrated = 0
        au_skipped = 0
        with self.dest_engine.connect() as dest_conn:
            with dest_conn.begin():
                for au_row in au_rows:
                    user_id_origin = int(au_row["user_id"])
                    account_id_origin = int(au_row["account_id"])

                    if user_id_origin not in migrated_user_ids:
                        au_skipped += 1
                        continue
                    if account_id_origin not in migrated_accounts:
                        au_skipped += 1
                        continue

                    new_au = {
                        **au_row,
                        "user_id": self.id_remapper.remap(user_id_origin, "users"),
                        "account_id": self.id_remapper.remap(account_id_origin, "accounts"),
                    }
                    try:
                        dest_conn.execute(dest_au.insert().values(**new_au))
                        au_migrated += 1
                    except Exception as exc:  # noqa: BLE001
                        self.logger.warning(
                            "UsersMigrator: account_users row skipped (user=%d account=%d): %s",
                            user_id_origin,
                            account_id_origin,
                            exc,
                        )
                        au_skipped += 1

        self.logger.info(
            "UsersMigrator: account_users complete — migrated=%d skipped=%d",
            au_migrated,
            au_skipped,
        )
        self.logger.info(
            "UsersMigrator: complete — migrated=%d skipped=%d failed=%d",
            result.migrated,
            result.skipped,
            len(result.failed_ids),
        )
        return result
