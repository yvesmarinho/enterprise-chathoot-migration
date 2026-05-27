"""Unit tests for schema_bootstrap utility."""

from unittest.mock import MagicMock, call, patch

import pytest
from sqlalchemy import MetaData, Table

from src.utils.schema_bootstrap import (
    bootstrap_public_schema,
    ensure_public_table_exists,
)


def test_bootstrap_public_schema_creates_all_tables():
    """bootstrap_public_schema creates all public schema tables."""
    source_engine = MagicMock()
    dest_engine = MagicMock()

    # Mock inspector to return table names
    mock_inspector = MagicMock()
    mock_inspector.get_table_names.return_value = ["accounts", "contacts", "inboxes"]

    # Mock Table creation
    mock_src_table = MagicMock(spec=Table)
    mock_src_table.to_metadata = MagicMock(return_value=MagicMock(spec=Table, indexes=[]))
    mock_src_table.indexes = []

    with patch("src.utils.schema_bootstrap.inspect", return_value=mock_inspector):
        with patch("src.utils.schema_bootstrap.Table", return_value=mock_src_table):
            with patch("src.utils.schema_bootstrap.MetaData"):
                result = bootstrap_public_schema(source_engine, dest_engine)

    assert result == ["accounts", "contacts", "inboxes"]


def test_bootstrap_public_schema_excludes_tables():
    """bootstrap_public_schema skips tables in exclude_tables."""
    source_engine = MagicMock()
    dest_engine = MagicMock()

    mock_inspector = MagicMock()
    mock_inspector.get_table_names.return_value = ["accounts", "contacts", "inboxes"]

    mock_src_table = MagicMock(spec=Table)
    mock_src_table.to_metadata = MagicMock(return_value=MagicMock(spec=Table, indexes=[]))
    mock_src_table.indexes = []

    with patch("src.utils.schema_bootstrap.inspect", return_value=mock_inspector):
        with patch("src.utils.schema_bootstrap.Table", return_value=mock_src_table):
            with patch("src.utils.schema_bootstrap.MetaData"):
                result = bootstrap_public_schema(
                    source_engine, dest_engine, exclude_tables=["contacts"]
                )

    # contacts should be excluded
    assert "contacts" not in result
    assert result == ["accounts", "inboxes"]


def test_bootstrap_public_schema_empty_exclude():
    """bootstrap_public_schema handles empty exclude_tables list."""
    source_engine = MagicMock()
    dest_engine = MagicMock()

    mock_inspector = MagicMock()
    mock_inspector.get_table_names.return_value = ["accounts"]

    mock_src_table = MagicMock(spec=Table)
    mock_src_table.to_metadata = MagicMock(return_value=MagicMock(spec=Table, indexes=[]))
    mock_src_table.indexes = []

    with patch("src.utils.schema_bootstrap.inspect", return_value=mock_inspector):
        with patch("src.utils.schema_bootstrap.Table", return_value=mock_src_table):
            with patch("src.utils.schema_bootstrap.MetaData"):
                result = bootstrap_public_schema(
                    source_engine, dest_engine, exclude_tables=[]
                )

    assert result == ["accounts"]


def test_ensure_public_table_exists_returns_false_when_exists():
    """ensure_public_table_exists returns False if table already exists in dest."""
    source_engine = MagicMock()
    dest_engine = MagicMock()

    mock_inspector = MagicMock()
    # Simulate table exists in dest
    mock_inspector.get_table_names.return_value = ["accounts"]

    with patch("src.utils.schema_bootstrap.inspect", return_value=mock_inspector):
        result = ensure_public_table_exists(source_engine, dest_engine, "accounts")

    assert result is False


def test_ensure_public_table_exists_returns_true_when_created():
    """ensure_public_table_exists returns True if table was created."""
    source_engine = MagicMock()
    dest_engine = MagicMock()

    mock_inspector = MagicMock()
    # First call: dest table doesn't exist
    # Second call: in _collect_public_dependencies
    mock_inspector.get_table_names.return_value = []

    mock_src_table = MagicMock(spec=Table)
    mock_src_table.foreign_keys = []
    mock_src_table.to_metadata = MagicMock(return_value=MagicMock(spec=Table, indexes=[]))
    mock_src_table.indexes = []

    with patch("src.utils.schema_bootstrap.inspect", return_value=mock_inspector):
        with patch("src.utils.schema_bootstrap.Table", return_value=mock_src_table):
            with patch("src.utils.schema_bootstrap.MetaData"):
                result = ensure_public_table_exists(source_engine, dest_engine, "accounts")

    assert result is True


def test_ensure_public_table_exists_removes_public_prefix():
    """ensure_public_table_exists normalizes table names (removes 'public.' prefix)."""
    source_engine = MagicMock()
    dest_engine = MagicMock()

    mock_inspector = MagicMock()
    # Table "accounts" exists (without prefix)
    mock_inspector.get_table_names.return_value = ["accounts"]

    with patch("src.utils.schema_bootstrap.inspect", return_value=mock_inspector):
        # Provide table name with prefix
        result = ensure_public_table_exists(source_engine, dest_engine, "public.accounts")

    # Should find it via normalized name
    assert result is False


