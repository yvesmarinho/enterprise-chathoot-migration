"""Unit tests for TeamMembersMigrator (T035)."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

from src.migrators.base_migrator import MigrationResult
from src.migrators.team_members_migrator import TeamMembersMigrator
from src.repository.migration_state_repository import MigrationStateRepository
from src.utils.id_remapper import IDRemapper


def _make_migrator(source_rows=None, migrated=None):
    """Build TeamMembersMigrator with mocked engines."""
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
        migrated.get("teams", {1}),
        migrated.get("users", {1}),
        set(),  # already_migrated
    ]

    remapper = IDRemapper({"team_members": 25, "teams": 80, "users": 150})
    logger = logging.getLogger("test_tm")

    return (
        TeamMembersMigrator(
            source_engine=source_engine,
            dest_engine=dest_engine,
            id_remapper=remapper,
            state_repo=state_repo,
            logger=logger,
        ),
        remapper,
    )


def test_team_members_basic_migration():
    """Basic team_member inserted with remapped FKs."""
    rows = [
        {
            "id": 1,
            "team_id": 1,
            "user_id": 1,
            "created_at": None,
            "updated_at": None,
        }
    ]

    migrator, _ = _make_migrator(
        source_rows=rows,
        migrated={"teams": {1}, "users": {1}},
    )

    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.team_members_migrator.Table"):
            migrator.migrate()

    assert len(remapped_rows) == 1


def test_team_members_orphan_team_id_skipped():
    """Unmigrated team_id causes skip."""
    rows = [
        {
            "id": 2,
            "team_id": 999,
            "user_id": 1,
            "created_at": None,
            "updated_at": None,
        }
    ]

    migrator, _ = _make_migrator(
        source_rows=rows,
        migrated={"teams": {1}, "users": {1}},
    )

    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=0, skipped=1)

    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.team_members_migrator.Table"):
            migrator.migrate()

    assert len(remapped_rows) == 0


# ---------------------------------------------------------------------------
# T025-3 — member_id and user_id remapped independently
# ---------------------------------------------------------------------------


def test_team_members_id_remapped():
    """member_id and user_id both remapped with correct offsets."""
    rows = [
        {
            "id": 3,
            "team_id": 1,
            "user_id": 1,
            "created_at": None,
            "updated_at": None,
        }
    ]

    migrator, remapper = _make_migrator(
        source_rows=rows,
        migrated={"teams": {1}, "users": {1}},
    )

    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.team_members_migrator.Table"):
            migrator.migrate()

    assert len(remapped_rows) == 1
    # member_id: source 3 + offset 25 = 28; user_id: source 1 + offset 150 = 151
    assert remapped_rows[0]["id"] == 28
    assert remapped_rows[0]["user_id"] == 151


# ---------------------------------------------------------------------------
# T025-4 — orphan user_id skipped
# ---------------------------------------------------------------------------


def test_team_members_orphan_user_id_skipped():
    """Unmigrated user_id causes skip."""
    rows = [
        {
            "id": 4,
            "team_id": 1,
            "user_id": 999,
            "created_at": None,
            "updated_at": None,
        }
    ]

    migrator, _ = _make_migrator(
        source_rows=rows,
        migrated={"teams": {1}, "users": {1}},  # user_id=999 not in migrated
    )

    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=0, skipped=1)

    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.team_members_migrator.Table"):
            migrator.migrate()

    assert len(remapped_rows) == 0


# ---------------------------------------------------------------------------
# T025-5 — Mixed team and user ids with partial skip
# ---------------------------------------------------------------------------


def test_team_members_mixed_teams_users_partial_skip():
    """Team members from multiple teams/users skip only orphaned ones."""
    rows = [
        {
            "id": 5,
            "team_id": 1,
            "user_id": 1,
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 6,
            "team_id": 1,
            "user_id": 2,
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 7,
            "team_id": 1,
            "user_id": 999,
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 8,
            "team_id": 999,
            "user_id": 1,
            "created_at": None,
            "updated_at": None,
        },
    ]

    migrator, _ = _make_migrator(
        source_rows=rows,
        migrated={"teams": {1}, "users": {1, 2}},
    )

    remapped_rows = []
    skipped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
            else:
                skipped_rows.append(row["id"])
        return MigrationResult(table=table_name, total_source=4, migrated=2, skipped=2)

    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.team_members_migrator.Table"):
            migrator.migrate()

    assert len(remapped_rows) == 2
    assert len(skipped_rows) == 2
    assert 7 in skipped_rows  # orphan user_id
    assert 8 in skipped_rows  # orphan team_id


# ---------------------------------------------------------------------------
# T031-6 — Empty source no-op
# ---------------------------------------------------------------------------


def test_team_members_empty_source_no_migration():
    """Empty source returns MigrationResult(0 migrated, 0 skipped)."""
    migrator, _ = _make_migrator(source_rows=[])

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        return MigrationResult(table=table_name, total_source=0, migrated=0, skipped=0)

    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.team_members_migrator.Table"):
            result = migrator.migrate()

    assert result.total_source == 0
    assert result.migrated == 0
    assert result.skipped == 0


# ---------------------------------------------------------------------------
# T031-7 — ID remapping with offset
# ---------------------------------------------------------------------------


def test_team_members_id_remapping_offset():
    """ID is remapped with offset_team_members."""
    rows = [
        {
            "id": 50,
            "team_id": 2,
            "user_id": 3,
            "created_at": None,
            "updated_at": None,
        }
    ]

    migrator, _ = _make_migrator(
        source_rows=rows,
        migrated={"teams": {2}, "users": {3}},
    )

    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.team_members_migrator.Table"):
            migrator.migrate()

    assert len(remapped_rows) == 1
    assert remapped_rows[0]["id"] == 50 + 25  # offset_team_members = 25
    assert remapped_rows[0]["team_id"] == 2 + 80  # offset_teams = 80
    assert remapped_rows[0]["user_id"] == 3 + 150  # offset_users = 150


# ---------------------------------------------------------------------------
# T031-8 — Multiple members same team
# ---------------------------------------------------------------------------


def test_team_members_multiple_same_team():
    """Multiple members in same team all migrated."""
    rows = [
        {
            "id": 9,
            "team_id": 3,
            "user_id": 4,
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 10,
            "team_id": 3,
            "user_id": 5,
            "created_at": None,
            "updated_at": None,
        },
    ]

    migrator, _ = _make_migrator(
        source_rows=rows,
        migrated={"teams": {3}, "users": {4, 5}},
    )

    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=2, migrated=2, skipped=0)

    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.team_members_migrator.Table"):
            migrator.migrate()

    assert len(remapped_rows) == 2


# ---------------------------------------------------------------------------
# T031-9 — Both FKs unmigrated (double orphan)
# ---------------------------------------------------------------------------


def test_team_members_both_fks_unmigrated_skipped():
    """Team member with both unmigrated FKs is skipped."""
    rows = [
        {
            "id": 11,
            "team_id": 999,
            "user_id": 999,
            "created_at": None,
            "updated_at": None,
        }
    ]

    migrator, _ = _make_migrator(
        source_rows=rows,
        migrated={"teams": {1}, "users": {1}},
    )

    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=0, skipped=1)

    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.team_members_migrator.Table"):
            migrator.migrate()

    assert len(remapped_rows) == 0


# ---------------------------------------------------------------------------
# POC Helper Methods — _table_name, _fetch_all_source_rows, _classify_row_poc
# ---------------------------------------------------------------------------


def test_team_members_table_name():
    """_table_name() returns 'team_members'."""
    migrator, _ = _make_migrator()
    assert migrator._table_name() == "team_members"


def test_team_members_fetch_all_source_rows():
    """_fetch_all_source_rows() returns all source rows."""
    rows = [
        {"id": 1, "team_id": 10, "user_id": 100},
        {"id": 2, "team_id": 11, "user_id": 101},
    ]
    migrator, _ = _make_migrator(source_rows=rows)

    with patch("src.migrators.team_members_migrator.Table"):
        result = migrator._fetch_all_source_rows()

    assert len(result) == 2
    assert result[0]["team_id"] == 10
    assert result[1]["user_id"] == 101


def test_team_members_classify_row_poc_clean():
    """_classify_row_poc returns WOULD_MIGRATE for clean row."""
    from src.reports.poc_reporter import Outcome

    migrator, _ = _make_migrator()
    row = {"id": 1, "team_id": 1, "user_id": 1}
    migrated_sets = {"teams": {1}, "users": {1}}

    outcome, reason = migrator._classify_row_poc(row, migrated_sets)

    assert outcome == Outcome.WOULD_MIGRATE
    assert reason == "clean"
