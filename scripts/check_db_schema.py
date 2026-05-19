#!/usr/bin/env python3
"""Check destination database schema.

Usage:
    python check_db_schema.py
    python check_db_schema.py --output schema_report.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

os.environ.setdefault("MIGRATION_DEST_KEY", "chatwoot004_dev")

from sqlalchemy import create_engine, text  # noqa: E402


def check_schema(output_path: Path | None = None) -> dict:
    """Check DB schema and table listing."""
    # Read credentials from .secrets/generate_erd.json
    secrets_path = _ROOT / ".secrets" / "generate_erd.json"
    if not secrets_path.exists():
        raise FileNotFoundError(f"Secrets file not found: {secrets_path}")

    secrets = json.loads(secrets_path.read_text())
    dest_key = os.environ.get("MIGRATION_DEST_KEY", "chatwoot004_dev")

    if dest_key not in secrets:
        available = [k for k in secrets if not k.startswith("_")]
        raise KeyError(f"Key '{dest_key}' not found. Available: {available}")

    cfg = secrets[dest_key]
    url = (
        f"postgresql+psycopg2://{cfg['username']}:{cfg['password']}"
        f"@{cfg['host']}:{cfg['port']}/{cfg['database']}"
        "?sslmode=disable"
    )

    print(f"Connecting to: {cfg['host']}:{cfg['port']}/{cfg['database']}")
    engine = create_engine(url, pool_pre_ping=True)

    result: dict = {
        "timestamp": datetime.now().isoformat(),  # noqa: DTZ005
        "connection": {
            "host": cfg["host"],
            "port": cfg["port"],
            "database": cfg["database"],
        },
    }

    with engine.connect() as conn:
        # List all schemas
        schemas = [
            row[0]
            for row in conn.execute(
                text("SELECT schema_name FROM information_schema.schemata ORDER BY schema_name")
            ).fetchall()
        ]
        result["schemas"] = schemas
        print(f"Schemas: {schemas}")

        # Count tables per schema
        tables_by_schema = {}
        for schema in schemas:
            if schema in ("information_schema", "pg_catalog", "pg_toast"):
                continue
            rows = conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = :s ORDER BY table_name"
                ),
                {"s": schema},
            ).fetchall()
            tables_by_schema[schema] = [r[0] for r in rows]

        result["tables_by_schema"] = tables_by_schema
        for schema, tables in tables_by_schema.items():
            print(f"  Schema '{schema}': {len(tables)} tables")
            if len(tables) <= 20:
                print(f"    {tables}")
            else:
                print(f"    (first 10): {tables[:10]}")

        # Check specifically for 'accounts' in any schema
        found = conn.execute(
            text(
                "SELECT table_schema, table_name FROM information_schema.tables "
                "WHERE table_name = 'accounts'"
            )
        ).fetchall()
        result["accounts_locations"] = [(r[0], r[1]) for r in found]
        print(f"'accounts' table found in: {result['accounts_locations']}")

        # Check search_path
        sp = conn.execute(text("SHOW search_path")).scalar()
        result["search_path"] = sp
        print(f"search_path: {sp}")

    # Save JSON
    if output_path is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")  # noqa: DTZ005
        output_path = Path(".tmp") / f"schema_{ts}.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str, ensure_ascii=False)

    print(f"\nReport saved: {output_path.resolve()}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Check database schema")
    parser.add_argument("--output", type=Path, help="Output JSON path")

    args = parser.parse_args()
    check_schema(args.output)


if __name__ == "__main__":
    main()
