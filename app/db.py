# =============================================================================
# db.py — Conexões compartilhadas
# =============================================================================
# Credenciais carregadas exclusivamente de .secrets/generate_erd.json
# (schema v2.0 — instâncias nomeadas)
#
# Variáveis de ambiente obrigatórias:
#   MIGRATION_SOURCE_KEY  — chave da instância SOURCE no secrets
#   MIGRATION_DEST_KEY    — chave da instância DEST no secrets
#
# Exemplo (produção):
#   export MIGRATION_SOURCE_KEY=chat-vya-digital
#   export MIGRATION_DEST_KEY=synchat-vya-digital
#
# Nunca imprime nem loga valores de credenciais.
# =============================================================================
import json
import os
from pathlib import Path

import psycopg2
import psycopg2.extras

_SECRETS_PATH = Path(__file__).parent.parent / ".secrets" / "generate_erd.json"
_REQUIRED_KEYS = frozenset({"host", "port", "username", "password", "database"})


def _load_secrets() -> tuple[dict, dict]:
    """Carrega SOURCE e DEST do arquivo de secrets usando env vars.

    :returns: Tupla (db_source, db_dest) com dicts prontos para psycopg2.
    :raises FileNotFoundError: Se .secrets/generate_erd.json não existir.
    :raises KeyError: Se faltar env vars ou instâncias/campos obrigatórios.
    """
    if not _SECRETS_PATH.exists():
        raise FileNotFoundError(f"Secrets file not found: {_SECRETS_PATH}")

    src_key = os.environ.get("MIGRATION_SOURCE_KEY", "").strip()
    dest_key = os.environ.get("MIGRATION_DEST_KEY", "").strip()

    data: dict = json.loads(_SECRETS_PATH.read_text())
    available = [k for k in data if not k.startswith("_")]

    if not src_key or not dest_key:
        raise KeyError(
            "Variáveis de ambiente obrigatórias não definidas.\n"
            f"  MIGRATION_SOURCE_KEY={'<não definido>' if not src_key else src_key!r}\n"
            f"  MIGRATION_DEST_KEY={'<não definido>' if not dest_key else dest_key!r}\n"
            f"Instâncias disponíveis no secrets: {available}\n"
            "Execute:\n"
            "  export MIGRATION_SOURCE_KEY=chat-vya-digital\n"
            "  export MIGRATION_DEST_KEY=synchat-vya-digital"
        )

    if src_key not in data:
        raise KeyError(
            f"MIGRATION_SOURCE_KEY={src_key!r} não encontrado no secrets.\n"
            f"Disponíveis: {available}"
        )
    if dest_key not in data:
        raise KeyError(
            f"MIGRATION_DEST_KEY={dest_key!r} não encontrado no secrets.\n"
            f"Disponíveis: {available}"
        )

    def to_psycopg2(inst: dict) -> dict:
        missing = _REQUIRED_KEYS - set(inst.keys())
        if missing:
            raise KeyError(f"missing keys in secrets instance: {sorted(missing)}")
        return {
            "dbname": inst["database"],
            "user": inst["username"],
            "password": inst["password"],
            "host": inst["host"],
            "port": int(inst["port"]),
        }

    return to_psycopg2(data[src_key]), to_psycopg2(data[dest_key])


_DB_SOURCE, _DB_DEST = _load_secrets()


def get_conn(db: dict):
    conn = psycopg2.connect(**db, connect_timeout=30)
    conn.autocommit = False
    with conn.cursor() as c:
        c.execute("SET statement_timeout = '300s'")
        c.execute("SET idle_in_transaction_session_timeout = '600s'")
    conn.commit()
    return conn


def src():
    return get_conn(_DB_SOURCE)


def dst():
    return get_conn(_DB_DEST)


def cur(conn):
    """Cursor que retorna dicts."""
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
