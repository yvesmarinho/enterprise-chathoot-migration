"""Abstract base class for all entity migrators.

:description: Defines the ``BaseMigrator`` contract and provides the shared
    ``_run_batches`` implementation that handles:

    * Already-migrated ID filtering (idempotency via ``MigrationStateRepository``)
    * Batch splitting (500 records per transaction)
    * ID remapping via ``IDRemapper``
    * Bulk-insert within a single transaction per batch
    * Per-record success/failure tracking in ``migration_state``
    * Fault-tolerance: batch failure is logged and execution continues

    Concrete migrators must implement :meth:`migrate` and supply the correct
    ``dest_table`` and ``remap_fn`` when calling ``_run_batches``.

    Example::

        class AccountsMigrator(BaseMigrator):
            def migrate(self) -> MigrationResult:
                with self.source_engine.connect() as conn:
                    rows = conn.execute(select(accounts_table)).mappings().all()
                return self._run_batches(
                    source_rows=list(rows),
                    table_name="accounts",
                    dest_table=dest_accounts_table,
                    remap_fn=lambda r: {**r, "id": self.id_remapper.remap(r["id"], "accounts")},
                )
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import Table
from sqlalchemy.engine import Engine

from src.reports.poc_reporter import Outcome, POCResult, RecordSample
from src.repository.base_repository import BaseRepository
from src.repository.migration_state_repository import MigrationStateRepository
from src.utils.id_remapper import IDRemapper

_BATCH_SIZE = 500


@dataclass
class MigrationResult:
    """Result of a single table migration run.

    :param table: Table name that was migrated.
    :param total_source: Total records found in source.
    :param migrated: Records successfully inserted in destination.
    :param skipped: Records skipped because already present in ``migration_state``.
    :param failed_ids: List of ``id_origem`` values that failed to insert.
    """

    table: str
    total_source: int
    migrated: int
    skipped: int
    failed_ids: list[int] = field(default_factory=list)


class BaseMigrator(ABC):
    """Abstract migrator providing shared batch-processing logic.

    :param source_engine: Read-only engine connected to the source database.
    :type source_engine: Engine
    :param dest_engine: Read-write engine connected to the destination database.
    :type dest_engine: Engine
    :param id_remapper: Session-scoped offset remapper.
    :type id_remapper: IDRemapper
    :param state_repo: Repository for the ``migration_state`` control table.
    :type state_repo: MigrationStateRepository
    :param logger: Logger instance (expected to have ``MaskingHandler`` attached).
    :type logger: logging.Logger
    """

    def __init__(
        self,
        source_engine: Engine,
        dest_engine: Engine,
        id_remapper: IDRemapper,
        state_repo: MigrationStateRepository,
        logger: logging.Logger,
    ) -> None:
        """Initialise the migrator with engines, remapper, state repo, and logger."""
        self.source_engine = source_engine
        self.dest_engine = dest_engine
        self.id_remapper = id_remapper
        self.state_repo = state_repo
        self.logger = logger
        self._repo = BaseRepository()

    @abstractmethod
    def migrate(self) -> MigrationResult:
        """Execute the migration for this entity.

        :returns: Summary of the migration run.
        :rtype: MigrationResult
        :raises SystemExit: Implementations MAY raise ``SystemExit(3)`` for
            catastrophic failure in root entities (e.g., ``accounts``).
        """

    @abstractmethod
    def _table_name(self) -> str:
        """Return the canonical table name for this migrator.

        Used by :meth:`poc_classify` to label :class:`POCResult`.

        :returns: Lowercased table name string (e.g., ``"accounts"``).
        :rtype: str
        """

    @abstractmethod
    def _fetch_all_source_rows(self) -> list[dict]:
        """Fetch every row from the source table.

        Read-only — MUST NOT write to source or destination.

        :returns: All source rows as plain dicts.
        :rtype: list[dict]
        """

    def _classify_row_poc(
        self,
        row: dict,  # noqa: ARG002
        migrated_sets: dict[str, set[int]],  # noqa: ARG002
    ) -> tuple[Outcome, str]:
        """Classify a single source row for the POC dry-run.

        Default implementation returns :attr:`Outcome.WOULD_MIGRATE`.
        Concrete migrators override to add FK-specific checks.

        Classification priority:

        1. Required FK absent → :attr:`Outcome.ORPHAN_FK_SKIP`
        2. Unique constraint violation expected → :attr:`Outcome.COLLISION`
        3. Nullable FK absent → :attr:`Outcome.WOULD_MIGRATE_MODIFIED`
        4. Otherwise → :attr:`Outcome.WOULD_MIGRATE`

        :param row: Source row as plain dict.
        :type row: dict
        :param migrated_sets: Sets of already-migrated destination IDs keyed by
            table name (e.g., ``{"accounts": {1, 2, 3}}``).
        :type migrated_sets: dict[str, set[int]]
        :returns: ``(outcome, reason)`` tuple.
        :rtype: tuple[Outcome, str]
        """
        # row and migrated_sets are intentionally unused in the base default;
        # they are referenced in all concrete overrides.
        del row, migrated_sets
        return Outcome.WOULD_MIGRATE, "no FK dependency"

    def _poc_safe_preview(self, row: dict) -> dict:
        """Return a non-sensitive field subset for sample preview.

        Concrete migrators may override to include table-specific safe columns.
        Default includes only ``id`` and ``created_at`` (non-PII).

        :param row: Source row as plain dict.
        :type row: dict
        :returns: Dict safe for inclusion in the POC report.
        :rtype: dict
        """
        return {
            "id": row.get("id"),
            "created_at": str(row.get("created_at", "")),
        }

    def poc_classify(
        self,
        already_migrated: set[int],
        migrated_sets: dict[str, set[int]],
    ) -> POCResult:
        """Classify all source rows without writing to the destination.

        Reads every source row, classifies each into one of five
        :class:`~src.reports.poc_reporter.Outcome` categories, and collects up
        to ``MAX_SAMPLES`` (10) records per category.  No INSERT, UPDATE, or
        DDL is executed.

        Classification steps per record:

        1. ``id_origem`` in *already_migrated* → ``ALREADY_MIGRATED``
        2. Required FK absent in *migrated_sets* → ``ORPHAN_FK_SKIP``
        3. Unique constraint violation expected → ``COLLISION``
        4. Nullable FK absent → ``WOULD_MIGRATE_MODIFIED``
        5. Otherwise → ``WOULD_MIGRATE``

        :param already_migrated: Set of ``id_origem`` values already present in
            ``migration_state`` for this table.
        :type already_migrated: set[int]
        :param migrated_sets: Destination ID sets per table, used by
            :meth:`_classify_row_poc` to check FK existence.
        :type migrated_sets: dict[str, set[int]]
        :returns: Aggregated classification result for this table.
        :rtype: POCResult

        >>> # doctest: skip (requires live DB)
        >>> result = migrator.poc_classify(
        ...     already_migrated=set(),
        ...     migrated_sets={"accounts": {1, 2}},
        ... )
        >>> isinstance(result, POCResult)
        True
        """
        source_rows = self._fetch_all_source_rows()
        table = self._table_name()
        result = POCResult(table=table, total_source=len(source_rows))

        for row in source_rows:
            id_orig = int(row["id"])
            if id_orig in already_migrated:
                outcome = Outcome.ALREADY_MIGRATED
                reason = "id_origem already in migration_state"
            else:
                outcome, reason = self._classify_row_poc(row, migrated_sets)

            result.add_record(
                RecordSample(
                    id_origem=id_orig,
                    outcome=outcome,
                    reason=reason,
                    masked_preview=self._poc_safe_preview(row),
                )
            )

        self.logger.info(
            "POC classify %s: total=%d counts=%s",
            table,
            result.total_source,
            result.outcome_counts,
        )
        return result

    def _run_batches(
        self,
        source_rows: list[dict],
        table_name: str,
        dest_table: Table,
        remap_fn: Callable[[dict], dict | None],
    ) -> MigrationResult:
        """Process *source_rows* in batches of 500 into *dest_table*.

        Steps per batch:

        1. Filter already-migrated IDs via :meth:`MigrationStateRepository.get_migrated_ids`.
        2. Apply *remap_fn* to each row — returning ``None`` skips the record.
        3. Bulk-insert the remapped rows inside a single transaction.
        4. Record success for each inserted ``id_origem``.
        5. On batch exception: record failure for each ID in the batch and
           continue to the next batch (fault-tolerant, non-catastrophic).

        :param source_rows: All rows fetched from the source, as plain dicts.
        :type source_rows: list[dict]
        :param table_name: Logical table name (must match ``migration_state.tabela``).
        :type table_name: str
        :param dest_table: SQLAlchemy ``Table`` object for the destination.
        :type dest_table: Table
        :param remap_fn: Callable that maps a source row dict to a destination
            row dict, or returns ``None`` to skip the record.
        :type remap_fn: Callable[[dict], dict | None]
        :returns: Aggregated migration result.
        :rtype: MigrationResult
        """
        total_source = len(source_rows)
        migrated = 0
        skipped = 0
        failed_ids: list[int] = []

        with self.dest_engine.connect() as dest_conn:
            already_done = self.state_repo.get_migrated_ids(dest_conn, table_name)

        # Split into batches
        batches = [
            source_rows[i : i + _BATCH_SIZE] for i in range(0, len(source_rows), _BATCH_SIZE)
        ]

        total_batches = len(batches)
        log_interval = max(1, total_batches // 10)
        for batch_num, batch in enumerate(batches, start=1):
            self.logger.debug(
                "Table %s — batch %d/%d (%d rows)",
                table_name,
                batch_num,
                total_batches,
                len(batch),
            )
            if batch_num % log_interval == 0 or batch_num == total_batches:
                self.logger.info(
                    "Table %s: %d/%d batches (%.0f%%) — migrated=%d skipped=%d failed=%d",
                    table_name,
                    batch_num,
                    total_batches,
                    100.0 * batch_num / total_batches,
                    migrated,
                    skipped,
                    len(failed_ids),
                )
            # Remap and filter
            pending: list[tuple[int, dict]] = []
            for row in batch:
                id_origem = int(row["id"])
                if id_origem in already_done:
                    skipped += 1
                    continue
                remapped = remap_fn(row)
                if remapped is None:
                    # remap_fn returns None → skip this record
                    skipped += 1
                    self.logger.warning(
                        "Table %s: id_origem=%d skipped by remap_fn (FK orphan or collision)",
                        table_name,
                        id_origem,
                    )
                    continue
                pending.append((id_origem, remapped))

            if not pending:
                continue

            ids_in_batch = [p[0] for p in pending]
            rows_to_insert = [p[1] for p in pending]

            try:
                with self.dest_engine.connect() as dest_conn:
                    with dest_conn.begin():
                        self._repo.bulk_insert(dest_conn, dest_table, rows_to_insert)
                        self.state_repo.record_success_bulk(
                            dest_conn,
                            table_name,
                            [
                                (id_origem, int(remapped.get("id", id_origem)))
                                for id_origem, remapped in pending
                            ],
                        )
                migrated += len(pending)
            except Exception as exc:  # noqa: BLE001
                self.logger.error(
                    "Table %s batch %d/%d FAILED (%d rows): %s — continuing",
                    table_name,
                    batch_num,
                    total_batches,
                    len(ids_in_batch),
                    exc,
                )
                failed_ids.extend(ids_in_batch)
                # Record individual failures (best effort, new connection)
                try:
                    with self.dest_engine.connect() as dest_conn:
                        with dest_conn.begin():
                            for id_origem in ids_in_batch:
                                self.state_repo.record_failure(
                                    dest_conn,
                                    table_name,
                                    id_origem,
                                    str(exc)[:100],
                                )
                except Exception as rec_exc:  # noqa: BLE001
                    self.logger.warning(
                        "Table %s: could not record failure state for batch %d: %s",
                        table_name,
                        batch_num,
                        rec_exc,
                    )

        self.logger.info(
            "Table %s: total=%d migrated=%d skipped=%d failed=%d",
            table_name,
            total_source,
            migrated,
            skipped,
            len(failed_ids),
        )

        return MigrationResult(
            table=table_name,
            total_source=total_source,
            migrated=migrated,
            skipped=skipped,
            failed_ids=failed_ids,
        )
