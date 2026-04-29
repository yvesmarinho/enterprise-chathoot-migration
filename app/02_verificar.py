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

    rows = [
        ("contacts",      count(sc, "contacts",      src_acc_id), count(dc, "contacts",      dest_acc_id)),
        ("conversations", count(sc, "conversations", src_acc_id), count(dc, "conversations", dest_acc_id)),
        ("messages",      count(sc, "messages",      src_acc_id), count(dc, "messages",      dest_acc_id)),
    ]

    print(f"\n  {'Tabela':20}  {'SOURCE':>10}  {'DEST':>10}  STATUS")
    print(f"  {'-'*20}  {'-'*10}  {'-'*10}  {'-'*15}")
    for table, src_n, dest_n in rows:
        status = "OK" if dest_n >= src_n else f"FALTA {src_n - dest_n:,}"
        print(f"  {table:20}  {src_n:>10,}  {dest_n:>10,}  {status}")

    # Orphan messages no DEST
    with cur(dc) as c:
        c.execute("""
            SELECT COUNT(1) n FROM public.messages m
            WHERE m.account_id = %s
              AND NOT EXISTS (
                  SELECT 1 FROM public.conversations c
                  WHERE c.id = m.conversation_id
              )
        """, (dest_acc_id,))
        orphans = c.fetchone()["n"]
    print(f"\n  Messages sem conversation (orphans): {orphans:,}")
    if orphans > 0:
        print(f"  ATENCAO: existem mensagens sem conversation valida!")

    # Verifica content_attributes nas messages migradas
    with cur(dc) as c:
        c.execute("""
            SELECT COUNT(1) n FROM public.messages
            WHERE account_id = %s
              AND content_attributes IS NOT NULL
              AND content_attributes::text NOT IN ('{}', 'null')
        """, (dest_acc_id,))
        ca_nonnull = c.fetchone()["n"]
    print(f"  Messages com content_attributes nao-nulo: {ca_nonnull:,}")
    if ca_nonnull > 0:
        print(f"  ATENCAO: podem causar erro no Chatwoot — investigue!")
        with cur(dc) as c:
            c.execute("""
                SELECT id, conversation_id, content_type,
                       content_attributes::text AS ca_raw
                FROM public.messages
                WHERE account_id = %s
                  AND content_attributes IS NOT NULL
                  AND content_attributes::text NOT IN ('{}', 'null')
                LIMIT 5
            """, (dest_acc_id,))
            for row in c.fetchall():
                print(f"    msg={row['id']} conv={row['conversation_id']} "
                      f"ct={row['content_type']} ca={str(row['ca_raw'] or '')[:80]}")

    # Amostra de conversations migradas
    print(f"\n  Amostra de conversations migradas (5 mais recentes):")
    with cur(dc) as c:
        c.execute("""
            SELECT id, display_id, status, contact_id,
                   custom_attributes->>'src_id' AS src_id,
                   created_at
            FROM public.conversations
            WHERE account_id = %s
              AND custom_attributes->>'src_id' IS NOT NULL
            ORDER BY id DESC LIMIT 5
        """, (dest_acc_id,))
        for row in c.fetchall():
            print(f"    dest_id={row['id']} src_id={row['src_id']} "
                  f"display={row['display_id']} status={row['status']}")

    sc.close()
    dc.close()
    print(f"\n{'='*65}\n")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Uso: python 02_verificar.py "nome da account"')
        sys.exit(1)
    run(sys.argv[1])
