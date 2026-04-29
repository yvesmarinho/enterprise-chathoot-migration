#!/usr/bin/env python3
# =============================================================================
# 07_diagnostico_attachment_display_id.py
# =============================================================================
# Diagnóstico: attachment ausente no DEST para uma conversa específica.
#
# Rastreia o caminho completo:
#   contact (nome) → conversation (display_id) → messages → attachments
#
# Uso:
#   python 07_diagnostico_attachment_display_id.py "Atendimento Vys Digital" 960
# =============================================================================

import sys
from db import src, dst, cur

SEP = "=" * 70
SEP2 = "-" * 70


def run(contact_name: str, display_id: int):
    sc = src()
    dc = dst()

    print(f"\n{SEP}")
    print(f"  DIAGNÓSTICO ATTACHMENT — contato='{contact_name}'  display_id={display_id}")
    print(SEP)

    # ── 1. Localizar o contato no SOURCE ─────────────────────────────────────
    print(f"\n{SEP2}")
    print("  [1] CONTATO NO SOURCE")
    print(SEP2)

    with cur(sc) as c:
        c.execute(
            "SELECT id, account_id, name, email, phone_number "
            "FROM public.contacts WHERE name=%s LIMIT 5",
            (contact_name,),
        )
        src_contacts = c.fetchall()

    if not src_contacts:
        print(f"  Nome exato '{contact_name}' não encontrado — tentando busca fuzzy ILIKE ...")
        words = [w for w in contact_name.split() if len(w) >= 3]
        pattern = "%" + "%".join(words) + "%" if words else f"%{contact_name}%"
        with cur(sc) as c:
            c.execute(
                "SELECT id, account_id, name, email, phone_number "
                "FROM public.contacts WHERE name ILIKE %s ORDER BY name LIMIT 10",
                (pattern,),
            )
            src_contacts = c.fetchall()

    if not src_contacts:
        print(f"  ERRO: nenhum contato com nome similar a '{contact_name}' encontrado na SOURCE.")
        print(f"         Execute sem o nome para buscar apenas pelo display_id:")
        print(f"         python 07_diagnostico_attachment_display_id.py '' {display_id}")
        # Fallback: buscar diretamente pela conversa display_id sem filtro de contato
        _buscar_por_display_id_global(sc, dc, display_id)
        sc.close()
        dc.close()
        return

    print(f"  Contatos encontrados ({len(src_contacts)}):")
    for ct in src_contacts:
        print(
            f"  contact_id={ct['id']}  account_id={ct['account_id']}  "
            f"name='{ct['name']}'  email={ct['email']}  phone={ct['phone_number']}"
        )

    src_contact = src_contacts[0]
    src_contact_id = src_contact["id"]
    src_account_id = src_contact["account_id"]

    # ── 2. Localizar a conversa display_id no SOURCE ──────────────────────────
    print(f"\n{SEP2}")
    print(f"  [2] CONVERSA display_id={display_id} NO SOURCE")
    print(SEP2)

    with cur(sc) as c:
        c.execute(
            "SELECT id, display_id, account_id, contact_id, status "
            "FROM public.conversations "
            "WHERE account_id=%s AND display_id=%s LIMIT 1",
            (src_account_id, display_id),
        )
        src_conv = c.fetchone()

    if not src_conv:
        print(
            f"  AVISO: conversa display_id={display_id} não encontrada no account_id={src_account_id}."
        )
        print(f"         Tentando busca global por display_id={display_id} ...")
        with cur(sc) as c:
            c.execute(
                "SELECT id, display_id, account_id, contact_id, status "
                "FROM public.conversations WHERE display_id=%s",
                (display_id,),
            )
            rows = c.fetchall()
        for r in rows:
            print(
                f"  [global] conv_id={r['id']}  account_id={r['account_id']}  "
                f"contact_id={r['contact_id']}  status={r['status']}"
            )
        if not rows:
            print("  ERRO: nenhuma conversa encontrada.")
            return
        src_conv = rows[0]
    else:
        print(
            f"  conv_id={src_conv['id']}  account_id={src_conv['account_id']}  "
            f"contact_id={src_conv['contact_id']}  status={src_conv['status']}"
        )

    src_conv_id = src_conv["id"]
    src_account_id = src_conv["account_id"]

    # ── 3. Mensagens da conversa no SOURCE ────────────────────────────────────
    print(f"\n{SEP2}")
    print(f"  [3] MENSAGENS DA CONVERSA src_conv_id={src_conv_id} NO SOURCE")
    print(SEP2)

    with cur(sc) as c:
        c.execute(
            "SELECT id, conversation_id, account_id, message_type, content "
            "FROM public.messages WHERE conversation_id=%s ORDER BY id",
            (src_conv_id,),
        )
        src_messages = c.fetchall()

    print(f"  Total de mensagens no SOURCE: {len(src_messages)}")
    for m in src_messages:
        print(
            f"  msg_id={m['id']}  type={m['message_type']}  "
            f"content={str(m['content'])[:60] if m['content'] else '(null)'}"
        )

    src_msg_ids = [m["id"] for m in src_messages]

    # ── 4. Attachments das mensagens no SOURCE ────────────────────────────────
    print(f"\n{SEP2}")
    print(f"  [4] ATTACHMENTS DAS MENSAGENS NO SOURCE")
    print(SEP2)

    if not src_msg_ids:
        print("  Nenhuma mensagem encontrada, portanto nenhum attachment esperado.")
        return

    with cur(sc) as c:
        c.execute(
            "SELECT id, message_id, account_id, file_type, external_url "
            "FROM public.attachments WHERE message_id = ANY(%s) ORDER BY id",
            (src_msg_ids,),
        )
        src_attachments = c.fetchall()

    print(f"  Total de attachments no SOURCE: {len(src_attachments)}")
    for a in src_attachments:
        print(
            f"  att_id={a['id']}  msg_id={a['message_id']}  "
            f"file_type={a['file_type']}  url={str(a['external_url'])[:80] if a['external_url'] else '(null)'}"
        )

    if not src_attachments:
        print("  AVISO: nenhum attachment encontrado na SOURCE para esta conversa.")
        return

    # ── 5. Localizar a conversa no DEST ──────────────────────────────────────
    print(f"\n{SEP2}")
    print(f"  [5] CONVERSA NO DEST (via src_id={src_conv_id})")
    print(SEP2)

    with cur(dc) as c:
        c.execute(
            "SELECT id, display_id, account_id, contact_id, status, "
            "custom_attributes->>'src_id' AS src_id "
            "FROM public.conversations "
            "WHERE custom_attributes->>'src_id'=%s LIMIT 1",
            (str(src_conv_id),),
        )
        dest_conv = c.fetchone()

    if not dest_conv:
        print(f"  PROBLEMA: conversa src_id={src_conv_id} NÃO encontrada no DEST!")
        print(f"            → A conversa não foi migrada. Attachments dependentes também ausentes.")
        _diagnosticar_conv_skip(sc, dc, src_conv_id, src_account_id)
        return

    dest_conv_id = dest_conv["id"]
    print(
        f"  dest_conv_id={dest_conv['id']}  display_id={dest_conv['display_id']}  "
        f"account_id={dest_conv['account_id']}  src_id={dest_conv['src_id']}"
    )

    # ── 6. Mensagens da conversa no DEST ─────────────────────────────────────
    print(f"\n{SEP2}")
    print(f"  [6] MENSAGENS DA CONVERSA NO DEST (dest_conv_id={dest_conv_id})")
    print(SEP2)

    with cur(dc) as c:
        c.execute(
            "SELECT id, conversation_id, "
            "custom_attributes->>'src_id' AS src_id, message_type "
            "FROM public.messages WHERE conversation_id=%s ORDER BY id",
            (dest_conv_id,),
        )
        dest_messages = c.fetchall()

    print(f"  Total de mensagens no DEST: {len(dest_messages)}")
    dest_msg_src_ids = {int(m["src_id"]): m["id"] for m in dest_messages if m["src_id"]}

    # Cruzar com src
    for sm in src_messages:
        dst_id = dest_msg_src_ids.get(sm["id"])
        status = f"→ dest_msg_id={dst_id}" if dst_id else "→ ❌ AUSENTE NO DEST"
        print(f"  src_msg_id={sm['id']}  {status}")

    # ── 7. Attachments no DEST ────────────────────────────────────────────────
    print(f"\n{SEP2}")
    print(f"  [7] ATTACHMENTS NO DEST")
    print(SEP2)

    dest_msg_ids = [m["id"] for m in dest_messages]
    if dest_msg_ids:
        with cur(dc) as c:
            c.execute(
                "SELECT id, message_id, account_id, file_type, external_url "
                "FROM public.attachments WHERE message_id = ANY(%s) ORDER BY id",
                (dest_msg_ids,),
            )
            dest_attachments = c.fetchall()
    else:
        dest_attachments = []

    print(f"  Total de attachments no DEST: {len(dest_attachments)}")
    for a in dest_attachments:
        print(
            f"  att_id={a['id']}  msg_id={a['message_id']}  "
            f"file_type={a['file_type']}  url={str(a['external_url'])[:80] if a['external_url'] else '(null)'}"
        )

    # ── 8. Diagnóstico cruzado ────────────────────────────────────────────────
    print(f"\n{SEP2}")
    print(f"  [8] DIAGNÓSTICO CRUZADO — CAUSA RAIZ")
    print(SEP2)

    for sa in src_attachments:
        src_msg_id = sa["message_id"]
        dest_msg_id = dest_msg_src_ids.get(src_msg_id)
        if not dest_msg_id:
            print(
                f"  ❌ att_id={sa['id']} AUSENTE: mensagem src_id={src_msg_id} "
                f"não foi migrada → attachment também ausente (skip em cascata)"
            )
        else:
            found = any(da["message_id"] == dest_msg_id for da in dest_attachments)
            if found:
                print(
                    f"  ✅ att_id={sa['id']} PRESENTE no DEST (msg src→dest: {src_msg_id}→{dest_msg_id})"
                )
            else:
                print(
                    f"  ❌ att_id={sa['id']} AUSENTE: mensagem migrada (dest_msg_id={dest_msg_id}), "
                    f"mas attachment NÃO foi inserido → investigar AttachmentsMigrator"
                )

    sc.close()
    dc.close()