def test_ensure_public_table_exists_with_foreign_key_dependencies():
    """ensure_public_table_exists creates FK-dependent tables."""
    source_engine = MagicMock()
    dest_engine = MagicMock()

    mock_inspector = MagicMock()
    mock_inspector.get_table_names.return_value = []

    # Create mock tables with FK dependency
    mock_fk_column = MagicMock()
    mock_fk_table = MagicMock(spec=Table)
    mock_fk_table.name = "accounts"
    mock_fk_table.schema = "public"
    mock_fk_column.table = mock_fk_table

    mock_fk = MagicMock()
    mock_fk.column = mock_fk_column

    mock_src_table = MagicMock(spec=Table)
    mock_src_table.name = "contacts"
    mock_src_table.schema = "public"
    mock_src_table.foreign_keys = [mock_fk]
    mock_src_table.to_metadata = MagicMock(return_value=MagicMock(spec=Table, indexes=[]))
    mock_src_table.indexes = []

    mock_account_table = MagicMock(spec=Table)
    mock_account_table.name = "accounts"
    mock_account_table.schema = "public"
    mock_account_table.foreign_keys = []
    mock_account_table.to_metadata = MagicMock(return_value=MagicMock(spec=Table, indexes=[]))
    mock_account_table.indexes = []

    table_map = {"contacts": mock_src_table, "accounts": mock_account_table}

    with patch("src.utils.schema_bootstrap.inspect", return_value=mock_inspector):
        with patch("src.utils.schema_bootstrap.Table", side_effect=lambda *a, **kw: table_map.get(a[0]) or mock_src_table):
            with patch("src.utils.schema_bootstrap.MetaData"):
                result = ensure_public_table_exists(source_engine, dest_engine, "contacts")

    assert result is True


def test_ensure_public_table_exists_avoids_recursive_fk_loop():
    """ensure_public_table_exists avoids infinite loops in FK recursion."""
    source_engine = MagicMock()
    dest_engine = MagicMock()

    mock_inspector = MagicMock()
    mock_inspector.get_table_names.return_value = []

    # Create circular FK: contacts → accounts → contacts
    mock_contacts_fk_col = MagicMock()
    mock_accounts_table = MagicMock(spec=Table)
    mock_accounts_table.name = "accounts"
    mock_accounts_table.schema = "public"
    mock_contacts_fk_col.table = mock_accounts_table

    mock_accounts_fk_col = MagicMock()
    mock_contacts_table = MagicMock(spec=Table)
    mock_contacts_table.name = "contacts"
    mock_contacts_table.schema = "public"
    mock_accounts_fk_col.table = mock_contacts_table

    mock_contacts_fk = MagicMock()
    mock_contacts_fk.column = mock_contacts_fk_col

    mock_accounts_fk = MagicMock()
    mock_accounts_fk.column = mock_accounts_fk_col

    mock_contacts_table.foreign_keys = [mock_contacts_fk]
    mock_accounts_table.foreign_keys = [mock_accounts_fk]

    # Mock to_metadata
    mock_contacts_table.to_metadata = MagicMock(return_value=MagicMock(spec=Table, indexes=[]))
    mock_contacts_table.indexes = []
    mock_accounts_table.to_metadata = MagicMock(return_value=MagicMock(spec=Table, indexes=[]))
    mock_accounts_table.indexes = []

    table_map = {"contacts": mock_contacts_table, "accounts": mock_accounts_table}

    with patch("src.utils.schema_bootstrap.inspect", return_value=mock_inspector):
        with patch("src.utils.schema_bootstrap.Table", side_effect=lambda *a, **kw: table_map.get(a[0])):
            with patch("src.utils.schema_bootstrap.MetaData"):
                result = ensure_public_table_exists(source_engine, dest_engine, "contacts")

    # Should complete without infinite recursion
    assert result is True


def test_ensure_public_table_exists_ignores_non_public_fk():
    """ensure_public_table_exists ignores FKs to non-public schemas."""
    source_engine = MagicMock()
    dest_engine = MagicMock()

    mock_inspector = MagicMock()
    mock_inspector.get_table_names.return_value = []

    # FK to a table in 'other_schema'
    mock_fk_column = MagicMock()
    mock_fk_table = MagicMock(spec=Table)
    mock_fk_table.name = "other_table"
    mock_fk_table.schema = "other_schema"
    mock_fk_column.table = mock_fk_table

    mock_fk = MagicMock()
    mock_fk.column = mock_fk_column

    mock_src_table = MagicMock(spec=Table)
    mock_src_table.name = "contacts"
    mock_src_table.schema = "public"
    mock_src_table.foreign_keys = [mock_fk]
    mock_src_table.to_metadata = MagicMock(return_value=MagicMock(spec=Table, indexes=[]))
    mock_src_table.indexes = []

    with patch("src.utils.schema_bootstrap.inspect", return_value=mock_inspector):
        with patch("src.utils.schema_bootstrap.Table", return_value=mock_src_table):
            with patch("src.utils.schema_bootstrap.MetaData"):
                result = ensure_public_table_exists(source_engine, dest_engine, "contacts")

    # Should only try to create contacts, not other_table
    assert result is True
