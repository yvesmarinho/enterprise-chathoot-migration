"""Unit tests for env_guard utility."""

import os
from unittest.mock import patch

import pytest

from src.utils.env_guard import assert_dev_only_env


def test_assert_dev_only_env_safe_dev_environment():
    """Test assert_dev_only_env does not raise when in safe DEV environment."""
    env_vars = {
        "DEV_ONLY_MODE": "true",
        "MIGRATION_ENV": "dev",
        "MIGRATION_SOURCE_KEY": "chat-vya-digital",
        "MIGRATION_DEST_KEY": "vya-chat-dev",
    }

    with patch.dict(os.environ, env_vars, clear=True):
        # Should not raise
        assert_dev_only_env()


def test_assert_dev_only_env_dev_only_mode_false_allows_prod():
    """Test assert_dev_only_env does not raise when DEV_ONLY_MODE=false."""
    env_vars = {
        "DEV_ONLY_MODE": "false",
        "MIGRATION_ENV": "prod",
        "MIGRATION_SOURCE_KEY": "chat-vya-digital",
        "MIGRATION_DEST_KEY": "synchat-vya-digital",
    }

    with patch.dict(os.environ, env_vars, clear=True):
        # Should not raise even with prod settings
        assert_dev_only_env()


def test_assert_dev_only_env_dev_only_mode_false_caseinsensitive():
    """Test assert_dev_only_env respects DEV_ONLY_MODE=False (case-insensitive)."""
    env_vars = {
        "DEV_ONLY_MODE": "False",
        "MIGRATION_ENV": "prod",
        "MIGRATION_SOURCE_KEY": "chat-vya-digital",
        "MIGRATION_DEST_KEY": "synchat-vya-digital",
    }

    with patch.dict(os.environ, env_vars, clear=True):
        # Should not raise — False is not "true" (case-insensitive)
        assert_dev_only_env()


def test_assert_dev_only_env_migration_env_prod_raises_system_exit():
    """Test assert_dev_only_env raises SystemExit when MIGRATION_ENV=prod."""
    env_vars = {
        "DEV_ONLY_MODE": "true",
        "MIGRATION_ENV": "prod",
        "MIGRATION_SOURCE_KEY": "chat-vya-digital",
        "MIGRATION_DEST_KEY": "vya-chat-prod",
    }

    with patch.dict(os.environ, env_vars, clear=True):
        with pytest.raises(SystemExit) as exc_info:
            assert_dev_only_env()

        assert exc_info.value.code == 1


def test_assert_dev_only_env_prod_dest_key_raises_system_exit():
    """Test assert_dev_only_env raises SystemExit when DEST is prod key."""
    env_vars = {
        "DEV_ONLY_MODE": "true",
        "MIGRATION_ENV": "dev",
        "MIGRATION_SOURCE_KEY": "chat-vya-digital",
        "MIGRATION_DEST_KEY": "synchat-vya-digital",
    }

    with patch.dict(os.environ, env_vars, clear=True):
        with pytest.raises(SystemExit) as exc_info:
            assert_dev_only_env()

        assert exc_info.value.code == 1


def test_assert_dev_only_env_dev_only_mode_default_true():
    """Test assert_dev_only_env defaults DEV_ONLY_MODE to true."""
    env_vars = {
        # DEV_ONLY_MODE not set — should default to "true"
        "MIGRATION_ENV": "dev",
        "MIGRATION_SOURCE_KEY": "chat-vya-digital",
        "MIGRATION_DEST_KEY": "vya-chat-dev",
    }

    with patch.dict(os.environ, env_vars, clear=True):
        # Should not raise with safe settings
        assert_dev_only_env()


def test_assert_dev_only_env_dev_only_mode_default_blocks_prod():
    """Test assert_dev_only_env defaults to blocking prod."""
    env_vars = {
        # DEV_ONLY_MODE not set — should default to "true"
        "MIGRATION_ENV": "dev",
        "MIGRATION_SOURCE_KEY": "chat-vya-digital",
        "MIGRATION_DEST_KEY": "synchat-vya-digital",
    }

    with patch.dict(os.environ, env_vars, clear=True):
        # Should raise because default blocks prod dest key
        with pytest.raises(SystemExit) as exc_info:
            assert_dev_only_env()

        assert exc_info.value.code == 1
