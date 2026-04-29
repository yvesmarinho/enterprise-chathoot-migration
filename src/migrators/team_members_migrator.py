"""Migrator for the ``team_members`` entity.

:description: Remaps ``id`` (offset_team_members), ``team_id`` (teams)
    and ``user_id`` (users). Records with orphaned ``team_id`` or ``user_id``
    are skipped with a WARNING log entry.
"""

from __future__ import annotations

from sqlalchemy import MetaData, Table

from src.migrators.base_migrator import BaseMigrator, MigrationResult


class TeamMembersMigrator(BaseMigrator):
    """Migrate all rows from ``team_members`` source → destination.

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
        """Execute team_members migration.

        :returns: Migration result summary for ``team_members``.
        :rtype: MigrationResult
        """
        self.logger.info("TeamMembersMigrator: starting")
        src_meta = MetaData()
        src_table = Table("team_members", src_meta, autoload_with=self.source_engine)
        dest_meta = MetaData()
        dest_table = Table("team_members", dest_meta, autoload_with=self.dest_engine)

        with self.dest_engine.connect() as conn:
            migrated_teams = self.state_repo.get_migrated_ids(conn, "teams")
            migrated_users = self.state_repo.get_migrated_ids(conn, "users")

        with self.source_engine.connect() as conn:
            rows = [dict(r) for r in conn.execute(src_table.select()).mappings().all()]

        self.logger.info("TeamMembersMigrator: %d source rows fetched", len(rows))

        def remap_fn(row: dict) -> dict | None:
            """Remap PK, team_id and user_id for a team_members row.

            :param row: Source row as plain dict.
            :type row: dict
            :returns: Destination row with remapped IDs, or ``None`` if FK orphan.
            :rtype: dict | None
            """
            team_id_origin = int(row["team_id"])
            user_id_origin = int(row["user_id"])

            if team_id_origin not in migrated_teams:
                self.logger.warning(
                    "TeamMembersMigrator: id=%d skipped — orphan team_id=%d",
                    row["id"],
                    team_id_origin,
                )
                return None

            if user_id_origin not in migrated_users:
                self.logger.warning(
                    "TeamMembersMigrator: id=%d skipped — orphan user_id=%d",
                    row["id"],
                    user_id_origin,
                )
                return None

            return {
                **row,
                "id": self.id_remapper.remap(int(row["id"]), "team_members"),
                "team_id": self.id_remapper.remap(team_id_origin, "teams"),
                "user_id": self.id_remapper.remap(user_id_origin, "users"),
            }

        result = self._run_batches(rows, "team_members", dest_table, remap_fn)

        self.logger.info(
            "TeamMembersMigrator: complete — migrated=%d skipped=%d failed=%d",
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

        :returns: ``"team_members"``
        :rtype: str
        """
        return "team_members"

    def _fetch_all_source_rows(self) -> list[dict]:
        """Fetch all rows from source ``team_members``.

        :returns: All source rows as plain dicts.
        :rtype: list[dict]
        """
        src_meta = MetaData()
        src_table = Table("team_members", src_meta, autoload_with=self.source_engine)
        with self.source_engine.connect() as conn:
            return [dict(r) for r in conn.execute(src_table.select()).mappings().all()]

    def _classify_row_poc(
        self,
        row: dict,
        migrated_sets: dict[str, set[int]],
    ) -> tuple:
        """Classify a team_members row for dry-run.

        :param row: Source row as plain dict.
        :type row: dict
        :param migrated_sets: Dest ID sets keyed by table name.
        :type migrated_sets: dict[str, set[int]]
        :returns: ``(outcome, reason)`` tuple.
        :rtype: tuple
        """
        from src.reports.poc_reporter import Outcome

        if int(row["team_id"]) not in migrated_sets.get("teams", set()):
            return (
                Outcome.ORPHAN_FK_SKIP,
                f"team_id={row['team_id']} not in migrated teams",
            )
        if int(row["user_id"]) not in migrated_sets.get("users", set()):
            return (
                Outcome.ORPHAN_FK_SKIP,
                f"user_id={row['user_id']} not in migrated users",
            )
        return Outcome.WOULD_MIGRATE, "clean"
