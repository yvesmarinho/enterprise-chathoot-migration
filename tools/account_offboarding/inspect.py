"""
inspect.py — Audita todas as tabelas Chatwoot que contêm dados de um account.

Uso:
    python inspect.py --db-key <key> --account-id <id>
    python inspect.py --config config.json
    python inspect.py --config config.json --account-id 45   # override

Saída: ./<db_key>_account_<id>_audit_YYYYMMDD_HHMMSS.json

Descrição:
    Descobre dinamicamente (via pg_constraint + information_schema) todas as
    tabelas que possuem dados referenciando o account_id informado.
    Estratégias:
        - Direto: tabelas com coluna 'account_id'
        - FK: tabelas com FK para contacts/conversations/messages/inboxes/accounts
    Não executa nenhuma modificação no banco.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import psycopg2
import psycopg2.extras

_ROOT_TABLES = {"contacts", "conversations", "messages", "inboxes", "accounts"}


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def _load_config(args) -> dict:
    cfg: dict = {}

    # 1. Arquivo de config (base)
    config_path = Path(args.config) if args.config else Path(__file__).parent / "config.json"
    if config_path.exists():
        cfg = json.loads(config_path.read_text())
    elif args.config:
        print(f"[inspect] ❌ Config não encontrado: {config_path}", file=sys.stderr)
        sys.exit(1)

    # 2. CLI sobrescreve
    if args.db_key:
        cfg["db_key"] = args.db_key
    if args.account_id is not None:
        cfg["account_id"] = args.account_id

    # 3. Validações
    if not cfg.get("db_key"):
        print("[inspect] ❌ 'db_key' não definido. Use --db-key ou config.json.", file=sys.stderr)
        sys.exit(1)
    if not cfg.get("account_id"):
        print(
            "[inspect] ❌ 'account_id' não definido (ou 0). Use --account-id ou config.json.",
            file=sys.stderr,
        )
        sys.exit(1)

    return cfg


def _load_secrets(cfg: dict) -> dict:
    secrets_path = Path(cfg.get("secrets_file", "../../.secrets/generate_erd.json"))
    if not secrets_path.is_absolute():
        secrets_path = Path(__file__).parent / secrets_path
    secrets = json.loads(secrets_path.read_text())
    key = cfg["db_key"]
    if key not in secrets:
        available = [k for k in secrets if not k.startswith("_")]
        print(
            f"[inspect] ❌ Chave '{key}' não encontrada em secrets. Disponíveis: {available}",
            file=sys.stderr,
        )
        sys.exit(1)
    return secrets[key]


def _get_conn(instance: dict):
    return psycopg2.connect(
        host=instance["host"],
        port=instance["port"],
        dbname=instance["database"],
        user=instance["username"],
        password=instance["password"],
        sslmode="disable",
    )


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def _tables_with_account_id(cur) -> list[str]:
    cur.execute("""
        SELECT table_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND column_name = 'account_id'
        ORDER BY table_name
    """)
    return [r["table_name"] for r in cur.fetchall()]


def _fk_dependents(cur, parent_table: str) -> list[tuple[str, str]]:
    """Retorna [(child_table, fk_column)] para tabelas com FK → parent_table.id."""
    cur.execute(
        """
        SELECT
            child_cl.relname  AS child_table,
            child_att.attname AS fk_column
        FROM pg_constraint  con
        JOIN pg_class       child_cl  ON child_cl.oid  = con.conrelid
        JOIN pg_namespace   child_ns  ON child_ns.oid  = child_cl.relnamespace
        JOIN pg_class       parent_cl ON parent_cl.oid = con.confrelid
        JOIN pg_namespace   parent_ns ON parent_ns.oid = parent_cl.relnamespace
        JOIN pg_attribute   child_att ON child_att.attrelid = con.conrelid
                                     AND child_att.attnum = ANY(con.conkey)
        WHERE con.contype   = 'f'
          AND parent_ns.nspname = 'public'
          AND parent_cl.relname = %s
          AND child_ns.nspname  = 'public'
    """,
        (parent_table,),
    )
    return [(r["child_table"], r["fk_column"]) for r in cur.fetchall()]


def _count(cur, table: str, where_clause: str) -> int | str:
    try:
        cur.execute(f"SELECT COUNT(*) AS n FROM public.{table} WHERE {where_clause}")
        return cur.fetchone()["n"]
    except Exception as exc:
        return f"ERROR: {exc}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Audita dados de um account Chatwoot.")
    parser.add_argument(
        "--config", default=None, help="Caminho para config.json (default: ./config.json)"
    )
    parser.add_argument("--db-key", default=None, help="Chave da instância no secrets file")
    parser.add_argument("--account-id", type=int, default=None, help="ID do account a auditar")
    args = parser.parse_args()

    cfg = _load_config(args)
    instance = _load_secrets(cfg)
    account_id = cfg["account_id"]
    db_key = cfg["db_key"]

    print(f"[inspect] Conectando a '{db_key}'…")
    conn = _get_conn(instance)
    conn.set_session(readonly=True, autocommit=True)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("SELECT current_database()")
    db = cur.fetchone()["current_database"]
    print(f"[inspect] Banco: {db}  |  account_id: {account_id}")

    results: dict[str, dict] = {}

    # --- 1. Direto: tabelas com account_id ---
    direct = _tables_with_account_id(cur)
    print(f"[inspect] {len(direct)} tabelas com coluna account_id…")
    for tbl in direct:
        n = _count(cur, tbl, f"account_id = {account_id}")
        results[tbl] = {"strategy": "account_id", "count": n}

    # --- 2. FK dependents das tabelas-raiz ---
    for root in sorted(_ROOT_TABLES):
        deps = _fk_dependents(cur, root)
        for child_tbl, fk_col in deps:
            # Prioridade: se a contagem direta encontrou dados, mantém;
            # se encontrou 0, pode ser que a FK dê resultado diferente.
            if child_tbl in results and results[child_tbl]["count"] != 0:
                continue
            where = f"{fk_col} IN (SELECT id FROM {root} WHERE account_id = {account_id})"
            n = _count(cur, child_tbl, where)
            if child_tbl not in results or (
                isinstance(n, int) and n > results[child_tbl].get("count", 0)
            ):
                results[child_tbl] = {
                    "strategy": f"fk_via_{root}.{fk_col}",
                    "count": n,
                }

    cur.close()
    conn.close()

    non_zero = {t: v for t, v in results.items() if isinstance(v["count"], int) and v["count"] > 0}

    print(f"\n[inspect] {len(non_zero)} tabelas com dados do account {account_id}:")
    for tbl, v in sorted(non_zero.items(), key=lambda x: -x[1]["count"]):
        print(f"  {tbl:45s} {v['count']:>6}  ({v['strategy']})")

    total = sum(v["count"] for v in non_zero.values())
    print(f"\n[inspect] Total de linhas: {total}")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = {
        "generated_at": ts,
        "db_key": db_key,
        "effective_database": db,
        "account_id": account_id,
        "total_rows": total,
        "non_zero_tables": non_zero,
        "all_tables": results,
    }
    out_path = Path(__file__).parent / f"{db_key}_account_{account_id}_audit_{ts}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=str, ensure_ascii=False)
    print(f"[inspect] Relatório salvo em: {out_path}")


if __name__ == "__main__":
    main()