def _diagnosticar_conv_skip(sc, dc, src_conv_id: int, src_account_id: int):
    """Tenta identificar por que a conversa não foi migrada."""
    print(f"\n  --- Investigando skip da conv src_id={src_conv_id} ---")

    with cur(sc) as c:
        c.execute(
            "SELECT id, account_id, inbox_id, contact_id, assignee_id "
            "FROM public.conversations WHERE id=%s",
            (src_conv_id,),
        )
        conv = c.fetchone()

    if not conv:
        print("  ERRO: conversa não existe mais na SOURCE.")
        return

    # Verificar se account_id foi migrado
    with cur(dc) as c:
        c.execute(
            "SELECT id FROM public.accounts " "WHERE custom_attributes->>'src_id'=%s LIMIT 1",
            (str(conv["account_id"]),),
        )
        acc_dest = c.fetchone()

    acc_status = f"✅ dest_id={acc_dest['id']}" if acc_dest else "❌ NÃO MIGRADO"
    print(f"  account_id={conv['account_id']}: {acc_status}")

    # Verificar se contact_id foi migrado
    with cur(dc) as c:
        c.execute(
            "SELECT id FROM public.contacts " "WHERE custom_attributes->>'src_id'=%s LIMIT 1",
            (str(conv["contact_id"]),),
        )
        contact_dest = c.fetchone()

    contact_status = f"✅ dest_id={contact_dest['id']}" if contact_dest else "❌ NÃO MIGRADO"
    print(f"  contact_id={conv['contact_id']}: {contact_status}")

    # Verificar inbox — inboxes usam migration_state (sem custom_attributes)
    with cur(dc) as c:
        c.execute(
            "SELECT id_destino FROM public.migration_state "
            "WHERE tabela='inboxes' AND id_origem=%s LIMIT 1",
            (conv["inbox_id"],),
        )
        inbox_state = c.fetchone()

    inbox_status = f"✅ dest_id={inbox_state['id_destino']}" if inbox_state else "❌ NÃO MIGRADO"
    print(f"  inbox_id={conv['inbox_id']}: {inbox_status}")


