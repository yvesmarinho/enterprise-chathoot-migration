"""Unit tests for CannedResponsesMigrator (T036)."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

from src.migrators.base_migrator import MigrationResult
from src.migrators.canned_responses_migrator import CannedResponsesMigrator
from src.repository.migration_state_repository import MigrationStateRepository
from src.utils.id_remapper import IDRemapper


def _make_migrator(source_rows=None, migrated=None):
    """Build CannedResponsesMigrator with mocked engines."""
    source_rows = source_rows or []
    migrated = migrated or {}

    source_engine = MagicMock()
    dest_engine = MagicMock()

    src_conn = MagicMock()
    src_conn.__enter__ = MagicMock(return_value=src_conn)
    src_conn.__exit__ = MagicMock(return_value=False)
    src_conn.execute.return_value.mappings.return_value.all.return_value = source_rows
    source_engine.connect.return_value = src_conn

    dest_conn = MagicMock()
    dest_conn.__enter__ = MagicMock(return_value=dest_conn)
    dest_conn.__exit__ = MagicMock(return_value=False)
    dest_conn.begin.return_value.__enter__ = MagicMock(return_value=None)
    dest_conn.begin.return_value.__exit__ = MagicMock(return_value=False)
    dest_engine.connect.return_value = dest_conn

    state_repo = MagicMock(spec=MigrationStateRepository)
    state_repo.get_migrated_ids.side_effect = [
        migrated.get("accounts", {1}),
        set(),  # already_migrated
    ]

    remapper = IDRemapper({"canned_responses": 15, "accounts": 30})
    logger = logging.getLogger("test_cr")

    return (
        CannedResponsesMigrator(
            source_engine=source_engine,
            dest_engine=dest_engine,
            id_remapper=remapper,
            state_repo=state_repo,
            logger=logger,
        ),
        remapper,
    )


def test_canned_responses_basic_migration():
    """Basic canned response inserted with remapped account_id."""
    rows = [
        {
            "id": 1,
            "account_id": 1,
            "short_code": "hello",
            "content": "Hello, how can I help?",
            "created_at": None,
            "updated_at": None,
        }
    ]

    migrator, _ = _make_migrator(source_rows=rows, migrated={"accounts": {1}})

    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.canned_responses_migrator.Table"):
            migrator.migrate()

    assert len(remapped_rows) == 1


def test_canned_responses_orphan_account_id_skipped():
    """Unmigrated account_id causes skip."""
    rows = [
        {
            "id": 2,
            "account_id": 999,
            "short_code": "goodbye",
            "content": "Goodbye!",
            "created_at": None,
            "updated_at": None,
        }
    ]

    migrator, _ = _make_migrator(source_rows=rows, migrated={"accounts": {1}})

    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=0, skipped=1)

    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.canned_responses_migrator.Table"):
            migrator.migrate()

    assert len(remapped_rows) == 0


# ---------------------------------------------------------------------------
# T024-3 — short_code field copied verbatim
# ---------------------------------------------------------------------------


def test_canned_responses_short_code_unchanged():
    """short_code field is copied as-is without modification."""
    short_code = "tech_support"
    rows = [
        {
            "id": 3,
            "account_id": 1,
            "short_code": short_code,
            "content": "Connecting to technical support team...",
            "created_at": None,
            "updated_at": None,
        }
    ]

    migrator, _ = _make_migrator(source_rows=rows, migrated={"accounts": {1}})
    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.canned_responses_migrator.Table"):
            migrator.migrate()

    assert remapped_rows[0]["short_code"] == short_code


# ---------------------------------------------------------------------------
# T024-4 — Mixed account_ids with partial skip
# ---------------------------------------------------------------------------


def test_canned_responses_mixed_accounts_partial_skip():
    """Canned responses from multiple accounts skip only orphaned ones."""
    rows = [
        {
            "id": 4,
            "account_id": 1,
            "short_code": "acct1_resp",
            "content": "Account 1 response",
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 5,
            "account_id": 2,
            "short_code": "acct2_resp",
            "content": "Account 2 response",
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 6,
            "account_id": 999,
            "short_code": "orphan_resp",
            "content": "Orphaned response",
            "created_at": None,
            "updated_at": None,
        },
    ]

    migrator, _ = _make_migrator(source_rows=rows, migrated={"accounts": {1, 2}})
    remapped_rows = []
    skipped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
            else:
                skipped_rows.append(row["id"])
        return MigrationResult(table=table_name, total_source=3, migrated=2, skipped=1)

    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.canned_responses_migrator.Table"):
            migrator.migrate()

    assert len(remapped_rows) == 2
    assert len(skipped_rows) == 1
    assert 6 in skipped_rows
