"""Unit tests for BaseMigrator._run_batches (T035)."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

from src.migrators.base_migrator import BaseMigrator, MigrationResult
from src.repository.migration_state_repository import MigrationStateRepository
from src.utils.id_remapper import IDRemapper

# ---------------------------------------------------------------------------
# Concrete test double — minimal concrete subclass
# ---------------------------------------------------------------------------


class _ConcreteMigrator(BaseMigrator):
    """Minimal concrete subclass for testing BaseMigrator._run_batches."""

    def migrate(self) -> MigrationResult:
        """Not used in these tests."""
        raise NotImplementedError


def _make_base_migrator(already_migrated=None):
    """Build a _ConcreteMigrator with mocked engines and repos."""
    already_migrated = already_migrated or set()

    source_engine = MagicMock()
    dest_engine = MagicMock()

    dest_conn = MagicMock()
    dest_conn.__enter__ = MagicMock(return_value=dest_conn)
    dest_conn.__exit__ = MagicMock(return_value=False)
    dest_conn.begin.return_value.__enter__ = MagicMock(return_value=None)
    dest_conn.begin.return_value.__exit__ = MagicMock(return_value=False)
    dest_engine.connect.return_value = dest_conn

    state_repo = MagicMock(spec=MigrationStateRepository)
    state_repo.get_migrated_ids.return_value = already_migrated

    remapper = IDRemapper({"test_table": 0})
    logger = logging.getLogger("test_base_migrator")

    migrator = _ConcreteMigrator(
        source_engine=source_engine,
        dest_engine=dest_engine,
        id_remapper=remapper,
        state_repo=state_repo,
        logger=logger,
    )
    return migrator, state_repo, dest_conn


# ---------------------------------------------------------------------------
# T035-1 — _run_batches skips records whose id_origem is in get_migrated_ids
# ---------------------------------------------------------------------------


def test_run_batches_skips_already_migrated():
    """Records with id_origem in get_migrated_ids result are skipped."""
    migrator, state_repo, dest_conn = _make_base_migrator(already_migrated={2, 3})

    rows = [{"id": 1}, {"id": 2}, {"id": 3}]
    dest_table = MagicMock()

    with patch.object(migrator._repo, "bulk_insert") as mock_insert:
        result = migrator._run_batches(
            rows, "test_table", dest_table, remap_fn=lambda r: r
        )

    # Only id=1 should be inserted
    assert result.migrated == 1
    assert result.skipped == 2
    # bulk_insert called with 1 row
    assert mock_insert.call_count == 1
    inserted_rows = mock_insert.call_args[0][2]
    assert len(inserted_rows) == 1
    assert inserted_rows[0]["id"] == 1


# ---------------------------------------------------------------------------
# T035-2 — Partial batch failure records failed status and continues
# ---------------------------------------------------------------------------


def test_run_batches_partial_failure_continues():
    """A batch failure records failed IDs and continues with subsequent batches."""
    migrator, state_repo, dest_conn = _make_base_migrator()

    # 1001 rows — 3 batches (500, 500, 1)
    rows = [{"id": i} for i in range(1, 1002)]
    dest_table = MagicMock()

    call_count = [0]

    def fail_first_batch(conn, table, records):
        call_count[0] += 1
        if call_count[0] == 1:
            raise RuntimeError("DB error on first batch")

    with patch.object(migrator._repo, "bulk_insert", side_effect=fail_first_batch):
        result = migrator._run_batches(
            rows, "test_table", dest_table, remap_fn=lambda r: r
        )

    assert len(result.failed_ids) == 500
    assert result.migrated == 501  # batches 2 (500) + 3 (1)
    assert result.total_source == 1001


# ---------------------------------------------------------------------------
# T035-3 — MigrationResult: migrated + skipped = total_source when re-running
# ---------------------------------------------------------------------------


def test_run_batches_rerun_zero_new_records():
    """Re-running with all IDs already migrated → migrated=0, skipped=total_source."""
    all_ids = set(range(1, 101))
    migrator, state_repo, dest_conn = _make_base_migrator(already_migrated=all_ids)

    rows = [{"id": i} for i in range(1, 101)]
    dest_table = MagicMock()

    with patch.object(migrator._repo, "bulk_insert") as mock_insert:
        result = migrator._run_batches(
            rows, "test_table", dest_table, remap_fn=lambda r: r
        )

    assert result.migrated == 0
    assert result.skipped == 100
    assert result.migrated + result.skipped == result.total_source
    mock_insert.assert_not_called()


# ---------------------------------------------------------------------------
# T035-4 — remap_fn returning None skips the record
# ---------------------------------------------------------------------------


def test_run_batches_remap_fn_none_skips():
    """Records where remap_fn returns None are counted as skipped."""
    migrator, state_repo, dest_conn = _make_base_migrator()

    rows = [{"id": 1}, {"id": 2}, {"id": 3}]
    dest_table = MagicMock()

    # remap_fn returns None for id=2
    def remap(row):
        return None if row["id"] == 2 else row

    with patch.object(migrator._repo, "bulk_insert"):
        result = migrator._run_batches(rows, "test_table", dest_table, remap_fn=remap)

    assert result.migrated == 2
    assert result.skipped == 1
