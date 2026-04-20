"""Diagnóstico de perda de dados pós-restauração dos bancos.

:description: Compara SOURCE (chatwoot_dev1_db) vs DEST (chatwoot004_dev1_db)
    por account para identificar onde ocorreu perda de conversas e anexos.

    Usa apenas queries simples (COUNT/GROUP BY) sem LEFT JOIN pesado para
    evitar timeout em tabelas de milhões de registros.

    Saída:
        .tmp/diagnostico_perda_YYYYMMDD_HHMMSS.json   — dados brutos
        .tmp/diagnostico_perda_YYYYMMDD_HHMMSS.csv    — tabela legível

Usage::

    python app/08_diagnostico_perda_dados.py
"""

from __future__ import annotations

import csv
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Connection

# Garante que src/ está no path quando executado diretamente
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from src.factory.connection_factory import ConnectionFactory  # noqa: E402

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
_LOG_DIR = _ROOT / ".tmp"
_LOG_DIR.mkdir(parents=True, exist_ok=True)
_TS = datetime.now().strftime("%Y%m%d_%H%M%S")  # noqa: DTZ005

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(_LOG_DIR / f"diagnostico_perda_{_TS}.log"), encoding="utf-8"),
    ],
)
log = logging.getLogger("diagnostico_perda")

# ---------------------------------------------------------------------------
# Queries — apenas COUNT simples, sem LEFT JOIN pesado
# ---------------------------------------------------------------------------

_SQL_ACCOUNTS = "SELECT id, name, status FROM accounts ORDER BY id"

_SQL_COUNT_BY_ACCOUNT = """
SELECT account_id, COUNT(*) AS total
FROM {table}
GROUP BY account_id
ORDER BY account_id
"""

_SQL_TOTALS = "SELECT COUNT(*) AS total FROM {table}"

_SQL_MIGRATION_STATE = """
SELECT tabela,
       COUNT(*) AS registrado,
       SUM(CASE WHEN dest_id IS NOT NULL THEN 1 ELSE 0 END) AS com_dest_id
FROM migration_state
GROUP BY tabela
ORDER BY tabela
"""

# FK violations — usa NOT IN com subquery de account_ids válidos (pequena)
# Muito mais leve que LEFT JOIN em tabelas de milhões de linhas.
_SQL_FK_CONV_NO_ACCOUNT = """
SELECT account_id, COUNT(*) AS total
FROM conversations
WHERE account_id NOT IN (SELECT id FROM accounts)
GROUP BY account_id
ORDER BY account_id
"""

_SQL_FK_MSG_NO_ACCOUNT = """
SELECT account_id, COUNT(*) AS total
FROM messages
WHERE account_id NOT IN (SELECT id FROM accounts)
GROUP BY account_id
ORDER BY account_id
"""

_SQL_FK_ATT_NO_MSG = """
SELECT COUNT(*) AS total
FROM attachments
WHERE message_id NOT IN (SELECT id FROM messages)
"""

_SQL_FK_CONTACT_NO_ACCOUNT = """
SELECT account_id, COUNT(*) AS total
FROM contacts
WHERE account_id NOT IN (SELECT id FROM accounts)
GROUP BY account_id
ORDER BY account_id
"""


def _fetch_count_by_account(conn: Connection, table: str) -> dict[int, int]:
    """Retorna {account_id: count} para a tabela informada."""
    rows = conn.execute(text(_SQL_COUNT_BY_ACCOUNT.format(table=table))).fetchall()
    return {int(r[0]): int(r[1]) for r in rows}


def _fetch_total(conn: Connection, table: str) -> int:
    """Retorna COUNT(*) da tabela."""
    row = conn.execute(text(_SQL_TOTALS.format(table=table))).fetchone()
    return int(row[0]) if row else 0


def _migration_state_exists(conn: Connection) -> bool:
    """Verifica se a tabela migration_state existe no DEST."""
    row = conn.execute(
        text(
            "SELECT EXISTS("
            "  SELECT 1 FROM information_schema.tables"
            "  WHERE table_schema='public' AND table_name='migration_state'"
            ")"
        )
    ).fetchone()
    return bool(row[0]) if row else False


