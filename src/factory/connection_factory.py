"""Factory for creating SQLAlchemy database engines.

:description: Provides :class:`ConnectionFactory` which loads credentials
    from ``.secrets/generate_erd.json`` and creates engines for the source
    (read-only) and destination (read-write) PostgreSQL databases.

    The secrets file uses a named-instance schema (version 2.0)::

        {
            "_schema_version": "2.0",
            "instance_a": {
                "host": "...", "port": 5432,
                "username": "...", "password": "...",
                "database": "db_origem"
            },
            "instance_b": {
                "host": "...", "port": 5432,
                "username": "...", "password": "...",
                "database": "db_destino"
            }
        }

    By default the **first** non-metadata instance (keys not starting with
    ``_``) is treated as the source and the **second** as the destination.
    This can be overridden via the constructor parameters.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine


class ConfigError(Exception):
    """Raised when credentials are missing or malformed.

    :description: Signals that ``.secrets/generate_erd.json`` is absent,
        unreadable, or missing required keys.
    """


_REQUIRED_INSTANCE_KEYS: frozenset[str] = frozenset(
    {"host", "port", "username", "password", "database"}
)

_DEFAULT_SECRETS_PATH = Path(".secrets") / "generate_erd.json"


class ConnectionFactory:
    """Creates SQLAlchemy engines for source and destination databases.

    Credentials are loaded exclusively from a JSON secrets file.
    No credential value is ever logged or printed.

    The secrets file must contain at least two named instances (keys that do
    not start with ``_``).  By default, the first instance is used as the
    **source** (read-only) and the second as the **destination** (read-write).

    :param secrets_path: Path to the JSON secrets file.
        Defaults to ``.secrets/generate_erd.json`` relative to CWD.
    :type secrets_path: Path | None
    :param source_instance: Key name of the source instance inside the secrets
        file.  If omitted, the first non-metadata key is used.
    :type source_instance: str | None
    :param dest_instance: Key name of the destination instance inside the
        secrets file.  If omitted, the second non-metadata key is used.
    :type dest_instance: str | None

    :raises ConfigError: If the secrets file is missing, unreadable, or does
        not contain the required instance keys.

    Example::

        factory = ConnectionFactory()
        src = factory.create_source_engine()
        dst = factory.create_dest_engine()
    """

    def __init__(
        self,
        secrets_path: Path | None = None,
        source_instance: str | None = None,
        dest_instance: str | None = None,
    ) -> None:
        """Initialise and load credentials from the secrets file.

        :param secrets_path: Override path to the secrets file.
        :type secrets_path: Path | None
        :param source_instance: Key of the source instance in the file.
        :type source_instance: str | None
        :param dest_instance: Key of the destination instance in the file.
        :type dest_instance: str | None
        :raises ConfigError: If the file is missing, malformed, or the
            requested instance keys are absent.
        """
        path = secrets_path or _DEFAULT_SECRETS_PATH
        all_instances = self._load(path)

        non_meta = [k for k in all_instances if not k.startswith("_")]
        if len(non_meta) < 2:
            raise ConfigError(
                "Secrets file must contain at least 2 database instances "
                f"(found {len(non_meta)})"
            )

        src_key = source_instance or non_meta[0]
        dst_key = dest_instance or non_meta[1]

        if src_key not in all_instances:
            raise ConfigError(f"Source instance '{src_key}' not found in secrets file")
        if dst_key not in all_instances:
            raise ConfigError(f"Dest instance '{dst_key}' not found in secrets file")

        self._source: dict[str, Any] = all_instances[src_key]
        self._dest: dict[str, Any] = all_instances[dst_key]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load(path: Path) -> dict[str, Any]:
        """Load and validate the secrets file at *path*.

        :param path: Path to the JSON secrets file.
        :type path: Path
        :returns: Full parsed JSON as a dict (metadata keys included).
        :rtype: dict[str, Any]
        :raises ConfigError: If the file is missing, not valid JSON, or any
            non-metadata instance is missing required keys.
        """
        if not path.exists():
            raise ConfigError(f"Secrets file not found: {path}")
        try:
            data: dict[str, Any] = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            raise ConfigError(f"Failed to read secrets file: {exc}") from exc

        for key, value in data.items():
            if key.startswith("_"):
                continue
            if not isinstance(value, dict):
                raise ConfigError(
                    f"Instance '{key}' must be a JSON object, got {type(value).__name__}"
                )
            missing = _REQUIRED_INSTANCE_KEYS - set(value.keys())
            if missing:
                raise ConfigError(f"Instance '{key}' missing required keys: {sorted(missing)}")
        return data

    def _build_url(self, instance: dict[str, Any]) -> str:
        """Build a PostgreSQL connection URL (no SSL) for *instance*.

        :param instance: Instance credentials dict from the secrets file.
        :type instance: dict[str, Any]
        :returns: SQLAlchemy connection URL string.
        :rtype: str
        """
        return (
            f"postgresql+psycopg2://{instance['username']}:{instance['password']}"
            f"@{instance['host']}:{instance['port']}/{instance['database']}"
            "?sslmode=disable"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_source_engine(self) -> Engine:
        """Create a read-only engine for the source database.

        The database name is read exclusively from the secrets file.
        The engine is configured with ``execution_options(no_autocommit=True)``
        to prevent accidental writes.

        :returns: SQLAlchemy engine connected to the source database.
        :rtype: Engine
        """
        url = self._build_url(self._source)
        return create_engine(
            url,
            execution_options={"no_autocommit": True},
            pool_pre_ping=True,
        )

    def create_dest_engine(self) -> Engine:
        """Create a read-write engine for the destination database.

        The database name is read exclusively from the secrets file.

        :returns: SQLAlchemy engine connected to the destination database.
        :rtype: Engine
        """
        url = self._build_url(self._dest)
        return create_engine(
            url,
            pool_pre_ping=True,
        )
