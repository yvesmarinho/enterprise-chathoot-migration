#!/usr/bin/env python3
# =============================================================================
# 05_diagnostico_completo.py — Análise profunda SOURCE vs DEST
# =============================================================================
# Executa análise completa e comparativa entre os dois bancos Chatwoot.
# Cobre: volumes, sobreposição, qualidade de dados, tipos de schema,
#        migrations diff, campos especiais e estimativa de migração.
#
# SOMENTE LEITURA — nunca escreve em nenhum banco.
# Nenhum dado sensível (email, nome, telefone, conteúdo) é impresso.
#
# Uso:
#   cd app/
#   python 05_diagnostico_completo.py
#   python 05_diagnostico_completo.py --salvar   # salva em ../tmp/
# =============================================================================

import datetime
import sys
from pathlib import Path

from db import cur, dst, src

BATCH_SIZE = 500
SEP = "=" * 76
SEP2 = "-" * 76

MAIN_TABLES = [
    "accounts",
    "users",
    "teams",
    "labels",
    "inboxes",
    "contacts",
    "conversations",
    "messages",
    "attachments",
    "contact_inboxes",
]

PIVOT_TABLES = [
    "conversation_participants",
    "team_memberships",
    "account_users",
    "notifications",
    "mentions",
    "conversations_labels",
    "assignments",
    "channel_email_mailboxes",
]

SPECIAL_COLUMNS = [
    ("messages", "content_attributes"),
    ("messages", "additional_attributes"),
    ("conversations", "uuid"),
    ("conversations", "display_id"),
    ("conversations", "custom_attributes"),
    ("contact_inboxes", "pubsub_token"),
    ("contact_inboxes", "source_id"),
    ("contacts", "custom_attributes"),
]


# ── helpers ──────────────────────────────────────────────────────────────────


def section(title: str) -> None:
    print(f"\n{SEP}")
    print(f"  {title}")
    print(SEP)


def subsection(title: str) -> None:
    print(f"\n{SEP2}")
    print(f"  {title}")
    print(SEP2)


def scalar(conn, sql: str, params: tuple = ()) -> int | None:
    with cur(conn) as c:
        c.execute(sql, params)
        row = c.fetchone()
        if row is None:
            return None
        return list(row.values())[0]


def fetchall(conn, sql: str, params: tuple = ()) -> list:
    with cur(conn) as c:
        c.execute(sql, params)
        return list(c.fetchall())


def count_table(conn, table: str) -> int:
    try:
        return scalar(conn, f"SELECT COUNT(1) FROM public.{table}") or 0
    except Exception:
        return -1  # tabela não existe


def count_where(conn, table: str, where: str, params: tuple = ()) -> int:
    sql = f"SELECT COUNT(1) FROM public.{table} WHERE {where}"
    return scalar(conn, sql, params) or 0


def table_exists(conn, table: str) -> bool:
    sql = """
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = %s
    """
    return scalar(conn, sql, (table,)) is not None


def column_type(conn, table: str, column: str) -> str:
    sql = """
        SELECT udt_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name   = %s
          AND column_name  = %s
    """
    return scalar(conn, sql, (table, column)) or "N/A"


def pct(part: int, total: int) -> str:
    if total == 0:
        return "  0.0%"
    return f"{part / total * 100:5.1f}%"


def fmt(n: int) -> str:
    return f"{n:>10,}"


# ── Bloco 1 — Inventário Global ───────────────────────────────────────────────


def bloco_inventario(sc, dc) -> None:
    section("BLOCO 1 — INVENTÁRIO GLOBAL DE TABELAS")
    print(f"\n  {'TABELA':<30}  {'SOURCE':>10}  {'DEST':>10}  {'DIFF':>10}")
    print(f"  {'-'*30}  {'-'*10}  {'-'*10}  {'-'*10}")

    totals_src = 0
    totals_dst = 0
    for table in MAIN_TABLES:
        sv = count_table(sc, table)
        dv = count_table(dc, table)
        diff = dv - sv if sv >= 0 and dv >= 0 else 0
        sv_s = fmt(sv) if sv >= 0 else "      N/A "
        dv_s = fmt(dv) if dv >= 0 else "      N/A "
        diff_s = f"{diff:>+10,}" if sv >= 0 and dv >= 0 else "       N/A"
        print(f"  {table:<30}  {sv_s}  {dv_s}  {diff_s}")
        if sv >= 0:
            totals_src += sv
        if dv >= 0:
            totals_dst += dv

    print(f"  {'-'*30}  {'-'*10}  {'-'*10}  {'-'*10}")
    print(
        f"  {'TOTAL PRINCIPAL':<30}  {fmt(totals_src)}  {fmt(totals_dst)}  {totals_dst - totals_src:>+10,}"
    )

    subsection("Tabelas Ancilares / Pivot")
    print(f"\n  {'TABELA':<35}  {'SOURCE':>10}  {'DEST':>10}")
    print(f"  {'-'*35}  {'-'*10}  {'-'*10}")
    for table in PIVOT_TABLES:
        sv = count_table(sc, table) if table_exists(sc, table) else -1
        dv = count_table(dc, table) if table_exists(dc, table) else -1
        sv_s = fmt(sv) if sv >= 0 else "     N/EX."
        dv_s = fmt(dv) if dv >= 0 else "     N/EX."
        print(f"  {table:<35}  {sv_s}  {dv_s}")


# ── Bloco 2 — Schema Migrations Diff ─────────────────────────────────────────


def bloco_migrations(sc, dc) -> None:
    section("BLOCO 2 — SCHEMA MIGRATIONS DIFF (T2)")

    src_migs = {r["version"] for r in fetchall(sc, "SELECT version FROM schema_migrations")}
    dst_migs = {r["version"] for r in fetchall(dc, "SELECT version FROM schema_migrations")}

    only_src = sorted(src_migs - dst_migs)
    only_dst = sorted(dst_migs - src_migs)
    common = len(src_migs & dst_migs)

    print(f"\n  SOURCE total migrations:  {len(src_migs):>5}")
    print(f"  DEST   total migrations:  {len(dst_migs):>5}")
    print(f"  Em comum:                 {common:>5}")
    print(f"  Apenas na SOURCE:         {len(only_src):>5}")
    print(f"  Apenas na DEST:           {len(only_dst):>5}")

    if only_src:
        print(f"\n  Migrations SOMENTE na SOURCE (origem tem schema mais recente):")
        for v in only_src:
            print(f"    + {v}")

    if only_dst:
        print(f"\n  Migrations SOMENTE na DEST (possível schema divergente — ATENÇÃO):")
        for v in only_dst:
            print(f"    + {v}")

    if not only_src and not only_dst:
        print(f"\n  ✓ Schemas idênticos — nenhuma migration divergente.")