def main() -> None:
    log.info("=== Diagnóstico de Perda de Dados — %s ===", _TS)

    factory = ConnectionFactory()
    src_engine = factory.create_source_engine()
    dest_engine = factory.create_dest_engine()

    report: dict = {
        "timestamp": _TS,
        "source_db": "chatwoot_dev1_db",
        "dest_db": "chatwoot004_dev1_db",
    }

    # ------------------------------------------------------------------
    # SOURCE — inventário completo
    # ------------------------------------------------------------------
    log.info("Coletando dados do SOURCE (chatwoot_dev1_db)...")
    with src_engine.connect() as src:
        src_accounts = {
            int(r[0]): {"name": str(r[1]), "status": r[2]}
            for r in src.execute(text(_SQL_ACCOUNTS)).fetchall()
        }
        src_contacts = _fetch_count_by_account(src, "contacts")
        src_convs = _fetch_count_by_account(src, "conversations")
        src_msgs = _fetch_count_by_account(src, "messages")
        src_atts = _fetch_count_by_account(src, "attachments")
        src_total_contacts = _fetch_total(src, "contacts")
        src_total_convs = _fetch_total(src, "conversations")
        src_total_msgs = _fetch_total(src, "messages")
        src_total_atts = _fetch_total(src, "attachments")

    log.info(
        "SOURCE totais — accounts=%d contacts=%d conversations=%d messages=%d attachments=%d",
        len(src_accounts),
        src_total_contacts,
        src_total_convs,
        src_total_msgs,
        src_total_atts,
    )
    report["source"] = {
        "accounts": src_accounts,
        "totals": {
            "contacts": src_total_contacts,
            "conversations": src_total_convs,
            "messages": src_total_msgs,
            "attachments": src_total_atts,
        },
    }

    # ------------------------------------------------------------------
    # DEST — inventário completo
    # ------------------------------------------------------------------
    log.info("Coletando dados do DEST (chatwoot004_dev1_db)...")
    with dest_engine.connect() as dest:
        dest_accounts = {
            int(r[0]): {"name": str(r[1]), "status": r[2]}
            for r in dest.execute(text(_SQL_ACCOUNTS)).fetchall()
        }
        dest_contacts = _fetch_count_by_account(dest, "contacts")
        dest_convs = _fetch_count_by_account(dest, "conversations")
        dest_msgs = _fetch_count_by_account(dest, "messages")
        dest_atts = _fetch_count_by_account(dest, "attachments")
        dest_total_contacts = _fetch_total(dest, "contacts")
        dest_total_convs = _fetch_total(dest, "conversations")
        dest_total_msgs = _fetch_total(dest, "messages")
        dest_total_atts = _fetch_total(dest, "attachments")

        # FK violations no DEST — queries leves com NOT IN
        log.info("Verificando FK violations no DEST (NOT IN queries)...")
        fk_conv_no_account = {
            int(r[0]): int(r[1]) for r in dest.execute(text(_SQL_FK_CONV_NO_ACCOUNT)).fetchall()
        }
        log.info("  conv→account: %d violações", sum(fk_conv_no_account.values()))

        fk_msg_no_account = {
            int(r[0]): int(r[1]) for r in dest.execute(text(_SQL_FK_MSG_NO_ACCOUNT)).fetchall()
        }
        log.info("  msg→account: %d violações", sum(fk_msg_no_account.values()))

        fk_att_no_msg = int((dest.execute(text(_SQL_FK_ATT_NO_MSG)).fetchone() or [0])[0])
        log.info("  att→message: %d violações", fk_att_no_msg)

        fk_contact_no_account = {
            int(r[0]): int(r[1]) for r in dest.execute(text(_SQL_FK_CONTACT_NO_ACCOUNT)).fetchall()
        }
        log.info("  contact→account: %d violações", sum(fk_contact_no_account.values()))

        # migration_state
        migration_state_data: list[dict] = []
        if _migration_state_exists(dest):
            log.info("migration_state encontrada no DEST — coletando cobertura...")
            rows = dest.execute(text(_SQL_MIGRATION_STATE)).fetchall()
            migration_state_data = [
                {"tabela": str(r[0]), "registrado": int(r[1]), "com_dest_id": int(r[2])}
                for r in rows
            ]
        else:
            log.warning(
                "migration_state NÃO encontrada no DEST — banco foi restaurado sem tabela de controle"
            )

    log.info(
        "DEST totais — accounts=%d contacts=%d conversations=%d messages=%d attachments=%d",
        len(dest_accounts),
        dest_total_contacts,
        dest_total_convs,
        dest_total_msgs,
        dest_total_atts,
    )

    report["dest"] = {
        "accounts": dest_accounts,
        "totals": {
            "contacts": dest_total_contacts,
            "conversations": dest_total_convs,
            "messages": dest_total_msgs,
            "attachments": dest_total_atts,
        },
        "fk_violations": {
            "conversations_sem_account": fk_conv_no_account,
            "messages_sem_account": fk_msg_no_account,
            "attachments_sem_message": fk_att_no_msg,
            "contacts_sem_account": fk_contact_no_account,
        },
        "migration_state": migration_state_data,
    }

    # ------------------------------------------------------------------
    # Comparação account a account (SOURCE accounts migrados)
    # Mapeamento esperado baseado no último log: src→dest
    # 1→1, 4→47, 17→17, 18→61, 25→68
    # ------------------------------------------------------------------
    ACCOUNT_MAP: dict[int, int] = {1: 1, 4: 47, 17: 17, 18: 61, 25: 68}

    comparison: list[dict] = []
    for src_id, dest_id in ACCOUNT_MAP.items():
        src_name = src_accounts.get(src_id, {}).get("name", "?")
        dest_name = dest_accounts.get(dest_id, {}).get("name", "?")

        row: dict = {
            "src_account_id": src_id,
            "dest_account_id": dest_id,
            "src_name": src_name,
            "dest_name": dest_name,
            "src_contacts": src_contacts.get(src_id, 0),
            "dest_contacts": dest_contacts.get(dest_id, 0),
            "delta_contacts": dest_contacts.get(dest_id, 0) - src_contacts.get(src_id, 0),
            "src_conversations": src_convs.get(src_id, 0),
            "dest_conversations": dest_convs.get(dest_id, 0),
            "delta_conversations": dest_convs.get(dest_id, 0) - src_convs.get(src_id, 0),
            "src_messages": src_msgs.get(src_id, 0),
            "dest_messages": dest_msgs.get(dest_id, 0),
            "delta_messages": dest_msgs.get(dest_id, 0) - src_msgs.get(src_id, 0),
            "src_attachments": src_atts.get(src_id, 0),
            "dest_attachments": dest_atts.get(dest_id, 0),
            "delta_attachments": dest_atts.get(dest_id, 0) - src_atts.get(src_id, 0),
        }

        # Flags de perda
        row["perda_conversas"] = row["delta_conversations"] < 0
        row["perda_mensagens"] = row["delta_messages"] < 0
        row["perda_anexos"] = row["delta_attachments"] < 0

        comparison.append(row)

        status = (
            "✅"
            if not any([row["perda_conversas"], row["perda_mensagens"], row["perda_anexos"]])
            else "❌"
        )
        log.info(
            "%s src_account=%d(%s) → dest_account=%d(%s) | "
            "conv: %d→%d (Δ%+d) | msg: %d→%d (Δ%+d) | att: %d→%d (Δ%+d)",
            status,
            src_id,
            src_name,
            dest_id,
            dest_name,
            row["src_conversations"],
            row["dest_conversations"],
            row["delta_conversations"],
            row["src_messages"],
            row["dest_messages"],
            row["delta_messages"],
            row["src_attachments"],
            row["dest_attachments"],
            row["delta_attachments"],
        )

    report["comparison_by_account"] = comparison

    # ------------------------------------------------------------------
    # Resumo FK violations
    # ------------------------------------------------------------------
    total_fk_conv_no_account = sum(fk_conv_no_account.values())
    total_fk_msg_no_account = sum(fk_msg_no_account.values())
    total_fk_contacts_no_account = sum(fk_contact_no_account.values())

    log.info(
        "FK VIOLATIONS DEST — conv_sem_account=%d | msg_sem_account=%d | "
        "att_sem_msg=%d | contacts_sem_account=%d",
        total_fk_conv_no_account,
        total_fk_msg_no_account,
        fk_att_no_msg,
        total_fk_contacts_no_account,
    )

    report["fk_violations_summary"] = {
        "conversations_sem_account_total": total_fk_conv_no_account,
        "messages_sem_account_total": total_fk_msg_no_account,
        "attachments_sem_message_total": fk_att_no_msg,
        "contacts_sem_account_total": total_fk_contacts_no_account,
    }

    report["migration_state_presente_no_dest"] = bool(migration_state_data)

    # ------------------------------------------------------------------
    # Persistência: JSON
    # ------------------------------------------------------------------
    json_path = _LOG_DIR / f"diagnostico_perda_{_TS}.json"
    json_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    log.info("JSON salvo: %s", json_path)

    # ------------------------------------------------------------------
    # Persistência: CSV (comparação por account)
    # ------------------------------------------------------------------
    csv_path = _LOG_DIR / f"diagnostico_perda_{_TS}.csv"
    if comparison:
        fieldnames = list(comparison[0].keys())
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(comparison)
        log.info("CSV salvo: %s", csv_path)

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Resumo final no log
    # ------------------------------------------------------------------
    log.info("=== RESUMO FINAL ===")
    log.info(
        "SOURCE: %d accounts | %d convs | %d msgs | %d atts",
        len(src_accounts),
        src_total_convs,
        src_total_msgs,
        src_total_atts,
    )
    log.info(
        "DEST  : %d accounts | %d convs | %d msgs | %d atts | fk_violations conv=%d msg=%d att=%d",
        len(dest_accounts),
        dest_total_convs,
        dest_total_msgs,
        dest_total_atts,
        total_fk_conv_no_account,
        total_fk_msg_no_account,
        fk_att_no_msg,
    )
    log.info(
        "migration_state no DEST: %s",
        "SIM" if migration_state_data else "NÃO — banco restaurado sem tabela de controle",
    )
    log.info("Arquivos gerados: %s | %s", json_path.name, csv_path.name if comparison else "N/A")


if __name__ == "__main__":
    main()
