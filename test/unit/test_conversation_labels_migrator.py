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


# ---------------------------------------------------------------------------
# T022-6 — _migrate_tags with new tag (insert)
# ---------------------------------------------------------------------------


def test_conversation_labels_migrate_tags_inserts_new_tag():
    """_migrate_tags inserts new tags and returns correct mapping."""
    source_engine = MagicMock()
    dest_engine = MagicMock()

    # Fetch SOURCE tags referenced by conversation label taggings
    src_conn = MagicMock()
    src_conn.__enter__ = MagicMock(return_value=src_conn)
    src_conn.__exit__ = MagicMock(return_value=False)
    src_conn.execute.return_value.mappings.return_value.all.return_value = [
        {"id": 10, "name": "urgent"}
    ]
    source_engine.connect.return_value = src_conn

    dest_conn = MagicMock()
    dest_conn.__enter__ = MagicMock(return_value=dest_conn)
    dest_conn.__exit__ = MagicMock(return_value=False)

    # Fetch DEST existing tags (empty initially)
    def execute_side_effect(stmt, *args, **kwargs):
        result = MagicMock()
        result.scalar.return_value = 100  # nextval('tags_id_seq')
        result.mappings.return_value.all.return_value = []
        return result

    dest_conn.execute.side_effect = execute_side_effect
    dest_conn.begin.return_value.__enter__ = MagicMock(return_value=None)
    dest_conn.begin.return_value.__exit__ = MagicMock(return_value=False)
    dest_engine.connect.return_value = dest_conn

    state_repo = MagicMock(spec=MigrationStateRepository)
    remapper = IDRemapper({})
    logger = logging.getLogger("test_tags")

    migrator = ConversationLabelsMigrator(
        source_engine=source_engine,
        dest_engine=dest_engine,
        id_remapper=remapper,
        state_repo=state_repo,
        logger=logger,
    )

    with patch("src.migrators.conversation_labels_migrator.ensure_public_table_exists"):
        with patch("src.migrators.conversation_labels_migrator.Table"):
            tag_id_map = migrator._migrate_tags()

    assert tag_id_map == {10: 100}


# ---------------------------------------------------------------------------
# T022-7 — _migrate_tags with existing tag (reuse)
# ---------------------------------------------------------------------------


def test_conversation_labels_migrate_tags_reuses_existing_tag():
    """_migrate_tags reuses existing DEST tags by name (case-insensitive)."""
    source_engine = MagicMock()
    dest_engine = MagicMock()

    # Fetch SOURCE tags
    src_conn = MagicMock()
    src_conn.__enter__ = MagicMock(return_value=src_conn)
    src_conn.__exit__ = MagicMock(return_value=False)
    src_conn.execute.return_value.mappings.return_value.all.return_value = [
        {"id": 10, "name": "urgent"}
    ]
    source_engine.connect.return_value = src_conn

    dest_conn = MagicMock()
    dest_conn.__enter__ = MagicMock(return_value=dest_conn)
    dest_conn.__exit__ = MagicMock(return_value=False)

    # Fetch DEST existing tags (urgent already exists as id=50)
    def execute_side_effect(stmt, *args, **kwargs):
        result = MagicMock()
        result.mappings.return_value.all.return_value = [{"id": 50, "name": "urgent"}]
        return result

    dest_conn.execute.side_effect = execute_side_effect
    dest_engine.connect.return_value = dest_conn

    state_repo = MagicMock(spec=MigrationStateRepository)
    remapper = IDRemapper({})
    logger = logging.getLogger("test_tags")

    migrator = ConversationLabelsMigrator(
        source_engine=source_engine,
        dest_engine=dest_engine,
        id_remapper=remapper,
        state_repo=state_repo,
        logger=logger,
    )

    with patch("src.migrators.conversation_labels_migrator.ensure_public_table_exists"):
        with patch("src.migrators.conversation_labels_migrator.Table"):
            tag_id_map = migrator._migrate_tags()

    assert tag_id_map == {10: 50}


# ---------------------------------------------------------------------------
# T022-8 — _migrate_tags empty (no tags)
# ---------------------------------------------------------------------------


