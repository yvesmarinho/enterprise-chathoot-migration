#!/usr/bin/env python3
"""Relatório de qualidade de dados do banco SOURCE (chatwoot_dev1_db).

Produz um relatório detalhado dos dados existentes no SOURCE:
  - Inventário por account
  - Integridade referencial (FK violations)
  - Completude de campos críticos (email, phone, inbox)
  - Contacts/conversations orphans pré-existentes na origem
  - Contagens por inbox, channel_type, label

Uso:
  cd <projeto_root>
  python3 .tmp/relatorio_qualidade_source.py
"""
from __future__ import annotations

import datetime
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "app"))

from db import cur, src

SEP = "=" * 76
SEP2 = "-" * 76


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
        if row is None:
            return None
        return list(row.values())[0]


def fetchall(conn, sql: str, params: tuple = ()) -> list:
    with cur(conn) as c:
        c.execute(sql, params)
        return list(c.fetchall())


def pct(part: int, total: int) -> str:
    if total == 0:
        return " -"
    return f"{part / total * 100:.1f}%"


# ── Bloco 1 — Inventário por Account ─────────────────────────────────────────


def bloco_inventario_por_account(sc) -> None:
    section("BLOCO 1 — INVENTÁRIO POR ACCOUNT")

    accounts = fetchall(sc, "SELECT id, name, status FROM public.accounts ORDER BY id")
    print(f"\n  Total accounts no SOURCE: {len(accounts)}")

    tables = ["contacts", "conversations", "messages", "attachments", "inboxes"]

    header = f"  {'ACCOUNT':<30}  {'ID':>5}  {'ST':>3}"
    for t in tables:
        header += f"  {t[:12]:>12}"
    print(f"\n{header}")
    print(f"  {'-'*30}  {'-'*5}  {'-'*3}" + "  " + "  ".join(["-" * 12] * len(tables)))

    totals = {t: 0 for t in tables}
    for a in accounts:
        row = f"  {a['name'][:30]:<30}  {a['id']:>5}  {str(a['status']):>3}"
        for t in tables:
            n = scalar(sc, f"SELECT COUNT(1) FROM public.{t} WHERE account_id=%s", (a["id"],)) or 0
            totals[t] += n
            row += f"  {n:>12,}"
        print(row)

    print(f"  {'-'*30}  {'-'*5}  {'-'*3}" + "  " + "  ".join(["-" * 12] * len(tables)))
    total_row = f"  {'TOTAL (accounts válidas)':<30}  {'':>5}  {'':>3}"
    for t in tables:
        total_row += f"  {totals[t]:>12,}"
    print(total_row)


# ── Bloco 2 — Integridade Referencial ─────────────────────────────────────────