# ── Bloco 3 — Tipos de Campos Especiais ──────────────────────────────────────


def bloco_field_types(sc, dc) -> None:
    section("BLOCO 3 — TIPOS DE CAMPOS ESPECIAIS (T1)")
    print(f"\n  {'TABELA.COLUNA':<45}  {'TIPO SOURCE':>12}  {'TIPO DEST':>12}  STATUS")
    print(f"  {'-'*45}  {'-'*12}  {'-'*12}  {'-'*20}")

    for table, col in SPECIAL_COLUMNS:
        t_src = column_type(sc, table, col)
        t_dst = column_type(dc, table, col)
        label = f"{table}.{col}"
        ok = "✓ iguais" if t_src == t_dst else "⚠ DIVERGENTE"
        print(f"  {label:<45}  {t_src:>12}  {t_dst:>12}  {ok}")

    print(
        f"""
  Legenda de tipos PostgreSQL:
    json     = tipo texto sem indexação — Rails pode retornar String (bug Rails push_event_data)
    jsonb    = binário indexável — Rails retorna Hash corretamente
    uuid     = UUID nativo
    text     = texto livre
    int4/int8 = inteiro
"""
    )


# ── Bloco 4 — Accounts ───────────────────────────────────────────────────────


def bloco_accounts(sc, dc) -> None:
    section("BLOCO 4 — ACCOUNTS — COLISÃO DE NOMES (T3)")

    src_accounts = fetchall(sc, "SELECT id, name, status FROM public.accounts ORDER BY id")
    dst_accounts = fetchall(dc, "SELECT id, name, status FROM public.accounts ORDER BY id")

    dst_by_name = {r["name"]: r for r in dst_accounts}
    src_by_name = {r["name"]: r for r in src_accounts}

    print(f"\n  SOURCE: {len(src_accounts)} accounts  |  DEST: {len(dst_accounts)} accounts")

    subsection("Accounts da SOURCE — mapeamento no DEST")
    print(f"\n  {'SRC_ID':>8}  {'DEST_ID':>8}  {'STATUS':>8}  {'RESULTADO':<25}  NOME")
    print(f"  {'-'*8}  {'-'*8}  {'-'*8}  {'-'*25}  {'-'*30}")

    for r in src_accounts:
        d = dst_by_name.get(r["name"])
        if d:
            resultado = f"MATCH → dest_id={d['id']}"
            dest_id_s = str(d["id"])
        else:
            resultado = "SEM MATCH — será inserida"
            dest_id_s = "—"
        print(
            f"  {r['id']:>8}  {dest_id_s:>8}  {str(r['status']):>8}  {resultado:<25}  {r['name'][:40]}"
        )

    subsection("Accounts EXCLUSIVAS do DEST (não existem na SOURCE)")
    only_dest = [r for r in dst_accounts if r["name"] not in src_by_name]
    print(f"\n  Total: {len(only_dest)}")
    for r in only_dest:
        print(f"    dest_id={r['id']:>5}  status={r['status']}  nome={r['name'][:40]}")


# ── Bloco 5 — Users ──────────────────────────────────────────────────────────


def bloco_users(sc, dc) -> None:
    section("BLOCO 5 — USERS — MAPEAMENTO POR EMAIL (sem imprimir emails)")

    src_uids = {r["uid"] for r in fetchall(sc, "SELECT uid FROM public.users")}
    dst_uids = {r["uid"] for r in fetchall(dc, "SELECT uid FROM public.users")}

    match = src_uids & dst_uids
    only_src = src_uids - dst_uids
    only_dst = dst_uids - src_uids

    print(f"\n  SOURCE total users:                {len(src_uids):>6,}")
    print(f"  DEST   total users:                {len(dst_uids):>6,}")
    print(f"  Com match por UID/email:           {len(match):>6,}  ← esses serão mapeados")
    print(
        f"  SOURCE sem match (sem conta DEST): {len(only_src):>6,}  ← assignee_id ficará NULL em conversas"
    )
    print(f"  DEST   exclusivos:                 {len(only_dst):>6,}")

    print(f"\n  ⚠  Conversas da SOURCE com assignee_id de usuarios sem match no DEST:")
    # Calculamos via Python (sets já carregados, sem cross-db query)
    if only_src:
        n_conv_sem_assignee = (
            scalar(
                sc,
                """
            SELECT COUNT(DISTINCT c.id) FROM public.conversations c
            JOIN public.users u ON u.id = c.assignee_id
            WHERE u.uid = ANY(%s)
        """,
                (list(only_src),),
            )
            or 0
        )
    else:
        n_conv_sem_assignee = 0
    print(f"  Conversations com assignee sem match: {n_conv_sem_assignee:>6,}")

    print(f"\n  Usuários por tipo (coluna 'type'):")
    # 'type' (STI Rails) existe em todos os schemas do Chatwoot para users
    avail = fetchall(
        sc,
        "SELECT COALESCE(type, 'User') AS tipo, COUNT(1) n FROM public.users GROUP BY 1 ORDER BY 2 DESC",
    )
    for r in avail:
        print(f"    {str(r['tipo']):20}  SOURCE={r['n']:>5}")


# ── Bloco 6 — Inboxes / Teams / Labels ───────────────────────────────────────


def bloco_simples(sc, dc) -> None:
    section("BLOCO 6 — INBOXES / TEAMS / LABELS — SOBREPOSIÇÃO POR NOME")

    for entity, key_col, extra_col in [
        ("inboxes", "name", "channel_type"),
        ("teams", "name", None),
        ("labels", "title", "color"),
    ]:
        subsection(f"{entity.upper()}")

        src_all = fetchall(
            sc,
            f"SELECT id, account_id, {key_col}"
            + (f", {extra_col}" if extra_col else "")
            + f" FROM public.{entity} ORDER BY account_id, id",
        )
        dst_all = fetchall(
            dc,
            f"SELECT id, account_id, {key_col}"
            + (f", {extra_col}" if extra_col else "")
            + f" FROM public.{entity} ORDER BY account_id, id",
        )

        dst_key = {(r["account_id"], r[key_col]): r["id"] for r in dst_all}

        match = sum(1 for r in src_all if (r["account_id"], r[key_col]) in dst_key)
        no_match = len(src_all) - match

        print(f"\n  SOURCE total: {len(src_all):>6,}")
        print(f"  DEST   total: {len(dst_all):>6,}")
        print(f"  Match (account_id + {key_col}):  {match:>6,}  ← reutilizar id destino")
        print(f"  Sem match (novos no DEST):       {no_match:>6,}  ← inserir novo")


# ── Bloco 7 — Contacts ───────────────────────────────────────────────────────


