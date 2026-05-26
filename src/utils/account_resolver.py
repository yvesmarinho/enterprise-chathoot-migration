"""Account Resolver — Busca account_id por nome dinamicamente."""

import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


def resolve_account_id(engine: Engine, account_name: str, fuzzy: bool = True) -> Optional[int]:
    """Resolve account_id a partir do nome da conta.

    Args:
        engine: SQLAlchemy engine conectado ao banco
        account_name: Nome completo ou parcial da conta
        fuzzy: Se True, usa ILIKE com wildcards; se False, match exato

    Returns:
        account_id se encontrado, None caso contrário

    Raises:
        ValueError: Se múltiplas contas corresponderem ao nome
    """
    if fuzzy:
        # Busca parcial case-insensitive
        query = text("""
            SELECT id, name, created_at
            FROM public.accounts
            WHERE name ILIKE :pattern
            ORDER BY created_at DESC
        """)
        pattern = f"%{account_name}%"
    else:
        # Match exato
        query = text("""
            SELECT id, name, created_at
            FROM public.accounts
            WHERE name = :account_name
            ORDER BY created_at DESC
        """)
        pattern = account_name

    try:
        with engine.connect() as conn:
            results = conn.execute(
                query, {"pattern": pattern} if fuzzy else {"account_name": pattern}
            ).fetchall()
    except ProgrammingError as exc:
        if "accounts" in str(exc).lower():
            logger.warning("DEST accounts table unavailable — treating as empty DEST")
            return None
        raise

    if not results:
        logger.warning("Account '%s' not found (fuzzy=%s)", account_name, fuzzy)
        return None

    if len(results) > 1:
        matches = "\n".join(f"  - ID {r[0]}: {r[1]} (created {r[2]})" for r in results)
        raise ValueError(
            f"Multiple accounts match '{account_name}':\n{matches}\n"
            f"Use exact name or set fuzzy=False"
        )

    account_id = results[0][0]
    account_full_name = results[0][1]

    logger.info(
        "Resolved '%s' → account_id=%d ('%s')",
        account_name,
        account_id,
        account_full_name,
    )

    return account_id


def get_account_stats(engine: Engine, account_id: int) -> dict:
    """Retorna estatísticas de uma conta.

    Args:
        engine: SQLAlchemy engine
        account_id: ID da conta

    Returns:
        Dict com contadores: conversations, messages, attachments, etc.
    """
    query = text("""
        SELECT
            a.id,
            a.name,
            a.created_at,
            (SELECT COUNT(*) FROM public.conversations WHERE account_id = a.id)
                AS conv_count,
            (SELECT COUNT(*) FROM public.messages m
             JOIN public.conversations c ON c.id = m.conversation_id
             WHERE c.account_id = a.id) AS msg_count,
            (SELECT COUNT(*) FROM public.attachments att
             JOIN public.messages m ON m.id = att.message_id
             JOIN public.conversations c ON c.id = m.conversation_id
             WHERE c.account_id = a.id) AS att_count,
            (SELECT COUNT(*) FROM public.active_storage_attachments asa
             JOIN public.attachments att ON att.id = asa.record_id
                AND asa.record_type = 'Attachment'
             JOIN public.messages m ON m.id = att.message_id
             JOIN public.conversations c ON c.id = m.conversation_id
             WHERE c.account_id = a.id) AS as_count
        FROM public.accounts a
        WHERE a.id = :account_id
    """)

    try:
        with engine.connect() as conn:
            result = conn.execute(query, {"account_id": account_id}).fetchone()
    except ProgrammingError as exc:
        if "accounts" in str(exc).lower():
            return {}
        raise

    if not result:
        return {}

    return {
        "id": result[0],
        "name": result[1],
        "created_at": result[2],
        "conversations": result[3],
        "messages": result[4],
        "attachments": result[5],
        "active_storage": result[6],
        "as_coverage_pct": (round(result[6] * 100.0 / result[5], 2) if result[5] > 0 else 0.0),
    }


def find_account_by_name_in_dest(
    dest_engine: Engine, account_name: str, fuzzy: bool = True
) -> Optional[dict]:
    """Busca account no DEST por nome (exato ou fuzzy).

    Args:
        dest_engine: Engine conectado ao DEST
        account_name: Nome completo ou parcial
        fuzzy: Se True, usa ILIKE; se False, match exato

    Returns:
        Dict com id, name, created_at se encontrado; None caso contrário

    Raises:
        ValueError: Se múltiplos accounts corresponderem (fuzzy=True)
    """
    if fuzzy:
        query = text("""
            SELECT id, name, created_at
            FROM public.accounts
            WHERE name ILIKE :pattern
            ORDER BY created_at DESC
        """)
        pattern = f"%{account_name}%"
    else:
        query = text("""
            SELECT id, name, created_at
            FROM public.accounts
            WHERE name = :account_name
            ORDER BY created_at DESC
        """)
        pattern = account_name

    try:
        with dest_engine.connect() as conn:
            results = conn.execute(
                query, {"pattern": pattern} if fuzzy else {"account_name": pattern}
            ).fetchall()
    except ProgrammingError as exc:
        if "accounts" in str(exc).lower():
            logger.warning("DEST accounts table unavailable — treating as empty DEST")
            return None
        raise

    if not results:
        return None

    if len(results) > 1:
        matches = "\n".join(f"  - ID {r[0]}: {r[1]} (created {r[2]})" for r in results)
        raise ValueError(
            f"Multiple accounts match '{account_name}' in DEST:\n{matches}\n"
            f"Use exact name or set fuzzy=False"
        )

    return {
        "id": results[0][0],
        "name": results[0][1],
        "created_at": results[0][2],
    }


def check_account_exists_with_data(
    dest_engine: Engine, account_name: str
) -> tuple[bool, Optional[dict]]:
    """Verifica se account existe no DEST e se tem dados.

    Args:
        dest_engine: Engine conectado ao DEST
        account_name: Nome do account para verificar

    Returns:
        Tupla (has_data: bool, stats: dict|None)
        - has_data=True se account existe E tem conversations/messages/attachments
        - stats=dict com id, name, conversations, messages, attachments
        - stats=None se account não existe
    """
    try:
        account = find_account_by_name_in_dest(dest_engine, account_name, fuzzy=True)
    except ValueError as e:
        # Múltiplos matches — tratar como "existe com dados" para safety
        logger.error("Erro ao verificar account no DEST: %s", e)
        raise

    if not account:
        return False, None

    # Account existe — buscar estatísticas
    stats = get_account_stats(dest_engine, account["id"])

    has_data = (
        stats.get("conversations", 0) > 0
        or stats.get("messages", 0) > 0
        or stats.get("attachments", 0) > 0
    )

    return has_data, stats