def bloco_integridade(sc) -> None:
    section("BLOCO 2 — INTEGRIDADE REFERENCIAL (FK VIOLATIONS NA ORIGEM)")

    checks = [
        (
            "contacts → accounts",
            "contacts",
            "SELECT COUNT(1) n FROM public.contacts ct WHERE NOT EXISTS (SELECT 1 FROM public.accounts a WHERE a.id = ct.account_id)",
        ),
        (
            "conversations → accounts",
            "conversations",
            "SELECT COUNT(1) n FROM public.conversations cv WHERE NOT EXISTS (SELECT 1 FROM public.accounts a WHERE a.id = cv.account_id)",
        ),
        (
            "conversations → contacts (nullable)",
            "conversations",
            "SELECT COUNT(1) n FROM public.conversations cv WHERE contact_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM public.contacts ct WHERE ct.id = cv.contact_id)",
        ),
        (
            "conversations → inboxes (nullable)",
            "conversations",
            "SELECT COUNT(1) n FROM public.conversations cv WHERE inbox_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM public.inboxes i WHERE i.id = cv.inbox_id)",
        ),
        (
            "messages → conversations",
            "messages",
            "SELECT COUNT(1) n FROM public.messages m WHERE NOT EXISTS (SELECT 1 FROM public.conversations c WHERE c.id = m.conversation_id)",
        ),
        (
            "messages → accounts",
            "messages",
            "SELECT COUNT(1) n FROM public.messages m WHERE NOT EXISTS (SELECT 1 FROM public.accounts a WHERE a.id = m.account_id)",
        ),
        (
            "attachments → messages",
            "attachments",
            "SELECT COUNT(1) n FROM public.attachments att WHERE NOT EXISTS (SELECT 1 FROM public.messages m WHERE m.id = att.message_id)",
        ),
        (
            "contact_inboxes → contacts",
            "contact_inboxes",
            "SELECT COUNT(1) n FROM public.contact_inboxes ci WHERE NOT EXISTS (SELECT 1 FROM public.contacts ct WHERE ct.id = ci.contact_id)",
        ),
        (
            "contact_inboxes → inboxes",
            "contact_inboxes",
            "SELECT COUNT(1) n FROM public.contact_inboxes ci WHERE NOT EXISTS (SELECT 1 FROM public.inboxes i WHERE i.id = ci.inbox_id)",
        ),
    ]

    total_sql = {
        "contacts": "SELECT COUNT(1) FROM public.contacts",
        "conversations": "SELECT COUNT(1) FROM public.conversations",
        "messages": "SELECT COUNT(1) FROM public.messages",
        "attachments": "SELECT COUNT(1) FROM public.attachments",
        "contact_inboxes": "SELECT COUNT(1) FROM public.contact_inboxes",
    }

    totals: dict[str, int] = {t: scalar(sc, sql) or 0 for t, sql in total_sql.items()}

    print(f"\n  {'CHECK':<40}  {'VIOLAÇÕES':>12}  {'TOTAL':>12}  {'%':>7}  STATUS")
    print(f"  {'-'*40}  {'-'*12}  {'-'*12}  {'-'*7}  {'-'*10}")

    grand_total = 0
    for check_name, table, count_sql in checks:
        n = scalar(sc, count_sql) or 0
        grand_total += n
        total = totals.get(table, 0)
        p = pct(n, total)
        status = "✅ OK" if n == 0 else ("⚠️  ALERTA" if n < 1000 else "❌ CRÍTICO")
        print(f"  {check_name:<40}  {n:>12,}  {total:>12,}  {p:>7}  {status}")

    print(f"\n  Total de violações FK detectadas: {grand_total:,}")

    subsection("Contacts orphans — breakdown por account_id (sem account no SOURCE)")
    rows = fetchall(
        sc,
        """
        SELECT account_id, COUNT(1) n
        FROM public.contacts
        WHERE account_id NOT IN (SELECT id FROM public.accounts)
        GROUP BY account_id
        ORDER BY n DESC
        """,
    )
    if not rows:
        print("\n  Nenhum contact orphan encontrado.")
    else:
        total_orphans = sum(r["n"] for r in rows)
        print(f"\n  Total de account_ids inválidos: {len(rows)}")
        print(f"  Total de contacts orphans:      {total_orphans:,}")
        print(f"\n  {'account_id':>12}  {'contacts':>12}  Nota")
        print(f"  {'-'*12}  {'-'*12}  {'-'*35}")
        for r in rows:
            print(f"  {r['account_id']:>12}  {r['n']:>12,}  account_id sem registro em accounts")

    subsection("Conversations orphans — breakdown por account_id")
    rows = fetchall(
        sc,
        """
        SELECT account_id, COUNT(1) n
        FROM public.conversations
        WHERE account_id NOT IN (SELECT id FROM public.accounts)
        GROUP BY account_id
        ORDER BY n DESC
        """,
    )
    if not rows:
        print("\n  Nenhuma conversation orphan.")
    else:
        for r in rows:
            print(f"  account_id={r['account_id']}  conversations={r['n']:,}")


# ── Bloco 3 — Completude de Campos Críticos ───────────────────────────────────


