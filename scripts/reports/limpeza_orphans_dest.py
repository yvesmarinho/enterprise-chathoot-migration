#!/usr/bin/env python3
"""Limpeza de dados orphans no DEST (chatwoot004_dev1_db).

Remove registros com FK violations causadas por accounts removidas, que
são PRÉ-EXISTENTES no DEST e não têm relação com a migração RUN-8.

Modo padrão: DRY-RUN (apenas conta, não deleta nada).
Para executar de verdade:  python3 ... --execute

Deleção em ordem segura de dependência (filhos antes dos pais):
  1. attachments       (FK → messages)
  2. notifications     (FK → conversations, se existir)
  3. conversation_participants (FK → conversations, se existir)
  4. messages          (FK → conversations)
  5. contact_inboxes   (FK → contacts, inboxes)
  6. conversations     (FK → accounts, contacts, inboxes)
  7. contacts          (FK → accounts)

Critério: account_id NOT IN (SELECT id FROM public.accounts)
  — ou —  fk referencing a removed parent

Uso:
  cd <projeto_root>
  python3 scripts/reports/limpeza_orphans_dest.py             # dry-run
  python3 scripts/reports/limpeza_orphans_dest.py --execute   # deleta de verdade
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "app"))

from db import cur, dst

SEP = "=" * 76
SEP2 = "-" * 76

DRY_RUN = "--execute" not in sys.argv


# ── helpers ───────────────────────────────────────────────────────────────────


def section(title: str) -> None:
    print(f"\n{SEP}")
    print(f"  {title}")
    print(SEP)


def subsection(title: str) -> None:
    print(f"\n{SEP2}")
    print(f"  {title}")
    print(SEP2)


def scalar(conn, sql: str, params: tuple = ()):
    with cur(conn) as c:
        c.execute(sql, params)
        row = c.fetchone()
        return list(row.values())[0] if row else None


def table_exists(conn, table_name: str) -> bool:
    result = scalar(
        conn,
        "SELECT COUNT(1) FROM information_schema.tables WHERE table_schema='public' AND table_name=%s",
        (table_name,),
    )
    return bool(result)


def column_exists(conn, table_name: str, column_name: str) -> bool:
    result = scalar(
        conn,
        "SELECT COUNT(1) FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=%s AND column_name=%s",
        (table_name, column_name),
    )
    return bool(result)


def count_orphans(conn, sql: str) -> int:
    return scalar(conn, sql) or 0


def delete_orphans(conn, table: str, where_clause: str, dry_run: bool) -> int:
    """Conta e opcionalmente deleta orphans de uma tabela."""
    count_sql = f"SELECT COUNT(1) FROM public.{table} WHERE {where_clause}"
    n = count_orphans(conn, count_sql)
    if n == 0:
        print(f"  ✅ {table:<25}  0 orphans — nada a fazer")
        return 0

    if dry_run:
        print(f"  ⚠️  {table:<25}  {n:>10,} orphans  [DRY-RUN — não deletado]")
    else:
        with cur(conn) as c:
            c.execute(f"DELETE FROM public.{table} WHERE {where_clause}")
            deleted = c.rowcount
        conn.commit()
        print(f"  🗑️  {table:<25}  {deleted:>10,} orphans DELETADOS")
        return deleted

    return n


# ── Diagnóstico ───────────────────────────────────────────────────────────────


def diagnostico(dc) -> dict:
    section("DIAGNÓSTICO — Orphans a remover")

    # Orphan accounts_ids presentes no DEST mas sem registro em accounts
    orphan_account_ids_sql = """
        SELECT DISTINCT account_id FROM (
            SELECT account_id FROM public.contacts
            UNION
            SELECT account_id FROM public.conversations
            UNION
            SELECT account_id FROM public.messages
        ) t
        WHERE account_id NOT IN (SELECT id FROM public.accounts)
        ORDER BY account_id
    """
    with cur(dc) as c:
        c.execute(orphan_account_ids_sql)
        orphan_acc_ids = [row["account_id"] for row in c.fetchall()]

    print(f"\n  account_ids inválidos no DEST: {len(orphan_acc_ids)}")
    print(f"  IDs: {orphan_acc_ids}")

    counts = {}

    print(f"\n  {'TABELA':<28}  {'ORPHANS':>12}  CONDIÇÃO")
    print(f"  {'-'*28}  {'-'*12}  {'-'*45}")

    # contacts orphans
    n = count_orphans(
        dc,
        "SELECT COUNT(1) FROM public.contacts "
        "WHERE account_id NOT IN (SELECT id FROM public.accounts)",
    )
    counts["contacts"] = n
    print(f"  {'contacts':<28}  {n:>12,}  account_id sem account")

    # conversations orphans
    n = count_orphans(
        dc,
        "SELECT COUNT(1) FROM public.conversations "
        "WHERE account_id NOT IN (SELECT id FROM public.accounts)",
    )
    counts["conversations"] = n
    print(f"  {'conversations':<28}  {n:>12,}  account_id sem account")

    # messages dependentes de conversations orphans
    n = count_orphans(
        dc,
        "SELECT COUNT(1) FROM public.messages m "
        "WHERE NOT EXISTS (SELECT 1 FROM public.conversations c WHERE c.id = m.conversation_id)",
    )
    counts["messages_no_conv"] = n
    print(f"  {'messages (sem conversation)':<28}  {n:>12,}  conversation_id inexistente")

    # messages com account_id inválido (mas conversations ok)
    n = count_orphans(
        dc,
        "SELECT COUNT(1) FROM public.messages m "
        "WHERE account_id NOT IN (SELECT id FROM public.accounts) "
        "AND EXISTS (SELECT 1 FROM public.conversations c WHERE c.id = m.conversation_id)",
    )
    counts["messages_no_account"] = n
    print(f"  {'messages (sem account)':<28}  {n:>12,}  account_id sem account (conv ok)")

    # attachments sem message válida
    n = count_orphans(
        dc,
        "SELECT COUNT(1) FROM public.attachments att "
        "WHERE NOT EXISTS (SELECT 1 FROM public.messages m WHERE m.id = att.message_id)",
    )
    counts["attachments"] = n
    print(f"  {'attachments':<28}  {n:>12,}  message_id inexistente")

    # contact_inboxes sem contact
    n = count_orphans(
        dc,
        "SELECT COUNT(1) FROM public.contact_inboxes ci "
        "WHERE NOT EXISTS (SELECT 1 FROM public.contacts ct WHERE ct.id = ci.contact_id)",
    )
    counts["contact_inboxes_no_contact"] = n
    print(f"  {'contact_inboxes (sem contact)':<28}  {n:>12,}  contact_id inexistente")

    # contact_inboxes sem inbox
    n = count_orphans(
        dc,
        "SELECT COUNT(1) FROM public.contact_inboxes ci "
        "WHERE NOT EXISTS (SELECT 1 FROM public.inboxes i WHERE i.id = ci.inbox_id)",
    )
    counts["contact_inboxes_no_inbox"] = n
    print(f"  {'contact_inboxes (sem inbox)':<28}  {n:>12,}  inbox_id inexistente")

    # Optional tables
    for tbl, fk_col, parent_tbl in [
        ("notifications", "conversation_id", "conversations"),
        ("conversation_participants", "conversation_id", "conversations"),
        ("conversation_labels", "conversation_id", "conversations"),
    ]:
        if not table_exists(dc, tbl):
            continue
        if not column_exists(dc, tbl, fk_col):
            print(f"  —  {tbl:<28}  (coluna {fk_col} não existe — ignorado)")
            continue
        n = count_orphans(
            dc,
            f"SELECT COUNT(1) FROM public.{tbl} t "
            f"WHERE NOT EXISTS (SELECT 1 FROM public.{parent_tbl} p WHERE p.id = t.{fk_col})",
        )
        counts[tbl] = n
        print(f"  {tbl:<28}  {n:>12,}  {fk_col} inexistente")

    # conversations com contact_id inválido (nullable — UPDATE, não DELETE)
    n = count_orphans(
        dc,
        "SELECT COUNT(1) FROM public.conversations "
        "WHERE contact_id IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM public.contacts ct WHERE ct.id = contact_id)",
    )
    counts["conversations_bad_contact"] = n
    print(
        f"  {'conversations (contact inválido)':<28}  {n:>12,}  contact_id inválido — será NULL-ificado"
    )

    total = sum(v for v in counts.values())
    print(f"\n  {'TOTAL orphans detectados':<28}  {total:>12,}")
    return counts


# ── Limpeza ────────────────────────────────────────────────────────────────────


def executar_limpeza(dc, dry_run: bool) -> None:
    mode = (
        "DRY-RUN — NENHUM DADO SERÁ ALTERADO" if dry_run else "⚡ MODO EXECUÇÃO — DELETANDO ORPHANS"
    )
    section(f"LIMPEZA — {mode}")

    print(f"\n  {'TABELA':<28}  {'QTD':>12}  AÇÃO")
    print(f"  {'-'*28}  {'-'*12}  {'-'*20}")

    total_deleted = 0

    # Ordem: filhos antes dos pais
    steps = [
        # 1. attachments sem message válida
        ("attachments", "NOT EXISTS (SELECT 1 FROM public.messages m WHERE m.id = message_id)"),
        # 2. Tabelas opcionais que dependem de conversations
        (
            "notifications",
            "NOT EXISTS (SELECT 1 FROM public.conversations c WHERE c.id = conversation_id)",
            True,
        ),  # flag: opcional
        (
            "conversation_participants",
            "NOT EXISTS (SELECT 1 FROM public.conversations c WHERE c.id = conversation_id)",
            True,
        ),
        (
            "conversation_labels",
            "NOT EXISTS (SELECT 1 FROM public.conversations c WHERE c.id = conversation_id)",
            True,
        ),
        # 3. messages sem conversation válida
        (
            "messages",
            "NOT EXISTS (SELECT 1 FROM public.conversations c WHERE c.id = conversation_id)",
        ),
        # 4. messages com account_id inválido
        ("messages", "account_id NOT IN (SELECT id FROM public.accounts)"),
        # 5. contact_inboxes sem contact ou inbox válido
        (
            "contact_inboxes",
            "NOT EXISTS (SELECT 1 FROM public.contacts ct WHERE ct.id = contact_id)",
        ),
        ("contact_inboxes", "NOT EXISTS (SELECT 1 FROM public.inboxes i WHERE i.id = inbox_id)"),
        # 6. conversations com account_id inválido
        ("conversations", "account_id NOT IN (SELECT id FROM public.accounts)"),
        # 7. contacts com account_id inválido
        ("contacts", "account_id NOT IN (SELECT id FROM public.accounts)"),
        # 8. mop-up: attachments que ficaram órfãos após deleção das messages acima
        ("attachments", "NOT EXISTS (SELECT 1 FROM public.messages m WHERE m.id = message_id)"),
        # 9. mop-up: contact_inboxes que ficaram órfãos após deleção dos contacts acima
        (
            "contact_inboxes",
            "NOT EXISTS (SELECT 1 FROM public.contacts ct WHERE ct.id = contact_id)",
        ),
    ]

    # 10. conversations com contact_id inválido — NULL-ifica (FK é nullable)
    NULL_CONTACT_WHERE = (
        "contact_id IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM public.contacts ct WHERE ct.id = contact_id)"
    )
    n_bad_contact = (
        scalar(
            dc,
            f"SELECT COUNT(1) FROM public.conversations WHERE {NULL_CONTACT_WHERE}",
        )
        or 0
    )
    if n_bad_contact == 0:
        print(f"  ✅ {'conversations.contact_id':<25}  0 inválidos — nada a fazer")
    elif dry_run:
        print(
            f"  ⚠️  {'conversations.contact_id':<25}  {n_bad_contact:>10,} inválidos  [DRY-RUN — não alterado]"
        )
        total_deleted += n_bad_contact
    else:
        with cur(dc) as c:
            c.execute(
                f"UPDATE public.conversations SET contact_id = NULL WHERE {NULL_CONTACT_WHERE}"
            )
            updated = c.rowcount
        dc.commit()
        print(f"  🔧 {'conversations.contact_id':<25}  {updated:>10,} registros NULL-ificados")
        total_deleted += updated

    for step in steps:
        table, where = step[0], step[1]
        optional = len(step) > 2 and step[2]

        if optional and not table_exists(dc, table):
            print(f"  —  {table:<25}  (tabela não existe — ignorado)")
            continue
        if optional and not column_exists(dc, table, "conversation_id"):
            print(f"  —  {table:<25}  (coluna conversation_id não existe — ignorado)")
            continue

        n = delete_orphans(dc, table, where, dry_run)
        total_deleted += n

    print(f"\n  {'─'*60}")
    if dry_run:
        print(f"  DRY-RUN concluído. Total de orphans detectados: {total_deleted:,}")
        print(f"  Para deletar de verdade: python3 {Path(__file__).name} --execute")
    else:
        print(f"  Limpeza concluída. Total deletado: {total_deleted:,} registros")


# ── Verificação pós-limpeza ───────────────────────────────────────────────────


def verificar_pos_limpeza(dc) -> None:
    section("VERIFICAÇÃO PÓS-LIMPEZA")

    checks = [
        (
            "contacts → accounts",
            "SELECT COUNT(1) FROM public.contacts WHERE account_id NOT IN (SELECT id FROM public.accounts)",
        ),
        (
            "conversations → accounts",
            "SELECT COUNT(1) FROM public.conversations WHERE account_id NOT IN (SELECT id FROM public.accounts)",
        ),
        (
            "messages → conversations",
            "SELECT COUNT(1) FROM public.messages m WHERE NOT EXISTS (SELECT 1 FROM public.conversations c WHERE c.id = m.conversation_id)",
        ),
        (
            "messages → accounts",
            "SELECT COUNT(1) FROM public.messages WHERE account_id NOT IN (SELECT id FROM public.accounts)",
        ),
        (
            "attachments → messages",
            "SELECT COUNT(1) FROM public.attachments att WHERE NOT EXISTS (SELECT 1 FROM public.messages m WHERE m.id = att.message_id)",
        ),
        (
            "conversations → contacts (nullable)",
            "SELECT COUNT(1) FROM public.conversations WHERE contact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM public.contacts ct WHERE ct.id = contact_id)",
        ),
        (
            "contact_inboxes → contacts",
            "SELECT COUNT(1) FROM public.contact_inboxes ci WHERE NOT EXISTS (SELECT 1 FROM public.contacts ct WHERE ct.id = ci.contact_id)",
        ),
        (
            "contact_inboxes → inboxes",
            "SELECT COUNT(1) FROM public.contact_inboxes ci WHERE NOT EXISTS (SELECT 1 FROM public.inboxes i WHERE i.id = ci.inbox_id)",
        ),
    ]

    print(f"\n  {'CHECK':<40}  {'VIOLATIONS':>12}  STATUS")
    print(f"  {'-'*40}  {'-'*12}  {'-'*10}")

    all_ok = True
    for check_name, sql in checks:
        n = scalar(dc, sql) or 0
        status = "✅ OK" if n == 0 else f"❌ {n:,} restantes"
        if n > 0:
            all_ok = False
        print(f"  {check_name:<40}  {n:>12,}  {status}")

    if all_ok:
        print(f"\n  ✅ DEST está íntegro — zero FK violations restantes.")
    else:
        print(f"\n  ⚠️  Ainda existem FK violations. Revise manualmente.")


# ── main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    dc = dst()
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print(f"\n{'='*76}")
    print(f"  LIMPEZA DE ORPHANS — DEST (chatwoot004_dev1_db)")
    print(f"  {ts}")
    if DRY_RUN:
        print(f"  MODO: DRY-RUN (sem alterações) — use --execute para deletar")
    else:
        print(f"  MODO: EXECUÇÃO ⚡ — dados serão DELETADOS permanentemente")
    print(f"{'='*76}")

    if not DRY_RUN:
        print("\n  ⚠️  ATENÇÃO: Esta operação DELETA dados do DEST permanentemente.")
        print("  Certifique-se de ter um backup antes de continuar.")
        resposta = input("  Digite 'CONFIRMAR' para prosseguir: ").strip()
        if resposta != "CONFIRMAR":
            print("  Operação cancelada.")
            dc.close()
            sys.exit(0)

    try:
        diagnostico(dc)
        executar_limpeza(dc, DRY_RUN)
        if not DRY_RUN:
            verificar_pos_limpeza(dc)
    finally:
        dc.close()


if __name__ == "__main__":
    main()
