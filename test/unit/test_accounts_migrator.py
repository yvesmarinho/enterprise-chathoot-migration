"""Unit tests for AccountsMigrator (T025)."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from src.migrators.accounts_migrator import AccountsMigrator
from src.migrators.base_migrator import MigrationResult
from src.repository.migration_state_repository import MigrationStateRepository
from src.utils.id_remapper import IDRemapper


def _make_migrator(source_rows=None, already_migrated=None):
    """Build an AccountsMigrator with fully mocked dependencies."""
    source_rows = source_rows or []
    already_migrated = already_migrated or set()

    source_engine = MagicMock()
    dest_engine = MagicMock()

    # Mock source connection — returns source_rows
    src_conn = MagicMock()
    src_conn.__enter__ = MagicMock(return_value=src_conn)
    src_conn.__exit__ = MagicMock(return_value=False)
    src_conn.execute.return_value.mappings.return_value.all.return_value = source_rows
    source_engine.connect.return_value = src_conn

    # Mock dest connection — get_migrated_ids returns already_migrated
    dest_conn = MagicMock()
    dest_conn.__enter__ = MagicMock(return_value=dest_conn)
    dest_conn.__exit__ = MagicMock(return_value=False)
    dest_conn.begin.return_value.__enter__ = MagicMock(return_value=None)
    dest_conn.begin.return_value.__exit__ = MagicMock(return_value=False)
    dest_engine.connect.return_value = dest_conn

    state_repo = MagicMock(spec=MigrationStateRepository)
    state_repo.get_migrated_ids.return_value = already_migrated

    remapper = IDRemapper({"accounts": 20})
    logger = logging.getLogger("test_accounts")

    migrator = AccountsMigrator(
        source_engine=source_engine,
        dest_engine=dest_engine,
        id_remapper=remapper,
        state_repo=state_repo,
        logger=logger,
    )
    return migrator


# ---------------------------------------------------------------------------
# T025-1 — Batch of 500 produces correct batching
# ---------------------------------------------------------------------------


def test_accounts_batch_splitting():
    """601 source rows produce 2 batches (500 + 101)."""
    rows = [
        {"id": i, "name": f"Account {i}", "created_at": None, "updated_at": None}
        for i in range(1, 602)
    ]

    with patch.object(AccountsMigrator, "_run_batches", wraps=None) as mock_run:
        mock_run.return_value = MigrationResult(
            table="accounts", total_source=601, migrated=601, skipped=0
        )
        migrator = _make_migrator(source_rows=rows)

        # Patch Table autoload
        with patch("src.migrators.accounts_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

        # Verify _run_batches was called with all 601 rows
        call_args = mock_run.call_args
        assert call_args.args[1] == "accounts"


# ---------------------------------------------------------------------------
# T025-2 — Offset is applied to id
# ---------------------------------------------------------------------------


def test_accounts_offset_applied_to_id():
    """ID remapping applies offset_accounts to each row's id."""
    rows = [{"id": 1, "name": "Acme", "created_at": None, "updated_at": None}]

    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            result = remap_fn(row)
            if result is not None:
                remapped_rows.append(result)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    migrator = _make_migrator(source_rows=rows)
    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.accounts_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert len(remapped_rows) == 1
    # offset_accounts=20, so id 1 → 21
    assert remapped_rows[0]["id"] == 21


# ---------------------------------------------------------------------------
# T025-3 — Exit code 3 raised on catastrophic failure
# ---------------------------------------------------------------------------


