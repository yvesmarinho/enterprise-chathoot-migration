"""Migrator for the ``attachments`` entity.

:description: Remaps two FK columns:

    * ``id``          → ``id + offset_attachments``
    * ``message_id``  → ``message_id + offset_messages``   (required — skip on orphan)
    * ``account_id``  → ``account_id + offset_accounts``   (required — skip on orphan)

    The ``external_url`` field (S3 reference) is copied verbatim — no file
    movement is performed.  Files remain in the original S3 bucket and are
    served by reference.
"""

from __future__ import annotations

from sqlalchemy import MetaData, Table

from src.migrators.base_migrator import BaseMigrator, MigrationResult


class AttachmentsMigrator(BaseMigrator):
    """Migrate all rows from ``attachments`` source → destination.

    ``external_url`` is copied as-is (S3 reference only — no actual file
    movement occurs).

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
        """Execute attachments migration.

        :returns: Migration result summary for ``attachments``.
        :rtype: MigrationResult
        """
        self.logger.info("AttachmentsMigrator: starting")
        src_meta = MetaData()
        src_table = Table("attachments", src_meta, autoload_with=self.source_engine)
        dest_meta = MetaData()
        dest_table = Table("attachments", dest_meta, autoload_with=self.dest_engine)

        with self.dest_engine.connect() as conn:
            migrated_messages = self.state_repo.get_migrated_ids(conn, "messages")
            migrated_accounts = self.state_repo.get_migrated_ids(conn, "accounts")

        with self.source_engine.connect() as conn:
            rows = [dict(r) for r in conn.execute(src_table.select()).mappings().all()]

        self.logger.info("AttachmentsMigrator: %d source rows fetched", len(rows))

        def remap_fn(row: dict) -> dict | None:
            """Remap PK and FK columns for an attachments row.

            :param row: Source row as plain dict.
            :type row: dict
            :returns: Destination row with remapped IDs or ``None`` if FK orphan.
            :rtype: dict | None
            """
            id_origin = int(row["id"])
            message_id_origin = int(row["message_id"])
            account_id_origin = int(row["account_id"])

            if message_id_origin not in migrated_messages:
                self.logger.warning(
                    "AttachmentsMigrator: id=%d skipped — orphan message_id=%d",
                    id_origin,
                    message_id_origin,
                )
                return None

            if account_id_origin not in migrated_accounts:
                self.logger.warning(
                    "AttachmentsMigrator: id=%d skipped — orphan account_id=%d",
                    id_origin,
                    account_id_origin,
                )
                return None

            return {
                **row,
                "id": self.id_remapper.remap(id_origin, "attachments"),
                "message_id": self.id_remapper.remap(message_id_origin, "messages"),
                "account_id": self.id_remapper.remap(account_id_origin, "accounts"),
                # external_url copied verbatim — no S3 operations
            }

        result = self._run_batches(rows, "attachments", dest_table, remap_fn)

        self.logger.info(
            "AttachmentsMigrator: complete — migrated=%d skipped=%d failed=%d",
            result.migrated,
            result.skipped,
            len(result.failed_ids),
        )
        return result