def _buscar_por_display_id_global(sc, dc, display_id: int):
    """Fallback: diagnóstico completo usando apenas display_id, sem nome do contato."""
    print(f"\n{SEP2}")
    print(f"  [FALLBACK] BUSCA GLOBAL POR display_id={display_id}")
    print(SEP2)

    with cur(sc) as c:
        c.execute(
            "SELECT c.id, c.display_id, c.account_id, c.contact_id, c.status, "
            "ct.name AS contact_name, a.name AS account_name "
            "FROM public.conversations c "
            "LEFT JOIN public.contacts ct ON ct.id = c.contact_id "
            "LEFT JOIN public.accounts a ON a.id = c.account_id "
            "WHERE c.display_id=%s",
            (display_id,),
        )
        src_convs = c.fetchall()

    if not src_convs:
        print(f"  ERRO: nenhuma conversa com display_id={display_id} encontrada na SOURCE.")
        return

    print(f"  Conversas na SOURCE com display_id={display_id}:")
    for r in src_convs:
        print(
            f"  conv_id={r['id']}  account='{r['account_name']}'  "
            f"contact='{r['contact_name']}'  status={r['status']}"
        )

    print(f"\n  Conversas no DEST com display_id={display_id}:")
    with cur(dc) as c:
        c.execute(
            "SELECT c.id, c.display_id, c.account_id, c.contact_id, c.status, "
            "ct.name AS contact_name, a.name AS account_name, "
            "c.custom_attributes->>'src_id' AS src_id "
            "FROM public.conversations c "
            "LEFT JOIN public.contacts ct ON ct.id = c.contact_id "
            "LEFT JOIN public.accounts a ON a.id = c.account_id "
            "WHERE c.display_id=%s",
            (display_id,),
        )
        dest_convs = c.fetchall()

    if not dest_convs:
        print(f"  Nenhuma conversa com display_id={display_id} encontrada no DEST.")
    for r in dest_convs:
        print(
            f"  conv_id={r['id']}  account='{r['account_name']}'  "
            f"contact='{r['contact_name']}'  status={r['status']}  src_id={r['src_id']}"
        )

    # Para cada conversa SOURCE, verificar attachments
    for src_conv in src_convs:
        src_conv_id = src_conv["id"]
        print(f"\n  -- Attachments da conversa SOURCE conv_id={src_conv_id} --")

        with cur(sc) as c:
            c.execute(
                "SELECT a.id, a.message_id, a.file_type, a.external_url "
                "FROM public.attachments a "
                "JOIN public.messages m ON m.id = a.message_id "
                "WHERE m.conversation_id=%s ORDER BY a.id",
                (src_conv_id,),
            )
            src_atts = c.fetchall()

        print(f"  SOURCE: {len(src_atts)} attachment(s)")
        for a in src_atts:
            print(
                f"    att_id={a['id']}  msg_id={a['message_id']}  "
                f"file_type={a['file_type']}  url={str(a['external_url'])[:80] if a['external_url'] else '(null)'}"
            )

        # Buscar no DEST via src_id da conversa
        with cur(dc) as c:
            c.execute(
                "SELECT id FROM public.conversations "
                "WHERE custom_attributes->>'src_id'=%s LIMIT 1",
                (str(src_conv_id),),
            )
            dest_conv = c.fetchone()

        if not dest_conv:
            print(
                f"  DEST: conversa src_id={src_conv_id} NÃO migrada → attachments ausentes em cascata"
            )
            _diagnosticar_conv_skip(sc, dc, src_conv_id, src_conv["account_id"])
            continue

        dest_conv_id = dest_conv["id"]
        with cur(dc) as c:
            c.execute(
                "SELECT a.id, a.message_id, a.file_type, a.external_url "
                "FROM public.attachments a "
                "JOIN public.messages m ON m.id = a.message_id "
                "WHERE m.conversation_id=%s ORDER BY a.id",
                (dest_conv_id,),
            )
            dest_atts = c.fetchall()

        print(f"  DEST (dest_conv_id={dest_conv_id}): {len(dest_atts)} attachment(s)")
        for a in dest_atts:
            print(
                f"    att_id={a['id']}  msg_id={a['message_id']}  "
                f"file_type={a['file_type']}  url={str(a['external_url'])[:80] if a['external_url'] else '(null)'}"
            )

        if len(src_atts) != len(dest_atts):
            print(
                f"  ❌ DIVERGÊNCIA: SOURCE={len(src_atts)}  DEST={len(dest_atts)}  "
                f"diff={len(src_atts) - len(dest_atts)}"
            )
        else:
            print(f"  ✅ Contagem de attachments coincide ({len(src_atts)})")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Uso: python 07_diagnostico_attachment_display_id.py <contact_name> <display_id>")
        print("     Use '' como contact_name para busca global por display_id.")
        sys.exit(1)

    _contact_name = sys.argv[1]
    _display_id = int(sys.argv[2])
    run(_contact_name, _display_id)