def test_conversation_labels_migrate_tags_empty():
    """_migrate_tags returns empty dict when no tags referenced."""
    source_engine = MagicMock()
    dest_engine = MagicMock()

    # No SOURCE tags referenced by conversation labels
    src_conn = MagicMock()
    src_conn.__enter__ = MagicMock(return_value=src_conn)
    src_conn.__exit__ = MagicMock(return_value=False)
    src_conn.execute.return_value.mappings.return_value.all.return_value = []
    source_engine.connect.return_value = src_conn

    state_repo = MagicMock(spec=MigrationStateRepository)
    remapper = IDRemapper({})
    logger = logging.getLogger("test_tags")

    migrator = ConversationLabelsMigrator(
        source_engine=source_engine,
        dest_engine=dest_engine,
        id_remapper=remapper,
        state_repo=state_repo,
        logger=logger,
    )

    tag_id_map = migrator._migrate_tags()

    assert tag_id_map == {}


# ---------------------------------------------------------------------------
# T022-9 — Empty source rows no-op
# ---------------------------------------------------------------------------


def test_conversation_labels_empty_source_no_op():
    """Empty source returns MigrationResult with 0 migrated/skipped."""
    migrator, _, tag_id_map = _make_migrator(
        source_rows=[],
        migrated={"conversations": {1}, "users": {1}},
        tag_id_map={},
    )

    with patch.object(migrator, "_migrate_tags", return_value=tag_id_map):
        with patch("src.migrators.conversation_labels_migrator.Table"):
            result = migrator.migrate()

    assert result.total_source == 0
    assert result.migrated == 0
    assert result.skipped == 0


# ---------------------------------------------------------------------------
# T022-10 — Multiple conversation_ids all valid
# ---------------------------------------------------------------------------


def test_conversation_labels_multiple_conversations_valid():
    """Multiple conversation labels all with valid conversation_ids are migrated."""
    rows = [
        {
            "id": 100,
            "tag_id": 5,
            "taggable_type": "Conversation",
            "taggable_id": 1,
            "context": "labels",
            "tagger_type": "User",
            "tagger_id": 1,
            "created_at": None,
        },
        {
            "id": 101,
            "tag_id": 6,
            "taggable_type": "Conversation",
            "taggable_id": 2,
            "context": "labels",
            "tagger_type": "User",
            "tagger_id": 1,
            "created_at": None,
        },
        {
            "id": 102,
            "tag_id": 7,
            "taggable_type": "Conversation",
            "taggable_id": 1,
            "context": "labels",
            "tagger_type": "User",
            "tagger_id": 1,
            "created_at": None,
        },
    ]

    migrator, remapper, tag_id_map = _make_migrator(
        source_rows=rows,
        migrated={"conversations": {1, 2}, "users": {1}},
        tag_id_map={5: 50, 6: 60, 7: 70},
    )

    remapped_rows = []

    def capture_batches(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=3, migrated=3, skipped=0)

    with patch.object(migrator, "_migrate_tags", return_value=tag_id_map):
        with patch.object(migrator, "_run_batches", side_effect=capture_batches):
            with patch("src.migrators.conversation_labels_migrator.Table"):
                migrator.migrate()

    assert len(remapped_rows) == 3
    assert remapped_rows[0]["taggable_id"] == 1 + 100
    assert remapped_rows[1]["taggable_id"] == 2 + 100
    assert remapped_rows[2]["taggable_id"] == 1 + 100


# ---------------------------------------------------------------------------
# T022-11 — Mixed valid and orphan conversation_ids
# ---------------------------------------------------------------------------


def test_conversation_labels_mixed_valid_orphan():
    """Multiple tags: some with valid conversation_ids, some orphan (skipped)."""
    rows = [
        {
            "id": 200,
            "tag_id": 5,
            "taggable_type": "Conversation",
            "taggable_id": 1,
            "context": "labels",
            "tagger_type": "User",
            "tagger_id": 1,
            "created_at": None,
        },
        {
            "id": 201,
            "tag_id": 6,
            "taggable_type": "Conversation",
            "taggable_id": 999,
            "context": "labels",
            "tagger_type": "User",
            "tagger_id": 1,
            "created_at": None,
        },
        {
            "id": 202,
            "tag_id": 7,
            "taggable_type": "Conversation",
            "taggable_id": 2,
            "context": "labels",
            "tagger_type": "User",
            "tagger_id": 1,
            "created_at": None,
        },
    ]

    migrator, remapper, tag_id_map = _make_migrator(
        source_rows=rows,
        migrated={"conversations": {1, 2}, "users": {1}},
        tag_id_map={5: 50, 6: 60, 7: 70},
    )

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

    with patch.object(migrator, "_migrate_tags", return_value=tag_id_map):
        with patch.object(migrator, "_run_batches", side_effect=capture_batches):
            with patch("src.migrators.conversation_labels_migrator.Table"):
                migrator.migrate()

    assert len(remapped_rows) == 2
    assert len(skipped_ids) == 1
    assert 201 in skipped_ids
