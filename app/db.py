# =============================================================================
# db.py — Conexões compartilhadas
# =============================================================================
# Credenciais carregadas exclusivamente de .secrets/generate_erd.json
# (schema v2.0 — instâncias nomeadas: primeiro non-_ = SOURCE, segundo = DEST)
# Nunca imprime nem loga valores de credenciais.
# =============================================================================
import json
from pathlib import Path

import psycopg2
import psycopg2.extras

_SECRETS_PATH = Path(__file__).parent.parent / ".secrets" / "generate_erd.json"
_REQUIRED_KEYS = frozenset({"host", "port", "username", "password", "database"})


def _load_secrets() -> tuple[dict, dict]:
    """Carrega SOURCE e DEST do arquivo de secrets.

    :returns: Tupla (db_source, db_dest) com dicts prontos para psycopg2.
    :rtype: tuple[dict, dict]
    :raises FileNotFoundError: Se .secrets/generate_erd.json não existir.
    :raises KeyError: Se faltar instâncias ou campos obrigatórios.
    """
    if not _SECRETS_PATH.exists():
        raise FileNotFoundError(f"Secrets file not found: {_SECRETS_PATH}")

    data: dict = json.loads(_SECRETS_PATH.read_text())
    instances = [k for k in data if not k.startswith("_")]

    if len(instances) < 2:
        raise KeyError(
            f"secrets file must have at least 2 database instances, found {len(instances)}"
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

    return to_psycopg2(data[instances[0]]), to_psycopg2(data[instances[1]])


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
