#!/usr/bin/env python3
"""Check conversation distribution for a given account.

Usage:
    python check_conversations.py --account-id 69
    python check_conversations.py --account-id 69 --inbox-id 526
    python check_conversations.py --account-id 69 --output report.json
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

os.environ.setdefault("MIGRATION_SOURCE_KEY", "chatwoot_dev")
os.environ.setdefault("MIGRATION_DEST_KEY", "chatwoot004_dev")

from sqlalchemy import text  # noqa: E402

from src.factory.connection_factory import ConnectionFactory  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("check-conversations")


def check_conversations(
    account_id: int, inbox_id: int | None = None, output_path: Path | None = None
) -> dict:
    """Check conversation distribution by status and inbox."""
    log.info("Checking conversations for account_id=%d", account_id)

    factory = ConnectionFactory()
    dest_engine = factory.create_dest_engine()

    result: dict = {
        "timestamp": datetime.now().isoformat(),  # noqa: DTZ005
        "account_id": account_id,
        "inbox_id": inbox_id,
    }

    with dest_engine.connect() as conn:
        # ── 1. Status breakdown ───────────────────────────────────────────────
        log.info("Status breakdown:")
        rows = conn.execute(
            text(
                "SELECT status, COUNT(*) as cnt FROM conversations "
                "WHERE account_id = :aid GROUP BY status ORDER BY cnt DESC"
            ),
            {"aid": account_id},
        ).fetchall()

        status_counts = {}
        for row in rows:
            status = str(row[0])
            count = int(row[1])
            status_counts[status] = count
            log.info("  status=%-10s → %5d conversations", status, count)

        result["status_breakdown"] = status_counts

        # ── 2. Inbox distribution ─────────────────────────────────────────────
        log.info("Inbox distribution:")
        rows = conn.execute(
            text(
                "SELECT inbox_id, COUNT(*) as cnt FROM conversations "
                "WHERE account_id = :aid GROUP BY inbox_id ORDER BY cnt DESC"
            ),
            {"aid": account_id},
        ).fetchall()

        inbox_counts = {}
        for row in rows:
            iid = int(row[0]) if row[0] is not None else None
            count = int(row[1])
            inbox_counts[str(iid)] = count
            log.info("  inbox_id=%-5s → %5d conversations", iid, count)

        result["inbox_distribution"] = inbox_counts

        # ── 3. Check specific inbox if provided ──────────────────────────────
        if inbox_id is not None:
            log.info("Conversations for inbox_id=%d:", inbox_id)
            row = conn.execute(
                text(
                    "SELECT COUNT(*) FROM conversations "
                    "WHERE account_id = :aid AND inbox_id = :iid"
                ),
                {"aid": account_id, "iid": inbox_id},
            ).fetchone()
            count = int(row[0]) if row else 0
            log.info("  Total: %d conversations", count)
            result["specific_inbox_count"] = count

            if count > 0:
                log.info("  Sample (5 most recent):")
                sample = conn.execute(
                    text(
                        "SELECT id, status, created_at, updated_at FROM conversations "
                        "WHERE account_id = :aid AND inbox_id = :iid "
                        "ORDER BY created_at DESC LIMIT 5"
                    ),
                    {"aid": account_id, "iid": inbox_id},
                ).fetchall()

                sample_data = []
                for row in sample:
                    conv_id, status, created, updated = row
                    log.info(
                        "    id=%d status=%s created=%s updated=%s",
                        conv_id,
                        status,
                        created,
                        updated,
                    )
                    sample_data.append({
                        "id": conv_id,
                        "status": str(status),
                        "created_at": str(created),
                        "updated_at": str(updated),
                    })
                result["sample"] = sample_data

        # ── 4. Total conversations ────────────────────────────────────────────
        row = conn.execute(
            text("SELECT COUNT(*) FROM conversations WHERE account_id = :aid"),
            {"aid": account_id},
        ).fetchone()
        total = int(row[0]) if row else 0
        log.info("Total conversations: %d", total)
        result["total"] = total

    # ── 5. Save JSON ──────────────────────────────────────────────────────────
    if output_path is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")  # noqa: DTZ005
        output_path = Path(".tmp") / f"conversations_{ts}.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str, ensure_ascii=False)

    log.info("Report saved: %s", output_path.resolve())
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Check conversation distribution")
    parser.add_argument("--account-id", type=int, required=True, help="Account ID to check")
    parser.add_argument("--inbox-id", type=int, help="Optional inbox ID for detailed check")
    parser.add_argument("--output", type=Path, help="Output JSON path")

    args = parser.parse_args()
    check_conversations(args.account_id, args.inbox_id, args.output)


if __name__ == "__main__":
    main()
