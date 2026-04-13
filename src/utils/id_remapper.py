"""Session-scoped ID offset remapper for database migration.

:description: Provides :class:`IDRemapper` which computes, once per session,
    the maximum ID currently present in each destination table and uses that
    value as a constant offset so that source IDs never collide with existing
    destination IDs.

    Formula: ``novo_id = id_origem + offset``
    where ``offset = MAX(id)`` of the destination table at session start.
    If the destination table is empty, ``offset = 0`` and source IDs carry
    over unchanged (safe — no collision is possible with an empty table).

    >>> r = IDRemapper({"contacts": 1000, "accounts": 20})
    >>> r.remap(5, "contacts")
    1005
    >>> r.remap(1, "accounts")
    21
    >>> r.remap(99, "unknown")
    Traceback (most recent call last):
        ...
    KeyError: "Table 'unknown' not found in offsets. Call compute_offsets first."
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine


class IDRemapper:
    """Computes and applies session-constant ID offsets.

    :param offsets: Pre-computed offset dict (for testing / manual use).
        If ``None``, call :meth:`compute_offsets` before :meth:`remap`.
    :type offsets: dict[str, int] | None

    Example::

        remapper = IDRemapper()
        remapper.compute_offsets(dest_engine, list_of_table_names)
        new_id = remapper.remap(old_id, "contacts")
    """

    def __init__(self, offsets: dict[str, int] | None = None) -> None:
        """Initialise with optional pre-computed offsets.

        :param offsets: Mapping of table name → offset value.
        :type offsets: dict[str, int] | None
        """
        self._offsets: dict[str, int] = offsets or {}
        # Explicit src→dest mappings that override the offset for specific IDs.
        # Used for merge-rule accounts (same id+name) and deduped contacts.
        self._aliases: dict[str, dict[int, int]] = {}

    @property
    def offsets(self) -> dict[str, int]:
        """Return a copy of the current offset dict (read-only view).

        :returns: Copy of the offset mapping.
        :rtype: dict[str, int]
        """
        return dict(self._offsets)

    def compute_offsets(self, dest_engine: Engine, table_names: list[str]) -> dict[str, int]:
        """Query ``MAX(id)`` on each table and store offsets in-memory.

        Must be called exactly once per migration session, before any
        :meth:`remap` calls.  The result is stored as an instance attribute
        and is not recomputed on subsequent calls.

        :param dest_engine: Engine connected to the destination database.
        :type dest_engine: Engine
        :param table_names: Names of tables whose ``MAX(id)`` to query.
        :type table_names: list[str]
        :returns: Computed offset mapping (table name → offset).
        :rtype: dict[str, int]
        """
        result: dict[str, int] = {}
        with dest_engine.connect() as conn:
            for table in table_names:
                row = conn.execute(text(f"SELECT MAX(id) FROM {table}")).fetchone()  # noqa: S608
                result[table] = int(row[0]) if row and row[0] is not None else 0
        self._offsets = result
        return result

    def remap(self, id_origem: int, table: str) -> int:
        """Apply the session offset to a single source record ID.

        Aliases (registered via :meth:`register_alias`) take precedence over
        the offset — this allows merge-rule accounts and deduplicated contacts
        to map to existing destination IDs rather than offset-shifted ones.

        :param id_origem: Original ID from the source database.
        :type id_origem: int
        :param table: Table name used to look up the offset.
        :type table: str
        :returns: Remapped ID for insertion into the destination database.
        :rtype: int
        :raises KeyError: If *table* is not in the computed offsets and has no alias.

        >>> r = IDRemapper({"contacts": 500})
        >>> r.remap(1, "contacts")
        501
        >>> r.register_alias("contacts", 99, 42)
        >>> r.remap(99, "contacts")
        42
        """
        tbl_aliases = self._aliases.get(table)
        if tbl_aliases is not None and id_origem in tbl_aliases:
            return tbl_aliases[id_origem]
        if table not in self._offsets:
            raise KeyError(f"Table '{table}' not found in offsets. Call compute_offsets first.")
        return id_origem + self._offsets[table]

    def register_alias(self, table: str, src_id: int, dest_id: int) -> None:
        """Register an explicit src→dest mapping that overrides the offset.

        Used for the accounts merge rule (same id+name → reuse dest_id) and
        for contact deduplication (same account_id+phone/email → reuse dest_id).
        Must be called before any downstream :meth:`remap` call that references
        the same table and source ID.

        :param table: Table name (e.g. ``"accounts"``, ``"contacts"``).
        :type table: str
        :param src_id: Source record ID.
        :type src_id: int
        :param dest_id: Existing destination record ID to map to.
        :type dest_id: int

        >>> r = IDRemapper({"accounts": 43})
        >>> r.register_alias("accounts", 1, 1)
        >>> r.remap(1, "accounts")
        1
        >>> r.remap(4, "accounts")
        47
        """
        self._aliases.setdefault(table, {})[src_id] = dest_id
