"""Unit tests for ConnectionFactory (T012).

All tests use mocked file I/O — no real database connection required.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.factory.connection_factory import ConfigError, ConnectionFactory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_CREDS = {
    "host": "db.example.com",
    "port": 5432,
    "user": "migrate_user",
    "password": "s3cr3t",
    "source_db": "chatwoot_dev1_db",
    "dest_db": "chatwoot004_dev1_db",
}


def _write_secrets(tmp_path: Path, data: dict) -> Path:
    """Write *data* as JSON into a temp secrets file and return the path."""
    p = tmp_path / ".secrets" / "generate_erd.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data))
    return p


# ---------------------------------------------------------------------------
# T012-1 — Missing secrets file raises ConfigError
# ---------------------------------------------------------------------------


def test_missing_secrets_file_raises_config_error(tmp_path: Path) -> None:
    """ConfigError is raised when the secrets file does not exist."""
    missing = tmp_path / ".secrets" / "generate_erd.json"
    with pytest.raises(ConfigError, match="Secrets file not found"):
        ConnectionFactory(secrets_path=missing)


# ---------------------------------------------------------------------------
# T012-2 — Invalid JSON raises ConfigError
# ---------------------------------------------------------------------------


def test_invalid_json_raises_config_error(tmp_path: Path) -> None:
    """ConfigError is raised when the secrets file contains invalid JSON."""
    p = tmp_path / ".secrets" / "generate_erd.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not valid json")
    with pytest.raises(ConfigError, match="Failed to read secrets file"):
        ConnectionFactory(secrets_path=p)


# ---------------------------------------------------------------------------
# T012-3 — Missing required keys raises ConfigError
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("missing_key", list(_VALID_CREDS.keys()))
def test_missing_required_key_raises_config_error(tmp_path: Path, missing_key: str) -> None:
    """ConfigError is raised when any single required key is absent."""
    creds = {k: v for k, v in _VALID_CREDS.items() if k != missing_key}
    p = _write_secrets(tmp_path, creds)
    with pytest.raises(ConfigError, match="missing required keys"):
        ConnectionFactory(secrets_path=p)


# ---------------------------------------------------------------------------
# T012-4 — Source engine URL contains source_db and sslmode=disable
# ---------------------------------------------------------------------------


def test_source_engine_url_contains_source_db_and_ssl_disable(
    tmp_path: Path,
) -> None:
    """create_source_engine() produces an engine URL with source_db and sslmode=disable."""
    p = _write_secrets(tmp_path, _VALID_CREDS)
    factory = ConnectionFactory(secrets_path=p)
    engine = factory.create_source_engine()
    url_str = str(engine.url)
    assert "chatwoot_dev1_db" in url_str
    assert "sslmode=disable" in url_str


# ---------------------------------------------------------------------------
# T012-5 — Destination engine URL contains dest_db and sslmode=disable
# ---------------------------------------------------------------------------


def test_dest_engine_url_contains_dest_db_and_ssl_disable(tmp_path: Path) -> None:
    """create_dest_engine() produces an engine URL with dest_db and sslmode=disable."""
    p = _write_secrets(tmp_path, _VALID_CREDS)
    factory = ConnectionFactory(secrets_path=p)
    engine = factory.create_dest_engine()
    url_str = str(engine.url)
    assert "chatwoot004_dev1_db" in url_str
    assert "sslmode=disable" in url_str


# ---------------------------------------------------------------------------
# T012-6 — Source engine has no_autocommit execution option
# ---------------------------------------------------------------------------


def test_source_engine_has_no_autocommit_option(tmp_path: Path) -> None:
    """create_source_engine() sets execution_options no_autocommit=True."""
    p = _write_secrets(tmp_path, _VALID_CREDS)
    factory = ConnectionFactory(secrets_path=p)
    engine = factory.create_source_engine()
    assert engine.get_execution_options().get("no_autocommit") is True


# ---------------------------------------------------------------------------
# T012-7 — Both engines are created from the same credentials
# ---------------------------------------------------------------------------


def test_both_engines_use_same_host(tmp_path: Path) -> None:
    """Source and destination engines share the same database host."""
    p = _write_secrets(tmp_path, _VALID_CREDS)
    factory = ConnectionFactory(secrets_path=p)
    src_url = str(factory.create_source_engine().url)
    dst_url = str(factory.create_dest_engine().url)
    assert "db.example.com" in src_url
    assert "db.example.com" in dst_url
