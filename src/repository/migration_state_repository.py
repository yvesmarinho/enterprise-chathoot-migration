"""Repository for the migration state tracking table.

:description: Manages the ``migration_state`` control table in the destination
    database.  This table is the single source of truth for idempotency:
    before inserting any batch, migrators query which IDs are already present
    with status ``'ok'`` and skip them.

    DDL (created automatically on first run)::

        CREATE TABLE IF NOT EXISTS migration_state (
            id          BIGSERIAL PRIMARY KEY,
            tabela      VARCHAR(100) NOT NULL,
            id_origem   BIGINT       NOT NULL,
            id_destino  BIGINT,
            status      VARCHAR(20)  NOT NULL DEFAULT 'ok',
            migrated_at TIMESTAMP    NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_migration_state UNIQUE (tabela, id_origem)
        );
        CREATE INDEX IF NOT EXISTS ix_migration_state_tabela
            ON migration_state(tabela);
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Connection, Engine

_metadata = MetaData()

migration_state_table = Table(
    "migration_state",
    _metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("tabela", String(100), nullable=False),
    Column("id_origem", BigInteger, nullable=False),
    Column("id_destino", BigInteger, nullable=True),
    Column("status", String(20), nullable=False, default="ok"),
    Column("migrated_at", DateTime(timezone=False), nullable=False),
    UniqueConstraint("tabela", "id_origem", name="uq_migration_state"),
)


class MigrationStateRepository:
    """Access layer for the ``migration_state`` control table.

    Example::

        repo = MigrationStateRepository()
        repo.create_table_if_not_exists(dest_engine)
        already = repo.get_migrated_ids(conn, "contacts")
        repo.record_success(conn, "contacts", id_origem=1, id_destino=226537)
    """

    def create_table_if_not_exists(self, engine: Engine) -> None:
        """Create the ``migration_state`` table and its index if absent.

        Safe to call multiple times (idempotent DDL via ``IF NOT EXISTS``).

        :param engine: Destination database engine.
        :type engine: Engine
        """
        _metadata.create_all(engine, tables=[migration_state_table], checkfirst=True)
        with engine.connect() as conn:
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_migration_state_tabela "
                    "ON migration_state(tabela)"
                )
            )
            conn.commit()

    def get_migrated_ids(self, conn: Connection, tabela: str) -> set[int]:
        """Return the set of ``id_origem`` values already migrated with status ``'ok'``.

        :param conn: Active SQLAlchemy Core connection.
        :type conn: Connection
        :param tabela: Table name to filter by.
        :type tabela: str
        :returns: Set of already-migrated source IDs.
        :rtype: set[int]
        """
        rows = conn.execute(
            select(migration_state_table.c.id_origem).where(
                migration_state_table.c.tabela == tabela,
                migration_state_table.c.status == "ok",
            )
        ).fetchall()
        return {int(row[0]) for row in rows}

    def record_success(
        self,
        conn: Connection,
        tabela: str,
        id_origem: int,
        id_destino: int,
    ) -> None:
        """Record a successfully migrated row.

        Uses ``INSERT ... ON CONFLICT DO NOTHING`` to ensure idempotency even
        if called multiple times for the same record.

        :param conn: Active SQLAlchemy Core connection.
        :type conn: Connection
        :param tabela: Table name.
        :type tabela: str
        :param id_origem: Source record ID.
        :type id_origem: int
        :param id_destino: Destination record ID after remapping.
        :type id_destino: int
        """
        conn.execute(
            insert(migration_state_table)
            .values(
                tabela=tabela,
                id_origem=id_origem,
                id_destino=id_destino,
                status="ok",
                migrated_at=datetime.now(tz=UTC).replace(tzinfo=None),
            )
            .on_conflict_do_nothing(constraint="uq_migration_state")
        )

    def record_failure(
        self,
        conn: Connection,
        tabela: str,
        id_origem: int,
        reason: str,
    ) -> None:
        """Record a failed migration attempt.

        :param conn: Active SQLAlchemy Core connection.
        :type conn: Connection
        :param tabela: Table name.
        :type tabela: str
        :param id_origem: Source record ID that failed.
        :type id_origem: int
        :param reason: Short description of the failure (no PII).
        :type reason: str
        """
        conn.execute(
            insert(migration_state_table)
            .values(
                tabela=tabela,
                id_origem=id_origem,
                id_destino=None,
                status=f"failed:{reason[:100]}",
                migrated_at=datetime.now(tz=UTC).replace(tzinfo=None),
            )
            .on_conflict_do_nothing(constraint="uq_migration_state")
        )
