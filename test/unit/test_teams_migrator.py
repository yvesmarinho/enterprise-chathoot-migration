"""Unit tests for TeamsMigrator (T028)."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

from src.migrators.base_migrator import MigrationResult
from src.migrators.teams_migrator import TeamsMigrator
from src.repository.migration_state_repository import MigrationStateRepository
from src.utils.id_remapper import IDRemapper


def _make_migrator(source_rows=None, migrated_accounts=None):
    source_rows = source_rows or []
    migrated_accounts = migrated_accounts if migrated_accounts is not None else {1}

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
    state_repo.get_migrated_ids.side_effect = [migrated_accounts, set()]

    remapper = IDRemapper({"teams": 22, "accounts": 20})
    logger = logging.getLogger("test_teams")

    return TeamsMigrator(
        source_engine=source_engine,
        dest_engine=dest_engine,
        id_remapper=remapper,
        state_repo=state_repo,
        logger=logger,
    )


# ---------------------------------------------------------------------------
# T028-1 — account_id is remapped correctly
# ---------------------------------------------------------------------------


def test_teams_account_id_remapped():
    """account_id is remapped with offset_accounts during migration."""
    rows = [
        {
            "id": 2,
            "account_id": 1,
            "name": "Support Team",
            "created_at": None,
            "updated_at": None,
        }
    ]
    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    migrator = _make_migrator(source_rows=rows, migrated_accounts={1})
    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.teams_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert remapped_rows[0]["account_id"] == 21  # 1 + 20
    assert remapped_rows[0]["id"] == 24  # 2 + 22


# ---------------------------------------------------------------------------
# T028-2 — 3 source records produce 1 batch (< 500)
# ---------------------------------------------------------------------------


def test_teams_small_volume_single_batch():
    """3 teams produce exactly 1 batch (all fit under batch size 500)."""
    rows = [
        {
            "id": i,
            "account_id": 1,
            "name": f"Team {i}",
            "created_at": None,
            "updated_at": None,
        }
        for i in range(1, 4)
    ]
    batches_processed = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        batches_processed.append(len(source_rows))
        return MigrationResult(
            table=table_name,
            total_source=len(source_rows),
            migrated=len(source_rows),
            skipped=0,
        )

    migrator = _make_migrator(source_rows=rows, migrated_accounts={1})
    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.teams_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert batches_processed == [3]  # all 3 rows passed to _run_batches at once


# ---------------------------------------------------------------------------
# T028-3 — Orphan account_id causes skip
# ---------------------------------------------------------------------------


def test_teams_orphan_account_id_skipped():
    """Team with unmigrated account_id is skipped."""
    rows = [
        {
            "id": 1,
            "account_id": 999,
            "name": "OrphanTeam",
            "created_at": None,
            "updated_at": None,
        }
    ]
    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=0, skipped=1)

    migrator = _make_migrator(source_rows=rows, migrated_accounts={1, 2, 3})
    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.teams_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert len(remapped_rows) == 0


# ---------------------------------------------------------------------------
# T028-4 — Team name field copied verbatim
# ---------------------------------------------------------------------------


def test_teams_name_field_unchanged():
    """Team name field is copied as-is without modification."""
    team_name = "Sales & Support"
    rows = [
        {
            "id": 5,
            "account_id": 1,
            "name": team_name,
            "created_at": None,
            "updated_at": None,
        }
    ]
    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    migrator = _make_migrator(source_rows=rows)
    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.teams_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert remapped_rows[0]["name"] == team_name


# ---------------------------------------------------------------------------
# T028-5 — Multiple account_ids with partial success
# ---------------------------------------------------------------------------


def test_teams_multiple_accounts_mixed_success():
    """Teams from multiple accounts with some orphaned."""
    rows = [
        {
            "id": 1,
            "account_id": 1,
            "name": "Team A",
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 2,
            "account_id": 2,
            "name": "Team B",
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 3,
            "account_id": 999,
            "name": "Orphan Team",
            "created_at": None,
            "updated_at": None,
        },
    ]
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

    migrator = _make_migrator(source_rows=rows, migrated_accounts={1, 2})
    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.teams_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert len(remapped_rows) == 2
    assert 999 not in [r["account_id"] for r in remapped_rows]
    assert skipped_rows == [3]


# ---------------------------------------------------------------------------
# T028-6 — Empty source returns zero migration
# ---------------------------------------------------------------------------


def test_teams_empty_source_no_migration():
    """Empty source rows returns MigrationResult(0 migrated, 0 skipped)."""
    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=0, migrated=0, skipped=0)

    migrator = _make_migrator(source_rows=[], migrated_accounts={1})
    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.teams_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            result = migrator.migrate()

    assert len(remapped_rows) == 0
    assert result.migrated == 0
    assert result.skipped == 0


# ---------------------------------------------------------------------------
# T028-7 — ID remapping with offset_teams
# ---------------------------------------------------------------------------


def test_teams_id_remapping_offset():
    """Team ID remapped using offset_teams (22)."""
    rows = [
        {
            "id": 100,
            "account_id": 1,
            "name": "Remote Team",
            "created_at": None,
            "updated_at": None,
        }
    ]
    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    migrator = _make_migrator(source_rows=rows, migrated_accounts={1})
    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.teams_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    # ID should be remapped: 100 + 22 (offset_teams)
    assert len(remapped_rows) == 1
    assert remapped_rows[0]["id"] == 100 + 22


# ---------------------------------------------------------------------------
# T028-8 — Team name with special characters preserved
# ---------------------------------------------------------------------------


def test_teams_name_special_chars_preserved():
    """Team name with special characters (accents, symbols) preserved."""
    special_name = "Équipe d'Assistance & Support™"
    rows = [
        {
            "id": 10,
            "account_id": 1,
            "name": special_name,
            "created_at": None,
            "updated_at": None,
        }
    ]
    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    migrator = _make_migrator(source_rows=rows, migrated_accounts={1})
    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.teams_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert remapped_rows[0]["name"] == special_name


# ---------------------------------------------------------------------------
# T028-9 — Multiple teams same account all migrated
# ---------------------------------------------------------------------------


def test_teams_multiple_teams_same_account():
    """Multiple teams from same account all migrated successfully."""
    rows = [
        {
            "id": 11,
            "account_id": 1,
            "name": "Team Sales",
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 12,
            "account_id": 1,
            "name": "Team Support",
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 13,
            "account_id": 1,
            "name": "Team Dev",
            "created_at": None,
            "updated_at": None,
        },
    ]
    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=3, migrated=3, skipped=0)

    migrator = _make_migrator(source_rows=rows, migrated_accounts={1})
    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.teams_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert len(remapped_rows) == 3
    assert all(r["account_id"] == 21 for r in remapped_rows)
    assert [r["id"] for r in remapped_rows] == [33, 34, 35]  # 11+22, 12+22, 13+22


# ---------------------------------------------------------------------------
# T028-10 — Empty source no-op
# ---------------------------------------------------------------------------


def test_teams_empty_source_no_migration():
    """Empty source returns MigrationResult(0 migrated, 0 skipped)."""

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        return MigrationResult(table=table_name, total_source=0, migrated=0, skipped=0)

    migrator = _make_migrator(source_rows=[])
    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.teams_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            result = migrator.migrate()

    assert result.total_source == 0
    assert result.migrated == 0
    assert result.skipped == 0


# ---------------------------------------------------------------------------
# T028-11 — ID remapping with offset_teams
# ---------------------------------------------------------------------------


def test_teams_id_remapping_offset():
    """Team ID is remapped using offset_teams (22)."""
    rows = [
        {
            "id": 100,
            "account_id": 1,
            "name": "Offset Test Team",
            "created_at": None,
            "updated_at": None,
        }
    ]
    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    migrator = _make_migrator(source_rows=rows, migrated_accounts={1})
    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.teams_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert len(remapped_rows) == 1
    assert remapped_rows[0]["id"] == 100 + 22  # offset_teams = 22


# ---------------------------------------------------------------------------
# T028-12 — Description field preserved (if present)
# ---------------------------------------------------------------------------


def test_teams_description_field_preserved():
    """Description field is copied as-is when present."""
    rows = [
        {
            "id": 14,
            "account_id": 1,
            "name": "Described Team",
            "description": "This team handles customer support",
            "created_at": None,
            "updated_at": None,
        }
    ]
    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    migrator = _make_migrator(source_rows=rows, migrated_accounts={1})
    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.teams_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert len(remapped_rows) == 1
    assert remapped_rows[0].get("description") == "This team handles customer support"


# ---------------------------------------------------------------------------
# T028-13 — Orphan account_id (not in migrated set)
# ---------------------------------------------------------------------------


def test_teams_orphan_account_skipped():
    """Team with account_id not in migrated accounts is skipped."""
    rows = [
        {
            "id": 15,
            "account_id": 999,
            "name": "Orphan Team",
            "created_at": None,
            "updated_at": None,
        }
    ]
    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=0, skipped=1)

    migrator = _make_migrator(source_rows=rows, migrated_accounts={1, 2})
    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.teams_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert len(remapped_rows) == 0


# ---------------------------------------------------------------------------
# T028-14 — Multiple teams mixed valid and orphan
# ---------------------------------------------------------------------------


def test_teams_multiple_mixed_orphan_valid():
    """Multiple teams: some valid, some orphan, only valid ones migrated."""
    rows = [
        {
            "id": 16,
            "account_id": 1,
            "name": "Valid Team 1",
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 17,
            "account_id": 999,
            "name": "Orphan Team",
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 18,
            "account_id": 2,
            "name": "Valid Team 2",
            "created_at": None,
            "updated_at": None,
        },
    ]
    remapped_rows = []
    skipped_ids = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
            else:
                skipped_ids.append(row["id"])
        return MigrationResult(table=table_name, total_source=3, migrated=2, skipped=1)

    migrator = _make_migrator(source_rows=rows, migrated_accounts={1, 2})
    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.teams_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert len(remapped_rows) == 2
    assert len(skipped_ids) == 1
    assert 17 in skipped_ids  # orphan account 999