def bloco_contacts(sc, dc) -> None:
    section("BLOCO 7 — CONTACTS — ANÁLISE PROFUNDA")

    src_total = count_table(sc, "contacts")
    dst_total = count_table(dc, "contacts")

    # Rastreio
    dst_with_src_id = count_where(dc, "contacts", "custom_attributes->>'src_id' IS NOT NULL")
    dst_without_src = dst_total - dst_with_src_id

    # Preenchimento de campos de chave no SOURCE
    src_with_email = count_where(sc, "contacts", "email IS NOT NULL AND email != ''")
    src_with_phone = count_where(sc, "contacts", "phone_number IS NOT NULL AND phone_number != ''")
    src_with_ident = count_where(sc, "contacts", "identifier IS NOT NULL AND identifier != ''")
    src_with_nothing = count_where(
        sc, "contacts", "email IS NULL AND phone_number IS NULL AND identifier IS NULL"
    )

    print(f"\n  SOURCE total contacts:              {fmt(src_total)}")
    print(f"  DEST   total contacts:              {fmt(dst_total)}")
    print(
        f"\n  DEST com src_id (já migrados):      {fmt(dst_with_src_id)}  ({pct(dst_with_src_id, dst_total)})"
    )
    print(
        f"  DEST sem src_id (nativos/chatwoot): {fmt(dst_without_src)}  ({pct(dst_without_src, dst_total)})"
    )

    print(f"\n  SOURCE — preenchimento de campos de chave de negócio:")
    print(f"    com email:      {fmt(src_with_email)}  ({pct(src_with_email, src_total)})")
    print(f"    com phone:      {fmt(src_with_phone)}  ({pct(src_with_phone, src_total)})")
    print(f"    com identifier: {fmt(src_with_ident)}  ({pct(src_with_ident, src_total)})")
    print(
        f"    sem nenhum:     {fmt(src_with_nothing)}  ({pct(src_with_nothing, src_total)})  ← fallback: name+account"
    )

    subsection("Sobreposição SOURCE × DEST por chave de negócio")

    # Sobreposição por email
    overlap_email = (
        scalar(
            sc,
            """
        SELECT COUNT(DISTINCT s.id) FROM public.contacts s
        WHERE s.email IS NOT NULL AND s.email != ''
          AND EXISTS (
              SELECT 1 FROM public.contacts d
              WHERE d.account_id = s.account_id
                AND d.email = s.email
          )
    """,
        )
        or 0
    )
    # Nota: esta query roda somente no SOURCE conectando ao SOURCE,
    # a comparação cross-DB é aproximada via Python (email/phone sets não carregados por privacidade)
    # — para maior precisão, use dblink ou importação temporária.
    print(f"\n  ⚠  Comparação cross-DB exata de emails/phones requer dblink ou CSV temporário.")
    print(
        f"     As contagens abaixo são internamente no SOURCE (verifica se o SOURCE tem duplicatas próprias).\n"
    )

    src_dup_email = (
        scalar(
            sc,
            """
        SELECT COUNT(*) FROM (
            SELECT email FROM public.contacts
            WHERE email IS NOT NULL
            GROUP BY email HAVING COUNT(1) > 1
        ) t
    """,
        )
        or 0
    )
    src_dup_phone = (
        scalar(
            sc,
            """
        SELECT COUNT(*) FROM (
            SELECT phone_number FROM public.contacts
            WHERE phone_number IS NOT NULL
            GROUP BY phone_number HAVING COUNT(1) > 1
        ) t
    """,
        )
        or 0
    )

    dst_dup_email = (
        scalar(
            dc,
            """
        SELECT COUNT(*) FROM (
            SELECT email FROM public.contacts
            WHERE email IS NOT NULL
            GROUP BY email HAVING COUNT(1) > 1
        ) t
    """,
        )
        or 0
    )
    dst_dup_phone = (
        scalar(
            dc,
            """
        SELECT COUNT(*) FROM (
            SELECT phone_number FROM public.contacts
            WHERE phone_number IS NOT NULL
            GROUP BY phone_number HAVING COUNT(1) > 1
        ) t
    """,
        )
        or 0
    )

    print(
        f"  Emails duplicados internamente — SOURCE: {src_dup_email:>6,}  |  DEST: {dst_dup_email:>6,}"
    )
    print(
        f"  Phones duplicados internamente — SOURCE: {src_dup_phone:>6,}  |  DEST: {dst_dup_phone:>6,}"
    )


# ── Bloco 8 — Conversations ──────────────────────────────────────────────────


def bloco_conversations(sc, dc) -> None:
    section("BLOCO 8 — CONVERSATIONS — ANÁLISE E QUALIDADE")

    src_total = count_table(sc, "conversations")
    dst_total = count_table(dc, "conversations")

    src_with_src_id = count_where(sc, "conversations", "custom_attributes->>'src_id' IS NOT NULL")
    dst_with_src_id = count_where(dc, "conversations", "custom_attributes->>'src_id' IS NOT NULL")
    dst_without_src = dst_total - dst_with_src_id

    # UUID duplicado — conversations no SOURCE
    src_dup_uuid = (
        scalar(
            sc,
            """
        SELECT COUNT(*) FROM (
            SELECT uuid FROM public.conversations
            WHERE uuid IS NOT NULL
            GROUP BY uuid HAVING COUNT(1) > 1
        ) t
    """,
        )
        or 0
    )
    dst_dup_uuid = (
        scalar(
            dc,
            """
        SELECT COUNT(*) FROM (
            SELECT uuid FROM public.conversations
            WHERE uuid IS NOT NULL
            GROUP BY uuid HAVING COUNT(1) > 1
        ) t
    """,
        )
        or 0
    )

    # Qualidade: conversations sem contact_id
    src_no_contact = count_where(sc, "conversations", "contact_id IS NULL")
    # Qualidade: conversations com contact_id que não existe na própria base (FK broken)
    src_broken_contact = (
        scalar(
            sc,
            """
        SELECT COUNT(1) FROM public.conversations c
        WHERE c.contact_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM public.contacts WHERE id = c.contact_id)
    """,
        )
        or 0
    )

    # Qualidade: conversations sem inbox_id válido
    src_broken_inbox = (
        scalar(
            sc,
            """
        SELECT COUNT(1) FROM public.conversations c
        WHERE c.inbox_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM public.inboxes WHERE id = c.inbox_id)
    """,
        )
        or 0
    )

    # display_id: max por account no destino
    display_id_by_account = fetchall(
        dc,
        """
        SELECT account_id, MAX(display_id) AS max_display_id,
               COUNT(1) AS total
        FROM public.conversations
        GROUP BY account_id
        ORDER BY account_id
    """,
    )

    print(f"\n  SOURCE total conversations:              {fmt(src_total)}")
    print(f"  DEST   total conversations:              {fmt(dst_total)}")
    print(f"\n  SOURCE com src_id nos custom_attributes: {fmt(src_with_src_id)}")
    print(f"  DEST   com src_id (já migrados):         {fmt(dst_with_src_id)}")
    print(f"  DEST   sem src_id (nativas/chatwoot):    {fmt(dst_without_src)}")

    print(f"\n  UUIDs duplicados — SOURCE: {src_dup_uuid:>6,}  |  DEST: {dst_dup_uuid:>6,}")
    print(f"     ↳ todos UUID DEVEM ser regenerados na migração (campo UNIQUE global)")

    print(f"\n  Qualidade SOURCE:")
    print(
        f"    sem contact_id (NULL):         {fmt(src_no_contact)}  ({pct(src_no_contact, src_total)})"
    )
    print(
        f"    contact_id FK quebrada:        {fmt(src_broken_contact)}  ({pct(src_broken_contact, src_total)})"
    )
    print(
        f"    inbox_id FK quebrada:          {fmt(src_broken_inbox)}  ({pct(src_broken_inbox, src_total)})"
    )

    subsection("display_id máximo por account_id no DEST (E4 — sequencial por account)")
    print(f"\n  {'DEST ACCOUNT_ID':>20}  {'MAX DISPLAY_ID':>16}  {'TOTAL CONVS':>12}")
    print(f"  {'-'*20}  {'-'*16}  {'-'*12}")
    for r in display_id_by_account:
        print(f"  {r['account_id']:>20}  {r['max_display_id']:>16,}  {r['total']:>12,}")


