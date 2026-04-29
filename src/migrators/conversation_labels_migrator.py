"""Migrator for conversation labels via ``taggings`` + ``tags`` tables.

:description: Chatwoot uses the ``acts-as-taggable-on`` gem which stores
    labels in two tables:

    * ``tags`` — unique label names (id, name, taggings_count)
    * ``taggings`` — polymorphic join (tag_id, taggable_type, taggable_id,
      context, tagger_type, tagger_id, created_at)

    Only ``taggable_type = 'Conversation'`` and ``context = 'labels'``
    entries are migrated. ``tags`` are deduplicated by name so pre-existing
    DEST tags are reused. ``taggings.taggable_id`` (conversation_id) and
    ``taggings.tagger_id`` (user_id, when tagger_type = 'User') are
    remapped via migration_state.

    Records with orphaned ``taggable_id`` (conversation not migrated) are
    skipped. Records with orphaned ``tagger_id`` keep tagger fields as NULL
    to avoid FK violations (tagger is informational only).
"""

from __future__ import annotations

from sqlalchemy import MetaData, Table, text

from src.migrators.base_migrator import BaseMigrator, MigrationResult


class ConversationLabelsMigrator(BaseMigrator):
    """Migrate conversation labels from SOURCE ``taggings`` + ``tags``
    to DEST, deduplicating tags by name.

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
        """Execute conversation labels migration (taggings + tags).

        :returns: Migration result summary for ``conversation_labels``.
        :rtype: MigrationResult
        """
        self.logger.info("ConversationLabelsMigrator: starting")

        with self.dest_engine.connect() as conn:
            migrated_convs = self.state_repo.get_migrated_ids(conn, "conversations")
            migrated_users = self.state_repo.get_migrated_ids(conn, "users")

        # ── Step 1: Migrate tags (dedup by name) ─────────────────────────────
        tag_id_map = self._migrate_tags()
        self.logger.info(
            "ConversationLabelsMigrator: %d tags resolved in DEST",
            len(tag_id_map),
        )
        # ──────────────────────────────────────────────────────────────────────

        # ── Step 2: Migrate taggings for conversations ─────────────────────
        dest_meta = MetaData()
        dest_table = Table("taggings", dest_meta, autoload_with=self.dest_engine)

        with self.source_engine.connect() as conn:
            rows = [
                dict(r)
                for r in conn.execute(
                    text(
                        "SELECT * FROM taggings "
                        "WHERE taggable_type = 'Conversation' "
                        "AND context = 'labels'"
                    )
                )
                .mappings()
                .all()
            ]

        self.logger.info("ConversationLabelsMigrator: %d source taggings fetched", len(rows))

        def remap_fn(row: dict) -> dict | None:
            """Remap tagging IDs for a taggings row.

            :param row: Source row as plain dict.
            :type row: dict
            :returns: Destination row with remapped IDs, or ``None`` if orphan.
            :rtype: dict | None
            """
            src_conv_id = int(row["taggable_id"])
            if src_conv_id not in migrated_convs:
                self.logger.warning(
                    "ConversationLabelsMigrator: tagging id=%d skipped"
                    " — orphan conversation_id=%d",
                    row["id"],
                    src_conv_id,
                )
                return None

            src_tag_id = int(row["tag_id"])
            dest_tag_id = tag_id_map.get(src_tag_id)
            if dest_tag_id is None:
                self.logger.warning(
                    "ConversationLabelsMigrator: tagging id=%d skipped" " — tag_id=%d not resolved",
                    row["id"],
                    src_tag_id,
                )
                return None

            new_row = {
                **row,
                "id": self.id_remapper.remap(int(row["id"]), "conversation_labels"),
                "tag_id": dest_tag_id,
                "taggable_id": self.id_remapper.remap(src_conv_id, "conversations"),
            }

            # Remap tagger_id only when tagger_type == 'User'
            tagger_type = row.get("tagger_type")
            tagger_id = row.get("tagger_id")
            if tagger_type == "User" and tagger_id is not None:
                src_tagger = int(tagger_id)
                if src_tagger in migrated_users:
                    new_row["tagger_id"] = self.id_remapper.remap(src_tagger, "users")
                else:
                    # tagger is informational — null it out rather than FK fail
                    new_row["tagger_type"] = None
                    new_row["tagger_id"] = None

            return new_row

        result = self._run_batches(rows, "conversation_labels", dest_table, remap_fn)

        self.logger.info(
            "ConversationLabelsMigrator: complete" " — migrated=%d skipped=%d failed=%d",
            result.migrated,
            result.skipped,
            len(result.failed_ids),
        )
        return result

    # ------------------------------------------------------------------
    # Step 1 helper: tags dedup
    # ------------------------------------------------------------------

    def _migrate_tags(self) -> dict[int, int]:
        """Migrate SOURCE tags referenced by conversation taggings to DEST.

        Tags are deduplicated by ``name``. If a tag with the same name
        already exists in DEST, its ID is reused and no INSERT is performed.

        :returns: Mapping ``{src_tag_id: dest_tag_id}``.
        :rtype: dict[int, int]
        """
        # Fetch SOURCE tags referenced by conversation label taggings
        with self.source_engine.connect() as conn:
            src_tags = [
                dict(r)
                for r in conn.execute(
                    text(
                        "SELECT DISTINCT t.id, t.name "
                        "FROM tags t "
                        "JOIN taggings tg ON tg.tag_id = t.id "
                        "WHERE tg.taggable_type = 'Conversation' "
                        "  AND tg.context = 'labels'"
                    )
                )
                .mappings()
                .all()
            ]

        if not src_tags:
            return {}

        # Fetch existing DEST tags by name (dedup)
        dest_tag_by_name: dict[str, int] = {}
        with self.dest_engine.connect() as conn:
            for row in conn.execute(text("SELECT id, name FROM tags")).mappings().all():
                dest_tag_by_name[str(row["name"]).lower()] = int(row["id"])

        tag_id_map: dict[int, int] = {}
        dest_meta = MetaData()
        dest_tags_table = Table("tags", dest_meta, autoload_with=self.dest_engine)

        for src_tag in src_tags:
            src_id = int(src_tag["id"])
            name = str(src_tag["name"])
            name_lower = name.lower()

            if name_lower in dest_tag_by_name:
                # Tag already exists in DEST — reuse
                tag_id_map[src_id] = dest_tag_by_name[name_lower]
                self.logger.debug(
                    "ConversationLabelsMigrator._migrate_tags:"
                    " tag '%s' already in DEST as id=%d",
                    name,
                    dest_tag_by_name[name_lower],
                )
                continue

            # Insert new tag and get its ID
            try:
                with self.dest_engine.connect() as conn:
                    with conn.begin():
                        new_id: int = conn.execute(text("SELECT nextval('tags_id_seq')")).scalar()
                        conn.execute(
                            dest_tags_table.insert().values(
                                id=new_id,
                                name=name,
                                taggings_count=0,
                            )
                        )
                tag_id_map[src_id] = new_id
                dest_tag_by_name[name_lower] = new_id
                self.logger.debug(
                    "ConversationLabelsMigrator._migrate_tags:" " inserted tag '%s' as dest id=%d",
                    name,
                    new_id,
                )
            except Exception as exc:  # noqa: BLE001
                self.logger.error(
                    "ConversationLabelsMigrator._migrate_tags:" " failed to insert tag '%s' — %s",
                    name,
                    exc,
                )

        return tag_id_map

    # ------------------------------------------------------------------
    # POC dry-run hooks
    # ------------------------------------------------------------------

    def _table_name(self) -> str:
        """Return canonical table name.

        :returns: ``"conversation_labels"``
        :rtype: str
        """
        return "conversation_labels"

    def _fetch_all_source_rows(self) -> list[dict]:
        """Fetch conversation label taggings from SOURCE.

        :returns: All relevant tagging rows as plain dicts.
        :rtype: list[dict]
        """
        with self.source_engine.connect() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    text(
                        "SELECT * FROM taggings "
                        "WHERE taggable_type = 'Conversation' "
                        "AND context = 'labels'"
                    )
                )
                .mappings()
                .all()
            ]

    def _classify_row_poc(
        self,
        row: dict,
        migrated_sets: dict[str, set[int]],
    ) -> tuple:
        """Classify a taggings row for dry-run.

        :param row: Source row as plain dict.
        :type row: dict
        :param migrated_sets: Dest ID sets keyed by table name.
        :type migrated_sets: dict[str, set[int]]
        :returns: ``(outcome, reason)`` tuple.
        :rtype: tuple
        """
        from src.reports.poc_reporter import Outcome

        if int(row["taggable_id"]) not in migrated_sets.get("conversations", set()):
            return (
                Outcome.ORPHAN_FK_SKIP,
                f"conversation_id={row['taggable_id']} not migrated",
            )
        return Outcome.WOULD_MIGRATE, "clean"
