#!/usr/bin/env python3
"""Check inbox ID mappings from migration_state.

Usage:
    python check_inbox_mapping.py --account-id 69
    python check_inbox_mapping.py --account-id 69 --output mapping.json
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
log = logging.getLogger("check-inbox-mapping")


def check_inbox_mapping(account_id: int, output_path: Path | None = None) -> dict:
    """Check inbox mappings for a specific account."""
    log.info("Checking inbox mappings for account_id=%d", account_id)

    factory = ConnectionFactory()
    dest_engine = factory.create_dest_engine()

    result: dict = {
        "timestamp": datetime.now().isoformat(),  # noqa: DTZ005
        "account_id": account_id,
        "inboxes": [],
        "mappings": [],
    }

    with dest_engine.connect() as conn:
        # Check inboxes for account_id
        log.info("Inboxes in DEST for account_id=%d:", account_id)
        rows = conn.execute(
            text(
                "SELECT id, name, channel_type FROM inboxes WHERE account_id = :aid ORDER BY id"
            ),
            {"aid": account_id},
        ).fetchall()

        for row in rows:
            inbox_id, name, channel_type = row
            log.info("  inbox_id=%d name=%r channel_type=%s", inbox_id, name, channel_type)
            result["inboxes"].append({
                "id": inbox_id,
                "name": str(name),
                "channel_type": str(channel_type),
            })

        # Check migration_state for inbox mapping
        log.info("\nInbox ID mapping from migration_state:")
        rows = conn.execute(
            text(
                "SELECT id_origem, id_destino FROM migration_state "
                "WHERE tabela = 'inboxes' ORDER BY id_origem"
            )
        ).fetchall()

        for row in rows:
            src_id, dest_id = row
            log.info("  src_inbox_id=%d → dest_inbox_id=%d", src_id, dest_id)
            result["mappings"].append({"source": src_id, "destination": dest_id})

    # Save JSON
    if output_path is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")  # noqa: DTZ005
        output_path = Path(".tmp") / f"inbox_mapping_{ts}.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str, ensure_ascii=False)

    log.info("Report saved: %s", output_path.resolve())
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Check inbox ID mappings")
    parser.add_argument("--account-id", type=int, required=True, help="Account ID to check")
    parser.add_argument("--output", type=Path, help="Output JSON path")

    args = parser.parse_args()
    check_inbox_mapping(args.account_id, args.output)


if __name__ == "__main__":
    main()
