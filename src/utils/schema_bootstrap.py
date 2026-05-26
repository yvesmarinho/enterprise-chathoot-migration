"""Bootstrap destination schema from the source database.

This helper is used when the destination database was restored without the
application tables. It reflects the public schema from the source and
creates the same tables in the destination before the migration pipeline
starts.
"""

from __future__ import annotations

from typing import Iterable

from sqlalchemy import MetaData, Table, inspect
from sqlalchemy.engine import Engine


def bootstrap_public_schema(
    source_engine: Engine,
    dest_engine: Engine,
    *,
    exclude_tables: Iterable[str] | None = None,
) -> list[str]:
    """Create missing public tables in DEST from SOURCE metadata.

    :param source_engine: Read-only source engine.
    :type source_engine: Engine
    :param dest_engine: Read-write destination engine.
    :type dest_engine: Engine
    :param exclude_tables: Optional table names to skip.
    :type exclude_tables: Iterable[str] | None
    :returns: Table names considered for bootstrap.
    :rtype: list[str]
    """
    skip = set(exclude_tables or ())
    inspector = inspect(source_engine)
    table_names = [name for name in inspector.get_table_names(schema="public") if name not in skip]

    source_meta = MetaData()
    dest_meta = MetaData(schema="public")
    dest_tables = []

    for table_name in table_names:
        src_table = Table(
            table_name,
            source_meta,
            schema="public",
            autoload_with=source_engine,
        )
        dest_table = src_table.to_metadata(dest_meta, schema="public")
        dest_table.indexes.clear()
        dest_tables.append(dest_table)

    dest_meta.create_all(dest_engine, tables=dest_tables, checkfirst=True)
    return table_names


def ensure_public_table_exists(
    source_engine: Engine,
    dest_engine: Engine,
    table_name: str,
) -> bool:
    """Create a single missing public table in DEST from SOURCE metadata.

    :param source_engine: Read-only source engine.
    :type source_engine: Engine
    :param dest_engine: Read-write destination engine.
    :type dest_engine: Engine
    :param table_name: Public table name to ensure.
    :type table_name: str
    :returns: ``True`` when the table was created, ``False`` if it already
        existed.
    :rtype: bool
    """
    normalized_name = table_name.removeprefix("public.")
    if normalized_name in inspect(dest_engine).get_table_names(schema="public"):
        return False

    src_meta = MetaData()
    source_tables: dict[str, Table] = {}

    def _collect_public_dependencies(name: str) -> None:
        key = name.removeprefix("public.")
        if key in source_tables:
            return
        src_tbl = Table(
            key,
            src_meta,
            schema="public",
            autoload_with=source_engine,
        )
        source_tables[key] = src_tbl
        for fk in src_tbl.foreign_keys:
            ref_tbl = fk.column.table
            ref_schema = ref_tbl.schema or "public"
            if ref_schema == "public":
                _collect_public_dependencies(ref_tbl.name)

    _collect_public_dependencies(normalized_name)

    # Keep all FK-related tables in the same metadata graph so SQLAlchemy can
    # resolve references during CREATE TABLE ordering.
    dest_meta = MetaData(schema="public")
    dest_tables: list[Table] = []
    for src_tbl in source_tables.values():
        dst_tbl = src_tbl.to_metadata(dest_meta, schema="public")
        dst_tbl.indexes.clear()
        dest_tables.append(dst_tbl)

    dest_meta.create_all(dest_engine, tables=dest_tables, checkfirst=True)
    return True
