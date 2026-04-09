# =============================================================================
# db.py — Conexões compartilhadas
# =============================================================================
import psycopg2
import psycopg2.extras

DB_SOURCE = {
    "dbname":   "",
    "user":     "",
    "password": "",
    "host":     "",
    "port":     ,
}

DB_DEST = {
    "dbname":   "",
    "user":     "",
    "password": "",
    "host":     "",
    "port":     ,
}

def get_conn(db: dict):
    conn = psycopg2.connect(**db, connect_timeout=30)
    conn.autocommit = False
    # Configura timeouts na sessão
    with conn.cursor() as c:
        c.execute("SET statement_timeout = '300s'")
        c.execute("SET idle_in_transaction_session_timeout = '600s'")
    conn.commit()
    return conn

def src():
    return get_conn(DB_SOURCE)

def dst():
    return get_conn(DB_DEST)

def cur(conn):
    """Cursor que retorna dicts."""
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
