#!/usr/bin/env python3
# =============================================================================
# 02_verificar.py — Verifica a migração de uma account
# =============================================================================
# Rode após cada account para confirmar integridade antes da próxima.
#
# Uso:
#   python 02_verificar.py "Vya Digital"
# =============================================================================

import sys, json
from db import src, dst, cur


def run(account_name: str):
    sc = src()
    dc = dst()

    print(f"\n{'='*65}")
    print(f"  VERIFICACAO — '{account_name}'")
    print(f"{'='*65}")

    # Account IDs
    with cur(sc) as c:
        c.execute("SELECT id FROM public.accounts WHERE name=%s", (account_name,))
        r = c.fetchone()
    src_acc_id = r["id"] if r else None

    with cur(dc) as c:
        c.execute("SELECT id FROM public.accounts WHERE name=%s", (account_name,))
        r = c.fetchone()
    dest_acc_id = r["id"] if r else None

    if not src_acc_id or not dest_acc_id:
        print("  Account nao encontrada em SOURCE ou DEST.")
        return

    print(f"\n  SOURCE account_id={src_acc_id}  |  DEST account_id={dest_acc_id}")

    # Contagens
    def count(conn, table, acc_id):
        with cur(conn) as c:
            c.execute(f"SELECT COUNT(1) n FROM public.{table} WHERE account_id=%s", (acc_id,))
            return c.fetchone()["n"]

    def count_contact_inboxes(conn, acc_id):
        # contact_inboxes não tem account_id — JOIN via inboxes
        with cur(conn) as c:
            c.execute(
                """
                SELECT COUNT(1) n
                FROM public.contact_inboxes ci
                JOIN public.inboxes i ON i.id = ci.inbox_id
                WHERE i.account_id = %s
            """,
                (acc_id,),
            )
            return c.fetchone()["n"]

    rows = [
        ("contacts", count(sc, "contacts", src_acc_id), count(dc, "contacts", dest_acc_id)),
        (
            "conversations",
            count(sc, "conversations", src_acc_id),
            count(dc, "conversations", dest_acc_id),
        ),
        ("messages", count(sc, "messages", src_acc_id), count(dc, "messages", dest_acc_id)),
        (
            "attachments",
            count(sc, "attachments", src_acc_id),
            count(dc, "attachments", dest_acc_id),
        ),
        ("inboxes", count(sc, "inboxes", src_acc_id), count(dc, "inboxes", dest_acc_id)),
        (
            "contact_inboxes",
            count_contact_inboxes(sc, src_acc_id),
            count_contact_inboxes(dc, dest_acc_id),
        ),
    ]

    print(f"\n  {'Tabela':20}  {'SOURCE':>10}  {'DEST':>10}  STATUS")
    print(f"  {'-'*20}  {'-'*10}  {'-'*10}  {'-'*15}")
    for table, src_n, dest_n in rows:
        status = "OK" if dest_n >= src_n else f"FALTA {src_n - dest_n:,}"
        print(f"  {table:20}  {src_n:>10,}  {dest_n:>10,}  {status}")

    # Orphan messages no DEST
    with cur(dc) as c:
        c.execute(
            """
            SELECT COUNT(1) n FROM public.messages m
            WHERE m.account_id = %s
              AND NOT EXISTS (
                  SELECT 1 FROM public.conversations c
                  WHERE c.id = m.conversation_id
              )
        """,
            (dest_acc_id,),
        )
        orphans = c.fetchone()["n"]
    print(f"\n  Messages sem conversation (orphans): {orphans:,}")
    if orphans > 0:
        print(f"  ATENCAO: existem mensagens sem conversation valida!")

    # Verifica content_attributes nas messages migradas
    with cur(dc) as c:
        c.execute(
            """
            SELECT COUNT(1) n FROM public.messages
            WHERE account_id = %s
              AND content_attributes IS NOT NULL
              AND content_attributes::text NOT IN ('{}', 'null')
        """,
            (dest_acc_id,),
        )
        ca_nonnull = c.fetchone()["n"]
    print(f"  Messages com content_attributes nao-nulo: {ca_nonnull:,}")
    if ca_nonnull > 0:
        print(f"  ATENCAO: podem causar erro no Chatwoot — investigue!")
        with cur(dc) as c:
            c.execute(
                """
                SELECT id, conversation_id, content_type,
                       content_attributes::text AS ca_raw
                FROM public.messages
                WHERE account_id = %s
                  AND content_attributes IS NOT NULL
                  AND content_attributes::text NOT IN ('{}', 'null')
                LIMIT 5
            """,
                (dest_acc_id,),
            )
            for row in c.fetchall():
                print(
                    f"    msg={row['id']} conv={row['conversation_id']} "
                    f"ct={row['content_type']} ca={str(row['ca_raw'] or '')[:80]}"
                )

    # Amostra de conversations migradas
    print(f"\n  Amostra de conversations migradas (5 mais recentes):")
    with cur(dc) as c:
        c.execute(
            """
            SELECT id, display_id, status, contact_id,
                   custom_attributes->>'src_id' AS src_id,
                   created_at
            FROM public.conversations
            WHERE account_id = %s
              AND custom_attributes->>'src_id' IS NOT NULL
            ORDER BY id DESC LIMIT 5
        """,
            (dest_acc_id,),
        )
        for row in c.fetchall():
            print(
                f"    dest_id={row['id']} src_id={row['src_id']} "
                f"display={row['display_id']} status={row['status']}"
            )

    # Cobertura de src_id (% de conversations com rastreabilidade)
    with cur(dc) as c:
        c.execute(
            """
            SELECT
                COUNT(1) AS total,
                COUNT(1) FILTER (WHERE custom_attributes->>'src_id' IS NOT NULL) AS with_src_id
            FROM public.conversations
            WHERE account_id = %s
        """,
            (dest_acc_id,),
        )
        cov = c.fetchone()
    total_conv = cov["total"] or 1
    pct = cov["with_src_id"] / total_conv * 100
    print(f"\n  Cobertura src_id: {cov['with_src_id']:,}/{total_conv:,} ({pct:.1f}%)")
    if pct < 95:
        print(f"  ATENCAO: menos de 95% das conversations têm src_id rastreável!")

    # Distribuição de status das conversations no DEST
    with cur(dc) as c:
        c.execute(
            """
            SELECT status, COUNT(1) n
            FROM public.conversations
            WHERE account_id = %s
            GROUP BY status ORDER BY n DESC
        """,
            (dest_acc_id,),
        )
        statuses = c.fetchall()
    print(f"\n  Distribuição de status (DEST):")
    for row in statuses:
        print(f"    {row['status']:20}  {row['n']:>8,}")

    # Display_id duplicado no DEST (nunca deve ocorrer)
    with cur(dc) as c:
        c.execute(
            """
            SELECT display_id, COUNT(1) n
            FROM public.conversations
            WHERE account_id = %s
            GROUP BY display_id HAVING COUNT(1) > 1
            LIMIT 5
        """,
            (dest_acc_id,),
        )
        dup_display = c.fetchall()
    if dup_display:
        print(f"\n  CRITICO: display_id duplicados no DEST ({len(dup_display)} casos):")
        for row in dup_display:
            print(f"    display_id={row['display_id']} count={row['n']}")
    else:
        print(f"\n  display_id duplicados: NENHUM (OK)")

    # Conversations com contact_id inválido (referência quebrada)
    with cur(dc) as c:
        c.execute(
            """
            SELECT COUNT(1) n
            FROM public.conversations cv
            WHERE cv.account_id = %s
              AND NOT EXISTS (
                  SELECT 1 FROM public.contacts ct
                  WHERE ct.id = cv.contact_id
              )
        """,
            (dest_acc_id,),
        )
        broken_contacts = c.fetchone()["n"]
    if broken_contacts > 0:
        print(f"  CRITICO: {broken_contacts:,} conversations com contact_id inválido!")
    else:
        print(f"  Referências contact_id: INTEGRAS (OK)")

    # Inbox names presentes no DEST
    print(f"\n  Inboxes migradas (DEST):")
    with cur(dc) as c:
        c.execute(
            """
            SELECT id, name, channel_type
            FROM public.inboxes
            WHERE account_id = %s
            ORDER BY id
        """,
            (dest_acc_id,),
        )
        for row in c.fetchall():
            print(f"    inbox_id={row['id']}  {row['channel_type']:30}  {row['name']}")

    sc.close()
    dc.close()
    print(f"\n{'='*65}\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Uso: python 02_verificar.py "nome da account"')
        sys.exit(1)
    run(sys.argv[1])
