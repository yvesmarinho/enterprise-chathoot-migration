"""Migrator for the ``inbox_members`` entity.

:description: Remaps two FK columns:

    * ``id``       → ``id + offset_inbox_members``
        * ``user_id``   → ``user_id + offset_users``
            (required — skip on orphan)
        * ``inbox_id``  → ``inbox_id + offset_inboxes``
            (required — skip on orphan)

    The destination table does not exist in older restored databases, so this
    migrator creates it on demand before loading data.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, Column, DateTime, MetaData, Table
from sqlalchemy import UniqueConstraint, text

from src.migrators.base_migrator import BaseMigrator, MigrationResult

_METADATA = MetaData()
_INBOX_MEMBERS_TABLE = Table(
    "inbox_members",
    _METADATA,
    Column("id", BigInteger, primary_key=True, autoincrement=False),
    Column("user_id", BigInteger, nullable=False),
    Column("inbox_id", BigInteger, nullable=False),
    Column("created_at", DateTime(timezone=False), nullable=False),
    Column("updated_at", DateTime(timezone=False), nullable=False),
    UniqueConstraint(
        "inbox_id",
        "user_id",
        name="uq_inbox_members_inbox_user",
    ),
)


class InboxMembersMigrator(BaseMigrator):
    """Migrate all rows from ``inbox_members`` source → destination."""

    def migrate(self) -> MigrationResult:
        """Execute inbox_members migration."""
        self.logger.info("InboxMembersMigrator: starting")

        # Older restored DEST databases may not have the table yet.
        _METADATA.create_all(
            self.dest_engine,
            tables=[_INBOX_MEMBERS_TABLE],
            checkfirst=True,
        )

        src_meta = MetaData()
        src_table = Table(
            "inbox_members",
            src_meta,
            autoload_with=self.source_engine,
        )

        with self.dest_engine.connect() as conn:
            migrated_users = self.state_repo.get_migrated_ids(conn, "users")
            migrated_inboxes = self.state_repo.get_migrated_ids(
                conn,
                "inboxes",
            )
            existing_pairs = {
                (int(row[0]), int(row[1])): int(row[2])
                for row in conn.execute(
                    text("SELECT inbox_id, user_id, id " "FROM public.inbox_members")
                ).fetchall()
            }

        rows = self._select_source_rows(src_table)
        self.logger.info(
            "InboxMembersMigrator: %d source rows fetched",
            len(rows),
        )

        # Register duplicates already present in DEST.
        dedup_pairs: list[tuple[int, int]] = []
        for row in rows:
            src_id = int(row["id"])
            src_user_id = int(row["user_id"])
            src_inbox_id = int(row["inbox_id"])

            if src_user_id not in migrated_users or src_inbox_id not in migrated_inboxes:
                continue

            dest_user_id = self.id_remapper.remap(src_user_id, "users")
            dest_inbox_id = self.id_remapper.remap(src_inbox_id, "inboxes")
            existing_dest_id = existing_pairs.get((dest_inbox_id, dest_user_id))
            if existing_dest_id is not None:
                dedup_pairs.append((src_id, existing_dest_id))
                self.id_remapper.register_alias(
                    "inbox_members",
                    src_id,
                    existing_dest_id,
                )

        if dedup_pairs:
            with self.dest_engine.connect() as conn:
                with conn.begin():
                    self.state_repo.record_success_bulk(
                        conn,
                        "inbox_members",
                        dedup_pairs,
                    )
            self.logger.info(
                "InboxMembersMigrator: %d pairs already present in DEST",
                len(dedup_pairs),
            )

        seen_pairs = set(existing_pairs)

        def remap_fn(row: dict) -> dict | None:
            """Remap PK and FK columns for an inbox_members row."""
            src_id = int(row["id"])
            src_user_id = int(row["user_id"])
            src_inbox_id = int(row["inbox_id"])

            if src_user_id not in migrated_users:
                self.logger.warning(
                    "InboxMembersMigrator: id=%d skipped — orphan user_id=%d",
                    src_id,
                    src_user_id,
                )
                return None

            if src_inbox_id not in migrated_inboxes:
                self.logger.warning(
                    "InboxMembersMigrator: id=%d skipped — orphan inbox_id=%d",
                    src_id,
                    src_inbox_id,
                )
                return None

            dest_user_id = self.id_remapper.remap(src_user_id, "users")
            dest_inbox_id = self.id_remapper.remap(src_inbox_id, "inboxes")
            unique_key = (dest_inbox_id, dest_user_id)

            if unique_key in seen_pairs:
                return None
            seen_pairs.add(unique_key)

            created_at = row.get("created_at") or datetime.now(tz=timezone.utc)
            updated_at = row.get("updated_at") or created_at

            return {
                "id": self.id_remapper.remap(src_id, "inbox_members"),
                "inbox_id": dest_inbox_id,
                "user_id": dest_user_id,
                "created_at": created_at,
                "updated_at": updated_at,
            }

        result = self._run_batches(
            rows,
            "inbox_members",
            _INBOX_MEMBERS_TABLE,
            remap_fn,
        )

        self.logger.info(
            "InboxMembersMigrator: complete — migrated=%d skipped=%d " "failed=%d",
            result.migrated,
            result.skipped,
            len(result.failed_ids),
        )
        return result

    def _table_name(self) -> str:
        return "inbox_members"

    def _fetch_all_source_rows(self) -> list[dict]:
        src_meta = MetaData()
        src_table = Table(
            "inbox_members",
            src_meta,
            autoload_with=self.source_engine,
        )
        return self._select_source_rows(src_table)

    def _classify_row_poc(
        self,
        row: dict,
        migrated_sets: dict[str, set[int]],
    ) -> tuple:
        from src.reports.poc_reporter import Outcome

        users = migrated_sets.get("users", set())
        inboxes = migrated_sets.get("inboxes", set())

        user_id = int(row["user_id"])
        if user_id not in users:
            return (
                Outcome.ORPHAN_FK_SKIP,
                f"user_id={user_id} not in migrated users",
            )

        inbox_id = int(row["inbox_id"])
        if inbox_id not in inboxes:
            return (
                Outcome.ORPHAN_FK_SKIP,
                f"inbox_id={inbox_id} not in migrated inboxes",
            )

        return Outcome.WOULD_MIGRATE, "clean"

    def _poc_safe_preview(self, row: dict) -> dict:
        return {
            "id": row.get("id"),
            "user_id": row.get("user_id"),
            "inbox_id": row.get("inbox_id"),
            "created_at": str(row.get("created_at", "")),
        }
