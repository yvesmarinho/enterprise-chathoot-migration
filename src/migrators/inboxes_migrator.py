"""Migrator for the ``inboxes`` entity.

:description: Remaps ``id`` (offset_inboxes) and ``account_id`` (offset_accounts).
    Records with an ``account_id`` that was not successfully migrated are
    skipped with a WARNING log entry.

    BUG-05 FIX: Each inbox has a polymorphic ``channel`` association
    (channel_type + channel_id).  The channel records must be migrated from
    SOURCE to DEST **before** the inbox row is inserted so that
    ``inboxes.channel_id`` references a valid DEST record.

    Channel tables handled: Channel::WebWidget, Channel::Api,
    Channel::FacebookPage, Channel::Telegram.  Unknown types are logged and
    the channel_id is left as-is (best-effort).

    Security: ``website_token`` (Channel::WebWidget) and ``identifier`` /
    ``hmac_token`` (Channel::Api) are regenerated with
    ``secrets.token_urlsafe()`` to prevent token collisions with existing DEST
    records.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

from sqlalchemy import MetaData, Table, text

from src.migrators.base_migrator import BaseMigrator, MigrationResult

# ── Channel-type → (dest_table, sequence, {field: generator}) ────────────────
_CHANNEL_CFG: dict[str, tuple[str, str, dict[str, object]]] = {
    "Channel::WebWidget": (
        "channel_web_widgets",
        "channel_web_widgets_id_seq",
        {"website_token": lambda: secrets.token_urlsafe(18)},
    ),
    "Channel::Api": (
        "channel_api",
        "channel_api_id_seq",
        {
            "identifier": lambda: secrets.token_urlsafe(24),
            "hmac_token": lambda: secrets.token_urlsafe(24),
        },
    ),
    "Channel::FacebookPage": (
        "channel_facebook_pages",
        "channel_facebook_pages_id_seq",
        {},
    ),
    "Channel::Telegram": (
        "channel_telegram",
        "channel_telegram_id_seq",
        {},
    ),
    "Channel::Email": (
        "channel_email",
        "channel_email_id_seq",
        {},
    ),
    "Channel::TwilioSms": (
        "channel_twilio_sms",
        "channel_twilio_sms_id_seq",
        {},
    ),
    "Channel::Whatsapp": (
        "channel_whatsapp",
        "channel_whatsapp_id_seq",
        {},
    ),
    "Channel::Line": (
        "channel_line",
        "channel_line_id_seq",
        {},
    ),
    "Channel::Sms": (
        "channel_sms",
        "channel_sms_id_seq",
        {},
    ),
}


class InboxesMigrator(BaseMigrator):
    """Migrate all rows from ``inboxes`` source → destination.

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
        """Execute inboxes migration (inboxes + channel records).

        :returns: Migration result summary for ``inboxes``.
        :rtype: MigrationResult
        """
        self.logger.info("InboxesMigrator: starting")
        src_meta = MetaData()
        src_table = Table("inboxes", src_meta, autoload_with=self.source_engine)
        dest_meta = MetaData()
        dest_table = Table("inboxes", dest_meta, autoload_with=self.dest_engine)

        with self.dest_engine.connect() as conn:
            migrated_accounts = self.state_repo.get_migrated_ids(conn, "accounts")

        with self.source_engine.connect() as conn:
            rows = [dict(r) for r in conn.execute(src_table.select()).mappings().all()]

        self.logger.info("InboxesMigrator: %d source rows fetched", len(rows))

        # ── BUG-05 FIX: migrate channel records and build channel_id mapping ─
        channel_id_map = self._migrate_channels(rows, migrated_accounts)
        self.logger.info(
            "InboxesMigrator: %d channel records migrated to DEST", len(channel_id_map)
        )

        def remap_fn(row: dict) -> dict | None:
            """Remap PK, FK and channel_id for an inboxes row.

            :param row: Source row as plain dict.
            :type row: dict
            :returns: Destination row with remapped IDs, or ``None`` if FK orphan.
            :rtype: dict | None
            """
            account_id_origin = int(row["account_id"])
            if account_id_origin not in migrated_accounts:
                self.logger.warning(
                    "InboxesMigrator: id=%d skipped — orphan account_id=%d",
                    row["id"],
                    account_id_origin,
                )
                return None

            new_row = {
                **row,
                "id": self.id_remapper.remap(int(row["id"]), "inboxes"),
                "account_id": self.id_remapper.remap(account_id_origin, "accounts"),
            }

            # BUG-05 FIX: remap channel_id to the newly inserted DEST channel
            channel_type = row.get("channel_type")
            src_channel_id = row.get("channel_id")
            if channel_type and src_channel_id is not None:
                dest_channel_id = channel_id_map.get((str(channel_type), int(src_channel_id)))
                if dest_channel_id is not None:
                    new_row["channel_id"] = dest_channel_id
                else:
                    self.logger.warning(
                        "InboxesMigrator: id=%d — channel %s/%s not in channel_id_map; "
                        "channel_id kept as SOURCE value (inbox may be invisible in API)",
                        row["id"],
                        channel_type,
                        src_channel_id,
                    )

            return new_row

        result = self._run_batches(rows, "inboxes", dest_table, remap_fn)

        self.logger.info(
            "InboxesMigrator: complete — migrated=%d skipped=%d failed=%d",
            result.migrated,
            result.skipped,
            len(result.failed_ids),
        )
        return result

    # ------------------------------------------------------------------
    # BUG-05 FIX: channel record migration
    # ------------------------------------------------------------------

    def _migrate_channels(
        self,
        source_rows: list[dict],
        migrated_accounts: set[int],
    ) -> dict[tuple[str, int], int]:
        """Fetch SOURCE channel records and insert them into DEST.

        For each unique ``(channel_type, channel_id)`` pair referenced by an
        inbox whose ``account_id`` was successfully migrated:

        1. Reads the channel record from SOURCE.
        2. Obtains a fresh DEST ID via ``nextval(sequence)``.
        3. Remaps ``account_id`` using the session remapper.
        4. Regenerates unique / security-sensitive fields (website_token,
           identifier, hmac_token) so they never collide with existing DEST
           tokens.
        5. Inserts the channel record into DEST.

        :param source_rows: All source inbox rows (as dicts).
        :type source_rows: list[dict]
        :param migrated_accounts: Set of source account IDs that were
            successfully migrated or merged.
        :type migrated_accounts: set[int]
        :returns: Mapping ``{(channel_type, src_channel_id): dest_channel_id}``.
        :rtype: dict[tuple[str, int], int]
        """
        # Collect unique (channel_type, channel_id) pairs for eligible inboxes
        needed: dict[tuple[str, int], None] = {}
        for row in source_rows:
            ct = str(row.get("channel_type") or "")
            cid = row.get("channel_id")
            if not ct or cid is None:
                continue
            if int(row["account_id"]) not in migrated_accounts:
                continue
            needed[(ct, int(cid))] = None

        if not needed:
            return {}

        # Group by channel_type to batch SOURCE reads
        by_type: dict[str, list[int]] = {}
        for ct, cid in needed:
            by_type.setdefault(ct, []).append(cid)

        channel_id_map: dict[tuple[str, int], int] = {}

        for channel_type, src_ids in by_type.items():
            cfg = _CHANNEL_CFG.get(channel_type)
            if cfg is None:
                self.logger.warning(
                    "InboxesMigrator._migrate_channels: unknown channel_type=%s "
                    "— %d channel(s) not migrated",
                    channel_type,
                    len(src_ids),
                )
                continue

            table_name, seq_name, regen_fields = cfg

            # Reflect DEST channel table once per type
            dest_ct_meta = MetaData()
            dest_ct_table = Table(table_name, dest_ct_meta, autoload_with=self.dest_engine)
            dest_valid_cols: set[str] = {c.name for c in dest_ct_table.columns}

            # Fetch all SOURCE channel records in one query
            with self.source_engine.connect() as src_conn:
                src_channel_rows: dict[int, dict] = {}
                for row in (
                    src_conn.execute(
                        text(f"SELECT * FROM {table_name} WHERE id = ANY(:ids)"),  # noqa: S608
                        {"ids": src_ids},
                    )
                    .mappings()
                    .all()
                ):
                    src_channel_rows[int(row["id"])] = dict(row)

            for src_channel_id in src_ids:
                src_row = src_channel_rows.get(src_channel_id)
                if src_row is None:
                    self.logger.warning(
                        "InboxesMigrator._migrate_channels: %s id=%d NOT FOUND in SOURCE "
                        "— creating minimal placeholder",
                        channel_type,
                        src_channel_id,
                    )
                    src_row = {}

                try:
                    with self.dest_engine.connect() as dest_conn:
                        with dest_conn.begin():
                            # Allocate new DEST ID from sequence
                            new_id: int = dest_conn.execute(
                                text(f"SELECT nextval('{seq_name}')")  # noqa: S608
                            ).scalar()

                            # Build insert dict: copy SOURCE columns, apply transforms
                            insert_dict: dict = {
                                k: v for k, v in src_row.items() if k in dest_valid_cols
                            }
                            insert_dict["id"] = new_id

                            # Remap account_id
                            acct_val = src_row.get("account_id")
                            if acct_val is not None:
                                src_acct = int(acct_val)
                                if src_acct in migrated_accounts:
                                    insert_dict["account_id"] = self.id_remapper.remap(
                                        src_acct, "accounts"
                                    )

                            # Regenerate unique / security fields
                            for field, gen_fn in regen_fields.items():
                                if field in dest_valid_cols:
                                    insert_dict[field] = gen_fn()  # type: ignore[operator]

                            # Ensure timestamps
                            now = datetime.now(tz=timezone.utc)
                            if "created_at" in dest_valid_cols:
                                insert_dict.setdefault("created_at", now)
                            if "updated_at" in dest_valid_cols:
                                insert_dict["updated_at"] = now

                            dest_conn.execute(dest_ct_table.insert().values(**insert_dict))

                    channel_id_map[(channel_type, src_channel_id)] = new_id
                    self.logger.debug(
                        "InboxesMigrator._migrate_channels: %s src_id=%d → dest_id=%d",
                        channel_type,
                        src_channel_id,
                        new_id,
                    )

                except Exception as exc:  # noqa: BLE001
                    # BUG-07 FIX: on UniqueViolation, look up the existing DEST
                    # channel record so the inbox can reference a valid channel_id.
                    # Each channel type may have a different unique column; we use
                    # a best-effort lookup by any unique-constraint column present
                    # in the source row.
                    _UNIQUE_LOOKUP: dict[str, list[str]] = {
                        "Channel::Whatsapp": ["phone_number"],
                        "Channel::Telegram": ["bot_token"],
                        "Channel::FacebookPage": ["page_id"],
                        "Channel::Api": ["identifier"],
                        "Channel::WebWidget": ["website_token"],
                    }
                    existing_id: int | None = None
                    for lookup_col in _UNIQUE_LOOKUP.get(channel_type, []):
                        lookup_val = src_row.get(lookup_col)
                        if lookup_val is None:
                            continue
                        try:
                            with self.dest_engine.connect() as lk_conn:
                                existing_id = lk_conn.execute(
                                    text(  # noqa: S608
                                        f"SELECT id FROM {table_name} WHERE {lookup_col} = :v LIMIT 1"
                                    ),
                                    {"v": lookup_val},
                                ).scalar()
                        except Exception:  # noqa: BLE001
                            pass
                        if existing_id is not None:
                            break

                    if existing_id is not None:
                        channel_id_map[(channel_type, src_channel_id)] = existing_id
                        self.logger.warning(
                            "InboxesMigrator._migrate_channels: %s id=%d already exists in DEST "
                            "as id=%d — reusing existing channel",
                            channel_type,
                            src_channel_id,
                            existing_id,
                        )
                    else:
                        self.logger.error(
                            "InboxesMigrator._migrate_channels: failed to migrate %s id=%d — %s",
                            channel_type,
                            src_channel_id,
                            exc,
                        )

        return channel_id_map

    # ------------------------------------------------------------------
    # POC dry-run hooks
    # ------------------------------------------------------------------

    def _table_name(self) -> str:
        """Return canonical table name.

        :returns: ``"inboxes"``
        :rtype: str
        """
        return "inboxes"

    def _fetch_all_source_rows(self) -> list[dict]:
        """Fetch all rows from source ``inboxes``.

        :returns: All source rows as plain dicts.
        :rtype: list[dict]
        """
        src_meta = MetaData()
        src_table = Table("inboxes", src_meta, autoload_with=self.source_engine)
        with self.source_engine.connect() as conn:
            return [dict(r) for r in conn.execute(src_table.select()).mappings().all()]

    def _classify_row_poc(  # type: ignore[override]
        self,
        row: dict,
        migrated_sets: dict[str, set[int]],
    ) -> tuple:
        """Classify an inboxes row: orphan account_id → ORPHAN_FK_SKIP.

        :param row: Source row as plain dict.
        :type row: dict
        :param migrated_sets: Dest ID sets keyed by table name.
        :type migrated_sets: dict[str, set[int]]
        :returns: ``(outcome, reason)`` tuple.
        :rtype: tuple
        """
        from src.reports.poc_reporter import Outcome

        account_id = int(row["account_id"])
        if account_id not in migrated_sets.get("accounts", set()):
            return (
                Outcome.ORPHAN_FK_SKIP,
                f"account_id={account_id} not in migrated accounts",
            )
        return Outcome.WOULD_MIGRATE, "clean"
