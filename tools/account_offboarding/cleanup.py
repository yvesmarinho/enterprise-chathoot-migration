"""
cleanup.py — Remove todos os dados de um account Chatwoot do banco de destino.

Uso:
    # Apenas visualiza o que seria removido (sem deletar):
    python cleanup.py --db-key <key> --account-id <id> --dry-run

    # Execução real (pede confirmação interativa):
    python cleanup.py --db-key <key> --account-id <id> --execute

    # Via config.json:
    python cleanup.py --config config.json --execute

Saída: ./<db_key>_account_<id>_cleanup_YYYYMMDD_HHMMSS.json

Ordem de deleção (respeita FK constraints do schema Chatwoot).
Executa em transação única — ROLLBACK automático se qualquer DELETE falhar.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import psycopg2
import psycopg2.extras


# Ordem de deleção — cada item: (table_name, WHERE_clause)
# Usa %(aid)s para account_id. Tabelas sem account_id direto usam subquery.
def _sql(table: str, where: str) -> tuple[str, str, str]:
    return (
        table,
        f"DELETE FROM public.{table} WHERE {where}",
        f"SELECT COUNT(*) AS n FROM public.{table} WHERE {where}",
    )


_STEPS: list[tuple[str, str, str]] = [
    # --- Dependentes de messages ---
    _sql("attachments", "account_id = %(aid)s"),
    _sql("mentions", "account_id = %(aid)s"),
    _sql("reporting_events", "account_id = %(aid)s"),
    _sql("messages", "account_id = %(aid)s"),
    # --- Dependentes de conversations ---
    _sql("conversation_participants", "account_id = %(aid)s"),
    _sql("csat_survey_responses", "account_id = %(aid)s"),
    _sql("applied_slas", "account_id = %(aid)s"),
    _sql("sla_events", "account_id = %(aid)s"),
    _sql(
        "contact_inboxes",
        "contact_id IN (SELECT id FROM public.contacts WHERE account_id = %(aid)s)",
    ),
    _sql("conversations", "account_id = %(aid)s"),
    # --- Dependentes de contacts ---
    _sql("contacts", "account_id = %(aid)s"),
    # --- Dependentes de inboxes ---
    _sql("agent_bot_inboxes", "account_id = %(aid)s"),
    _sql("inbox_members", "inbox_id IN (SELECT id FROM public.inboxes WHERE account_id = %(aid)s)"),
    _sql("working_hours", "account_id = %(aid)s"),
    _sql("channel_api", "account_id = %(aid)s"),
    _sql("channel_whatsapp", "account_id = %(aid)s"),
    _sql("channel_web_widgets", "account_id = %(aid)s"),
    _sql("channel_email", "account_id = %(aid)s"),
    _sql("channel_facebook_pages", "account_id = %(aid)s"),
    _sql("channel_telegram", "account_id = %(aid)s"),
    _sql("channel_sms", "account_id = %(aid)s"),
    _sql("channel_twilio_sms", "account_id = %(aid)s"),
    _sql("channel_line", "account_id = %(aid)s"),
    _sql("channel_twitter_profiles", "account_id = %(aid)s"),
    _sql("inboxes", "account_id = %(aid)s"),
    # --- Agent bots (após agent_bot_inboxes) ---
    _sql("agent_bots", "account_id = %(aid)s"),
    # --- Notificações ---
    _sql("notification_settings", "account_id = %(aid)s"),
    _sql("notifications", "account_id = %(aid)s"),
    # --- Teams ---
    _sql("team_memberships", "team_id IN (SELECT id FROM public.teams WHERE account_id = %(aid)s)"),
    _sql("teams", "account_id = %(aid)s"),
    # --- Portals / Knowledge Base ---
    _sql(
        "portal_members", "portal_id IN (SELECT id FROM public.portals WHERE account_id = %(aid)s)"
    ),
    _sql("categories", "account_id = %(aid)s"),
    _sql("articles", "account_id = %(aid)s"),
    _sql("folders", "account_id = %(aid)s"),
    _sql("portals", "account_id = %(aid)s"),
    # --- Demais tabelas de nível account ---
    _sql("labels", "account_id = %(aid)s"),
    _sql("canned_responses", "account_id = %(aid)s"),
    _sql("automation_rules", "account_id = %(aid)s"),
    _sql("macros", "account_id = %(aid)s"),
    _sql("campaigns", "account_id = %(aid)s"),
    _sql("dashboard_apps", "account_id = %(aid)s"),
    _sql("custom_attribute_definitions", "account_id = %(aid)s"),
    _sql("custom_filters", "account_id = %(aid)s"),
    _sql("custom_roles", "account_id = %(aid)s"),
    _sql("data_imports", "account_id = %(aid)s"),
    _sql("email_templates", "account_id = %(aid)s"),
    _sql("sla_policies", "account_id = %(aid)s"),
    _sql("webhooks", "account_id = %(aid)s"),
    _sql("integrations_hooks", "account_id = %(aid)s"),
    _sql("telegram_bots", "account_id = %(aid)s"),
    # --- Vínculo users↔account (não remove users) ---
    _sql("account_users", "account_id = %(aid)s"),
    # --- Raiz ---
    _sql("accounts", "id = %(aid)s"),
]


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def _load_config(args) -> dict:
    cfg: dict = {}

    config_path = Path(args.config) if args.config else Path(__file__).parent / "config.json"
    if config_path.exists():
        cfg = json.loads(config_path.read_text())
    elif args.config:
        print(f"[cleanup] ❌ Config não encontrado: {config_path}", file=sys.stderr)
        sys.exit(1)

    if args.db_key:
        cfg["db_key"] = args.db_key
    if args.account_id is not None:
        cfg["account_id"] = args.account_id

    if not cfg.get("db_key"):
        print("[cleanup] ❌ 'db_key' não definido. Use --db-key ou config.json.", file=sys.stderr)
        sys.exit(1)
    if not cfg.get("account_id"):
        print(
            "[cleanup] ❌ 'account_id' não definido (ou 0). Use --account-id ou config.json.",
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
            f"[cleanup] ❌ Chave '{key}' não encontrada em secrets. Disponíveis: {available}",
            file=sys.stderr,
        )
        sys.exit(1)
    return secrets[key]


def _get_conn(instance: dict):
    conn = psycopg2.connect(
        host=instance["host"],
        port=instance["port"],
        dbname=instance["database"],
        user=instance["username"],
        password=instance["password"],
        sslmode="disable",
    )
    conn.autocommit = False
    return conn


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Remove todos os dados de um account Chatwoot.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config", default=None, help="Caminho para config.json (default: ./config.json)"
    )
    parser.add_argument("--db-key", default=None, help="Chave da instância no secrets file")
    parser.add_argument("--account-id", type=int, default=None, help="ID do account a remover")

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run", action="store_true", help="Apenas mostra o que seria removido (sem deletar)"
    )
    mode.add_argument(
        "--execute", action="store_true", help="Executa a deleção real (pede confirmação)"
    )

    args = parser.parse_args()

    cfg = _load_config(args)
    instance = _load_secrets(cfg)
    account_id = cfg["account_id"]
    db_key = cfg["db_key"]
    dry_run = args.dry_run

    mode_label = "DRY-RUN" if dry_run else "EXECUÇÃO REAL"
    print(f"[cleanup] Modo: {mode_label}")
    print(f"[cleanup] Conectando a '{db_key}'…")

    conn = _get_conn(instance)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Força leitura/escrita (case o role tenha default_transaction_read_only=on)
    cur.execute("SET SESSION default_transaction_read_only = off")
    conn.commit()

    cur.execute("SELECT current_database()")
    db = cur.fetchone()["current_database"]
    print(f"[cleanup] Banco: {db}  |  account_id: {account_id}")

    params = {"aid": account_id}
    log: list[dict] = []
    pre_counts: dict[str, int] = {}
    post_counts: dict[str, int] = {}
    residual = 0
    verdict = ""

    try:
        # --- PRÉ-CONTAGEM ---
        print(f"\n[cleanup] Contagem pré-deleção:")
        for label, _, count_sql in _STEPS:
            try:
                cur.execute(count_sql, params)
                n = cur.fetchone()["n"]
            except psycopg2.Error:
                conn.rollback()
                n = 0
            pre_counts[label] = n
            if n > 0:
                print(f"  {label:25s} {n:>6}")

        total_pre = sum(pre_counts.values())
        if total_pre == 0:
            print(
                f"\n[cleanup] ✅ Nenhum dado encontrado para account_id={account_id} — nada a fazer."
            )
            cur.close()
            conn.close()
            return

        print(f"\n[cleanup] Total a remover: {total_pre:,}")

        if dry_run:
            print(f"\n[cleanup] DRY-RUN concluído — nenhuma deleção executada.")
            conn.rollback()
            conn.close()
            return

        # --- CONFIRMAÇÃO ---
        print(f"\n⚠️  Você está prestes a DELETAR permanentemente {total_pre:,} linhas")
        print(f"   Banco  : {db}")
        print(f"   Account: {account_id}")
        confirm = input("\nDigite o account_id para confirmar: ").strip()
        if confirm != str(account_id):
            print("[cleanup] Confirmação incorreta — operação cancelada.")
            conn.rollback()
            conn.close()
            sys.exit(0)

        # --- DELEÇÃO ---
        print(f"\n[cleanup] Iniciando transação…")
        for label, delete_sql, _ in _STEPS:
            if pre_counts.get(label, 0) == 0:
                log.append({"table": label, "deleted": 0, "skipped": True})
                continue
            cur.execute(delete_sql, params)
            deleted = cur.rowcount
            log.append({"table": label, "deleted": deleted, "skipped": False})
            print(f"  DELETE {label:25s} → {deleted:,} linhas removidas")

        conn.commit()
        print(f"\n[cleanup] ✅ COMMIT efetuado.")

        # --- PÓS-VERIFICAÇÃO ---
        print(f"\n[cleanup] Verificação pós-deleção:")
        for label, _, count_sql in _STEPS:
            try:
                cur.execute(count_sql, params)
                n = cur.fetchone()["n"]
            except psycopg2.Error:
                conn.rollback()
                n = 0
            post_counts[label] = n
            status = "✅" if n == 0 else "❌ AINDA EXISTE"
            if pre_counts.get(label, 0) > 0 or n > 0:
                print(f"  {label:25s} {n:>6}  {status}")

        residual = sum(post_counts.values())
        verdict = "✅ LIMPEZA COMPLETA" if residual == 0 else f"❌ {residual:,} linhas residuais"
        print(f"\n[cleanup] {verdict}")

    except Exception as exc:
        conn.rollback()
        print(f"\n[cleanup] ❌ ROLLBACK — erro: {exc}", file=sys.stderr)
        cur.close()
        conn.close()
        raise

    cur.close()
    conn.close()

    # --- LOG JSON ---
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = {
        "generated_at": ts,
        "mode": mode_label,
        "db_key": db_key,
        "effective_database": db,
        "account_id": account_id,
        "pre_counts": pre_counts,
        "deletions": log,
        "post_counts": post_counts,
        "residual_rows": residual,
        "verdict": verdict,
    }
    out_path = Path(__file__).parent / f"{db_key}_account_{account_id}_cleanup_{ts}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=str, ensure_ascii=False)
    print(f"[cleanup] Log salvo em: {out_path}")


if __name__ == "__main__":
    main()