# ── Bloco 9 — Messages ───────────────────────────────────────────────────────


def bloco_messages(sc, dc) -> None:
    section("BLOCO 9 — MESSAGES — ANÁLISE E QUALIDADE")

    src_total = count_table(sc, "messages")
    dst_total = count_table(dc, "messages")

    src_with_src_id = count_where(sc, "messages", "additional_attributes->>'src_id' IS NOT NULL")
    dst_with_src_id = count_where(dc, "messages", "additional_attributes->>'src_id' IS NOT NULL")

    # Qualidade: messages sem conversation válida na própria base
    src_broken_conv = (
        scalar(
            sc,
            """
        SELECT COUNT(1) FROM public.messages m
        WHERE NOT EXISTS (
            SELECT 1 FROM public.conversations c WHERE c.id = m.conversation_id
        )
    """,
        )
        or 0
    )

    # content_attributes: quantas NÃO são NULL no source
    src_ca_not_null = count_where(sc, "messages", "content_attributes IS NOT NULL")
    dst_ca_not_null = count_where(dc, "messages", "content_attributes IS NOT NULL")

    # Por tipo de mensagem
    msg_types = fetchall(
        sc,
        "SELECT message_type, COUNT(1) n FROM public.messages GROUP BY 1 ORDER BY 2 DESC",
    )

    # Distribuição por data (última semana, último mês, último ano)
    msg_age = fetchall(
        sc,
        """
        SELECT
            COUNT(1) FILTER (WHERE created_at >= NOW() - INTERVAL '7 days')  AS ultimos_7d,
            COUNT(1) FILTER (WHERE created_at >= NOW() - INTERVAL '30 days') AS ultimos_30d,
            COUNT(1) FILTER (WHERE created_at >= NOW() - INTERVAL '1 year')  AS ultimo_ano,
            MIN(created_at)::date AS mais_antigo,
            MAX(created_at)::date AS mais_recente
        FROM public.messages
    """,
    )

    print(f"\n  SOURCE total messages:                   {fmt(src_total)}")
    print(f"  DEST   total messages:                   {fmt(dst_total)}")
    print(f"\n  SOURCE com src_id (rastreio):            {fmt(src_with_src_id)}")
    print(f"  DEST   com src_id (já migrados):         {fmt(dst_with_src_id)}")

    print(f"\n  Qualidade SOURCE:")
    print(
        f"    conversation_id FK quebrada:   {fmt(src_broken_conv)}  ({pct(src_broken_conv, src_total)})"
    )

    print(f"\n  content_attributes NÃO NULL (serão forçados para NULL na migração — E5):")
    print(f"    SOURCE: {fmt(src_ca_not_null)}  ({pct(src_ca_not_null, src_total)})")
    print(f"    DEST:   {fmt(dst_ca_not_null)}  ({pct(dst_ca_not_null, dst_total)})")

    print(f"\n  Distribuição temporal SOURCE:")
    if msg_age:
        r = msg_age[0]
        print(f"    mais antigo:   {r['mais_antigo']}")
        print(f"    mais recente:  {r['mais_recente']}")
        print(f"    últimos 7d:    {r['ultimos_7d']:>10,}")
        print(f"    últimos 30d:   {r['ultimos_30d']:>10,}")
        print(f"    último ano:    {r['ultimo_ano']:>10,}")

    print(f"\n  Tipos de mensagem (SOURCE):")
    type_map = {0: "incoming", 1: "outgoing", 2: "activity", 3: "template"}
    for r in msg_types:
        label = type_map.get(r["message_type"], str(r["message_type"]))
        print(f"    {label:<12}  {r['n']:>10,}  ({pct(r['n'], src_total)})")


# ── Bloco 10 — Attachments ───────────────────────────────────────────────────


def bloco_attachments(sc, dc) -> None:
    section("BLOCO 10 — ATTACHMENTS")

    src_total = count_table(sc, "attachments")
    dst_total = count_table(dc, "attachments")

    # FK quebrada: attachment sem message válida
    src_broken = (
        scalar(
            sc,
            """
        SELECT COUNT(1) FROM public.attachments a
        WHERE NOT EXISTS (SELECT 1 FROM public.messages m WHERE m.id = a.message_id)
    """,
        )
        or 0
    )

    # Por file_type
    types = fetchall(
        sc,
        "SELECT file_type, COUNT(1) n FROM public.attachments GROUP BY 1 ORDER BY 2 DESC LIMIT 10",
    )

    # Attachments com external_url NULL (sem URL S3)
    no_url = count_where(sc, "attachments", "external_url IS NULL OR external_url = ''")

    print(f"\n  SOURCE total attachments:  {fmt(src_total)}")
    print(f"  DEST   total attachments:  {fmt(dst_total)}")
    print(f"\n  SOURCE message_id FK quebrada:  {fmt(src_broken)}  ({pct(src_broken, src_total)})")
    print(f"  SOURCE sem external_url (S3):   {fmt(no_url)}    ({pct(no_url, src_total)})")

    print(f"\n  Tipos de arquivo (SOURCE):")
    type_map = {
        0: "image",
        1: "audio",
        2: "video",
        3: "file",
        4: "location",
        5: "fallback",
        6: "share",
    }
    for r in types:
        label = type_map.get(r["file_type"], str(r["file_type"]))
        print(f"    {label:<12}  {r['n']:>8,}")


