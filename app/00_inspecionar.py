#!/usr/bin/env python3
# =============================================================================
# 00_inspecionar.py — Inspeciona SOURCE e compara com DEST antes de migrar
# =============================================================================
# RODE ESTE SCRIPT PRIMEIRO — nao altera nada em nenhum banco.
#
# Para cada inbox do SOURCE, verifica se ja existe no DEST com o mesmo nome
# e mostra o status: [JA EXISTE], [FALTA CRIAR] ou [NOME DIFERENTE].
# Isso evita criar duplicatas no DEST.
#
# Uso:
#   python 00_inspecionar.py "Vya Digital"
# =============================================================================

import sys
from db import src, dst, cur

SEP  = "=" * 70
SEP2 = "-" * 70

def run(account_name: str):
    sc = src()
    dc = dst()

    print(f"\n{SEP}")
    print(f"  INSPECAO: '{account_name}'")
    print(SEP)

    # ── Account SOURCE ────────────────────────────────────────────────────────
    with cur(sc) as c:
        c.execute("SELECT id, name, status FROM public.accounts WHERE name = %s",
                  (account_name,))
        src_acc = c.fetchone()

    if not src_acc:
        print(f"\n  ERRO: account '{account_name}' nao encontrada no SOURCE.")
        sc.close(); dc.close(); return

    src_acc_id = src_acc["id"]
    print(f"\n  SOURCE  id={src_acc_id}  name='{src_acc['name']}'  status={src_acc['status']}")

    # ── Account DEST ──────────────────────────────────────────────────────────
    with cur(dc) as c:
        c.execute("SELECT id, name, status FROM public.accounts WHERE name = %s",
                  (account_name,))
        dest_acc = c.fetchone()

    if dest_acc:
        dest_acc_id = dest_acc["id"]
        print(f"  DEST    id={dest_acc_id}  name='{dest_acc['name']}'  status={dest_acc['status']}")
    else:
        dest_acc_id = None
        print(f"  DEST    [NAO EXISTE] — a account sera mapeada pelo nome no momento da migracao")

    # ── Volumes SOURCE vs DEST ────────────────────────────────────────────────
    print(f"\n{SEP2}")
    print(f"  VOLUMES")
    print(SEP2)

    def count_src(table):
        with cur(sc) as c:
            c.execute(f"SELECT COUNT(1) n FROM public.{table} WHERE account_id=%s", (src_acc_id,))
            return c.fetchone()["n"]

    def count_dst(table):
        if not dest_acc_id: return 0
        with cur(dc) as c:
            c.execute(f"SELECT COUNT(1) n FROM public.{table} WHERE account_id=%s", (dest_acc_id,))
            return c.fetchone()["n"]

    for table in ["contacts", "conversations", "messages"]:
        sn = count_src(table)
        dn = count_dst(table)
        diff = dn - sn
        status = "ok" if dn == 0 else f"DEST ja tem {dn:,} registros"
        print(f"  {table:15}  SOURCE={sn:>8,}  DEST={dn:>8,}  {status}")

    # ── Users SOURCE → verifica no DEST ──────────────────────────────────────
    print(f"\n{SEP2}")
    print(f"  USERS (verificando se existem no DEST pelo email)")
    print(SEP2)

    with cur(sc) as c:
        c.execute("""
            SELECT u.id, u.name, u.email, au.role
            FROM public.users u
            JOIN public.account_users au ON au.user_id = u.id
            WHERE au.account_id = %s
            ORDER BY u.id
        """, (src_acc_id,))
        src_users = c.fetchall()

    print(f"\n  {'EMAIL':40}  {'ROLE':6}  STATUS")
    print(f"  {'-'*40}  {'-'*6}  {'-'*25}")
    for u in src_users:
        with cur(dc) as c:
            c.execute("SELECT id FROM public.users WHERE email=%s LIMIT 1", (u["email"],))
            found = c.fetchone()
        status = f"[OK] dest_id={found['id']}" if found else "[FALTA] nao existe no DEST"
        print(f"  {u['email']:40}  {str(u['role']):6}  {status}")

    # ── Inboxes SOURCE → compara com DEST ────────────────────────────────────
    print(f"\n{SEP2}")
    print(f"  INBOXES SOURCE vs DEST")
    print(SEP2)

    with cur(sc) as c:
        c.execute("""
            SELECT id, name, channel_type
            FROM public.inboxes
            WHERE account_id = %s
            ORDER BY id
        """, (src_acc_id,))
        src_inboxes = c.fetchall()

    # Inboxes que ja existem no DEST para esta account
    dest_inboxes = []
    if dest_acc_id:
        with cur(dc) as c:
            c.execute("""
                SELECT id, name, channel_type
                FROM public.inboxes
                WHERE account_id = %s
                ORDER BY id
            """, (dest_acc_id,))
            dest_inboxes = c.fetchall()

    dest_inbox_names = {i["name"]: i for i in dest_inboxes}

    print(f"\n  {'INBOX SOURCE':35}  {'CANAL':25}  SITUACAO NO DEST")
    print(f"  {'-'*35}  {'-'*25}  {'-'*30}")

    acao_necessaria = []
    for si in src_inboxes:
        di = dest_inbox_names.get(si["name"])
        with cur(sc) as c:
            c.execute("""
                SELECT COUNT(1) n FROM public.conversations
                WHERE account_id=%s AND inbox_id=%s
            """, (src_acc_id, si["id"]))
            n_conv = c.fetchone()["n"]

        if di:
            situacao = f"[JA EXISTE] dest_id={di['id']}"
        else:
            situacao = f"[FALTA CRIAR] — {n_conv:,} convs dependem desta inbox"
            acao_necessaria.append({
                "name":         si["name"],
                "channel_type": si["channel_type"],
                "n_conv":       n_conv,
            })

        print(f"  {si['name'][:35]:35}  {si['channel_type'][:25]:25}  {situacao}")

    # Inboxes que existem no DEST mas NAO no SOURCE (pre-existentes)
    src_inbox_names = {i["name"] for i in src_inboxes}
    dest_only = [i for i in dest_inboxes if i["name"] not in src_inbox_names]
    if dest_only:
        print(f"\n  Inboxes ja existentes no DEST (nao sao do SOURCE):")
        for i in dest_only:
            print(f"    id={i['id']:4}  {i['name']}")

    # ── Conversations por inbox SOURCE ────────────────────────────────────────
    print(f"\n{SEP2}")
    print(f"  CONVERSATIONS POR INBOX (SOURCE)")
    print(SEP2)

    with cur(sc) as c:
        c.execute("""
            SELECT inbox_id, COUNT(1) n
            FROM public.conversations
            WHERE account_id = %s
            GROUP BY inbox_id ORDER BY n DESC
        """, (src_acc_id,))
        conv_by_inbox = c.fetchall()

    print(f"\n  {'INBOX':35}  {'CONVERSATIONS':>15}")
    print(f"  {'-'*35}  {'-'*15}")
    for row in conv_by_inbox:
        name = next((i["name"] for i in src_inboxes if i["id"] == row["inbox_id"]), f"id={row['inbox_id']}")
        mapeada = "[OK]" if name in dest_inbox_names else "[SEM MAPEAMENTO]"
        print(f"  {name[:35]:35}  {row['n']:>15,}  {mapeada}")

    # ── Plano de ação ─────────────────────────────────────────────────────────
    print(f"\n{SEP}")
    print(f"  PLANO DE ACAO")
    print(SEP)

    if not acao_necessaria:
        print(f"\n  [OK] Todas as inboxes ja existem no DEST.")
        print(f"  Pode rodar: python 01_migrar_account.py \"{account_name}\"")
    else:
        print(f"\n  As seguintes inboxes precisam ser criadas no DEST antes de migrar:")
        print(f"  (crie pelo painel do Chatwoot no banco DEST com exatamente o mesmo nome)\n")
        for item in acao_necessaria:
            print(f"  [ ] Nome:    '{item['name']}'")
            print(f"      Canal:   {item['channel_type']}")
            print(f"      Volume:  {item['n_conv']:,} conversations dependem desta inbox")
            print()
        print(f"  Apos criar as inboxes, rode este script novamente para confirmar.")
        print(f"  Quando todas estiverem [JA EXISTE], rode:")
        print(f"  python 01_migrar_account.py \"{account_name}\"")

    sc.close(); dc.close()
    print(f"\n{SEP}\n")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Uso: python 00_inspecionar.py "nome da account"')
        sys.exit(1)
    run(sys.argv[1])
