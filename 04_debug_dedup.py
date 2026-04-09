#!/usr/bin/env python3
# =============================================================================
# 04_debug_dedup.py — Investiga por que conversations aparecem como dedup
# =============================================================================
import sys
from db import src, dst, cur

def run(account_name):
    sc = src()
    dc = dst()

    with cur(sc) as c:
        c.execute("SELECT id FROM public.accounts WHERE name=%s", (account_name,))
        r = c.fetchone()
    src_acc_id = r["id"]

    with cur(dc) as c:
        c.execute("SELECT id FROM public.accounts WHERE name=%s", (account_name,))
        r = c.fetchone()
    dest_acc_id = r["id"]

    print(f"\nAccount: SOURCE={src_acc_id}  DEST={dest_acc_id}")

    # 1. Quantas conversations no DEST tem src_id preenchido?
    with cur(dc) as c:
        c.execute("""
            SELECT COUNT(1) n FROM public.conversations
            WHERE account_id=%s AND custom_attributes->>'src_id' IS NOT NULL
        """, (dest_acc_id,))
        with_src = c.fetchone()["n"]

    with cur(dc) as c:
        c.execute("""
            SELECT COUNT(1) n FROM public.conversations
            WHERE account_id=%s AND custom_attributes->>'src_id' IS NULL
        """, (dest_acc_id,))
        without_src = c.fetchone()["n"]

    print(f"\nConversations no DEST:")
    print(f"  Com src_id:    {with_src:,}")
    print(f"  Sem src_id:    {without_src:,}")

    # 2. Pega amostra das 5 primeiras conversations do SOURCE
    # e verifica exatamente o que acontece na query de dedup
    with cur(sc) as c:
        c.execute("""
            SELECT id FROM public.conversations
            WHERE account_id=%s ORDER BY id LIMIT 10
        """, (src_acc_id,))
        src_ids = [r["id"] for r in c.fetchall()]

    print(f"\nPrimeiros 10 IDs do SOURCE: {src_ids}")
    print(f"\nVerificando dedup para cada um:")

    for sid in src_ids:
        with cur(dc) as c:
            c.execute("""
                SELECT id, custom_attributes->>'src_id' as src_id_val
                FROM public.conversations
                WHERE account_id=%s AND custom_attributes->>'src_id'=%s
                LIMIT 1
            """, (dest_acc_id, str(sid)))
            found = c.fetchone()

        if found:
            print(f"  src_conv_id={sid} -> DEDUP! dest_id={found['id']} src_id_val='{found['src_id_val']}'")
        else:
            print(f"  src_conv_id={sid} -> NAO existe no DEST com src_id={sid}")

    # 3. Mostra amostra de conversations do DEST com src_id
    if with_src > 0:
        print(f"\nAmostra de conversations no DEST com src_id (5 primeiras):")
        with cur(dc) as c:
            c.execute("""
                SELECT id, custom_attributes->>'src_id' as src_id_val,
                       custom_attributes::text as ca
                FROM public.conversations
                WHERE account_id=%s AND custom_attributes->>'src_id' IS NOT NULL
                ORDER BY id LIMIT 5
            """, (dest_acc_id,))
            for r in c.fetchall():
                print(f"  dest_id={r['id']}  src_id='{r['src_id_val']}'  ca={r['ca'][:80]}")

    # 4. Mostra amostra de conversations sem src_id
    if without_src > 0:
        print(f"\nAmostra de conversations no DEST SEM src_id (5 primeiras):")
        with cur(dc) as c:
            c.execute("""
                SELECT id, display_id, status,
                       custom_attributes::text as ca
                FROM public.conversations
                WHERE account_id=%s AND custom_attributes->>'src_id' IS NULL
                ORDER BY id LIMIT 5
            """, (dest_acc_id,))
            for r in c.fetchall():
                print(f"  dest_id={r['id']}  display_id={r['display_id']}  ca={r['ca'][:80]}")

    # 5. Verifica se o contact_map estava vazio (todos os contacts com dedup)
    # significa que contact_map tinha src mas conversations nao tinham
    print(f"\nContacts no DEST:")
    with cur(dc) as c:
        c.execute("""
            SELECT COUNT(1) n FROM public.contacts
            WHERE account_id=%s AND custom_attributes->>'src_id' IS NOT NULL
        """, (dest_acc_id,))
        print(f"  Com src_id: {c.fetchone()['n']:,}")
    with cur(dc) as c:
        c.execute("""
            SELECT COUNT(1) n FROM public.contacts
            WHERE account_id=%s AND custom_attributes->>'src_id' IS NULL
        """, (dest_acc_id,))
        print(f"  Sem src_id: {c.fetchone()['n']:,}")

    sc.close(); dc.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Uso: python 04_debug_dedup.py "nome da account"')
        sys.exit(1)
    run(sys.argv[1])