def bloco_completude(sc) -> None:
    section("BLOCO 3 — COMPLETUDE DE CAMPOS CRÍTICOS")

    total_contacts = scalar(sc, "SELECT COUNT(1) FROM public.contacts") or 0
    total_conversations = scalar(sc, "SELECT COUNT(1) FROM public.conversations") or 0
    total_messages = scalar(sc, "SELECT COUNT(1) FROM public.messages") or 0

    subsection("Contacts — campos identificadores")
    sem_email = (
        scalar(sc, "SELECT COUNT(1) FROM public.contacts WHERE email IS NULL OR email = ''") or 0
    )
    sem_phone = (
        scalar(
            sc,
            "SELECT COUNT(1) FROM public.contacts WHERE phone_number IS NULL OR phone_number = ''",
        )
        or 0
    )
    sem_ambos = (
        scalar(
            sc,
            "SELECT COUNT(1) FROM public.contacts WHERE (email IS NULL OR email = '') AND (phone_number IS NULL OR phone_number = '')",
        )
        or 0
    )
    com_email = total_contacts - sem_email
    com_phone = total_contacts - sem_phone

    print(f"\n  Total contacts (global):           {total_contacts:>10,}")
    print(
        f"  Com email:                         {com_email:>10,}  ({pct(com_email, total_contacts)})"
    )
    print(
        f"  Sem email:                         {sem_email:>10,}  ({pct(sem_email, total_contacts)})"
    )
    print(
        f"  Com phone:                         {com_phone:>10,}  ({pct(com_phone, total_contacts)})"
    )
    print(
        f"  Sem phone:                         {sem_phone:>10,}  ({pct(sem_phone, total_contacts)})"
    )
    print(
        f"  Sem email E sem phone:             {sem_ambos:>10,}  ({pct(sem_ambos, total_contacts)})  ← identificação impossível"
    )

    subsection("Contacts com account válida — completude")
    valid_total = (
        scalar(
            sc,
            "SELECT COUNT(1) FROM public.contacts WHERE account_id IN (SELECT id FROM public.accounts)",
        )
        or 0
    )
    valid_sem_email = (
        scalar(
            sc,
            "SELECT COUNT(1) FROM public.contacts WHERE account_id IN (SELECT id FROM public.accounts) AND (email IS NULL OR email = '')",
        )
        or 0
    )
    valid_sem_phone = (
        scalar(
            sc,
            "SELECT COUNT(1) FROM public.contacts WHERE account_id IN (SELECT id FROM public.accounts) AND (phone_number IS NULL OR phone_number = '')",
        )
        or 0
    )
    valid_sem_ambos = (
        scalar(
            sc,
            "SELECT COUNT(1) FROM public.contacts WHERE account_id IN (SELECT id FROM public.accounts) AND (email IS NULL OR email = '') AND (phone_number IS NULL OR phone_number = '')",
        )
        or 0
    )

    print(f"\n  Contacts com account válida (em escopo): {valid_total:>8,}")
    print(
        f"  Com email:    {valid_total - valid_sem_email:>8,}  ({pct(valid_total - valid_sem_email, valid_total)})"
    )
    print(f"  Sem email:    {valid_sem_email:>8,}  ({pct(valid_sem_email, valid_total)})")
    print(
        f"  Com phone:    {valid_total - valid_sem_phone:>8,}  ({pct(valid_total - valid_sem_phone, valid_total)})"
    )
    print(f"  Sem phone:    {valid_sem_phone:>8,}  ({pct(valid_sem_phone, valid_total)})")
    print(
        f"  Sem ambos:    {valid_sem_ambos:>8,}  ({pct(valid_sem_ambos, valid_total)})  ← identificação impossível"
    )

    subsection("Conversations — campos críticos")
    # Chatwoot conversations.status: 0=open, 1=resolved, 2=pending, 3=snoozed (integer enum)
    sem_contact = (
        scalar(sc, "SELECT COUNT(1) FROM public.conversations WHERE contact_id IS NULL") or 0
    )
    sem_inbox = scalar(sc, "SELECT COUNT(1) FROM public.conversations WHERE inbox_id IS NULL") or 0
    abertas = scalar(sc, "SELECT COUNT(1) FROM public.conversations WHERE status=0") or 0
    resolvidas = scalar(sc, "SELECT COUNT(1) FROM public.conversations WHERE status=1") or 0
    pendentes = scalar(sc, "SELECT COUNT(1) FROM public.conversations WHERE status=2") or 0
    snoozed = scalar(sc, "SELECT COUNT(1) FROM public.conversations WHERE status=3") or 0
    outras = total_conversations - abertas - resolvidas - pendentes - snoozed

    print(f"\n  Total conversations:               {total_conversations:>10,}")
    print(
        f"  Sem contact_id (anônimas):        {sem_contact:>10,}  ({pct(sem_contact, total_conversations)})"
    )
    print(
        f"  Sem inbox_id:                      {sem_inbox:>10,}  ({pct(sem_inbox, total_conversations)})"
    )
    print(
        f"  Status open (0):                   {abertas:>10,}  ({pct(abertas, total_conversations)})"
    )
    print(
        f"  Status resolved (1):               {resolvidas:>10,}  ({pct(resolvidas, total_conversations)})"
    )
    print(
        f"  Status pending (2):                {pendentes:>10,}  ({pct(pendentes, total_conversations)})"
    )
    print(
        f"  Status snoozed (3):                {snoozed:>10,}  ({pct(snoozed, total_conversations)})"
    )
    print(
        f"  Outros status:                     {outras:>10,}  ({pct(outras, total_conversations)})"
    )

    subsection("Messages — tipo e conteúdo")
    sem_content = (
        scalar(sc, "SELECT COUNT(1) FROM public.messages WHERE content IS NULL OR content = ''")
        or 0
    )
    com_attachment = scalar(sc, "SELECT COUNT(DISTINCT message_id) FROM public.attachments") or 0

    msg_types = fetchall(
        sc,
        "SELECT message_type, COUNT(1) n FROM public.messages GROUP BY message_type ORDER BY n DESC",
    )
    type_labels = {0: "incoming", 1: "outgoing", 2: "activity", 3: "template"}

    print(f"\n  Total messages:                    {total_messages:>10,}")
    print(
        f"  Sem content (ex: só attachment):  {sem_content:>10,}  ({pct(sem_content, total_messages)})"
    )
    print(
        f"  Com attachment:                    {com_attachment:>10,}  ({pct(com_attachment, total_messages)})"
    )
    print(f"\n  Breakdown por message_type:")
    for r in msg_types:
        label = type_labels.get(r["message_type"], f"type_{r['message_type']}")
        print(f"    {label:<12}  {r['n']:>10,}  ({pct(r['n'], total_messages)})")


