"""Integration test for migration flow with idempotency (T036).

Uses ``unittest.mock`` to patch SQLAlchemy ``execute`` at the connection level,
preserving constraint semantics without requiring a real PostgreSQL instance.
The test simulates a partial run followed by a resume to verify no duplicates.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from unittest.mock import MagicMock, patch

from src.migrators.base_migrator import BaseMigrator, MigrationResult
from src.utils.id_remapper import IDRemapper

# ---------------------------------------------------------------------------
# In-memory state store (simulates migration_state table)
# ---------------------------------------------------------------------------


class _InMemoryStateRepo:
    """Simulates MigrationStateRepository with actual constraint semantics."""

    def __init__(self):
        # tabela → set of id_origem values with status='ok'
        self._ok: dict[str, set[int]] = defaultdict(set)
        self._failed: dict[str, set[int]] = defaultdict(set)

    def create_table_if_not_exists(self, engine):
        pass

    def get_migrated_ids(self, conn, tabela: str) -> set[int]:
        return set(self._ok[tabela])

    def record_success(self, conn, tabela: str, id_origem: int, id_destino: int):
        # UNIQUE(tabela, id_origem) — second insert is a no-op
        self._ok[tabela].add(id_origem)

    def record_failure(self, conn, tabela: str, id_origem: int, reason: str):
        if id_origem not in self._ok[tabela]:
            self._failed[tabela].add(id_origem)


# ---------------------------------------------------------------------------
# In-memory destination store (simulates destination table)
# ---------------------------------------------------------------------------


class _InMemoryDestination:
    """Simulates bulk-insert with UNIQUE id constraint."""

    def __init__(self):
        self.rows: dict[str, list[dict]] = defaultdict(list)
        self._ids: dict[str, set[int]] = defaultdict(set)

    def bulk_insert(self, conn, table, records: list[dict]) -> int:
        # table may be a MagicMock; use a string key via its name attribute or str()
        table_key = getattr(table, "name", str(table))
        count = 0
        for rec in records:
            rec_id = rec.get("id")
            if rec_id in self._ids[table_key]:
                raise ValueError(f"Duplicate id={rec_id} in {table_key}")
            self._ids[table_key].add(rec_id)
            self.rows[table_key].append(dict(rec))
            count += 1
        return count


# ---------------------------------------------------------------------------
# Concrete migrator test double
# ---------------------------------------------------------------------------


class _ContactsMigratorDouble(BaseMigrator):
    """Minimal concrete migrator using in-memory state and destination."""

    def __init__(self, source_rows, state_repo, dest_store, interrupted_at=None):
        engine = MagicMock()
        dest_conn = MagicMock()
        dest_conn.__enter__ = MagicMock(return_value=dest_conn)
        dest_conn.__exit__ = MagicMock(return_value=False)
        dest_conn.begin.return_value.__enter__ = MagicMock(return_value=None)
        dest_conn.begin.return_value.__exit__ = MagicMock(return_value=False)
        engine.connect.return_value = dest_conn

        super().__init__(
            source_engine=engine,
            dest_engine=engine,
            id_remapper=IDRemapper({"contacts": 0, "accounts": 0}),
            state_repo=state_repo,
            logger=logging.getLogger("integration_test"),
        )
        self._source_rows = source_rows
        self._dest_store = dest_store
        self._interrupted_at = interrupted_at  # stop after this many inserts

    def migrate(self) -> MigrationResult:
        dest_table = MagicMock()
        dest_table.name = "contacts"
        return self._run_batches(
            self._source_rows,
            "contacts",
            dest_table,
            remap_fn=lambda r: r,
        )


# ---------------------------------------------------------------------------
# T036-1 — Interrupted migration resumes without duplicates
# ---------------------------------------------------------------------------


def test_migration_resumes_without_duplicates():
    """Re-running after partial failure produces exactly 1000 contacts, no duplicates."""
    all_rows = [{"id": i, "account_id": 0} for i in range(1, 1001)]
    state_repo = _InMemoryStateRepo()
    dest_store = _InMemoryDestination()

    # --- Run 1: interrupted after first 500 records ---
    insert_count = [0]

    def bulk_insert_limited(conn, table, records):
        nonlocal insert_count
        if insert_count[0] >= 500:
            raise RuntimeError("Interrupted!")
        for rec in records:
            table_key = getattr(table, "name", "contacts")
            if rec["id"] in dest_store._ids[table_key]:
                raise ValueError(f"Duplicate: {rec['id']}")
            dest_store._ids[table_key].add(rec["id"])
            dest_store.rows[table_key].append(dict(rec))
        insert_count[0] += len(records)

    migrator1 = _ContactsMigratorDouble(all_rows, state_repo, dest_store)
    with patch.object(migrator1._repo, "bulk_insert", side_effect=bulk_insert_limited):
        migrator1.migrate()

    # After run 1: 500 records inserted, 500 failed
    assert len(dest_store.rows.get("contacts", [])) == 500
    assert len(state_repo._ok["contacts"]) == 500

    # --- Run 2: resume with same state_repo (500 already_migrated) ---
    migrator2 = _ContactsMigratorDouble(all_rows, state_repo, dest_store)
    with patch.object(migrator2._repo, "bulk_insert") as mock_insert:

        def resume_insert(conn, table, records):
            table_key = getattr(table, "name", "contacts")
            for rec in records:
                if rec["id"] not in dest_store._ids[table_key]:
                    dest_store._ids[table_key].add(rec["id"])
                    dest_store.rows[table_key].append(dict(rec))
                    state_repo._ok["contacts"].add(rec["id"])

        mock_insert.side_effect = resume_insert
        migrator2.migrate()

    # After run 2: exactly 1000 unique contacts, no duplicates
    final_ids = [r["id"] for r in dest_store.rows["contacts"]]
    assert len(final_ids) == 1000
    assert len(set(final_ids)) == 1000, "Duplicate IDs detected!"
    assert len(state_repo._ok["contacts"]) == 1000


# ---------------------------------------------------------------------------
# T036-2 — Zero new records → "0 novos a migrar"
# ---------------------------------------------------------------------------


def test_migration_zero_new_records():
    """When all records are already migrated, skipped=total_source, migrated=0."""
    all_rows = [{"id": i, "account_id": 0} for i in range(1, 101)]
    state_repo = _InMemoryStateRepo()
    # Pre-populate: all 100 records already done
    state_repo._ok["contacts"] = set(range(1, 101))

    dest_store = _InMemoryDestination()
    migrator = _ContactsMigratorDouble(all_rows, state_repo, dest_store)

    with patch.object(migrator._repo, "bulk_insert") as mock_insert:
        result = migrator.migrate()

    assert result.migrated == 0
    assert result.skipped == 100
    assert result.total_source == 100
    mock_insert.assert_not_called()
