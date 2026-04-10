"""Factory for creating SQLAlchemy database engines.

:description: Provides :class:`ConnectionFactory` which loads credentials
    from ``.secrets/generate_erd.json`` and creates engines for the source
    (read-only) and destination (read-write) PostgreSQL databases.

    >>> from pathlib import Path
    >>> import json, tempfile
    >>> d = tempfile.mkdtemp()
    >>> p = Path(d) / ".secrets" / "generate_erd.json"
    >>> p.parent.mkdir()
    >>> _ = p.write_text(json.dumps(
    ...     {"host":"h","port":5432,"user":"u","password":"p",
    ...      "source_db":"src","dest_db":"dst"}
    ... ))
    >>> cf = ConnectionFactory(secrets_path=p)
    >>> cf._creds["host"]
    'h'
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


_REQUIRED_KEYS: frozenset[str] = frozenset(
    {"host", "port", "user", "password", "source_db", "dest_db"}
)

_DEFAULT_SECRETS_PATH = Path(".secrets") / "generate_erd.json"


class ConnectionFactory:
    """Creates SQLAlchemy engines for source and destination databases.

    Credentials are loaded exclusively from a JSON secrets file.
    No credential value is ever logged or printed.

    :param secrets_path: Path to the JSON secrets file.
        Defaults to ``.secrets/generate_erd.json`` relative to CWD.
    :type secrets_path: Path | None

    :raises ConfigError: If the secrets file is missing, unreadable,
        or does not contain all required keys.

    Example::

        factory = ConnectionFactory()
        src = factory.create_source_engine()
        dst = factory.create_dest_engine()
    """

    def __init__(self, secrets_path: Path | None = None) -> None:
        """Initialise and load credentials from the secrets file.

        :param secrets_path: Override path to the secrets file.
        :type secrets_path: Path | None
        :raises ConfigError: If the file is missing or malformed.
        """
        path = secrets_path or _DEFAULT_SECRETS_PATH
        self._creds: dict[str, Any] = self._load(path)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load(path: Path) -> dict[str, Any]:
        """Load and validate credentials from *path*.

        :param path: Path to the JSON secrets file.
        :type path: Path
        :returns: Validated credentials dictionary.
        :rtype: dict[str, Any]
        :raises ConfigError: If file is missing, not valid JSON, or
            missing required keys.
        """
        if not path.exists():
            raise ConfigError(f"Secrets file not found: {path}")
        try:
            data: dict[str, Any] = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            raise ConfigError(f"Failed to read secrets file: {exc}") from exc

        missing = _REQUIRED_KEYS - set(data.keys())
        if missing:
            raise ConfigError(f"Secrets file missing required keys: {sorted(missing)}")
        return data

    def _build_url(self, db_name: str) -> str:
        """Build a PostgreSQL connection URL (no SSL).

        :param db_name: Target database name.
        :type db_name: str
        :returns: SQLAlchemy connection URL string.
        :rtype: str
        """
        c = self._creds
        return (
            f"postgresql+psycopg2://{c['user']}:{c['password']}"
            f"@{c['host']}:{c['port']}/{db_name}"
            "?sslmode=disable"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_source_engine(self) -> Engine:
        """Create a read-only engine for ``chatwoot_dev1_db``.

        The engine is configured with ``sslmode=disable`` and
        ``execution_options(no_autocommit=True)`` to prevent accidental writes.

        :returns: SQLAlchemy engine connected to the source database.
        :rtype: Engine
        :raises ConfigError: If credentials are not loaded.
        """
        url = self._build_url(self._creds["source_db"])
        return create_engine(
            url,
            execution_options={"no_autocommit": True},
            pool_pre_ping=True,
        )

    def create_dest_engine(self) -> Engine:
        """Create a read-write engine for ``chatwoot004_dev1_db``.

        :returns: SQLAlchemy engine connected to the destination database.
        :rtype: Engine
        :raises ConfigError: If credentials are not loaded.
        """
        url = self._build_url(self._creds["dest_db"])
        return create_engine(
            url,
            pool_pre_ping=True,
        )