# ── Bloco 4 — Inboxes e Canais ────────────────────────────────────────────────


def bloco_inboxes(sc) -> None:
    section("BLOCO 4 — INBOXES E CANAIS")

    inboxes = fetchall(
        sc,
        """
        SELECT i.id, i.name, i.channel_type, i.account_id, a.name acc_name
        FROM public.inboxes i
        LEFT JOIN public.accounts a ON a.id = i.account_id
        ORDER BY i.account_id, i.id
        """,
    )

    print(f"\n  Total inboxes no SOURCE: {len(inboxes)}")
    print(f"\n  {'ID':>5}  {'ACCOUNT':<22}  {'CANAL':<30}  {'CHANNEL_TYPE':<20}")
    print(f"  {'-'*5}  {'-'*22}  {'-'*30}  {'-'*20}")

    current_acc = None
    for r in inboxes:
        if r["acc_name"] != current_acc:
            current_acc = r["acc_name"]
            print(f"\n  — {r['acc_name'] or '(sem account)'} (account_id={r['account_id']}) —")
        channel = r["channel_type"].replace("Channel::", "") if r["channel_type"] else "N/A"
        print(
            f"  {r['id']:>5}  {(r['acc_name'] or '')[:22]:<22}  {r['name'][:30]:<30}  {channel:<20}"
        )

    subsection("Breakdown por channel_type")
    ch_rows = fetchall(
        sc,
        "SELECT channel_type, COUNT(1) n_inboxes FROM public.inboxes GROUP BY channel_type ORDER BY n_inboxes DESC",
    )
    print(f"\n  {'CHANNEL_TYPE':<35}  {'INBOXES':>8}")
    print(f"  {'-'*35}  {'-'*8}")
    for r in ch_rows:
        print(f"  {(r['channel_type'] or 'NULL'):<35}  {r['n_inboxes']:>8,}")


# ── Bloco 5 — Labels ─────────────────────────────────────────────────────────


def bloco_labels(sc) -> None:
    section("BLOCO 5 — LABELS")

    labels = fetchall(
        sc,
        """
        SELECT l.title, l.account_id, a.name acc_name
        FROM public.labels l
        LEFT JOIN public.accounts a ON a.id = l.account_id
        ORDER BY l.account_id, l.title
        """,
    )
    print(f"\n  Total labels no SOURCE: {len(labels)}")

    by_account: dict = {}
    for r in labels:
        key = (r["account_id"], r["acc_name"] or "sem account")
        by_account.setdefault(key, []).append(r)

    for (acc_id, acc_name), lbls in sorted(by_account.items()):
        print(f"\n  [{acc_id:>3}] {acc_name[:40]}  ({len(lbls)} labels)")
        for r in lbls[:10]:
            print(f"        '{r['title']}'")
        if len(lbls) > 10:
            print(f"        ... +{len(lbls) - 10} labels omitidas")


# ── Bloco 6 — Resumo Executivo ────────────────────────────────────────────────


