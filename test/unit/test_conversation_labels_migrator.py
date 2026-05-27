"""Unit tests for ConversationLabelsMigrator (T022)."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

from src.migrators.base_migrator import MigrationResult
from src.migrators.conversation_labels_migrator import ConversationLabelsMigrator
from src.repository.migration_state_repository import MigrationStateRepository
from src.utils.id_remapper import IDRemapper


def _make_migrator(source_rows=None, migrated=None, tag_id_map=None):
    """Build ConversationLabelsMigrator with mocked engines."""
    source_rows = source_rows or []
    migrated = migrated or {}
    tag_id_map = tag_id_map or {}

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
        migrated.get("conversations", {1}),
        migrated.get("users", {1}),
        set(),  # already_migrated
    ]

    remapper = IDRemapper({"conversation_labels": 10000, "conversations": 100, "users": 50})
    logger = logging.getLogger("test_cl")

    return (
        ConversationLabelsMigrator(
            source_engine=source_engine,
            dest_engine=dest_engine,
            id_remapper=remapper,
            state_repo=state_repo,
            logger=logger,
        ),
        remapper,
        tag_id_map,
    )


# ---------------------------------------------------------------------------
# T022-1 — orphan conversation_id skipped
# ---------------------------------------------------------------------------


def test_conversation_labels_orphan_conversation_id_skipped():
    """Tagging with unmigrated conversation_id is skipped."""
    rows = [
        {
            "id": 1,
            "tag_id": 5,
            "taggable_type": "Conversation",
            "taggable_id": 999,
            "context": "labels",
            "tagger_type": "User",
            "tagger_id": 1,
            "created_at": None,
        }
    ]

    migrator, _, tag_id_map = _make_migrator(
        source_rows=rows,
        migrated={"conversations": {1, 2}, "users": {1}},
        tag_id_map={5: 50},
    )

    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=0, skipped=1)

    with patch.object(migrator, "_migrate_tags", return_value=tag_id_map):
        with patch.object(migrator, "_run_batches", side_effect=capture_batches):
            with patch("src.migrators.conversation_labels_migrator.Table"):
                migrator.migrate()

    assert len(remapped_rows) == 0


# ---------------------------------------------------------------------------
# T022-2 — unmapped tag_id skipped
# ---------------------------------------------------------------------------


def test_conversation_labels_unmapped_tag_id_skipped():
    """Tagging with unmapped tag_id is skipped."""
    rows = [
        {
            "id": 2,
            "tag_id": 999,
            "taggable_type": "Conversation",
            "taggable_id": 1,
            "context": "labels",
            "tagger_type": "User",
            "tagger_id": 1,
            "created_at": None,
        }
    ]

    migrator, _, tag_id_map = _make_migrator(
        source_rows=rows,
        migrated={"conversations": {1}, "users": {1}},
        tag_id_map={5: 50},  # tag_id=999 not in map
    )

    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=0, skipped=1)

    with patch.object(migrator, "_migrate_tags", return_value=tag_id_map):
        with patch.object(migrator, "_run_batches", side_effect=capture_batches):
            with patch("src.migrators.conversation_labels_migrator.Table"):
                migrator.migrate()

    assert len(remapped_rows) == 0


# ---------------------------------------------------------------------------
# T022-3 — ID remapping and tag_id substitution
# ---------------------------------------------------------------------------


def test_conversation_labels_id_remapped_tag_id_substituted():
    """Tagging ID, conversation_id, and tag_id are all remapped."""
    rows = [
        {
            "id": 3,
            "tag_id": 5,
            "taggable_type": "Conversation",
            "taggable_id": 1,
            "context": "labels",
            "tagger_type": "User",
            "tagger_id": 1,
            "created_at": None,
        }
    ]

    migrator, remapper, tag_id_map = _make_migrator(
        source_rows=rows,
        migrated={"conversations": {1}, "users": {1}},
        tag_id_map={5: 50},
    )

    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    with patch.object(migrator, "_migrate_tags", return_value=tag_id_map):
        with patch.object(migrator, "_run_batches", side_effect=capture_batches):
            with patch("src.migrators.conversation_labels_migrator.Table"):
                migrator.migrate()

    assert len(remapped_rows) == 1
    assert remapped_rows[0]["id"] == 3 + 10000
    assert remapped_rows[0]["tag_id"] == 50  # from tag_id_map
    assert remapped_rows[0]["taggable_id"] == 1 + 100


# ---------------------------------------------------------------------------
# T022-4 — orphan tagger_id nulled when tagger_type=User
# ---------------------------------------------------------------------------


def test_conversation_labels_orphan_tagger_id_nulled():
    """Unmigrated tagger_id is nulled (tagger is informational only)."""
    rows = [
        {
            "id": 4,
            "tag_id": 5,
            "taggable_type": "Conversation",
            "taggable_id": 1,
            "context": "labels",
            "tagger_type": "User",
            "tagger_id": 999,
            "created_at": None,
        }
    ]

    migrator, _, tag_id_map = _make_migrator(
        source_rows=rows,
        migrated={"conversations": {1}, "users": {1}},  # user_id=999 NOT migrated
        tag_id_map={5: 50},
    )

    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    with patch.object(migrator, "_migrate_tags", return_value=tag_id_map):
        with patch.object(migrator, "_run_batches", side_effect=capture_batches):
            with patch("src.migrators.conversation_labels_migrator.Table"):
                migrator.migrate()

    assert len(remapped_rows) == 1
    assert remapped_rows[0]["tagger_id"] is None
    assert remapped_rows[0]["tagger_type"] is None


# ---------------------------------------------------------------------------
# T022-5 — non-User tagger unchanged
# ---------------------------------------------------------------------------


def test_conversation_labels_non_user_tagger_unchanged():
    """Tagging with tagger_type != 'User' passes through unchanged."""
    rows = [
        {
            "id": 5,
            "tag_id": 5,
            "taggable_type": "Conversation",
            "taggable_id": 1,
            "context": "labels",
            "tagger_type": "AgentBot",
            "tagger_id": 999,
            "created_at": None,
        }
    ]

    migrator, _, tag_id_map = _make_migrator(
        source_rows=rows,
        migrated={"conversations": {1}, "users": {}},
        tag_id_map={5: 50},
    )

    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    with patch.object(migrator, "_migrate_tags", return_value=tag_id_map):
        with patch.object(migrator, "_run_batches", side_effect=capture_batches):
            with patch("src.migrators.conversation_labels_migrator.Table"):
                migrator.migrate()

    assert len(remapped_rows) == 1
    assert remapped_rows[0]["tagger_type"] == "AgentBot"
    assert remapped_rows[0]["tagger_id"] == 999  # unchanged