# ── Bloco 11 — contact_inboxes ───────────────────────────────────────────────


def bloco_contact_inboxes(sc, dc) -> None:
    section("BLOCO 11 — CONTACT_INBOXES — CAMPOS ESPECIAIS")

    src_total = count_table(sc, "contact_inboxes")
    dst_total = count_table(dc, "contact_inboxes")

    src_pubsub_null = count_where(sc, "contact_inboxes", "pubsub_token IS NULL")
    dst_pubsub_null = count_where(dc, "contact_inboxes", "pubsub_token IS NULL")
    src_source_null = count_where(sc, "contact_inboxes", "source_id IS NULL")

    # Colisão de pubsub_token entre as duas bases
    # (requer cross-db, calculamos via Python)
    src_tokens = {
        r["pubsub_token"]
        for r in fetchall(
            sc,
            "SELECT pubsub_token FROM public.contact_inboxes WHERE pubsub_token IS NOT NULL",
        )
    }
    dst_tokens = {
        r["pubsub_token"]
        for r in fetchall(
            dc,
            "SELECT pubsub_token FROM public.contact_inboxes WHERE pubsub_token IS NOT NULL",
        )
    }
    token_collision = len(src_tokens & dst_tokens)

    print(f"\n  SOURCE total contact_inboxes: {fmt(src_total)}")
    print(f"  DEST   total contact_inboxes: {fmt(dst_total)}")
    print(f"\n  pubsub_token NULL  — SOURCE: {src_pubsub_null:>8,}  |  DEST: {dst_pubsub_null:>8,}")
    print(f"  source_id NULL     — SOURCE: {src_source_null:>8,}")
    print(f"\n  Colisão de pubsub_token entre SOURCE e DEST: {token_collision:>6,}")
    if token_collision > 0:
        print(f"  ⚠  CRÍTICO: {token_collision} tokens idênticos nos dois bancos!")
        print(f"     Confirma obrigatoriedade da regra: pubsub_token = NULL na inserção.")
    else:
        print(f"  ✓ Nenhuma colisão de token encontrada.")


# ── Bloco 12 — IDs e Offsets ─────────────────────────────────────────────────


def bloco_offsets(sc, dc) -> None:
    section("BLOCO 12 — IDs MÁXIMOS E OFFSETS DE MIGRAÇÃO")

    tables_with_seq = [
        "accounts",
        "contacts",
        "conversations",
        "messages",
        "attachments",
        "inboxes",
        "users",
        "teams",
        "labels",
        "contact_inboxes",
    ]

    print(
        f"\n  {'TABELA':<25}  {'MAX ID SOURCE':>14}  {'MAX ID DEST':>12}  {'OFFSET (max_dest)':>18}  {'NOVO ID MIN':>12}"
    )
    print(f"  {'-'*25}  {'-'*14}  {'-'*12}  {'-'*18}  {'-'*12}")

    for table in tables_with_seq:
        try:
            max_src = scalar(sc, f"SELECT COALESCE(MAX(id), 0) FROM public.{table}") or 0
            max_dst = scalar(dc, f"SELECT COALESCE(MAX(id), 0) FROM public.{table}") or 0
            offset = max_dst
            new_min = max_src + max_dst if max_src > 0 else 0
            # Exemplo: id_origem=1 + offset=max_dst → novo_id = id_origem + max_dst
            # menor novo_id = 1 + max_dst
            smallest_src = scalar(sc, f"SELECT COALESCE(MIN(id), 0) FROM public.{table}") or 0
            new_min_real = smallest_src + offset if smallest_src > 0 else max_dst + 1
            print(
                f"  {table:<25}  {max_src:>14,}  {max_dst:>12,}  {offset:>18,}  {new_min_real:>12,}"
            )
        except Exception as e:
            print(f"  {table:<25}  ERRO: {e}")

    print(
        f"""
  Fórmula: novo_id = id_origem + offset  (onde offset = MAX(id_destino))
  Isso garante que o menor novo_id = min_id_origem + max_id_destino
  — nunca colide com IDs existentes no destino.

  ⚠  E1 do Debate D3: spec.md FR-002 define offset = max+1 (INCORRETO).
     A fórmula correta é offset = max (sem +1) conforme constitution.md.
"""
    )


# ── Bloco 13 — Resumo de Qualidade Geral ─────────────────────────────────────


def bloco_qualidade_geral(sc, dc) -> None:
    section("BLOCO 13 — RESUMO DE QUALIDADE GERAL — PONTOS DE RISCO")

    checks = []

    # Conversations sem contact_id
    n = scalar(sc, "SELECT COUNT(1) FROM public.conversations WHERE contact_id IS NULL") or 0
    checks.append(("⚠ ALTO", f"Conversations SOURCE sem contact_id", n))

    # Conversations com contact_id FK broken
    n = (
        scalar(
            sc,
            """
        SELECT COUNT(1) FROM public.conversations c
        WHERE c.contact_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM public.contacts WHERE id = c.contact_id)
    """,
        )
        or 0
    )
    checks.append(("⚠ ALTO", f"Conversations SOURCE com contact_id FK quebrada", n))

    # Messages com conversation FK broken
    n = (
        scalar(
            sc,
            """
        SELECT COUNT(1) FROM public.messages m
        WHERE NOT EXISTS (SELECT 1 FROM public.conversations c WHERE c.id = m.conversation_id)
    """,
        )
        or 0
    )
    checks.append(("⚠ ALTO", f"Messages SOURCE com conversation_id FK quebrada", n))

    # Attachments com message FK broken
    n = (
        scalar(
            sc,
            """
        SELECT COUNT(1) FROM public.attachments a
        WHERE NOT EXISTS (SELECT 1 FROM public.messages m WHERE m.id = a.message_id)
    """,
        )
        or 0
    )
    checks.append(("⚠ MED", f"Attachments SOURCE com message_id FK quebrada", n))

    # Contacts sem nenhuma chave de negócio
    n = (
        scalar(
            sc,
            """
        SELECT COUNT(1) FROM public.contacts
        WHERE email IS NULL AND phone_number IS NULL
          AND identifier IS NULL
          AND (custom_attributes->>'src_id') IS NULL
    """,
        )
        or 0
    )
    checks.append(("⚠ MED", f"Contacts SOURCE sem nenhuma chave de negócio", n))

    # Messages com content_attributes não NULL (serão forçados NULL)
    n = (
        scalar(
            sc,
            "SELECT COUNT(1) FROM public.messages WHERE content_attributes IS NOT NULL",
        )
        or 0
    )
    checks.append(("⚠ ALTO", f"Messages SOURCE com content_attributes (perda de dados)", n))

    # Conversations com uuid nulo
    n = scalar(sc, "SELECT COUNT(1) FROM public.conversations WHERE uuid IS NULL") or 0
    checks.append(("ℹ INFO", f"Conversations SOURCE com uuid NULL", n))

    print(f"\n  {'NÍVEL':<8}  {'N':>9}  DESCRIÇÃO")
    print(f"  {'-'*8}  {'-'*9}  {'-'*55}")
    for nivel, desc, n in checks:
        marker = "◉" if n > 0 else "✓"
        print(f"  {nivel:<8}  {n:>9,}  {marker} {desc}")


