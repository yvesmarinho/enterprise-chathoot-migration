#!/usr/bin/env python3
"""Validate post-migration data integrity and row counts.

Usage:
    python validate_migration.py --account-id 69
    python validate_migration.py --account-id 69 --output validation_report.json
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# Ensure project root is on sys.path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

os.environ.setdefault("MIGRATION_SOURCE_KEY", "chatwoot_dev")
os.environ.setdefault("MIGRATION_DEST_KEY", "chatwoot004_dev")

from sqlalchemy import text  # noqa: E402

from src.factory.connection_factory import ConnectionFactory  # noqa: E402
from src.utils.fk_validator import FKValidator  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("validate-migration")


def build_count_queries(account_id: int) -> list[tuple[str, str, dict]]:
    """Build per-table count queries scoped to account_id."""
    return [
        ("accounts", "SELECT COUNT(*) FROM accounts WHERE id = :aid", {"aid": account_id}),
        (
            "custom_attribute_definitions",
            "SELECT COUNT(*) FROM custom_attribute_definitions WHERE account_id = :aid",
            {"aid": account_id},
        ),
        (
            "canned_responses",
            "SELECT COUNT(*) FROM canned_responses WHERE account_id = :aid",
            {"aid": account_id},
        ),
        ("inboxes", "SELECT COUNT(*) FROM inboxes WHERE account_id = :aid", {"aid": account_id}),
        ("webhooks", "SELECT COUNT(*) FROM webhooks WHERE account_id = :aid", {"aid": account_id}),
        (
            "users (via account_users)",
            "SELECT COUNT(*) FROM account_users WHERE account_id = :aid",
            {"aid": account_id},
        ),
        ("teams", "SELECT COUNT(*) FROM teams WHERE account_id = :aid", {"aid": account_id}),
        (
            "team_members (via teams)",
            "SELECT COUNT(tm.*) FROM team_members tm JOIN teams t ON t.id = tm.team_id WHERE t.account_id = :aid",
            {"aid": account_id},
        ),
        ("labels", "SELECT COUNT(*) FROM labels WHERE account_id = :aid", {"aid": account_id}),
        ("contacts", "SELECT COUNT(*) FROM contacts WHERE account_id = :aid", {"aid": account_id}),
        (
            "contact_inboxes (via contacts)",
            "SELECT COUNT(ci.*) FROM contact_inboxes ci JOIN contacts c ON c.id = ci.contact_id WHERE c.account_id = :aid",
            {"aid": account_id},
        ),
        (
            "conversations",
            "SELECT COUNT(*) FROM conversations WHERE account_id = :aid",
            {"aid": account_id},
        ),
        ("messages", "SELECT COUNT(*) FROM messages WHERE account_id = :aid", {"aid": account_id}),
        (
            "attachments",
            "SELECT COUNT(*) FROM attachments WHERE account_id = :aid",
            {"aid": account_id},
        ),
        (
            "conversation_labels (via taggings)",
            "SELECT COUNT(tg.*) FROM taggings tg JOIN conversations cv ON cv.id = tg.taggable_id "
            "WHERE cv.account_id = :aid AND tg.taggable_type = 'Conversation' AND tg.context = 'labels'",
            {"aid": account_id},
        ),
    ]


def validate_migration(account_id: int, output_path: Path | None = None) -> dict:
    """Run full validation: FK integrity + row counts."""
    log.info("Validating migration for account_id=%d", account_id)

    factory = ConnectionFactory()
    dest_engine = factory.create_dest_engine()

    # ── 1. FK integrity check ─────────────────────────────────────────────────
    log.info("Running FK integrity check (account_id=%d)…", account_id)
    fk_validator = FKValidator()
    fk_report = fk_validator.validate(dest_engine, account_id=account_id)

    fk_results: dict[str, int] = {}
    for rel, orphan_count in fk_report.orphan_counts.items():
        status = "✓ OK" if orphan_count == 0 else f"✗ VIOLATION ({orphan_count} orphans)"
        log.info("  FK %-55s %s", rel, status)
        fk_results[rel] = orphan_count

    total_violations = sum(fk_results.values())
    log.info("FK integrity: %d total violations", total_violations)

    # ── 2. Per-table row counts ───────────────────────────────────────────────
    log.info("Querying per-table row counts…")
    count_results: list[dict] = []
    count_queries = build_count_queries(account_id)

    with dest_engine.connect() as conn:
        for label, sql, params in count_queries:
            try:
                row = conn.execute(text(sql), params).fetchone()
                count = int(row[0]) if row else 0
                status = "✓"
            except Exception as exc:
                count = -1
                status = f"✗ ERROR: {exc}"
                log.warning("  Count query failed for %s: %s", label, exc)

            log.info("  %-45s %6d  %s", label, count, status)
            count_results.append({"table": label, "count": count, "status": status})

    # ── 3. Build report ───────────────────────────────────────────────────────
    report = {
        "timestamp": datetime.now().isoformat(),  # noqa: DTZ005
        "account_id": account_id,
        "fk_integrity": {
            "total_violations": total_violations,
            "details": fk_results,
        },
        "table_counts": count_results,
    }

    # ── 4. Save JSON ──────────────────────────────────────────────────────────
    if output_path is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")  # noqa: DTZ005
        output_path = Path(".tmp") / f"validation_{ts}.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str, ensure_ascii=False)

    log.info("Validation report saved: %s", output_path.resolve())
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate post-migration FK integrity and row counts"
    )
    parser.add_argument(
        "--account-id",
        type=int,
        required=True,
        help="Destination account_id to validate",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output JSON path (default: .tmp/validation_<timestamp>.json)",
    )

    args = parser.parse_args()
    validate_migration(args.account_id, args.output)


if __name__ == "__main__":
    main()
