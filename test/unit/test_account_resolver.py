"""Unit tests for account_resolver utility."""

import logging
from datetime import datetime
from unittest.mock import MagicMock, patch, call

import pytest

from src.utils.account_resolver import resolve_account_id


@pytest.fixture
def mock_engine():
    """Create a mocked SQLAlchemy engine."""
    engine = MagicMock()
    return engine


def test_resolve_account_id_fuzzy_single_match(mock_engine):
    """Test fuzzy search returns account_id when exactly 1 match found."""
    created_at = datetime(2025, 1, 15, 10, 0, 0)
    results = [(42, "Empresa XYZ Ltda", created_at)]

    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.execute.return_value.fetchall.return_value = results

    mock_engine.connect.return_value = mock_conn

    result = resolve_account_id(mock_engine, "Empresa XYZ", fuzzy=True)

    assert result == 42
    mock_engine.connect.assert_called_once()


def test_resolve_account_id_exact_single_match(mock_engine):
    """Test exact search returns account_id when match found."""
    created_at = datetime(2025, 1, 15, 10, 0, 0)
    results = [(99, "Empresa ABC", created_at)]

    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.execute.return_value.fetchall.return_value = results

    mock_engine.connect.return_value = mock_conn

    result = resolve_account_id(mock_engine, "Empresa ABC", fuzzy=False)

    assert result == 99


def test_resolve_account_id_fuzzy_multiple_matches_raises_error(mock_engine):
    """Test fuzzy search raises ValueError when multiple matches found."""
    created_at1 = datetime(2025, 1, 10, 10, 0, 0)
    created_at2 = datetime(2025, 1, 15, 10, 0, 0)
    results = [
        (42, "Empresa XYZ Ltda", created_at2),
        (10, "Empresa XYZ Brasil", created_at1),
    ]

    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.execute.return_value.fetchall.return_value = results

    mock_engine.connect.return_value = mock_conn

    with pytest.raises(ValueError) as exc_info:
        resolve_account_id(mock_engine, "Empresa XYZ", fuzzy=True)

    assert "Multiple accounts match" in str(exc_info.value)
    assert "ID 42" in str(exc_info.value)
    assert "ID 10" in str(exc_info.value)


def test_resolve_account_id_no_results_returns_none(mock_engine):
    """Test search returns None when no matches found."""
    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.execute.return_value.fetchall.return_value = []

    mock_engine.connect.return_value = mock_conn

    result = resolve_account_id(mock_engine, "NonExistent Corp", fuzzy=True)

    assert result is None


def test_resolve_account_id_programming_error_accounts_table_unavailable(mock_engine):
    """Test search returns None when accounts table unavailable (ProgrammingError)."""
    from sqlalchemy.exc import ProgrammingError

    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.execute.side_effect = ProgrammingError(
        "relation \"public.accounts\" does not exist",
        "SELECT ...",
        None
    )

    mock_engine.connect.return_value = mock_conn

    result = resolve_account_id(mock_engine, "Any Corp", fuzzy=True)

    assert result is None


def test_resolve_account_id_programming_error_other_raises(mock_engine):
    """Test search raises when ProgrammingError is not about accounts table."""
    from sqlalchemy.exc import ProgrammingError

    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.execute.side_effect = ProgrammingError(
        "syntax error in SQL",
        "SELECT ...",
        None
    )

    mock_engine.connect.return_value = mock_conn

    with pytest.raises(ProgrammingError):
        resolve_account_id(mock_engine, "Any Corp", fuzzy=True)
