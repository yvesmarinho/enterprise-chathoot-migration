"""CLI entrypoint for the enterprise Chatwoot migration.

:description: Orchestrates the full migration pipeline from ``chatwoot_db``
    (source, read-only — key ``chat-vya-digital``) to ``chatwoot004_dev1_db``
    (DEV destination — key ``vya-chat-dev``) or ``chatwoot004_db``
    (PROD destination — key ``synchat-vya-digital``) respecting FK order:

    ``accounts → inboxes → users → teams → labels → contacts →
    conversations → messages → attachments``

Usage::

    python src/migrar.py --env dev [--account "Nome"] [--dry-run] [--verbose]
    python src/migrar.py --env prod --account "Nome"

Exit codes:

    * ``0`` — all tables migrated (or classified) successfully
    * ``1`` — partial failure (some IDs failed, non-catastrophic)
    * ``3`` — catastrophic failure in ``accounts`` (root entity) — aborted

Options:
    ``--env``      ``dev`` (SOURCE=chatwoot_db DEST=chatwoot004_dev1_db) or
                  ``prod`` (SOURCE=chatwoot_db DEST=chatwoot004_db).
    ``--dry-run``  Skip all writes; log what *would* be done.
    ``--poc``      Classify all source rows (requires ``--dry-run``);
                  generates ``.tmp/poc_YYYYMMDD_HHMMSS_report.txt``.
    ``--only-table``  Migrate/classify a single table.
    ``--verbose``  Set log level to DEBUG.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from sqlalchemy import text

from src.factory.connection_factory import ConnectionFactory
from src.migrators.accounts_migrator import AccountsMigrator
from src.migrators.active_storage_attachments_migrator import (
    ActiveStorageAttachmentsMigrator,
)
from src.migrators.active_storage_blobs_migrator import ActiveStorageBlobsMigrator
from src.migrators.active_storage_variant_records_migrator import (
    ActiveStorageVariantRecordsMigrator,
)
from src.migrators.attachments_migrator import AttachmentsMigrator
from src.migrators.canned_responses_migrator import CannedResponsesMigrator
from src.migrators.contact_inboxes_migrator import ContactInboxesMigrator
from src.migrators.contacts_migrator import ContactsMigrator
from src.migrators.conversation_labels_migrator import (
    ConversationLabelsMigrator,
)
from src.migrators.conversations_migrator import ConversationsMigrator
from src.migrators.custom_attribute_definitions_migrator import (
    CustomAttributeDefinitionsMigrator,
)
from src.migrators.inboxes_migrator import InboxesMigrator
from src.migrators.inbox_members_migrator import InboxMembersMigrator
from src.migrators.labels_migrator import LabelsMigrator
from src.migrators.messages_migrator import MessagesMigrator
from src.migrators.team_members_migrator import TeamMembersMigrator
from src.migrators.teams_migrator import TeamsMigrator
from src.migrators.users_migrator import UsersMigrator
from src.migrators.webhooks_migrator import WebhooksMigrator
from src.reports.poc_reporter import POCReporter
from src.reports.validation_reporter import ValidationReporter
from src.repository.migration_state_repository import MigrationStateRepository
from src.utils.account_resolver import (
    check_account_exists_with_data,
    resolve_account_id,
)
from src.utils.env_guard import assert_dev_only_env
from src.utils.fk_validator import FKValidator
from src.utils.id_remapper import IDRemapper
from src.utils.log_masker import MaskingHandler

# DEV / PROD env presets — shortcut for MIGRATION_SOURCE_KEY / MIGRATION_DEST_KEY
#
# dev:  SOURCE=chat-vya-digital (chatwoot_db @ wfdb02, site: chat.vya.digital — READ-ONLY)
#               DEST=vya-chat-dev (chatwoot004_dev1_db @ wfdb02, site: vya-chat-dev — READ-WRITE)
# prod: SOURCE=chat-vya-digital (chatwoot_db)
#               DEST=synchat-vya-digital (chatwoot004_db)
_ENV_PRESETS: dict[str, tuple[str, str]] = {
    "dev": ("chat-vya-digital", "vya-chat-dev"),
    "prod": ("chat-vya-digital", "synchat-vya-digital"),
}

# Canonical FK migration order
# Inbox members added for UI visibility; ActiveStorage tables added after attachments (2026-05-26 — D18)
_MIGRATION_ORDER = [
    "accounts",
    "custom_attribute_definitions",
    "canned_responses",
    "inboxes",
    "webhooks",
    "users",
    "teams",
    "team_members",
    "inbox_members",
    "labels",
    "contacts",
    "contact_inboxes",
    "conversations",
    "messages",
    "attachments",
    "active_storage_blobs",  # Root table — no FK dependencies
    "active_storage_attachments",  # FK: blob_id, record_id (polymorphic)
    "active_storage_variant_records",  # FK: blob_id
    "conversation_labels",
]

_MIGRATOR_MAP = {
    "accounts": AccountsMigrator,
    "custom_attribute_definitions": CustomAttributeDefinitionsMigrator,
    "canned_responses": CannedResponsesMigrator,
    "inboxes": InboxesMigrator,
    "webhooks": WebhooksMigrator,
    "users": UsersMigrator,
    "teams": TeamsMigrator,
    "team_members": TeamMembersMigrator,
    "inbox_members": InboxMembersMigrator,
    "labels": LabelsMigrator,
    "contacts": ContactsMigrator,
    "contact_inboxes": ContactInboxesMigrator,
    "conversations": ConversationsMigrator,
    "messages": MessagesMigrator,
    "attachments": AttachmentsMigrator,
    "active_storage_blobs": ActiveStorageBlobsMigrator,
    "active_storage_attachments": ActiveStorageAttachmentsMigrator,
    "active_storage_variant_records": ActiveStorageVariantRecordsMigrator,
    "conversation_labels": ConversationLabelsMigrator,
}


def _setup_logging(verbose: bool) -> tuple[logging.Logger, Path]:
    """Configure root logger with MaskingHandler + FileHandler.

    :param verbose: If True, set level to DEBUG; otherwise INFO.
    :type verbose: bool
    :returns: Tuple of (configured logger, path to the log file).
    :rtype: tuple[logging.Logger, Path]
    """
    log_dir = Path(".tmp")
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")  # noqa: DTZ005
    log_file = log_dir / f"migration_{timestamp}.log"

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    stream_inner = logging.StreamHandler(sys.stdout)
    stream_inner.setFormatter(formatter)
    stream_inner.setLevel(logging.DEBUG)
    stream_masking = MaskingHandler(stream_inner)

    file_inner = logging.FileHandler(str(log_file), encoding="utf-8")
    file_inner.setFormatter(formatter)
    file_inner.setLevel(logging.DEBUG)
    file_masking = MaskingHandler(file_inner)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(stream_masking)
    root.addHandler(file_masking)
    root.setLevel(logging.DEBUG if verbose else logging.INFO)

    return logging.getLogger("migrar"), log_file


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments.

    :param argv: Argument list (defaults to sys.argv).
    :type argv: list[str] | None
    :returns: Parsed arguments namespace.
    :rtype: argparse.Namespace
    """
    parser = argparse.ArgumentParser(
        description="Enterprise Chatwoot DB migration tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip all writes; log what would be done.",
    )
    parser.add_argument(
        "--only-table",
        metavar="TABLE",
        choices=_MIGRATION_ORDER,
        help=f"Migrate only this table. Choices: {', '.join(_MIGRATION_ORDER)}",
    )
    parser.add_argument(
        "--poc",
        action="store_true",
        help=(
            "Classify all source rows without writing to destination. "
            "Must be combined with --dry-run. "
            "Generates .tmp/poc_YYYYMMDD_HHMMSS_report.txt."
        ),
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Set log level to DEBUG.",
    )
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        help=(
            "Convenience shortcut that sets MIGRATION_SOURCE_KEY and "
            "MIGRATION_DEST_KEY automatically. "
            "dev = chat-vya-digital (chatwoot_db) / vya-chat-dev (chatwoot004_dev1_db). "
            "prod = chat-vya-digital (chatwoot_db) / synchat-vya-digital (chatwoot004_db). "
            "Overrides the env vars when provided."
        ),
    )
    parser.add_argument(
        "--account",
        metavar="ACCOUNT_NAME",
        help=(
            "Migrate only this account (matched by name, case-insensitive). "
            "If omitted, migrates all accounts found in SOURCE."
        ),
    )
    parser.add_argument(
        "--force-overwrite",
        action="store_true",
        help=(
            "Sobrescrever account no DEST mesmo que já tenha dados. "
            "⚠️ CUIDADO: Causa PERDA DE DADOS permanente. "
            "Executa cleanup automático antes da migração."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the migration pipeline.

    :param argv: CLI argument list (for testing injection).
    :type argv: list[str] | None
    :returns: Exit code (0 = success, 1 = partial failure, 3 = catastrophic).
    :rtype: int
    """
    args = _parse_args(argv)

    # Apply --env shortcut before ConnectionFactory reads the env vars
    if args.env:
        src_key, dst_key = _ENV_PRESETS[args.env]
        os.environ["MIGRATION_SOURCE_KEY"] = src_key
        os.environ["MIGRATION_DEST_KEY"] = dst_key

    # DEV-only guardrail — must run after --env resolves env vars
    assert_dev_only_env()

    logger, log_file = _setup_logging(args.verbose)

    logger.info("=== Enterprise Chatwoot Migration starting ===")
    if args.env:
        logger.info(
            "--env %s → SOURCE_KEY=%s DEST_KEY=%s",
            args.env,
            os.environ["MIGRATION_SOURCE_KEY"],
            os.environ["MIGRATION_DEST_KEY"],
        )
    if args.account:
        logger.info("Account filter: %r (single-account mode)", args.account)
    if args.poc and not args.dry_run:
        logger.error("--poc requires --dry-run. Aborting.")
        return 2
    if args.dry_run:
        logger.warning("DRY-RUN mode — no writes will be performed")
    if args.poc:
        logger.warning("POC mode — classifying source rows, no writes")

    # (1) Record start time
    start_time = time.time()

    # (2) Load credentials and create engines
    factory = ConnectionFactory()
    source_engine = factory.create_source_engine()
    dest_engine = factory.create_dest_engine()
    logger.info("Engines created")

    # (2a) Resolve --account to source account_id using fuzzy matching
    account_id_filter: int | None = None
    if args.account:
        try:
            account_id_filter = resolve_account_id(source_engine, args.account, fuzzy=True)
        except ValueError as e:
            # Multiple matches — log and abort
            logger.error("Account resolution failed: %s", e)
            return 3

        if account_id_filter is None:
            logger.error("Account not found in SOURCE: %r", args.account)
            return 3

        logger.info(
            "Account filter resolved: %r → src_account_id=%d",
            args.account,
            account_id_filter,
        )

        # (2a.1) Verificar se account já existe no DEST (validação P0 — D21)
        if not args.dry_run:
            try:
                has_data, dest_stats = check_account_exists_with_data(dest_engine, args.account)
            except ValueError as e:
                # Múltiplos matches no DEST — abortar
                logger.error("Validação DEST falhou: %s", e)
                return 4

            if has_data and dest_stats:
                # Account existe no DEST COM DADOS
                dest_account_id = dest_stats["id"]
                logger.error(
                    "❌ Account '%s' já existe no DEST (ID=%d) com dados:",
                    args.account,
                    dest_account_id,
                )
                logger.error("   Conversations: %d", dest_stats["conversations"])
                logger.error("   Messages: %d", dest_stats["messages"])
                logger.error("   Attachments: %d", dest_stats["attachments"])
                logger.error(
                    "   ActiveStorage: %d (%.2f%%)",
                    dest_stats["active_storage"],
                    dest_stats["as_coverage_pct"],
                )
                logger.error("")

                if not args.force_overwrite:
                    logger.error("Opções:")
                    logger.error(
                        "  1. Use --force-overwrite para sobrescrever (⚠️  PERDA DE DADOS)"
                    )
                    logger.error("  2. Limpe o account manualmente:")
                    logger.error(
                        "     uv run python scripts/cleanup_accounts.py --account-ids %d",
                        dest_account_id,
                    )
                    logger.error("  3. Escolha outro account no SOURCE")
                    return 4
                else:
                    # --force-overwrite ativo — executar cleanup automático
                    logger.warning(
                        "⚠️  Account '%s' (ID=%d) será SOBRESCRITO (--force-overwrite ativo)",
                        args.account,
                        dest_account_id,
                    )
                    logger.info("Executando cleanup automático...")

                    # Import inline para evitar circular dependency
                    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
                    from cleanup_accounts import delete_account_data

                    try:
                        delete_account_data(dest_engine, [dest_account_id], dry_run=False)
                        logger.info("✅ Cleanup concluído — account %d removido", dest_account_id)
                    except Exception as cleanup_error:
                        logger.error("❌ Erro no cleanup: %s", cleanup_error)
                        return 5

            elif dest_stats:
                # Account existe mas VAZIO — apenas warning
                logger.warning(
                    "⚠️  Account '%s' já existe no DEST (ID=%d) mas está VAZIO",
                    args.account,
                    dest_stats["id"],
                )
                logger.info("Continuando migração...")
            else:
                # Account NÃO existe no DEST — OK
                logger.info("✅ Account '%s' não existe no DEST — será criado", args.account)

    # (2b) Create migration_state table if not exists
    state_repo = MigrationStateRepository()
    if not args.dry_run:
        state_repo.create_table_if_not_exists(dest_engine)
        logger.info("migration_state table verified")

    # (3) Compute offsets once for the session
    # "conversation_labels" is a logical name — actual DB table is "taggings"
    _offset_tables = [t if t != "conversation_labels" else "taggings" for t in _MIGRATION_ORDER]
    remapper = IDRemapper()
    remapper.compute_offsets(dest_engine, _offset_tables)
    # Register "conversation_labels" offset so ConversationLabelsMigrator.remap works
    remapper._offsets["conversation_labels"] = remapper._offsets.get("taggings", 0)
    logger.info("Offsets computed: %s", remapper.offsets)

    # (3b) Pre-seed remapper aliases from migration_state so that id_remapper.remap()
    # returns the correct dest_id even after restarts where the computed offset may
    # differ from the offset used in a previous run.
    if not args.dry_run:
        total_aliases = 0
        with dest_engine.connect() as conn:
            for table in _MIGRATION_ORDER:
                pairs = state_repo.get_migrated_id_pairs(conn, table)
                for src_id, dest_id in pairs:
                    remapper.register_alias(table, src_id, dest_id)
                total_aliases += len(pairs)
        logger.info("Pre-loaded %d ID mappings from migration_state into remapper", total_aliases)

    # (3c) Resolve destination account_id for account-scoped validation.
    # Uses remapper.remap() so aliases from merged accounts are honoured.
    dest_account_id: int | None = None
    if account_id_filter is not None:
        dest_account_id = remapper.remap(account_id_filter, "accounts")
        logger.info("Destination account_id for validation: %d", dest_account_id)

    # (4) Determine which tables to migrate
    tables_to_migrate = [args.only_table] if args.only_table else list(_MIGRATION_ORDER)

    results: list = []
    poc_results: list = []
    # Simulated destination ID sets used by classify_row_poc for FK checks.
    # After classifying each table we populate it with the source IDs that
    # WOULD be migrated so downstream migrators get a realistic FK set.
    _poc_migrated_sets: dict[str, set[int]] = {}

    # (5) Run migrators in FK order
    for table_name in tables_to_migrate:
        migrator_cls = _MIGRATOR_MAP[table_name]
        migrator = migrator_cls(
            source_engine=source_engine,
            dest_engine=dest_engine,
            id_remapper=remapper,
            state_repo=state_repo,
            logger=logging.getLogger(f"migrar.{table_name}"),
            account_id_filter=account_id_filter,
        )

        if args.poc:
            # POC mode: classify without writing
            logger.info("[POC] Classifying table: %s", table_name)
            already_migrated: set[int] = set()
            try:
                with dest_engine.connect() as conn:
                    already_migrated = state_repo.get_migrated_ids(conn, table_name)
            except Exception:  # noqa: BLE001
                pass  # state table may not exist; treat as empty
            poc_result = migrator.poc_classify(
                already_migrated=already_migrated,
                migrated_sets=_poc_migrated_sets,
            )
            poc_results.append(poc_result)
            # Populate _poc_migrated_sets with the FULL set of IDs that
            # would survive (WOULD_MIGRATE + WOULD_MIGRATE_MODIFIED).
            # POCResult.surviving_ids is populated by add_record() for every
            # classified record — not limited to the sample cap — so FK chain
            # validation in downstream tables is accurate.
            _poc_migrated_sets[table_name] = poc_result.surviving_ids
            logger.debug(
                "[POC] %s surviving=%d (full set)",
                table_name,
                len(poc_result.surviving_ids),
            )
            continue

        if args.dry_run:
            logger.info("[DRY-RUN] Would migrate table: %s", table_name)
            continue

        logger.info(">>> Iniciando migração: %s", table_name)
        # AccountsMigrator may raise SystemExit(3) on failure — let it propagate
        result = migrator.migrate()
        results.append(result)

    # (6) Compute elapsed and generate report
    elapsed = time.time() - start_time
    logger.info("Migration pipeline elapsed: %.2fs", elapsed)

    if poc_results:
        poc_reporter = POCReporter()
        poc_path = poc_reporter.generate(poc_results, elapsed)
        logger.info("POC report saved: %s", poc_path)
        logger.info("=== POC dry-run completed (exit code 0) ===")
        logger.info("Log file: %s", log_file)
        return 0

    if results:
        reporter = ValidationReporter()
        report_path = reporter.generate(results, dest_engine, elapsed, account_id=dest_account_id)
        logger.info("Validation report saved: %s", report_path)

        # (7) FK post-validation
        fk_validator = FKValidator()
        fk_report = fk_validator.validate(dest_engine, account_id=dest_account_id)
        for rel, orphan_count in fk_report.orphan_counts.items():
            if orphan_count > 0:
                logger.warning("FK violation: %s — %d orphans", rel, orphan_count)
            else:
                logger.info("FK OK: %s", rel)

    # (7b) Reset PostgreSQL sequences to avoid nextval() collisions (HTTP 500 trigger)
    if not args.dry_run:
        _SEQUENCE_TABLES = [
            ("conversations", "conversations_id_seq"),
            ("messages", "messages_id_seq"),
            ("contacts", "contacts_id_seq"),
            ("contact_inboxes", "contact_inboxes_id_seq"),
            ("inboxes", "inboxes_id_seq"),
            ("accounts", "accounts_id_seq"),
            ("users", "users_id_seq"),
            ("teams", "teams_id_seq"),
            ("labels", "labels_id_seq"),
            ("webhooks", "webhooks_id_seq"),
            ("attachments", "attachments_id_seq"),
        ]
        logger.info("Resetting PostgreSQL sequences post-migration…")
        with dest_engine.begin() as conn:
            for table, seq in _SEQUENCE_TABLES:
                try:
                    conn.execute(
                        text(
                            f"SELECT setval('{seq}',"  # noqa: S608
                            f" COALESCE((SELECT MAX(id) FROM {table}), 1))"
                        )
                    )
                    logger.debug("Sequence reset: %s", seq)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Could not reset sequence %s: %s", seq, exc)
        logger.info("Sequence reset complete.")

    # (8) Determine exit code
    total_failed = sum(len(r.failed_ids) for r in results)
    if total_failed > 0:
        logger.warning("Migration completed with %d failed records (exit code 1)", total_failed)
        return 1

    logger.info("=== Migration completed successfully (exit code 0) ===")
    logger.info("Log file: %s", log_file)
    return 0


if __name__ == "__main__":
    sys.exit(main())
