#!/usr/bin/env python3
# =============================================================================
# 03_diagnostico_overlap.py — Analisa sobreposicao SOURCE vs DEST
# =============================================================================
# Para accounts mistas (parte migrada, parte criada no Chatwoot),
# mostra exatamente o que ja existe, o que tem src_id e o que nao tem.
# Isso define a estrategia correta de migracao sem duplicar dados.
#
# Uso:
#   python 03_diagnostico_overlap.py "Vya Digital"
#   python 03_diagnostico_overlap.py "Unimed Pocos PJ"
# =============================================================================

import sys, json
from db import src, dst, cur

SEP  = "=" * 70
SEP2 = "-" * 70

def run(account_name: str):
    sc = src()
    dc = dst()

    print(f"\n{SEP}")
    print(f"  DIAGNOSTICO OVERLAP: '{account_name}'")
    print(SEP)

    # IDs das accounts
    with cur(sc) as c:
        c.execute("SELECT id FROM public.accounts WHERE name=%s", (account_name,))
        r = c.fetchone()
    if not r:
        print(f"  ERRO: account nao encontrada no SOURCE."); return
    src_acc_id = r["id"]

    with cur(dc) as c:
        c.execute("SELECT id FROM public.accounts WHERE name=%s", (account_name,))
        r = c.fetchone()
    if not r:
        print(f"  Account nao existe no DEST ainda — migracao direta, sem overlap.")
        return
    dest_acc_id = r["id"]

    print(f"\n  SOURCE account_id={src_acc_id}  |  DEST account_id={dest_acc_id}")

    # ── CONTACTS ──────────────────────────────────────────────────────────────
    print(f"\n{SEP2}")
    print(f"  CONTACTS")
    print(SEP2)

    with cur(sc) as c:
        c.execute("SELECT COUNT(1) n FROM public.contacts WHERE account_id=%s", (src_acc_id,))
        src_total = c.fetchone()["n"]

    with cur(dc) as c:
        c.execute("SELECT COUNT(1) n FROM public.contacts WHERE account_id=%s", (dest_acc_id,))
        dest_total = c.fetchone()["n"]

    with cur(dc) as c:
        c.execute("""
            SELECT COUNT(1) n FROM public.contacts
            WHERE account_id=%s AND custom_attributes->>'src_id' IS NOT NULL
        """, (dest_acc_id,))
        dest_with_src = c.fetchone()["n"]

    dest_without_src = dest_total - dest_with_src

    print(f"\n  SOURCE total:              {src_total:>8,}")
    print(f"  DEST total:                {dest_total:>8,}")
    print(f"  DEST com src_id (migrado): {dest_with_src:>8,}")
    print(f"  DEST sem src_id (nativo):  {dest_without_src:>8,}")

    # Verifica sobreposicao por phone/email
    with cur(sc) as c:
        c.execute("""
            SELECT COUNT(1) n FROM public.contacts s
            WHERE s.account_id=%s
              AND EXISTS (
                  SELECT 1 FROM public.contacts d
                  WHERE d.account_id=%s
                    AND d.phone_number IS NOT NULL
                    AND d.phone_number = s.phone_number
              )
        """, (src_acc_id, dest_acc_id))
        overlap_phone = c.fetchone()["n"]

    with cur(sc) as c:
        c.execute("""
            SELECT COUNT(1) n FROM public.contacts s
            WHERE s.account_id=%s
              AND s.email IS NOT NULL
              AND EXISTS (
                  SELECT 1 FROM public.contacts d
                  WHERE d.account_id=%s
                    AND d.email = s.email
              )
        """, (src_acc_id, dest_acc_id))
        overlap_email = c.fetchone()["n"]

    print(f"\n  Sobreposicao SOURCE vs DEST:")
    print(f"  Mesmo phone_number: {overlap_phone:>8,}  (ja existem no DEST, nao serao duplicados)")
    print(f"  Mesmo email:        {overlap_email:>8,}  (ja existem no DEST, nao serao duplicados)")
    estimativa_novos = src_total - max(overlap_phone, overlap_email)
    print(f"  Estimativa novos:   {estimativa_novos:>8,}  (serao inseridos)")

    # ── CONVERSATIONS ─────────────────────────────────────────────────────────
    print(f"\n{SEP2}")
    print(f"  CONVERSATIONS")
    print(SEP2)

    with cur(sc) as c:
        c.execute("SELECT COUNT(1) n FROM public.conversations WHERE account_id=%s", (src_acc_id,))
        src_total_c = c.fetchone()["n"]

    with cur(dc) as c:
        c.execute("SELECT COUNT(1) n FROM public.conversations WHERE account_id=%s", (dest_acc_id,))
        dest_total_c = c.fetchone()["n"]

    with cur(dc) as c:
        c.execute("""
            SELECT COUNT(1) n FROM public.conversations
            WHERE account_id=%s AND custom_attributes->>'src_id' IS NOT NULL
        """, (dest_acc_id,))
        dest_conv_with_src = c.fetchone()["n"]

    dest_conv_without_src = dest_total_c - dest_conv_with_src

    print(f"\n  SOURCE total:              {src_total_c:>8,}")
    print(f"  DEST total:                {dest_total_c:>8,}")
    print(f"  DEST com src_id (migrado): {dest_conv_with_src:>8,}")
    print(f"  DEST sem src_id (nativo):  {dest_conv_without_src:>8,}")
    print(f"  A migrar (estimativa):     {src_total_c - dest_conv_with_src:>8,}")

    # ── MESSAGES ──────────────────────────────────────────────────────────────
    print(f"\n{SEP2}")
    print(f"  MESSAGES")
    print(SEP2)

    with cur(sc) as c:
        c.execute("SELECT COUNT(1) n FROM public.messages WHERE account_id=%s", (src_acc_id,))
        src_total_m = c.fetchone()["n"]

    with cur(dc) as c:
        c.execute("SELECT COUNT(1) n FROM public.messages WHERE account_id=%s", (dest_acc_id,))
        dest_total_m = c.fetchone()["n"]

    with cur(dc) as c:
        c.execute("""
            SELECT COUNT(1) n FROM public.messages
            WHERE account_id=%s
              AND additional_attributes->>'src_id' IS NOT NULL
        """, (dest_acc_id,))
        dest_msg_with_src = c.fetchone()["n"]

    print(f"\n  SOURCE total:              {src_total_m:>8,}")
    print(f"  DEST total:                {dest_total_m:>8,}")
    print(f"  DEST com src_id (migrado): {dest_msg_with_src:>8,}")
    print(f"  DEST sem src_id (nativo):  {dest_total_m - dest_msg_with_src:>8,}")
    print(f"  A migrar (estimativa):     {src_total_m - dest_msg_with_src:>8,}")

    # ── INBOXES ───────────────────────────────────────────────────────────────
    print(f"\n{SEP2}")
    print(f"  INBOXES")
    print(SEP2)

    with cur(sc) as c:
        c.execute("""
            SELECT id, name, channel_type FROM public.inboxes
            WHERE account_id=%s ORDER BY id
        """, (src_acc_id,))
        src_inboxes = c.fetchall()

    with cur(dc) as c:
        c.execute("""
            SELECT id, name, channel_type FROM public.inboxes
            WHERE account_id=%s ORDER BY id
        """, (dest_acc_id,))
        dest_inboxes = c.fetchall()

    dest_inbox_by_name = {i["name"]: i for i in dest_inboxes}

    print(f"\n  {'INBOX SOURCE':35}  {'CANAL':20}  STATUS")
    print(f"  {'-'*35}  {'-'*20}  {'-'*25}")
    for si in src_inboxes:
        di = dest_inbox_by_name.get(si["name"])
        status = f"[JA EXISTE] dest_id={di['id']}" if di else "[FALTA CRIAR]"
        with cur(sc) as c:
            c.execute("SELECT COUNT(1) n FROM public.conversations "
                      "WHERE account_id=%s AND inbox_id=%s", (src_acc_id, si["id"]))
            n = c.fetchone()["n"]
        print(f"  {si['name'][:35]:35}  {si['channel_type'][:20]:20}  {status}  ({n:,} convs)")

    print(f"\n  Inboxes so no DEST (nativas):")
    src_names = {i["name"] for i in src_inboxes}
    dest_only = [i for i in dest_inboxes if i["name"] not in src_names]
    if dest_only:
        for i in dest_only:
            with cur(dc) as c:
                c.execute("SELECT COUNT(1) n FROM public.conversations "
                          "WHERE account_id=%s AND inbox_id=%s", (dest_acc_id, i["id"]))
                n = c.fetchone()["n"]
            print(f"  dest_id={i['id']:4}  {i['name'][:35]}  ({n:,} convs no DEST)")
    else:
        print(f"  Nenhuma.")

    # ── CONCLUSAO ─────────────────────────────────────────────────────────────
    print(f"\n{SEP}")
    print(f"  CONCLUSAO E ESTRATEGIA")
    print(SEP)
    print(f"""
  1. Contacts:
     - {dest_with_src:,} ja migrados (tem src_id) → serao pulados
     - {dest_without_src:,} nativos (sem src_id) → dedup por phone/email/identifier
     - ~{estimativa_novos:,} novos do SOURCE → serao inseridos

  2. Conversations:
     - {dest_conv_with_src:,} ja migradas (tem src_id) → serao puladas
     - {dest_conv_without_src:,} nativas (sem src_id) → NAO duplicadas (dedup por src_id garante isso)
     - {src_total_c - dest_conv_with_src:,} do SOURCE ainda nao migradas → serao inseridas

  3. Messages:
     - Todas as messages de conversations novas serao inseridas
     - Messages de conversations ja existentes serao puladas (dedup por src_id)

  O script 01_migrar_account.py ja trata tudo isso corretamente.
  Pode rodar sem risco de duplicar dados existentes.

  Comando:
    python 01_migrar_account.py "{account_name}"
    """)

    sc.close()
    dc.close()
    print(SEP + "\n")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Uso: python 03_diagnostico_overlap.py "nome da account"')
        sys.exit(1)
    run(sys.argv[1])
