"""Unit tests for ContactInboxesMigrator (T029)."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

from src.migrators.base_migrator import MigrationResult
from src.migrators.contact_inboxes_migrator import ContactInboxesMigrator
from src.repository.migration_state_repository import MigrationStateRepository
from src.utils.id_remapper import IDRemapper


def _make_migrator(source_rows=None, migrated=None, dest_ci_pairs=None):
    """Build ContactInboxesMigrator with mocked engines.
    
    :param source_rows: Source contact_inboxes rows.
    :param migrated: Dict with 'contacts' and 'inboxes' migrated ID sets.
    :param dest_ci_pairs: List of (contact_id, inbox_id, ci_id) tuples already in DEST.
    """
    source_rows = source_rows or []
    migrated = migrated or {}
    dest_ci_pairs = dest_ci_pairs or []

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
    # For dedup pair lookup — return the existing pairs in DEST
    dest_conn.execute.return_value.fetchall.return_value = dest_ci_pairs
    dest_engine.connect.return_value = dest_conn

    state_repo = MagicMock(spec=MigrationStateRepository)
    state_repo.get_migrated_ids.side_effect = [
        migrated.get("contacts", {1}),
        migrated.get("inboxes", {1}),
        set(),  # already_migrated
    ]

    remapper = IDRemapper({"contact_inboxes": 50, "contacts": 100, "inboxes": 200})
    logger = logging.getLogger("test_ci")

    return (
        ContactInboxesMigrator(
            source_engine=source_engine,
            dest_engine=dest_engine,
            id_remapper=remapper,
            state_repo=state_repo,
            logger=logger,
        ),
        remapper,
    )


# ---------------------------------------------------------------------------
# T029-1 — Basic dedup: (contact_id, inbox_id) pair matching
# ---------------------------------------------------------------------------


def test_contact_inboxes_dedup_by_pair():
    """Dedup registers alias and logs; INSERT still occurs (handled by remap_fn constraint).
    
    NOTE: contact_inboxes registers alias for deduped pairs but does NOT filter in remap_fn.
    The actual constraint violation is left to database-level uniqueness.
    """
    ci_rows = [
        {
            "id": 10,
            "contact_id": 1,
            "inbox_id": 1,
            "role": "agent",
            "created_at": None,
            "updated_at": None,
        }
    ]

    # Source pair (1, 1) remaps to (101, 201) in DEST; that pair already exists with ci_id=999
    dest_ci_pairs = [(101, 201, 999)]

    migrator, remapper = _make_migrator(
        source_rows=ci_rows,
        migrated={"contacts": {1}, "inboxes": {1}},
        dest_ci_pairs=dest_ci_pairs,
    )

    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.contact_inboxes_migrator.Table"):
            migrator.migrate()

    # Row IS inserted (remap_fn doesn't check alias)
    assert len(remapped_rows) == 1
    # But alias WAS registered by dedup logic
    assert remapper.has_alias("contact_inboxes", 10)


# ---------------------------------------------------------------------------
# T029-2 — Non-dedup: unique pair inserted with remapped IDs
# ---------------------------------------------------------------------------


def test_contact_inboxes_unique_pair_inserted():
    """Unique (contact_id, inbox_id) pair is inserted with remapped IDs."""
    ci_rows = [
        {
            "id": 11,
            "contact_id": 1,
            "inbox_id": 1,
            "role": "agent",
            "created_at": None,
            "updated_at": None,
        }
    ]

    migrator, remapper = _make_migrator(
        source_rows=ci_rows,
        migrated={"contacts": {1}, "inboxes": {1}},
    )

    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.contact_inboxes_migrator.Table"):
            migrator.migrate()

    # Unique pair inserted
    assert len(remapped_rows) == 1
    # IDs remapped with offsets
    assert remapped_rows[0]["contact_id"] > 1
    assert remapped_rows[0]["inbox_id"] > 1


# ---------------------------------------------------------------------------
# T029-3 — Orphan contact_id: record skipped
# ---------------------------------------------------------------------------


def test_contact_inboxes_orphan_contact_id_skipped():
    """Unmigrated contact_id causes record skip."""
    ci_rows = [
        {
            "id": 12,
            "contact_id": 999,  # Not migrated
            "inbox_id": 1,
            "role": "agent",
            "created_at": None,
            "updated_at": None,
        }
    ]

    migrator, _ = _make_migrator(
        source_rows=ci_rows,
        migrated={"contacts": {1}, "inboxes": {1}},
    )

    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=0, skipped=1)

    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.contact_inboxes_migrator.Table"):
            migrator.migrate()

    # Orphan contact_id: skipped
    assert len(remapped_rows) == 0


# ---------------------------------------------------------------------------
# T029-4 — Orphan inbox_id: record skipped
# ---------------------------------------------------------------------------


def test_contact_inboxes_orphan_inbox_id_skipped():
    """Unmigrated inbox_id causes record skip."""
    ci_rows = [
        {
            "id": 13,
            "contact_id": 1,
            "inbox_id": 999,  # Not migrated
            "role": "agent",
            "created_at": None,
            "updated_at": None,
        }
    ]

    migrator, _ = _make_migrator(
        source_rows=ci_rows,
        migrated={"contacts": {1}, "inboxes": {1}},
    )

    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=0, skipped=1)

    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.contact_inboxes_migrator.Table"):
            migrator.migrate()

    # Orphan inbox_id: skipped
    assert len(remapped_rows) == 0


# ---------------------------------------------------------------------------
# T029-5 — Multiple rows with mixed dedup/insert outcomes
# ---------------------------------------------------------------------------


def test_contact_inboxes_batch_mixed_dedup_and_insert():
    """Batch with 3 rows: 1 deduped (alias registered), 2 unique (inserted)."""
    ci_rows = [
        {
            "id": 14,
            "contact_id": 1,
            "inbox_id": 1,
            "role": "agent",
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 15,
            "contact_id": 1,
            "inbox_id": 2,
            "role": "guest",
            "created_at": None,
            "updated_at": None,
        },
        {
            "id": 16,
            "contact_id": 2,
            "inbox_id": 1,
            "role": "agent",
            "created_at": None,
            "updated_at": None,
        },
    ]

    # Pair (1, 1) remaps to (101, 201) and already exists in DEST
    dest_ci_pairs = [(101, 201, 999)]

    migrator, _ = _make_migrator(
        source_rows=ci_rows,
        migrated={"contacts": {1, 2}, "inboxes": {1, 2}},
        dest_ci_pairs=dest_ci_pairs,
    )

    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=3, migrated=3, skipped=0)

    with patch.object(migrator, "_run_batches", side_effect=capture_batches):
        with patch("src.migrators.contact_inboxes_migrator.Table"):
            migrator.migrate()

    # All 3 rows inserted (dedup doesn't skip in remap_fn)
    assert len(remapped_rows) == 3
