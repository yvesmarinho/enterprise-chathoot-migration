"""POC dry-run reporter for migration occurrence classification.

Collects up to ``MAX_SAMPLES`` (10) records per :class:`Outcome` type per
table and generates a structured plain-text report at
``.tmp/poc_YYYYMMDD_HHMMSS_report.txt``.

Designed to be called from ``src/migrar.py --dry-run --poc`` without
performing any INSERT, UPDATE, or DDL on the destination database.
"""

from __future__ import annotations

import enum
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MAX_SAMPLES: int = 10

_SEPARATOR = "=" * 80
_DASH = "-" * 80


class Outcome(str, enum.Enum):
    """Classification of a single source record during POC dry-run.

    :cvar WOULD_MIGRATE: Record will be inserted with remapped IDs.
    :cvar WOULD_MIGRATE_MODIFIED: Record inserted with nullable FKs set to
        NULL (parent not yet migrated).
    :cvar ORPHAN_FK_SKIP: Required FK points to a non-existent parent; record
        would be discarded entirely.
    :cvar ALREADY_MIGRATED: ID found in ``migration_state``; record would be
        skipped for idempotency.
    :cvar COLLISION: Unique constraint violation expected; record would fail
        on insert.

    >>> Outcome.WOULD_MIGRATE.value
    'WOULD_MIGRATE'
    >>> list(Outcome)  # doctest: +NORMALIZE_WHITESPACE
    [<Outcome.WOULD_MIGRATE: 'WOULD_MIGRATE'>,
     <Outcome.WOULD_MIGRATE_MODIFIED: 'WOULD_MIGRATE_MODIFIED'>,
     <Outcome.ORPHAN_FK_SKIP: 'ORPHAN_FK_SKIP'>,
     <Outcome.ALREADY_MIGRATED: 'ALREADY_MIGRATED'>,
     <Outcome.COLLISION: 'COLLISION'>]
    """

    WOULD_MIGRATE = "WOULD_MIGRATE"
    WOULD_MIGRATE_MODIFIED = "WOULD_MIGRATE_MODIFIED"
    ORPHAN_FK_SKIP = "ORPHAN_FK_SKIP"
    ALREADY_MIGRATED = "ALREADY_MIGRATED"
    COLLISION = "COLLISION"


@dataclass
class RecordSample:
    """A single sampled source record with its POC classification.

    :param id_origem: Primary key of the source record.
    :type id_origem: int
    :param outcome: Classification result.
    :type outcome: Outcome
    :param reason: Human-readable explanation of the classification.
    :type reason: str
    :param masked_preview: Non-sensitive field subset; PII already masked
        before construction.
    :type masked_preview: dict[str, Any]
    """

    id_origem: int
    outcome: Outcome
    reason: str
    masked_preview: dict[str, Any] = field(default_factory=dict)


@dataclass
class POCResult:
    """Aggregated classification results for a single migration table.

    :param table: Name of the migrated table.
    :type table: str
    :param total_source: Total number of records read from SOURCE.
    :type total_source: int
    :param outcome_counts: Count of records per :attr:`Outcome` value.
    :type outcome_counts: dict[str, int]
    :param samples: Up to ``MAX_SAMPLES`` records per :attr:`Outcome` value.
    :type samples: dict[str, list[RecordSample]]
    """

    table: str
    total_source: int
    outcome_counts: dict[str, int] = field(default_factory=dict)
    samples: dict[str, list[RecordSample]] = field(default_factory=dict)
    surviving_ids: set[int] = field(default_factory=set)

    def add_record(self, sample: RecordSample) -> None:
        """Classify and optionally sample a source record.

        Increments the counter for ``sample.outcome`` and appends the sample
        to the bucket list if fewer than ``MAX_SAMPLES`` entries are stored.
        For outcomes that imply the record *will* be present on the
        destination (WOULD_MIGRATE, WOULD_MIGRATE_MODIFIED), the
        ``id_origem`` is also added to :attr:`surviving_ids` so downstream
        FK checks can reference the full prospective set (not just the
        capped sample).

        :param sample: Classified record to register.
        :type sample: RecordSample
        :returns: None
        :rtype: None

        >>> result = POCResult(table="contacts", total_source=100)
        >>> s = RecordSample(
        ...     id_origem=1, outcome=Outcome.WOULD_MIGRATE, reason="clean"
        ... )
        >>> result.add_record(s)
        >>> result.outcome_counts[Outcome.WOULD_MIGRATE.value]
        1
        >>> len(result.samples[Outcome.WOULD_MIGRATE.value])
        1
        >>> 1 in result.surviving_ids
        True
        """
        key = sample.outcome.value
        self.outcome_counts[key] = self.outcome_counts.get(key, 0) + 1
        bucket = self.samples.setdefault(key, [])
        if len(bucket) < MAX_SAMPLES:
            bucket.append(sample)
        if sample.outcome in (
            Outcome.WOULD_MIGRATE,
            Outcome.WOULD_MIGRATE_MODIFIED,
        ):
            self.surviving_ids.add(sample.id_origem)