def bloco_resumo(sc) -> None:
    section("BLOCO 6 — RESUMO EXECUTIVO")

    total_accounts = scalar(sc, "SELECT COUNT(1) FROM public.accounts") or 0
    total_contacts = scalar(sc, "SELECT COUNT(1) FROM public.contacts") or 0
    total_conversations = scalar(sc, "SELECT COUNT(1) FROM public.conversations") or 0
    total_messages = scalar(sc, "SELECT COUNT(1) FROM public.messages") or 0
    total_attachments = scalar(sc, "SELECT COUNT(1) FROM public.attachments") or 0
    total_inboxes = scalar(sc, "SELECT COUNT(1) FROM public.inboxes") or 0

    fk_contacts = (
        scalar(
            sc,
            "SELECT COUNT(1) FROM public.contacts WHERE account_id NOT IN (SELECT id FROM public.accounts)",
        )
        or 0
    )
    fk_convs = (
        scalar(
            sc,
            "SELECT COUNT(1) FROM public.conversations WHERE account_id NOT IN (SELECT id FROM public.accounts)",
        )
        or 0
    )
    fk_msgs = (
        scalar(
            sc,
            "SELECT COUNT(1) FROM public.messages m WHERE NOT EXISTS (SELECT 1 FROM public.conversations c WHERE c.id = m.conversation_id)",
        )
        or 0
    )

    pct_orphan_ct = fk_contacts / total_contacts * 100 if total_contacts > 0 else 0
    pct_orphan_cv = fk_convs / total_conversations * 100 if total_conversations > 0 else 0
    pct_orphan_msg = fk_msgs / total_messages * 100 if total_messages > 0 else 0

    print(
        f"""
  ┌─────────────────────────────────────────────────────────────────┐
  │  SOURCE: chatwoot_dev1_db — Qualidade dos dados               │
  │  Gerado em: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}                                    │
  └─────────────────────────────────────────────────────────────────┘

  VOLUMES TOTAIS
  {'accounts':<30} {total_accounts:>12,}
  {'contacts':<30} {total_contacts:>12,}
  {'conversations':<30} {total_conversations:>12,}
  {'messages':<30} {total_messages:>12,}
  {'attachments':<30} {total_attachments:>12,}
  {'inboxes':<30} {total_inboxes:>12,}

  INTEGRIDADE REFERENCIAL (FK VIOLATIONS)
  {'contacts orphans':<30} {fk_contacts:>12,}  ({pct_orphan_ct:.1f}%)  {'❌ CRÍTICO' if fk_contacts > 1000 else ('⚠️  ALERTA' if fk_contacts > 0 else '✅ OK')}
  {'conversations orphans':<30} {fk_convs:>12,}  ({pct_orphan_cv:.1f}%)  {'❌ CRÍTICO' if fk_convs > 1000 else ('⚠️  ALERTA' if fk_convs > 0 else '✅ OK')}
  {'messages sem conversation':<30} {fk_msgs:>12,}  ({pct_orphan_msg:.1f}%)  {'❌ CRÍTICO' if fk_msgs > 1000 else ('⚠️  ALERTA' if fk_msgs > 0 else '✅ OK')}

  AVALIAÇÃO GERAL
  {'─'*60}
  Orphan rate:
    contacts:     {pct_orphan_ct:5.1f}%  ({fk_contacts:,} de {total_contacts:,})
    conversations:{pct_orphan_cv:5.1f}%  ({fk_convs:,} de {total_conversations:,})
    messages:     {pct_orphan_msg:5.1f}%  ({fk_msgs:,} de {total_messages:,})

  NOTA: contacts/conversations com account_id inválido NÃO serão
  migrados — são data decay da base SOURCE e não têm account destino.
  {'─'*60}"""
    )


# ── main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    sc = src()
    now = datetime.datetime.now()
    ts_label = now.strftime("%Y-%m-%d %H:%M:%S")
    ts_file = now.strftime("%Y%m%d-%H%M%S")

    buf = io.StringIO()
    _orig_stdout = sys.stdout
    sys.stdout = buf

    print(f"\n{'='*76}")
    print(f"  RELATÓRIO DE QUALIDADE — SOURCE (chatwoot_dev1_db)")
    print(f"  {ts_label}")
    print(f"  SOMENTE LEITURA — nenhum dado sensível impresso")
    print(f"{'='*76}")

    try:
        bloco_inventario_por_account(sc)
        bloco_integridade(sc)
        bloco_completude(sc)
        bloco_inboxes(sc)
        bloco_labels(sc)
        bloco_resumo(sc)
    finally:
        sc.close()
        sys.stdout = _orig_stdout

    out_path = (
        Path(__file__).parent.parent.parent / "tmp" / f"relatorio_qualidade_source_{ts_file}.txt"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(buf.getvalue())
    print(f"Relatório salvo em: {out_path}")


if __name__ == "__main__":
    main()
