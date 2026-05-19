#!/usr/bin/env python3
"""Rollback migrated data from destination database.

Usage:
    python rollback_account.py --account-id 69 --dry-run
    python rollback_account.py --account-id 69  # Executes actual rollback
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

os.environ.setdefault("MIGRATION_DEST_KEY", "chatwoot004_dev")

from sqlalchemy import text  # noqa: E402

from src.factory.connection_factory import ConnectionFactory  # noqa: E402

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
log = logging.getLogger("rollback")


def rollback_account(account_id: int, dry_run: bool = True, output_path: Path | None = None) -> dict:
    """Rollback all data for a given account_id."""
    mode_str = "DRY RUN (no data deleted)" if dry_run else "⚠️ LIVE — DELETING DATA"
    print("=" * 80)
    print(f"  Rollback Account ID: {account_id}")
    print(f"  Mode: {mode_str}")
    print("=" * 80)

    factory = ConnectionFactory()
    dest_engine = factory.create_dest_engine()

    result: dict = {
        "timestamp": datetime.now().isoformat(),  # noqa: DTZ005
        "account_id": account_id,
        "dry_run": dry_run,
        "deleted": {},
    }

    # Dependency-ordered deletion (children first)
    delete_order = [
        ("taggings", "taggable_id IN (SELECT id FROM conversations WHERE account_id = :aid)", "Conversation labels"),
        ("attachments", "account_id = :aid", "Attachments"),
        ("messages", "account_id = :aid", "Messages"),
        ("conversations", "account_id = :aid", "Conversations"),
        ("contact_inboxes", "contact_id IN (SELECT id FROM contacts WHERE account_id = :aid)", "Contact inboxes"),
        ("contacts", "account_id = :aid", "Contacts"),
        ("team_members", "team_id IN (SELECT id FROM teams WHERE account_id = :aid)", "Team members"),
        ("teams", "account_id = :aid", "Teams"),
        ("labels", "account_id = :aid", "Labels"),
        ("webhooks", "account_id = :aid", "Webhooks"),
        ("canned_responses", "account_id = :aid", "Canned responses"),
        ("custom_attribute_definitions", "account_id = :aid", "Custom attributes"),
        ("inboxes", "account_id = :aid", "Inboxes"),
        ("account_users", "account_id = :aid", "Account users"),
        ("accounts", "id = :aid", "Accounts"),
    ]

    with dest_engine.connect() as conn:
        for table, where_clause, label in delete_order:
            # Count first
            count_sql = f"SELECT COUNT(*) FROM {table} WHERE {where_clause}"
            row = conn.execute(text(count_sql), {"aid": account_id}).fetchone()
            count = int(row[0]) if row else 0

            if count == 0:
                print(f"  {label:30s}: 0 rows (skip)")
                result["deleted"][table] = 0
                continue

            print(f"  {label:30s}: {count} rows", end="")

            if not dry_run:
                delete_sql = f"DELETE FROM {table} WHERE {where_clause}"
                conn.execute(text(delete_sql), {"aid": account_id})
                conn.commit()
                print(" → DELETED ✗")
            else:
                print(" → would delete")

            result["deleted"][table] = count

    print("\n" + "=" * 80)
    if dry_run:
        print("  DRY RUN complete. No data was deleted.")
        print("  Re-run without --dry-run to execute actual rollback.")
    else:
        print("  ⚠️ ROLLBACK COMPLETE — Data deleted permanently.")

    # Save JSON
    if output_path is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")  # noqa: DTZ005
        output_path = Path(".tmp") / f"rollback_{ts}.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str, ensure_ascii=False)

    print(f"  Report saved: {output_path.resolve()}")
    print("=" * 80)

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Rollback migrated data for an account")
    parser.add_argument("--account-id", type=int, required=True, help="Account ID to rollback")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Dry run mode (show what would be deleted)",
    )
    parser.add_argument("--output", type=Path, help="Output JSON path")

    args = parser.parse_args()

    if not args.dry_run:
        confirm = input(
            f"\n⚠️ WARNING: This will DELETE all data for account_id={args.account_id}.\n"
            "Type 'DELETE' to confirm: "
        )
        if confirm != "DELETE":
            print("Rollback cancelled.")
            sys.exit(0)

    rollback_account(args.account_id, args.dry_run, args.output)


if __name__ == "__main__":
    main()