# ── Bloco 14 — Estimativa de Migração ────────────────────────────────────────


def bloco_estimativa(sc, dc) -> None:
    section("BLOCO 14 — ESTIMATIVA DE MIGRAÇÃO (T4)")

    tables = [
        ("contacts", "accounts, contacts"),
        ("conversations", "conversations"),
        ("messages", "messages"),
        ("attachments", "attachments"),
        ("inboxes", "inboxes"),
        ("users", "users (mapeamento)"),
        ("teams", "teams"),
        ("labels", "labels"),
        ("contact_inboxes", "contact_inboxes"),
    ]

    latency_fast_ms = 5  # batch simples
    latency_dedup_ms = 50  # batch com lookup de business key

    print(
        f"\n  Premissas: batch_size={BATCH_SIZE}  latência_simples={latency_fast_ms}ms/batch  "
        f"latência_dedup={latency_dedup_ms}ms/batch\n"
    )
    print(
        f"  {'TABELA':<20}  {'TOTAL SOURCE':>14}  {'BATCHES':>8}  "
        f"{'S/ DEDUP':>10}  {'C/ DEDUP':>10}"
    )
    print(f"  {'-'*20}  {'-'*14}  {'-'*8}  {'-'*10}  {'-'*10}")

    total_fast = 0
    total_slow = 0

    for table, note in tables:
        n = count_table(sc, table)
        batches = (n + BATCH_SIZE - 1) // BATCH_SIZE
        fast_s = batches * latency_fast_ms / 1_000
        slow_s = batches * latency_dedup_ms / 1_000
        total_fast += fast_s
        total_slow += slow_s
        print(f"  {table:<20}  {n:>14,}  {batches:>8,}  " f"{fast_s:>9.1f}s  {slow_s:>9.1f}s")

    print(f"  {'-'*20}  {'-'*14}  {'-'*8}  {'-'*10}  {'-'*10}")
    print(f"  {'TOTAL':<20}  {'':>14}  {'':>8}  " f"{total_fast:>9.1f}s  {total_slow:>9.1f}s")

    print(
        f"""
  Estimativa SEM dedup lookup:  {total_fast:.0f}s ({total_fast/60:.1f} min)
  Estimativa COM dedup lookup:  {total_slow:.0f}s ({total_slow/60:.1f} min)

  Nota: latências baseadas em network ~10ms. Com lookup por business key
  (query extra por batch), o tempo real pode ser 2-10× maior em volumes
  de contacts/conversations com dedup por JSON path (custom_attributes).
  Execute --dry-run para medir tempo real antes da migração.
"""
    )


# ── main ──────────────────────────────────────────────────────────────────────


# ── Bloco 15 — Diff de Colunas entre Schemas ─────────────────────────────────


def bloco_diff_colunas(sc, dc) -> None:
    section("BLOCO 15 — DIFF DE COLUNAS ENTRE SCHEMAS (migrations divergentes)")

    main_tables_all = [
        "accounts",
        "users",
        "teams",
        "labels",
        "inboxes",
        "contacts",
        "conversations",
        "messages",
        "attachments",
        "contact_inboxes",
    ]

    def get_columns(conn, table: str) -> dict[str, dict]:
        """Retorna {column_name: {data_type, is_nullable, column_default}}."""
        rows = fetchall(
            conn,
            """
            SELECT column_name, udt_name AS data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            ORDER BY ordinal_position
            """,
            (table,),
        )
        return {r["column_name"]: r for r in rows}

    total_only_src = 0
    total_only_dst = 0
    total_type_diff = 0

    for table in main_tables_all:
        src_cols = get_columns(sc, table)
        dst_cols = get_columns(dc, table)

        only_src = sorted(set(src_cols) - set(dst_cols))
        only_dst = sorted(set(dst_cols) - set(src_cols))
        type_diff = sorted(
            col
            for col in set(src_cols) & set(dst_cols)
            if src_cols[col]["data_type"] != dst_cols[col]["data_type"]
        )

        total_only_src += len(only_src)
        total_only_dst += len(only_dst)
        total_type_diff += len(type_diff)

        if not only_src and not only_dst and not type_diff:
            print(f"\n  {table:<22}  ✓ schemas idênticos")
            continue

        print(f"\n  {table:<22}  ⚠  diffs encontrados")

        if only_src:
            print(f"    Colunas APENAS na SOURCE (dados que seriam perdidos no INSERT):")
            for col in only_src:
                t = src_cols[col]["data_type"]
                print(f"      - {col:<35}  tipo={t}")

        if only_dst:
            print(f"    Colunas APENAS no DEST (risco de NOT NULL sem provider):")
            for col in only_dst:
                d = dst_cols[col]
                nullable = "nullable" if d["is_nullable"] == "YES" else "NOT NULL"
                default = f"  default={d['column_default']}" if d["column_default"] else ""
                risk = (
                    "✓ ok"
                    if d["is_nullable"] == "YES" or d["column_default"]
                    else "⚠ INSERT FALHARÁ"
                )
                print(f"      - {col:<35}  tipo={d['data_type']}  {nullable}{default}  {risk}")

        if type_diff:
            print(f"    Colunas com TIPO DIVERGENTE:")
            for col in type_diff:
                t_src = src_cols[col]["data_type"]
                t_dst = dst_cols[col]["data_type"]
                print(f"      - {col:<35}  SOURCE={t_src}  DEST={t_dst}")

    print(f"\n  {SEP2}")
    print(f"  RESUMO TOTAL:")
    print(f"    Colunas só na SOURCE (perda de dados): {total_only_src:>5}")
    print(f"    Colunas só no DEST   (risco INSERT):   {total_only_dst:>5}")
    print(f"    Colunas com tipo divergente:           {total_type_diff:>5}")
    if total_only_src == 0 and total_only_dst == 0 and total_type_diff == 0:
        print(f"\n  ✓ Todos os schemas das tabelas principais são idênticos.")
    else:
        print(f"\n  ⚠  Ação requerida antes da migração — revisar colunas acima.")


