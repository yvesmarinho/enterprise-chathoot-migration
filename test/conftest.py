"""Shared pytest fixtures for enterprise-chathoot-migration tests.

:description: Provides mock DB engines, connections, and secrets loader stubs
    used across unit and integration test suites.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy.engine import Engine

# ---------------------------------------------------------------------------
# Secrets fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_secrets(tmp_path: Path) -> Path:
    """Create a temporary .secrets/generate_erd.json for testing.

    :returns: Path to the secrets file.
    :rtype: Path
    """
    secrets_dir = tmp_path / ".secrets"
    secrets_dir.mkdir()
    secrets_file = secrets_dir / "generate_erd.json"
    secrets_file.write_text(
        json.dumps(
            {
                "host": "localhost",
                "port": 5432,
                "user": "test_user",
                "password": "test_pass",
                "source_db": "chatwoot_dev1_db",
                "dest_db": "chatwoot004_dev1_db",
            }
        )
    )
    return secrets_file


# ---------------------------------------------------------------------------
# Mock engine fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_source_engine() -> MagicMock:
    """Return a MagicMock representing a read-only SQLAlchemy source engine.

    :returns: Mock engine for chatwoot_dev1_db.
    :rtype: MagicMock
    """
    engine = MagicMock(spec=Engine)
    engine.url = MagicMock()
    engine.url.database = "chatwoot_dev1_db"
    return engine


@pytest.fixture()
def mock_dest_engine() -> MagicMock:
    """Return a MagicMock representing a read-write SQLAlchemy dest engine.

    :returns: Mock engine for chatwoot004_dev1_db.
    :rtype: MagicMock
    """
    engine = MagicMock(spec=Engine)
    engine.url = MagicMock()
    engine.url.database = "chatwoot004_dev1_db"
    return engine


@pytest.fixture()
def mock_conn() -> MagicMock:
    """Return a MagicMock SQLAlchemy connection with context-manager support.

    :returns: Mock connection.
    :rtype: MagicMock
    """
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    return conn