def test_accounts_exit_code_3_on_failure():
    """SystemExit(3) is raised when any records fail to migrate."""
    rows = [{"id": 1, "name": "Acme", "created_at": None, "updated_at": None}]

    migrator = _make_migrator(source_rows=rows)
    with patch.object(
        migrator,
        "_run_batches",
        return_value=MigrationResult(
            table="accounts",
            total_source=1,
            migrated=0,
            skipped=0,
            failed_ids=[1],
        ),
    ):
        with patch("src.migrators.accounts_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            with pytest.raises(SystemExit) as exc_info:
                migrator.migrate()
    assert exc_info.value.code == 3


# ---------------------------------------------------------------------------
# T025-4 — No exit when all records succeed
# ---------------------------------------------------------------------------


def test_accounts_no_exit_on_success():
    """No SystemExit is raised when migration is fully successful."""
    rows = [{"id": 2, "name": "Beta", "created_at": None, "updated_at": None}]

    migrator = _make_migrator(source_rows=rows)
    with patch.object(
        migrator,
        "_run_batches",
        return_value=MigrationResult(table="accounts", total_source=1, migrated=1, skipped=0),
    ):
        with patch("src.migrators.accounts_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            result = migrator.migrate()
    assert result.migrated == 1


# ---------------------------------------------------------------------------
# T025-5 — Merge rule: account with same id+name skips INSERT, alias registered
# ---------------------------------------------------------------------------


def _make_migrator_with_dest_accounts(source_rows, dest_accounts_rows, already_migrated=None):
    """Build AccountsMigrator where dest DB returns specific account rows."""
    already_migrated = already_migrated or set()

    source_engine = MagicMock()
    dest_engine = MagicMock()

    # Source connection: returns source_rows for table select
    src_conn = MagicMock()
    src_conn.__enter__ = MagicMock(return_value=src_conn)
    src_conn.__exit__ = MagicMock(return_value=False)
    src_conn.execute.return_value.mappings.return_value.all.return_value = source_rows
    source_engine.connect.return_value = src_conn

    # Dest connection: first execute call returns dest_accounts_rows (for merge check),
    # subsequent calls return already_migrated set (for _run_batches)
    dest_conn = MagicMock()
    dest_conn.__enter__ = MagicMock(return_value=dest_conn)
    dest_conn.__exit__ = MagicMock(return_value=False)
    dest_conn.begin.return_value.__enter__ = MagicMock(return_value=None)
    dest_conn.begin.return_value.__exit__ = MagicMock(return_value=False)
    # text() query returns dest_accounts_rows as (id, name) tuples
    dest_conn.execute.return_value.fetchall.return_value = dest_accounts_rows
    dest_engine.connect.return_value = dest_conn

    state_repo = MagicMock(spec=MigrationStateRepository)
    state_repo.get_migrated_ids.return_value = already_migrated

    remapper = IDRemapper({"accounts": 43})
    logger = logging.getLogger("test_accounts_merge")

    return (
        AccountsMigrator(
            source_engine=source_engine,
            dest_engine=dest_engine,
            id_remapper=remapper,
            state_repo=state_repo,
            logger=logger,
        ),
        remapper,
        state_repo,
    )


def test_accounts_merge_rule_skips_insert_and_registers_alias():
    """Accounts with same id+name in DEST: alias registered, record_success called, INSERT skipped."""
    src_rows = [
        {"id": 1, "name": "Vya Digital", "created_at": None, "updated_at": None},
        {"id": 4, "name": "Sol Copernico", "created_at": None, "updated_at": None},
    ]
    # DEST has id=1 "Vya Digital" — should trigger merge rule
    dst_rows = [(1, "Vya Digital"), (20, "Other Account")]

    migrator, remapper, state_repo = _make_migrator_with_dest_accounts(src_rows, dst_rows)

    with patch.object(
        migrator,
        "_run_batches",
        return_value=MigrationResult(table="accounts", total_source=2, migrated=1, skipped=0),
    ):
        with patch("src.migrators.accounts_migrator.Table"):
            migrator.migrate()

    # Alias registered: remapping id=1 should return 1 (not 1+43=44)
    assert remapper.remap(1, "accounts") == 1

    # Offset still applied for unmatched id=4
    assert remapper.remap(4, "accounts") == 47

    # record_success called for merged account (id_origem=1, id_destino=1)
    calls = state_repo.record_success.call_args_list
    merged_call = next(
        (c for c in calls if c.args[1] == "accounts" and c.args[2] == 1 and c.args[3] == 1),
        None,
    )
    assert merged_call is not None, "record_success not called for merged account id=1"


def test_accounts_merge_rule_no_match_uses_offset():
    """When no account matches by id+name, all IDs use offset normally."""
    src_rows = [
        {"id": 4, "name": "Sol Copernico", "created_at": None, "updated_at": None},
    ]
    # DEST has no account matching id=4 + "Sol Copernico"
    dst_rows = [(1, "Vya Digital"), (17, "Unimed Poços PJ")]

    migrator, remapper, state_repo = _make_migrator_with_dest_accounts(src_rows, dst_rows)

    with patch.object(
        migrator,
        "_run_batches",
        return_value=MigrationResult(table="accounts", total_source=1, migrated=1, skipped=0),
    ):
        with patch("src.migrators.accounts_migrator.Table"):
            migrator.migrate()

    # No alias; offset applied: 4 + 43 = 47
    assert remapper.remap(4, "accounts") == 47

    # record_success NOT called with merge (no matching merge found)
    merge_calls = [c for c in state_repo.record_success.call_args_list if c.args[1] == "accounts"]
    # Should be empty since merge rule did not fire
    assert len(merge_calls) == 0


def test_accounts_merge_rule_name_mismatch_no_alias():
    """Same id but different name in DEST does NOT trigger merge rule."""
    src_rows = [
        {"id": 1, "name": "Vya Digital NEW", "created_at": None, "updated_at": None},
    ]
    # DEST has id=1 but different name
    dst_rows = [(1, "Vya Digital")]

    migrator, remapper, _ = _make_migrator_with_dest_accounts(src_rows, dst_rows)

    with patch.object(
        migrator,
        "_run_batches",
        return_value=MigrationResult(table="accounts", total_source=1, migrated=1, skipped=0),
    ):
        with patch("src.migrators.accounts_migrator.Table"):
            migrator.migrate()

    # No alias registered — remap uses offset: 1 + 43 = 44
    assert remapper.remap(1, "accounts") == 44