class POCReporter:
    """Generates a POC dry-run report from multi-table classification
    results.
    """

    def generate(
        self,
        results: list[POCResult],
        duration_seconds: float,
    ) -> Path:
        """Generate and persist the POC dry-run report.

        Writes a plain-text report to ``.tmp/poc_YYYYMMDD_HHMMSS_report.txt``
        containing a summary table (one row per migrated table, counts per
        :class:`Outcome`) and a samples section (up to ``MAX_SAMPLES`` records
        per :class:`Outcome` per table). Creates ``.tmp/`` if absent.

        :param results: List of classification results, one per table.
        :type results: list[POCResult]
        :param duration_seconds: Total elapsed classification time in seconds.
        :type duration_seconds: float
        :returns: Absolute path of the generated report file.
        :rtype: Path
        :raises OSError: If ``.tmp/`` cannot be created or the file cannot be
            written.
        """
        tmp_dir = Path(".tmp")
        tmp_dir.mkdir(exist_ok=True)

        ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
        report_path = tmp_dir / f"poc_{ts}_report.txt"

        lines = _build_report_lines(results, duration_seconds)
        report_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("POC report saved to %s", report_path)

        return report_path


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _build_report_lines(
    results: list[POCResult],
    duration_seconds: float,
) -> list[str]:
    """Build the plain-text report as a list of lines.

    :param results: Classification results per table.
    :type results: list[POCResult]
    :param duration_seconds: Elapsed classification time.
    :type duration_seconds: float
    :returns: Lines ready for ``"\\n".join()``.
    :rtype: list[str]
    """
    lines: list[str] = []

    # ── Header ──────────────────────────────────────────────────────────────
    lines += [
        _SEPARATOR,
        "POC DRY-RUN REPORT — Enterprise Chatwoot Migration",
        f"Generated : {datetime.now(tz=timezone.utc).isoformat()}",
        f"Duration  : {duration_seconds:.2f}s",
        _SEPARATOR,
        "",
    ]

    # ── Summary table ────────────────────────────────────────────────────────
    lines.append(
        f"{'TABLE':<30} {'TOTAL':>8} {'MIGRATE':>8} {'MODIFIED':>10}"
        f" {'ORPHAN':>8} {'DEDUP':>8} {'COLLISION':>10}"
    )
    lines.append(_DASH)

    for r in results:
        c = r.outcome_counts
        lines.append(
            f"{r.table:<30}"
            f" {r.total_source:>8}"
            f" {c.get(Outcome.WOULD_MIGRATE.value, 0):>8}"
            f" {c.get(Outcome.WOULD_MIGRATE_MODIFIED.value, 0):>10}"
            f" {c.get(Outcome.ORPHAN_FK_SKIP.value, 0):>8}"
            f" {c.get(Outcome.ALREADY_MIGRATED.value, 0):>8}"
            f" {c.get(Outcome.COLLISION.value, 0):>10}"
        )

    lines.append("")

    # ── Samples per table per outcome ────────────────────────────────────────
    for r in results:
        if not r.samples:
            continue
        lines.append(f"── {r.table} ──")
        for outcome_key, sample_list in r.samples.items():
            total = r.outcome_counts.get(outcome_key, 0)
            lines.append(f"  [{outcome_key}]  " f"({len(sample_list)} sample(s), total={total})")
            for s in sample_list:
                preview = json.dumps(s.masked_preview, ensure_ascii=False)
                lines.append(
                    f"    id={s.id_origem}" f"  reason={s.reason!r}" f"  preview={preview}"
                )
        lines.append("")

    return lines
