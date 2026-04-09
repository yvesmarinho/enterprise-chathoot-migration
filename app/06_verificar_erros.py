#!/usr/bin/env python3
# =============================================================================
# 06_verificar_erros.py — Verifica e reprocessa erros de uma migracao
# =============================================================================
# Le o arquivo de erros e tenta reprocessar as conversations que falharam.
#
# Uso:
#   python 06_verificar_erros.py "Sol Copernico"
# =============================================================================

import sys, json
from db import src, dst, cur

def run(account_name: str):
    import os
    errfile = f"logs/erros_{account_name.replace(' ','_')}.jsonl"

    if not os.path.exists(errfile):
        print(f"  Nenhum arquivo de erros encontrado: {errfile}")
        return

    with open(errfile, encoding="utf-8") as f:
        erros = [json.loads(l) for l in f if l.strip()]

    print(f"\n{'='*65}")
    print(f"  ERROS: '{account_name}'")
    print(f"{'='*65}")
    print(f"\n  Total de erros: {len(erros)}")

    sc = src()
    dc = dst()

    with cur(sc) as c:
        c.execute("SELECT id FROM public.accounts WHERE name=%s", (account_name,))
        r = c.fetchone()
    src_acc_id = r["id"] if r else None

    with cur(dc) as c:
        c.execute("SELECT id FROM public.accounts WHERE name=%s", (account_name,))
        r = c.fetchone()
    dest_acc_id = r["id"] if r else None

    conv_erros = [e for e in erros if e["phase"] == "conversations"]
    msg_erros  = [e for e in erros if e["phase"] == "messages"]
    other      = [e for e in erros if e["phase"] not in ("conversations", "messages")]

    print(f"  Conversations: {len(conv_erros)}")
    print(f"  Messages:      {len(msg_erros)}")
    print(f"  Outros:        {len(other)}")

    # Verifica se as conversations com erro foram migradas mesmo assim
    print(f"\n  Verificando conversations com erro no DEST:")
    for e in conv_erros:
        src_conv_id = e["id"]
        with cur(dc) as c:
            c.execute("""
                SELECT id FROM public.conversations
                WHERE account_id=%s AND custom_attributes->>'src_id'=%s LIMIT 1
            """, (dest_acc_id, str(src_conv_id)))
            found = c.fetchone()

        if found:
            print(f"  conv src={src_conv_id} → JA EXISTE no DEST (dest_id={found['id']}) — erro foi na reconexao, dados ok")
        else:
            print(f"  conv src={src_conv_id} → NAO ENCONTRADA no DEST — precisa reprocessar")
            print(f"    Razao: {e['reason'][:100]}")

    if conv_erros:
        print(f"\n  Se alguma conversation nao foi migrada, rode novamente:")
        print(f"  python 01_migrar_account.py \"{account_name}\"")
        print(f"  (a idempotencia vai pular as que ja existem e processar as que faltam)")

    # Resumo do DEST
    print(f"\n  Estado atual no DEST:")
    for table in ["contacts", "conversations", "messages"]:
        with cur(sc) as c:
            c.execute(f"SELECT COUNT(1) n FROM public.{table} WHERE account_id=%s", (src_acc_id,))
            sn = c.fetchone()["n"]
        with cur(dc) as c:
            c.execute(f"SELECT COUNT(1) n FROM public.{table} WHERE account_id=%s", (dest_acc_id,))
            dn = c.fetchone()["n"]
        status = "[OK]" if dn >= sn else f"[FALTA {sn-dn:,}]"
        print(f"  {table:15} SOURCE={sn:>8,}  DEST={dn:>8,}  {status}")

    sc.close()
    dc.close()
    print(f"\n{'='*65}\n")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Uso: python 06_verificar_erros.py "nome da account"')
        sys.exit(1)
    run(sys.argv[1])
