"""Generic bulk-insert repository using SQLAlchemy Core.

:description: Provides :class:`BaseRepository` with a single
    :meth:`bulk_insert` method that wraps a list of record dicts in an
    explicit transaction and inserts them into the given table.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, Table, insert


class BaseRepository:
    """Generic repository providing bulk-insert over SQLAlchemy Core.

    No ORM unit-of-work is used; inserts are performed via
    ``session.execute(insert(table), list_of_dicts)`` inside an explicit
    transaction per call.

    Example::

        repo = BaseRepository()
        count = repo.bulk_insert(conn, my_table, records)
    """

    def bulk_insert(
        self,
        conn: Connection,
        table: Table,
        records: list[dict[str, Any]],
    ) -> int:
        """Insert *records* into *table* within a single transaction.

        :param conn: Active SQLAlchemy Core connection.
        :type conn: Connection
        :param table: SQLAlchemy :class:`~sqlalchemy.schema.Table` object.
        :type table: Table
        :param records: List of row dicts matching the table column names.
        :type records: list[dict[str, Any]]
        :returns: Number of rows inserted (``len(records)`` on success).
        :rtype: int
        :raises Exception: Re-raises any SQLAlchemy error after rolling back.
        """
        if not records:
            return 0
        conn.execute(insert(table), records)
        return len(records)
