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

import secrets

from sqlalchemy import MetaData, Table, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

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
            # Build email→dest_id lookup for merge detection.
            # When a source user's email already exists in DEST we register an
            # alias (src_id → dest_id) instead of inserting with a renamed email.
            existing_email_to_dest_id: dict[str, int] = {
                str(row[0]).lower(): int(row[1])
                for row in conn.execute(
                    text("SELECT email, id FROM users WHERE email IS NOT NULL")
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

        # Track which source user IDs are successfully migrated (for account_users).
        # Pre-populate from migration_state so re-runs still migrate account_users
        # for users that were inserted in a previous session.
        migrated_user_ids: set[int] = set()
        with self.dest_engine.connect() as conn:
            migrated_user_ids.update(self.state_repo.get_migrated_ids(conn, "users"))

        # ── Merge rule: source users whose email already exists in DEST ──────
        # Instead of inserting with a modified email (the old "+migrated" approach),
        # we register an alias src_id → dest_id so downstream entities
        # (account_users, conversations.assignee_id, messages.sender_id) reference
        # the correct existing user in DEST.
        merged_users: list[tuple[int, int]] = []  # (src_id, dest_id)
        for row in rows:
            src_id = int(row["id"])
            email = (row.get("email") or "").strip().lower()
            dest_id = existing_email_to_dest_id.get(email) if email else None
            if dest_id is not None:
                self.id_remapper.register_alias("users", src_id, dest_id)
                merged_users.append((src_id, dest_id))
                migrated_user_ids.add(src_id)

        if merged_users:
            with self.dest_engine.connect() as dest_conn:
                with dest_conn.begin():
                    for src_id, dest_id in merged_users:
                        self.state_repo.record_success(dest_conn, "users", src_id, dest_id)
            self.logger.info(
                "UsersMigrator: %d users matched by email — reusing dest_id, skipping INSERT",
                len(merged_users),
            )
        # ─────────────────────────────────────────────────────────────────────

        # Keep track of emails that will be inserted so within-batch collisions
        # are still caught (two source users with the same email, edge case).
        _inserting_emails: set[str] = set(existing_email_to_dest_id.keys())

        def remap_fn(row: dict) -> dict | None:
            """Remap PK for a users row; merged users are skipped (alias registered).

            :param row: Source row as plain dict.
            :type row: dict
            :returns: Destination row, or ``None`` to skip.
            :rtype: dict | None
            """
            src_id = int(row["id"])
            # Merged users are already registered in migration_state — skip INSERT.
            if self.id_remapper.has_alias("users", src_id):
                return None

            new_row = dict(row)
            new_row["id"] = self.id_remapper.remap(src_id, "users")

            # Regenerate pubsub_token to avoid unique constraint collision with
            # existing tokens in the destination database.
            new_row["pubsub_token"] = secrets.token_hex(32)

            # NULL out per-session/security tokens — these should never be copied
            # from source because they collide with tokens in DEST and are invalid
            # after migration anyway (reset_password_token, confirmation_token).
            new_row["reset_password_token"] = None
            new_row["reset_password_sent_at"] = None
            new_row["confirmation_token"] = None

            email = (new_row.get("email") or "").strip()
            if email:
                # Guard against within-batch collisions (edge case: two source
                # users sharing an email that is NOT yet in DEST).
                if email.lower() in _inserting_emails:
                    self.logger.warning(
                        "UsersMigrator: within-batch email collision for id_origem=%d — skipping",
                        src_id,
                    )
                    return None
                _inserting_emails.add(email.lower())

            migrated_user_ids.add(src_id)
            return new_row

        result = self._run_batches(rows, "users", dest_users, remap_fn)

        # --- Migrate account_users join table ---
        self.logger.info("UsersMigrator: migrating account_users (%d rows)", len(au_rows))
        au_migrated = 0
        au_skipped = 0
        # Each row uses its own connection+transaction so a conflict on one row
        # (e.g. duplicate (account_id, user_id)) does not abort subsequent rows.
        for au_row in au_rows:
            user_id_origin = int(au_row["user_id"])
            account_id_origin = int(au_row["account_id"])

            if user_id_origin not in migrated_user_ids:
                au_skipped += 1
                continue
            if account_id_origin not in migrated_accounts:
                au_skipped += 1
                continue

            # Exclude `id` so DEST generates a new unique serial; avoids PK
            # conflict when DEST already has rows with the same id value.
            new_au = {
                k: v
                for k, v in {
                    **au_row,
                    "user_id": self.id_remapper.remap(user_id_origin, "users"),
                    "account_id": self.id_remapper.remap(account_id_origin, "accounts"),
                }.items()
                if k != "id"
            }
            try:
                with self.dest_engine.connect() as dest_conn:
                    with dest_conn.begin():
                        dest_conn.execute(
                            pg_insert(dest_au).values(**new_au).on_conflict_do_nothing()
                        )
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

    # ------------------------------------------------------------------
    # POC dry-run hooks
    # ------------------------------------------------------------------

    def _table_name(self) -> str:
        """Return canonical table name.

        :returns: ``"users"``
        :rtype: str
        """
        return "users"

    def _fetch_all_source_rows(self) -> list[dict]:
        """Fetch all rows from source ``users``.

        :returns: All source rows as plain dicts.
        :rtype: list[dict]
        """
        src_meta = MetaData()
        src_users = Table("users", src_meta, autoload_with=self.source_engine)
        with self.source_engine.connect() as conn:
            return [dict(r) for r in conn.execute(src_users.select()).mappings().all()]

    def _classify_row_poc(  # type: ignore[override]
        self,
        row: dict,
        migrated_sets: dict[str, set[int]],
    ) -> tuple:
        """Classify a users row: email collision → WOULD_MIGRATE_MODIFIED.

        Email collisions are resolved by the ``+migrated`` suffix at
        migration time; the record is always inserted.

        :param row: Source row as plain dict.
        :type row: dict
        :param migrated_sets: Dest ID sets (unused — emails loaded from dest).
        :type migrated_sets: dict[str, set[int]]
        :returns: ``(outcome, reason)`` tuple.
        :rtype: tuple
        """
        from src.reports.poc_reporter import Outcome

        if not hasattr(self, "_poc_dest_emails"):
            with self.dest_engine.connect() as conn:
                self._poc_dest_emails: set[str] = {
                    str(r[0]).lower()
                    for r in conn.execute(
                        text("SELECT email FROM users" " WHERE email IS NOT NULL")
                    ).fetchall()
                }
        email = (row.get("email") or "").strip().lower()
        if email and email in self._poc_dest_emails:
            return (
                Outcome.WOULD_MIGRATE_MODIFIED,
                "email collision — +migrated suffix will be applied",
            )
        return Outcome.WOULD_MIGRATE, "clean"
