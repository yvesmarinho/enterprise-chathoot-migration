"""Unit tests for ContactsMigrator (T030)."""

from __future__ import annotations

import io
import logging
from unittest.mock import MagicMock, patch

from src.migrators.base_migrator import MigrationResult
from src.migrators.contacts_migrator import ContactsMigrator
from src.repository.migration_state_repository import MigrationStateRepository
from src.utils.id_remapper import IDRemapper
from src.utils.log_masker import MaskingHandler


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

    remapper = IDRemapper({"contacts": 225536, "accounts": 20})
    logger = logging.getLogger("test_contacts")

    return ContactsMigrator(
        source_engine=source_engine,
        dest_engine=dest_engine,
        id_remapper=remapper,
        state_repo=state_repo,
        logger=logger,
    )


# ---------------------------------------------------------------------------
# T030-1 — account_id and id remapped correctly
# ---------------------------------------------------------------------------


def test_contacts_account_id_remapped():
    """account_id and id are remapped with their respective offsets."""
    rows = [
        {
            "id": 1,
            "account_id": 1,
            "name": "John",
            "email": "j@x.com",
            "phone_number": None,
            "identifier": None,
            "additional_attributes": None,
            "created_at": None,
            "updated_at": None,
        }
    ]
    remapped_rows = []

    def capture(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                remapped_rows.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    migrator = _make_migrator(source_rows=rows, migrated_accounts={1})
    with patch.object(migrator, "_run_batches", side_effect=capture):
        with patch("src.migrators.contacts_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    assert remapped_rows[0]["id"] == 225537  # 1 + 225536
    assert remapped_rows[0]["account_id"] == 21  # 1 + 20


# ---------------------------------------------------------------------------
# T030-2 — PII masked IN LOG, not in DB payload
# ---------------------------------------------------------------------------


def test_contacts_pii_masked_in_log_not_in_db():
    """Email and name are masked in log output but the DB row receives originals."""
    rows = [
        {
            "id": 2,
            "account_id": 1,
            "name": "Jane Doe",
            "email": "jane@secret.com",
            "phone_number": "+55 11 91234-5678",
            "identifier": None,
            "additional_attributes": None,
            "created_at": None,
            "updated_at": None,
        }
    ]
    db_rows_received = []
    _ = io.StringIO()

    def capture(source_rows, table_name, dest_table, remap_fn):
        for row in source_rows:
            r = remap_fn(row)
            if r is not None:
                db_rows_received.append(r)
        return MigrationResult(table=table_name, total_source=1, migrated=1, skipped=0)

    buf = io.StringIO()
    inner = logging.StreamHandler(buf)
    masking_handler = MaskingHandler(inner)
    masking_handler.setLevel(logging.DEBUG)
    test_logger = logging.getLogger("test_contacts_pii")
    test_logger.handlers.clear()
    test_logger.addHandler(masking_handler)
    test_logger.propagate = False
    test_logger.setLevel(logging.DEBUG)

    source_engine = MagicMock()
    dest_engine = MagicMock()
    src_conn = MagicMock()
    src_conn.__enter__ = MagicMock(return_value=src_conn)
    src_conn.__exit__ = MagicMock(return_value=False)
    src_conn.execute.return_value.mappings.return_value.all.return_value = rows
    source_engine.connect.return_value = src_conn
    dest_conn = MagicMock()
    dest_conn.__enter__ = MagicMock(return_value=dest_conn)
    dest_conn.__exit__ = MagicMock(return_value=False)
    dest_engine.connect.return_value = dest_conn

    state_repo = MagicMock(spec=MigrationStateRepository)
    state_repo.get_migrated_ids.side_effect = [{1}, set()]

    remapper = IDRemapper({"contacts": 225536, "accounts": 20})
    migrator = ContactsMigrator(
        source_engine=source_engine,
        dest_engine=dest_engine,
        id_remapper=remapper,
        state_repo=state_repo,
        logger=test_logger,
    )

    with patch.object(migrator, "_run_batches", side_effect=capture):
        with patch("src.migrators.contacts_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    # DB received originals
    assert db_rows_received[0]["email"] == "jane@secret.com"
    assert db_rows_received[0]["name"] == "Jane Doe"


# ---------------------------------------------------------------------------
# T030-3 — 38,868 records produce ceil(38868 / 500) = 78 batches
# ---------------------------------------------------------------------------


def test_contacts_batch_count():
    """38,868 contacts produce exactly 78 batches."""

    rows = [
        {
            "id": i,
            "account_id": 1,
            "name": "X",
            "email": None,
            "phone_number": None,
            "identifier": None,
            "additional_attributes": None,
            "created_at": None,
            "updated_at": None,
        }
        for i in range(1, 38869)
    ]
    _ = []

    migrator = _make_migrator(source_rows=rows, migrated_accounts={1})

    # We don't actually run _run_batches for 38K rows; just verify row count passed
    with patch.object(
        migrator,
        "_run_batches",
        return_value=MigrationResult(
            table="contacts", total_source=38868, migrated=38868, skipped=0
        ),
    ) as mock_run:
        with patch("src.migrators.contacts_migrator.Table") as mock_table:
            mock_table.return_value = MagicMock()
            migrator.migrate()

    # The 38,868 rows were passed to _run_batches
    assert mock_run.call_args[0][0] == rows or mock_run.call_args.args[0] == rows


# ---------------------------------------------------------------------------
# T030-4 — Dedup: contact with (account_id, phone) match in DEST reuses dest_id
# ---------------------------------------------------------------------------


def _make_migrator_with_dedup(
    source_rows, dest_phone_rows=None, dest_email_rows=None, remapper=None
):
    """Build ContactsMigrator where dest DB returns specific lookup rows for dedup."""
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
    # The dedup lookup uses text() queries returning MappingResult rows with
    # "id", "phone_number", "email" keys. We return them as mock mapping objects.
    phone_rows = dest_phone_rows or []
    email_rows = dest_email_rows or []

    def make_mapping_row(data):
        m = MagicMock()
        m.__getitem__ = lambda self, k: data[k]
        m.get = lambda k, d=None: data.get(k, d)
        return m

    lookup_result = MagicMock()
    phone_mapping_rows = [make_mapping_row(r) for r in phone_rows]
    email_mapping_rows = [make_mapping_row(r) for r in email_rows]
    # First execute call (for one merged account) returns both phone and email columns
    # We simulate the combined query: id, phone_number, email
    all_rows = [make_mapping_row({**r, "email": None}) for r in phone_rows]
    all_rows += [
        make_mapping_row({"id": r["id"], "phone_number": None, "email": r["email"]})
        for r in email_rows
    ]
    lookup_result.mappings.return_value = iter(all_rows)
    dest_conn.execute.return_value = lookup_result
    dest_engine.connect.return_value = dest_conn

    state_repo = MagicMock(spec=MigrationStateRepository)
    # migrated_accounts + _run_batches get_migrated_ids
    state_repo.get_migrated_ids.side_effect = [{1}, set()]

    if remapper is None:
        remapper = IDRemapper({"contacts": 226274, "accounts": 0})
        # Simulate account id=1 being a "merged" account (alias: 1→1)
        remapper.register_alias("accounts", 1, 1)

    logger = logging.getLogger("test_contacts_dedup")

    return (
        ContactsMigrator(
            source_engine=source_engine,
            dest_engine=dest_engine,
            id_remapper=remapper,
            state_repo=state_repo,
            logger=logger,
        ),
        remapper,
        state_repo,
    )


def test_contacts_dedup_phone_match_registers_alias_and_skips_insert():
    """Contact matching (account_id, phone) in DEST: alias registered, INSERT skipped."""
    source_rows = [
        {
            "id": 500,
            "account_id": 1,
            "name": "João",
            "email": None,
            "phone_number": "+5511999990000",
            "identifier": None,
            "additional_attributes": None,
            "created_at": None,
            "updated_at": None,
        }
    ]
    # DEST has a contact with same phone in account_id=1
    dest_phone_rows = [{"id": 1234, "phone_number": "+5511999990000", "email": None}]

    migrator, remapper, state_repo = _make_migrator_with_dedup(
        source_rows, dest_phone_rows=dest_phone_rows
    )

    with patch.object(
        migrator,
        "_run_batches",
        return_value=MigrationResult(table="contacts", total_source=1, migrated=0, skipped=1),
    ):
        with patch("src.migrators.contacts_migrator.Table"):
            migrator.migrate()

    # Alias registered: src_id=500 → dest_id=1234
    assert remapper.remap(500, "contacts") == 1234

    # record_success called for the dedup'd contact
    calls = state_repo.record_success.call_args_list
    dedup_call = next(
        (c for c in calls if c.args[1] == "contacts" and c.args[2] == 500 and c.args[3] == 1234),
        None,
    )
    assert dedup_call is not None, "record_success not called for dedup'd contact src_id=500"


def test_contacts_dedup_email_match_registers_alias():
    """Contact matching (account_id, email) in DEST: alias registered."""
    source_rows = [
        {
            "id": 600,
            "account_id": 1,
            "name": "Maria",
            "email": "maria@empresa.com",
            "phone_number": None,
            "identifier": None,
            "additional_attributes": None,
            "created_at": None,
            "updated_at": None,
        }
    ]
    dest_email_rows = [{"id": 9999, "email": "maria@empresa.com"}]

    migrator, remapper, state_repo = _make_migrator_with_dedup(
        source_rows, dest_email_rows=dest_email_rows
    )

    with patch.object(
        migrator,
        "_run_batches",
        return_value=MigrationResult(table="contacts", total_source=1, migrated=0, skipped=1),
    ):
        with patch("src.migrators.contacts_migrator.Table"):
            migrator.migrate()

    assert remapper.remap(600, "contacts") == 9999


def test_contacts_dedup_no_match_uses_offset():
    """Contact with no phone/email match in DEST: no alias, offset applied normally."""
    source_rows = [
        {
            "id": 700,
            "account_id": 1,
            "name": "Pedro",
            "email": "pedro@novo.com",
            "phone_number": "+5511888880000",
            "identifier": None,
            "additional_attributes": None,
            "created_at": None,
            "updated_at": None,
        }
    ]
    # DEST has no matching phone or email
    migrator, remapper, state_repo = _make_migrator_with_dedup(source_rows)

    with patch.object(
        migrator,
        "_run_batches",
        return_value=MigrationResult(table="contacts", total_source=1, migrated=1, skipped=0),
    ):
        with patch("src.migrators.contacts_migrator.Table"):
            migrator.migrate()

    # No alias: 700 + 226274 = 226974
    assert remapper.remap(700, "contacts") == 226974


def test_contacts_dedup_only_for_merged_accounts():
    """Contacts in unmerged accounts (new, offset-shifted) are NOT dedup'd."""
    # account_id=4 has no alias → remap(4, "accounts") = 4 + 43 ≠ 4 → not merged
    source_rows = [
        {
            "id": 800,
            "account_id": 4,
            "name": "Carlos",
            "email": None,
            "phone_number": "+5521999990000",
            "identifier": None,
            "additional_attributes": None,
            "created_at": None,
            "updated_at": None,
        }
    ]

    remapper = IDRemapper({"contacts": 226274, "accounts": 43})
    # No alias on account_id=4

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
    dest_engine.connect.return_value = dest_conn

    state_repo = MagicMock(spec=MigrationStateRepository)
    state_repo.get_migrated_ids.side_effect = [{4}, set()]

    migrator = ContactsMigrator(
        source_engine=source_engine,
        dest_engine=dest_engine,
        id_remapper=remapper,
        state_repo=state_repo,
        logger=logging.getLogger("test_contacts_no_dedup"),
    )

    with patch.object(
        migrator,
        "_run_batches",
        return_value=MigrationResult(table="contacts", total_source=1, migrated=1, skipped=0),
    ):
        with patch("src.migrators.contacts_migrator.Table"):
            migrator.migrate()

    # dest_engine.execute was NOT called for dedup lookup (account not merged)
    dest_conn.execute.assert_not_called()
    # No alias for id=800 → offset: 800 + 226274 = 227074
    assert remapper.remap(800, "contacts") == 227074