# ── Bloco 16 — Sobreposição cross-DB de Contacts ─────────────────────────────


def bloco_overlap_contacts(sc, dc) -> None:
    section("BLOCO 16 — SOBREPOSIÇÃO CROSS-DB DE CONTACTS (deduplicação)")

    # A chave de deduplicação é (account_id, phone) e (account_id, email).
    # O mesmo phone em contas distintas representa contacts legítimos diferentes;
    # só há duplicata quando account_id + campo de contato coincidem nos dois bancos.

    print(f"\n  Nota: chave de deduplicação = (account_id, phone) e (account_id, email)")
    print(f"  Valores brutos não são impressos.\n")

    # ── Carregar tuplas (account_id, phone) ──────────────────────────────────
    src_phones: set[tuple] = {
        (r["account_id"], str(r["phone_number"]).strip().lower())
        for r in fetchall(
            sc,
            "SELECT account_id, phone_number FROM public.contacts "
            "WHERE phone_number IS NOT NULL AND phone_number != ''",
        )
    }
    dst_phones: set[tuple] = {
        (r["account_id"], str(r["phone_number"]).strip().lower())
        for r in fetchall(
            dc,
            "SELECT account_id, phone_number FROM public.contacts "
            "WHERE phone_number IS NOT NULL AND phone_number != ''",
        )
    }

    # ── Carregar tuplas (account_id, email) ──────────────────────────────────
    src_emails: set[tuple] = {
        (r["account_id"], str(r["email"]).strip().lower())
        for r in fetchall(
            sc,
            "SELECT account_id, email FROM public.contacts "
            "WHERE email IS NOT NULL AND email != ''",
        )
    }
    dst_emails: set[tuple] = {
        (r["account_id"], str(r["email"]).strip().lower())
        for r in fetchall(
            dc,
            "SELECT account_id, email FROM public.contacts "
            "WHERE email IS NOT NULL AND email != ''",
        )
    }

    phone_overlap = len(src_phones & dst_phones)
    email_overlap = len(src_emails & dst_emails)
    phone_only_src = len(src_phones - dst_phones)
    email_only_src = len(src_emails - dst_emails)

    print(f"  {'':38}  {'SOURCE':>10}  {'DEST':>10}  {'OVERLAP':>10}  {'SÓ SRC':>10}")
    print(f"  {'-'*38}  {'-'*10}  {'-'*10}  {'-'*10}  {'-'*10}")
    print(
        f"  {'(account_id, phone) únicos':<38}  {len(src_phones):>10,}  {len(dst_phones):>10,}"
        f"  {phone_overlap:>10,}  {phone_only_src:>10,}"
    )
    print(
        f"  {'(account_id, email) únicos':<38}  {len(src_emails):>10,}  {len(dst_emails):>10,}"
        f"  {email_overlap:>10,}  {email_only_src:>10,}"
    )

    # ── Contacts SOURCE com match → seriam duplicados ─────────────────────────
    src_rows_phones = fetchall(
        sc,
        "SELECT id, account_id, phone_number FROM public.contacts "
        "WHERE phone_number IS NOT NULL AND phone_number != ''",
    )
    src_rows_emails = fetchall(
        sc,
        "SELECT id, account_id, email FROM public.contacts "
        "WHERE email IS NOT NULL AND email != ''",
    )

    contacts_with_phone_match = {
        r["id"]
        for r in src_rows_phones
        if (r["account_id"], str(r["phone_number"]).strip().lower()) in dst_phones
    }
    contacts_with_email_match = {
        r["id"]
        for r in src_rows_emails
        if (r["account_id"], str(r["email"]).strip().lower()) in dst_emails
    }
    contacts_with_any_match = contacts_with_phone_match | contacts_with_email_match

    src_total = scalar(sc, "SELECT COUNT(1) FROM public.contacts") or 0
    print(f"\n  Contacts SOURCE com duplicata no DEST (mesmo account_id + phone OU email):")
    print(
        f"    Por (account_id, phone):  {len(contacts_with_phone_match):>8,}  ({pct(len(contacts_with_phone_match), src_total)})"
    )
    print(
        f"    Por (account_id, email):  {len(contacts_with_email_match):>8,}  ({pct(len(contacts_with_email_match), src_total)})"
    )
    print(
        f"    Por qualquer um:          {len(contacts_with_any_match):>8,}  ({pct(len(contacts_with_any_match), src_total)})"
    )
    print(
        f"\n  → {len(contacts_with_any_match):,} contacts SOURCE devem ser MAPEADOS para o id DEST existente (sem INSERT)."
    )
    print(
        f"  → {src_total - len(contacts_with_any_match):,} contacts SOURCE sem duplicata → inserir com id remapeado."
    )

    # ── Por account: quantos contacts da SOURCE têm match no DEST ────────────
    src_accounts_with_contacts = fetchall(
        sc,
        "SELECT account_id, COUNT(1) AS total FROM public.contacts GROUP BY account_id ORDER BY account_id",
    )
    if src_accounts_with_contacts:
        print(f"\n  Distribuição por account_id (SOURCE):")
        print(f"  {'ACCOUNT_ID':>12}  {'TOTAL SRC':>12}  {'COM MATCH':>12}  {'SEM MATCH':>12}")
        print(f"  {'-'*12}  {'-'*12}  {'-'*12}  {'-'*12}")

        # Mapear contact_id → account_id na SOURCE para contagem por conta
        id_to_acct: dict[int, int] = {}
        for r in fetchall(sc, "SELECT id, account_id FROM public.contacts"):
            id_to_acct[r["id"]] = r["account_id"]

        acct_match: dict[int, int] = {}
        for cid in contacts_with_any_match:
            acct = id_to_acct.get(cid)
            if acct is not None:
                acct_match[acct] = acct_match.get(acct, 0) + 1

        for row in src_accounts_with_contacts:
            acct_id = row["account_id"]
            total = row["total"]
            matched = acct_match.get(acct_id, 0)
            print(f"  {acct_id:>12}  {total:>12,}  {matched:>12,}  {total - matched:>12,}")

    print(
        f"""
  Regra de deduplicação (chave composta):
    1. Se (account_id_src, phone) existe no DEST → mapear contact_id SOURCE → contact_id DEST (não inserir)
    2. Se (account_id_src, email) existe no DEST → idem (phone tem precedência se ambos batem)
    3. Se sem match na mesma account → inserir com id remapeado normalmente
    Observação: account_id_src = account_id_dest para accounts com match de id+nome (Bloco 17)
"""
    )


# ── Bloco 17 — Accounts com id+nome iguais: regra de merge ───────────────────


