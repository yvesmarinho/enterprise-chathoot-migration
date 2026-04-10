"""CLI entrypoint for the enterprise Chatwoot migration.

:description: Orchestrates the full migration pipeline from ``chatwoot_dev1_db``
    (source) to ``chatwoot004_dev1_db`` (destination) respecting the FK dependency
    order:

    ``accounts → inboxes → users → teams → labels → contacts →
    conversations → messages → attachments``

Usage::

    python src/migrar.py [--dry-run] [--only-table <name>] [--verbose]

Exit codes:

    * ``0`` — all tables migrated successfully (0 failed IDs)
    * ``1`` — partial failure (some IDs failed, non-catastrophic)
    * ``3`` — catastrophic failure in ``accounts`` (root entity) — aborted

Options:
    ``--dry-run``      Skip all writes; log what *would* be done.
    ``--only-table``   Migrate a single table (FK order check still applies).
    ``--verbose``      Set log level to DEBUG.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

from src.factory.connection_factory import ConnectionFactory
from src.migrators.accounts_migrator import AccountsMigrator
from src.migrators.attachments_migrator import AttachmentsMigrator
from src.migrators.contacts_migrator import ContactsMigrator
from src.migrators.conversations_migrator import ConversationsMigrator
from src.migrators.inboxes_migrator import InboxesMigrator
from src.migrators.labels_migrator import LabelsMigrator
from src.migrators.messages_migrator import MessagesMigrator
from src.migrators.teams_migrator import TeamsMigrator
from src.migrators.users_migrator import UsersMigrator
from src.reports.validation_reporter import ValidationReporter
from src.repository.migration_state_repository import MigrationStateRepository
from src.utils.fk_validator import FKValidator
from src.utils.id_remapper import IDRemapper
from src.utils.log_masker import MaskingHandler

# Canonical FK migration order
_MIGRATION_ORDER = [
    "accounts",
    "inboxes",
    "users",
    "teams",
    "labels",
    "contacts",
    "conversations",
    "messages",
    "attachments",
]

_MIGRATOR_MAP = {
    "accounts": AccountsMigrator,
    "inboxes": InboxesMigrator,
    "users": UsersMigrator,
    "teams": TeamsMigrator,
    "labels": LabelsMigrator,
    "contacts": ContactsMigrator,
    "conversations": ConversationsMigrator,
    "messages": MessagesMigrator,
    "attachments": AttachmentsMigrator,
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
        "--verbose",
        action="store_true",
        help="Set log level to DEBUG.",
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
    logger, log_file = _setup_logging(args.verbose)

    logger.info("=== Enterprise Chatwoot Migration starting ===")
    if args.dry_run:
        logger.warning("DRY-RUN mode — no writes will be performed")

    # (1) Record start time
    start_time = time.time()

    # (2) Load credentials and create engines
    factory = ConnectionFactory()
    source_engine = factory.create_source_engine()
    dest_engine = factory.create_dest_engine()
    logger.info("Engines created")

    # (2b) Create migration_state table if not exists
    state_repo = MigrationStateRepository()
    if not args.dry_run:
        state_repo.create_table_if_not_exists(dest_engine)
        logger.info("migration_state table verified")

    # (3) Compute offsets once for the session
    remapper = IDRemapper()
    offsets = remapper.compute_offsets(dest_engine, _MIGRATION_ORDER)
    logger.info("Offsets computed: %s", offsets)

    # (4) Determine which tables to migrate
    tables_to_migrate = [args.only_table] if args.only_table else list(_MIGRATION_ORDER)

    results = []

    # (5) Run migrators in FK order
    for table_name in tables_to_migrate:
        migrator_cls = _MIGRATOR_MAP[table_name]
        migrator = migrator_cls(
            source_engine=source_engine,
            dest_engine=dest_engine,
            id_remapper=remapper,
            state_repo=state_repo,
            logger=logging.getLogger(f"migrar.{table_name}"),
        )

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

    if results:
        reporter = ValidationReporter()
        report_path = reporter.generate(results, dest_engine, elapsed)
        logger.info("Validation report saved: %s", report_path)

        # (7) FK post-validation
        fk_validator = FKValidator()
        fk_report = fk_validator.validate(dest_engine)
        for rel, orphan_count in fk_report.orphan_counts.items():
            if orphan_count > 0:
                logger.warning("FK violation: %s — %d orphans", rel, orphan_count)
            else:
                logger.info("FK OK: %s", rel)

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
