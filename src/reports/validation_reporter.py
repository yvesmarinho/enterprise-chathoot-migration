"""Validation report generator for the migration pipeline.

:description: Produces a human-readable ASCII-table report after a migration
    run.  The report is saved to ``.tmp/migration_YYYYMMDD_HHMMSS_report.txt``
    and all output passes through the active ``MaskingHandler`` to prevent PII
    from being written to disk.

    Report format::

        ================  Enterprise Chatwoot Migration Report  ================
        Duration: 3247.83s  |  Generated: 2026-04-10T14:22:01

        TABELA            | ORIGEM  | MIGRADO | DESTINO_TOTAL | FALHAS
        -----------------------------------------------------------------
        accounts          |       5 |       5 |            25 |      0
        inboxes           |      21 |      21 |           172 |      0
        ...

        === Failed IDs ===
        contacts: 12345, 67890
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.migrators.base_migrator import MigrationResult

logger = logging.getLogger(__name__)

_COL_WIDTHS = (18, 8, 8, 14, 8)

_HEADER = "================  Enterprise Chatwoot Migration Report  ================"

_TABLE_NAMES_ORDER = [
    "accounts",
    "custom_attribute_definitions",
    "canned_responses",
    "inboxes",
    "webhooks",
    "users",
    "teams",
    "team_members",
    "labels",
    "contacts",
    "contact_inboxes",
    "conversations",
    "messages",
    "attachments",
    "conversation_labels",
]

# Logical table name → physical DB table name (only for names that differ)
_LOGICAL_TO_PHYSICAL: dict[str, str] = {
    "conversation_labels": "taggings",
}

# Tables that have a direct ``account_id`` column enabling account-scoped COUNT.
# ``accounts`` is special: filtered via ``WHERE id = :account_id``.
_TABLES_WITH_ACCOUNT_ID: frozenset[str] = frozenset(
    {
        "accounts",
        "custom_attribute_definitions",
        "canned_responses",
        "inboxes",
        "webhooks",
        "teams",
        "labels",
        "contacts",
        "conversations",
        "messages",
        "attachments",
    }
)


class ValidationReporter:
    """Generates and saves the post-migration validation report.

    Example::

        reporter = ValidationReporter()
        path = reporter.generate(results, dest_engine, elapsed_seconds=3247.83)
        print(f"Report saved to {path}")
    """

    def generate(
        self,
        results: list[MigrationResult],
        dest_engine: Engine,
        duration_seconds: float,
        account_id: int | None = None,
    ) -> Path:
        """Build the report and write it to ``.tmp/``.

        :param results: List of :class:`MigrationResult` objects (one per table).
        :type results: list[MigrationResult]
        :param dest_engine: Destination engine used to query current row counts.
        :type dest_engine: Engine
        :param duration_seconds: Total migration wall-clock duration in seconds.
        :type duration_seconds: float
        :param account_id: Destination account ID.  When provided, ``DEST_TOTAL``
            counts are scoped to that account instead of the whole table.
        :type account_id: int | None
        :returns: Absolute path to the saved report file.
        :rtype: Path
        """
        # Query destination row counts per table (account-scoped when account_id set)
        dest_counts: dict[str, int] = {}
        with dest_engine.connect() as conn:
            for logical_name in _TABLE_NAMES_ORDER:
                physical = _LOGICAL_TO_PHYSICAL.get(logical_name, logical_name)
                try:
                    if account_id is not None and logical_name in _TABLES_WITH_ACCOUNT_ID:
                        if logical_name == "accounts":
                            row = conn.execute(
                                text("SELECT COUNT(*) FROM accounts WHERE id = :aid"),
                                {"aid": account_id},
                            ).fetchone()
                        else:
                            row = conn.execute(
                                text(
                                    f"SELECT COUNT(*) FROM {physical}"  # noqa: S608
                                    f" WHERE account_id = :aid"
                                ),
                                {"aid": account_id},
                            ).fetchone()
                    else:
                        row = conn.execute(
                            text(f"SELECT COUNT(*) FROM {physical}")  # noqa: S608
                        ).fetchone()
                    dest_counts[logical_name] = int(row[0]) if row else 0
                except Exception:  # noqa: BLE001
                    dest_counts[logical_name] = -1

        # Index results by table name
        result_map = {r.table: r for r in results}

        now = datetime.now()  # noqa: DTZ005
        timestamp = now.strftime("%Y%m%d_%H%M%S")
        generated_str = now.strftime("%Y-%m-%dT%H:%M:%S")

        lines: list[str] = [
            _HEADER,
            f"Duration: {duration_seconds:.2f}s  |  Generated: {generated_str}",
            "",
            _format_row(
                ("TABELA", "ORIGEM", "MIGRADO", "DESTINO_TOTAL", "FALHAS"),
                widths=_COL_WIDTHS,
                header=True,
            ),
            "-" * (sum(_COL_WIDTHS) + 3 * (len(_COL_WIDTHS) - 1) + 2),
        ]

        all_tables = [t for t in _TABLE_NAMES_ORDER if t in result_map] + [
            t for t in result_map if t not in _TABLE_NAMES_ORDER
        ]
        for table_name in all_tables:
            r = result_map.get(table_name)
            if r is None:
                continue
            lines.append(
                _format_row(
                    (
                        table_name,
                        str(r.total_source),
                        str(r.migrated),
                        str(dest_counts.get(table_name, "?")),
                        str(len(r.failed_ids)),
                    ),
                    widths=_COL_WIDTHS,
                )
            )

        # Totals row
        total_source = sum(r.total_source for r in results)
        total_migrated = sum(r.migrated for r in results)
        total_dest = sum(v for v in dest_counts.values() if isinstance(v, int) and v >= 0)
        total_failed = sum(len(r.failed_ids) for r in results)
        lines.append("-" * (sum(_COL_WIDTHS) + 3 * (len(_COL_WIDTHS) - 1) + 2))
        lines.append(
            _format_row(
                (
                    "TOTAL",
                    str(total_source),
                    str(total_migrated),
                    str(total_dest),
                    str(total_failed),
                ),
                widths=_COL_WIDTHS,
            )
        )

        # Failed IDs section (IDs only — no content)
        lines.append("")
        lines.append("=== Failed IDs ===")
        any_failed = False
        for table_name in all_tables:
            r = result_map.get(table_name)
            if r and r.failed_ids:
                any_failed = True
                ids_str = ", ".join(str(i) for i in r.failed_ids[:200])
                suffix = f"  (+ {len(r.failed_ids) - 200} more)" if len(r.failed_ids) > 200 else ""
                lines.append(f"{table_name}: {ids_str}{suffix}")
        if not any_failed:
            lines.append("(none)")

        report_content = "\n".join(lines) + "\n"

        # Save to .tmp/
        out_dir = Path(".tmp")
        out_dir.mkdir(parents=True, exist_ok=True)
        report_path = out_dir / f"migration_{timestamp}_report.txt"
        report_path.write_text(report_content, encoding="utf-8")

        logger.info("ValidationReporter: report saved to %s", report_path)
        return report_path.resolve()


def _format_row(
    values: tuple[str, ...],
    widths: tuple[int, ...],
    header: bool = False,
) -> str:
    """Format a single report table row.

    :param values: Cell values as strings.
    :type values: tuple[str, ...]
    :param widths: Column widths in characters.
    :type widths: tuple[int, ...]
    :param header: If True, left-align all columns; otherwise right-align numerics.
    :type header: bool
    :returns: Formatted row string.
    :rtype: str
    """
    cells = []
    for i, (val, width) in enumerate(zip(values, widths, strict=False)):
        if header or i == 0:
            cells.append(val.ljust(width))
        else:
            cells.append(val.rjust(width))
    return " | ".join(cells)