def bloco_accounts_merge(sc, dc) -> None:
    section("BLOCO 17 — ACCOUNTS COM id+NOME IGUAIS — REGRA DE MERGE")

    src_accounts = fetchall(sc, "SELECT id, name FROM public.accounts ORDER BY id")
    dst_accounts = fetchall(dc, "SELECT id, name FROM public.accounts ORDER BY id")

    dst_by_id_name = {(r["id"], r["name"]): r for r in dst_accounts}

    # Accounts com mesmo id E mesmo nome
    matched = [r for r in src_accounts if (r["id"], r["name"]) in dst_by_id_name]
    not_matched = [r for r in src_accounts if (r["id"], r["name"]) not in dst_by_id_name]

    print(f"\n  Regra: conta com mesmo id E mesmo nome → reutilizar dest_id (sem INSERT)")
    print(f"         dados filhos inexistentes no DEST → importar com FK mapeada para dest_id")
    print(f"\n  Accounts SOURCE com MATCH (id+nome):")
    print(f"  {'SRC_ID':>8}  {'DEST_ID':>8}  NOME")
    print(f"  {'-'*8}  {'-'*8}  {'-'*40}")
    for r in matched:
        print(f"  {r['id']:>8}  {r['id']:>8}  {r['name'][:50]}")

    print(f"\n  Accounts SOURCE SEM match (serão inseridas com id remapeado):")
    print(f"  {'SRC_ID':>8}  {'NOVO_ID':>8}  NOME")
    print(f"  {'-'*8}  {'-'*8}  {'-'*40}")
    dst_max_id = max((r["id"] for r in dst_accounts), default=0)
    for r in not_matched:
        novo_id = r["id"] + dst_max_id
        print(f"  {r['id']:>8}  {novo_id:>8}  {r['name'][:50]}")

    # Para cada account com match, listar dados filhos SOURCE vs DEST
    child_entities = [
        ("inboxes", "account_id", "name"),
        ("teams", "account_id", "name"),
        ("labels", "account_id", "title"),
        ("contacts", "account_id", None),
        ("conversations", "account_id", None),
        ("users", None, None),  # account_users como proxy
    ]

    for acc in matched:
        acc_id = acc["id"]
        acc_name = acc["name"]
        subsection(f"Account id={acc_id} — '{acc_name}'")

        for entity, fk_col, name_col in child_entities:
            if fk_col is None:
                continue

            if not table_exists(sc, entity):
                continue

            src_count = count_where(sc, entity, f"{fk_col} = %s", (acc_id,))
            dst_count = count_where(dc, entity, f"{fk_col} = %s", (acc_id,))

            if name_col:
                # Comparar por nome para ver quais existem só na SOURCE
                src_names = {
                    r[name_col]
                    for r in fetchall(
                        sc,
                        f"SELECT {name_col} FROM public.{entity} WHERE {fk_col} = %s",
                        (acc_id,),
                    )
                    if r[name_col]
                }
                dst_names = {
                    r[name_col]
                    for r in fetchall(
                        dc,
                        f"SELECT {name_col} FROM public.{entity} WHERE {fk_col} = %s",
                        (acc_id,),
                    )
                    if r[name_col]
                }
                only_src_names = sorted(src_names - dst_names)
                already_in_dst = sorted(src_names & dst_names)

                print(f"\n    {entity.upper():<18}  SOURCE={src_count:>6,}  DEST={dst_count:>6,}")
                if already_in_dst:
                    print(
                        f"      Já existem no DEST (não importar): {', '.join(already_in_dst[:5])}"
                        + (f" ... +{len(already_in_dst)-5}" if len(already_in_dst) > 5 else "")
                    )
                if only_src_names:
                    print(
                        f"      Apenas na SOURCE (importar):       {', '.join(only_src_names[:5])}"
                        + (f" ... +{len(only_src_names)-5}" if len(only_src_names) > 5 else "")
                    )
                if not only_src_names and not already_in_dst:
                    print(f"      ✓ nenhuma entrada na SOURCE")
            else:
                # Sem comparação por nome — só contagens
                print(
                    f"\n    {entity.upper():<18}  SOURCE={src_count:>6,}  DEST={dst_count:>6,}"
                    + (
                        f"  → {src_count} registros a avaliar para merge"
                        if src_count > 0
                        else "  ✓ vazio"
                    )
                )

        # account_users (join table) — via conta
        src_au = count_where(sc, "account_users", "account_id = %s", (acc_id,))
        dst_au = count_where(dc, "account_users", "account_id = %s", (acc_id,))
        print(f"\n    {'ACCOUNT_USERS':<18}  SOURCE={src_au:>6,}  DEST={dst_au:>6,}")

    print(
        f"""
  Resumo da regra de importação para accounts com match:
    • A account NÃO é reinserida — dest_id existente é reutilizado como FK
    • Entidades filhas com mesmo nome → não importar (já existem)
    • Entidades filhas sem correspondência → importar com FK = dest_id da account
    • IDs das filhas migradas → offset normal (id_origem + MAX(id_dest) por tabela)
    • Conversations/Messages/Contacts → verificar sobreposição individualmente (Blocos 7/8/16)
"""
    )


def main() -> None:
    salvar = "--salvar" in sys.argv
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    print(f"\n{SEP}")
    print(f"  DIAGNÓSTICO COMPLETO — SOURCE vs DEST")
    print(f"  {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  SOMENTE LEITURA — nenhum dado sensível impresso")
    print(SEP)

    sc = src()
    dc = dst()

    try:
        bloco_inventario(sc, dc)
        bloco_migrations(sc, dc)
        bloco_field_types(sc, dc)
        bloco_accounts(sc, dc)
        bloco_users(sc, dc)
        bloco_simples(sc, dc)
        bloco_contacts(sc, dc)
        bloco_conversations(sc, dc)
        bloco_messages(sc, dc)
        bloco_attachments(sc, dc)
        bloco_contact_inboxes(sc, dc)
        bloco_offsets(sc, dc)
        bloco_qualidade_geral(sc, dc)
        bloco_estimativa(sc, dc)
        bloco_diff_colunas(sc, dc)
        bloco_overlap_contacts(sc, dc)
        bloco_accounts_merge(sc, dc)

        print(f"\n{SEP}")
        print(f"  FIM DO DIAGNÓSTICO")
        print(SEP)

    finally:
        sc.close()
        dc.close()

    if salvar:
        out_dir = Path(__file__).parent.parent / ".tmp"
        out_dir.mkdir(exist_ok=True)
        print(f"\n  Use: python 05_diagnostico_completo.py 2>&1 | tee ../.tmp/diagnostico_{ts}.txt")


if __name__ == "__main__":
    main()
