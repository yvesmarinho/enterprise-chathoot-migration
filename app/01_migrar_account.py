#!/usr/bin/env python3
# =============================================================================
# 01_migrar_account.py — Migra UMA account completa SOURCE → DEST
# =============================================================================
# O script faz TUDO automaticamente:
#   1. Cria a account no DEST (se nao existir)
#   2. Cria as inboxes no DEST copiando os canais do SOURCE
#   3. Mapeia users por email
#   4. Migra contacts (dedup por identifier/phone/email)
#   5. Migra conversations + messages (loop aninhado, igual ao SQL original)
#
# REGRA CRITICA — content_attributes = NULL sempre nas messages
# Evita o erro "no implicit conversion of Hash into String" no Rails.
#
# Uso:
#   python 01_migrar_account.py "Sol Copernico"
#   python 01_migrar_account.py "Sol Copernico" --dry-run

# =============================================================================

import sys, json, uuid as uuid_lib, time, os
import psycopg2
from db import src, dst, cur

DRY_RUN = "--dry-run" in sys.argv

# =============================================================================
# HELPERS
# =============================================================================

def jdumps(v):
    """Serializa para JSON string. None retorna None."""
    if v is None:
        return None
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return v

def log(msg):
    print(f"  {msg}")

def log_err(phase, entity_id, reason, errfile):
    entry = json.dumps({
        "phase": phase,
        "id": str(entity_id),
        "reason": str(reason)[:400]
    }, ensure_ascii=False)
    with open(errfile, "a", encoding="utf-8") as f:
        f.write(entry + "\n")
    print(f"  [ERRO] {phase} id={entity_id}: {str(reason)[:120]}")

def reconnect_dst():
    for attempt in range(1, 6):
        try:
            time.sleep(5)
            print(f"  [RECONEXAO] tentativa {attempt}...")
            c = dst()
            print(f"  [RECONEXAO] OK")
            return c
        except Exception as e:
            print(f"  [RECONEXAO] falhou: {e}")
    raise RuntimeError("Nao foi possivel reconectar ao DEST.")

# =============================================================================
# FASE 0 — ACCOUNT
# =============================================================================

def migrate_account(sc, dc, src_acc_id, account_name, errfile):
    """Cria a account no DEST se nao existir. Retorna dest_acc_id."""
    with cur(dc) as c:
        c.execute("SELECT id FROM public.accounts WHERE name=%s", (account_name,))
        existing = c.fetchone()

    if existing:
        dest_acc_id = existing["id"]
        log(f"Account ja existe no DEST: id={dest_acc_id}")
        return dest_acc_id

    # Busca dados completos da account no SOURCE
    with cur(sc) as c:
        c.execute("SELECT * FROM public.accounts WHERE id=%s", (src_acc_id,))
        row = c.fetchone()

    if DRY_RUN:
        log(f"[DRY-RUN] Criaria account '{account_name}'")
        return -1

    with cur(dc) as c:
        c.execute("""
            INSERT INTO public.accounts
                (name, created_at, updated_at, locale, domain,
                 support_email, feature_flags, auto_resolve_duration,
                 limits, custom_attributes, status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
        """, (
            row["name"], row["created_at"], row["updated_at"],
            row["locale"], row["domain"], row["support_email"],
            row["feature_flags"], row["auto_resolve_duration"],
            jdumps(row["limits"]), jdumps(row["custom_attributes"]),
            row["status"],
        ))
        dest_acc_id = c.fetchone()["id"]
    dc.commit()
    log(f"Account criada no DEST: id={dest_acc_id}")
    return dest_acc_id

# =============================================================================
# FASE 1 — INBOXES + CANAIS
# =============================================================================

# Campos jsonb por tabela de canal
CHANNEL_JSONB = {
    "channel_whatsapp":    {"provider_config", "message_templates"},
    "channel_web_widgets": {"pre_chat_form_options"},
    "channel_api":         {"additional_attributes"},
    "channel_email":       {"provider_config"},
}

# Colunas a copiar do SOURCE por tipo de canal
CHANNEL_COLS = {
    "Channel::Whatsapp": {
        "table": "channel_whatsapp",
        "cols":  ["account_id","phone_number","provider","provider_config",
                  "created_at","updated_at"],
    },
    "Channel::WebWidget": {
        "table": "channel_web_widgets",
        "cols":  ["website_url","account_id","created_at","updated_at",
                  "website_token","widget_color","welcome_title","welcome_tagline",
                  "feature_flags","reply_time","hmac_token","pre_chat_form_enabled",
                  "pre_chat_form_options","hmac_mandatory","continuity_via_email"],
    },
    "Channel::Api": {
        "table": "channel_api",
        "cols":  ["account_id","webhook_url","created_at","updated_at",
                  "identifier","hmac_token","hmac_mandatory","additional_attributes"],
    },
    "Channel::Email": {
        "table": "channel_email",
        "cols":  ["account_id","email","forward_to_email","created_at","updated_at"],
    },
    "Channel::Telegram": {
        "table": "channel_telegram",
        "cols":  ["account_id","bot_name","bot_token","created_at","updated_at"],
    },
}

def create_channel(sc, dc, channel_type, src_channel_id, dest_acc_id):
    """Cria o registro do canal no DEST e retorna o novo channel_id."""
    cfg = CHANNEL_COLS.get(channel_type)
    if not cfg:
        log(f"  Canal '{channel_type}' sem suporte automatico — inbox sera criada sem canal especifico")
        return None

    table    = cfg["table"]
    cols     = cfg["cols"]
    jsonb_fs = CHANNEL_JSONB.get(table, set())

    with cur(sc) as c:
        c.execute(f"SELECT * FROM public.{table} WHERE id=%s", (src_channel_id,))
        src_row = c.fetchone()

    if not src_row:
        log(f"  Canal nao encontrado: {table}.id={src_channel_id}")
        return None

    values = []
    for col in cols:
        if col == "account_id":
            values.append(dest_acc_id)
        elif col in jsonb_fs:
            values.append(jdumps(src_row.get(col)))
        else:
            values.append(src_row.get(col))

    col_sql  = ", ".join(cols)
    ph_sql   = ", ".join(["%s"] * len(cols))

    # Whatsapp: phone_number tem unique constraint — verifica antes
    if table == "channel_whatsapp":
        phone = src_row.get("phone_number")
        with cur(dc) as c:
            c.execute("SELECT id FROM public.channel_whatsapp WHERE phone_number=%s LIMIT 1",
                      (phone,))
            existing = c.fetchone()
        if existing:
            log(f"  WhatsApp {phone} ja existe no DEST (channel_id={existing['id']}) — reutilizando")
            return existing["id"]

    with cur(dc) as c:
        c.execute(
            f"INSERT INTO public.{table} ({col_sql}) VALUES ({ph_sql}) RETURNING id",
            values
        )
        return c.fetchone()["id"]
    # commit feito junto com a inbox

def migrate_inboxes(sc, dc, src_acc_id, dest_acc_id, errfile):
    """
    Cria todas as inboxes do SOURCE no DEST.
    Se ja existir inbox com mesmo nome + account no DEST, reutiliza.
    Retorna dict: src_inbox_id -> dest_inbox_id
    """
    inbox_map = {}

    with cur(sc) as c:
        c.execute("""
            SELECT id, name, channel_type, channel_id,
                   enable_auto_assignment, greeting_enabled, greeting_message,
                   email_address, working_hours_enabled, out_of_office_message,
                   timezone, enable_email_collect, csat_survey_enabled,
                   allow_messages_after_resolved, auto_assignment_config,
                   lock_to_single_conversation, sender_name_type, business_name,
                   created_at, updated_at
            FROM public.inboxes
            WHERE account_id=%s ORDER BY id
        """, (src_acc_id,))
        src_inboxes = c.fetchall()

    log(f"Inboxes SOURCE: {len(src_inboxes)}")

    for si in src_inboxes:
        src_inbox_id = si["id"]

        # Verifica se ja existe no DEST pelo nome + account
        with cur(dc) as c:
            c.execute("""
                SELECT id FROM public.inboxes
                WHERE account_id=%s AND name=%s LIMIT 1
            """, (dest_acc_id, si["name"]))
            existing = c.fetchone()

        if existing:
            inbox_map[src_inbox_id] = existing["id"]
            log(f"  Inbox '{si['name']}' ja existe no DEST → dest_id={existing['id']}")
            continue

        if DRY_RUN:
            inbox_map[src_inbox_id] = -(src_inbox_id)
            log(f"  [DRY-RUN] Criaria inbox '{si['name']}' ({si['channel_type']})")
            continue

        try:
            # Cria o canal correspondente
            new_channel_id = create_channel(
                sc, dc, si["channel_type"], si["channel_id"], dest_acc_id
            )

            with cur(dc) as c:
                c.execute("""
                    INSERT INTO public.inboxes (
                        channel_id, account_id, name, created_at, updated_at,
                        channel_type, enable_auto_assignment, greeting_enabled,
                        greeting_message, email_address, working_hours_enabled,
                        out_of_office_message, timezone, enable_email_collect,
                        csat_survey_enabled, allow_messages_after_resolved,
                        auto_assignment_config, lock_to_single_conversation,
                        sender_name_type, business_name
                    ) VALUES (
                        %s,%s,%s,%s,%s,
                        %s,%s,%s,
                        %s,%s,%s,
                        %s,%s,%s,
                        %s,%s,
                        %s,%s,
                        %s,%s
                    ) RETURNING id
                """, (
                    new_channel_id or si["channel_id"],
                    dest_acc_id,
                    si["name"], si["created_at"], si["updated_at"],
                    si["channel_type"],
                    si.get("enable_auto_assignment", True),
                    si.get("greeting_enabled", False),
                    si.get("greeting_message"),
                    si.get("email_address"),
                    si.get("working_hours_enabled", False),
                    si.get("out_of_office_message"),
                    si.get("timezone", "UTC"),
                    si.get("enable_email_collect", True),
                    si.get("csat_survey_enabled", False),
                    si.get("allow_messages_after_resolved", True),
                    jdumps(si.get("auto_assignment_config") or {}),
                    si.get("lock_to_single_conversation", False),
                    si.get("sender_name_type", 0),
                    si.get("business_name"),
                ))
                new_inbox_id = c.fetchone()["id"]

            dc.commit()
            inbox_map[src_inbox_id] = new_inbox_id
            log(f"  Inbox '{si['name']}' criada → dest_id={new_inbox_id}")

        except Exception as e:
            dc.rollback()
            log_err("inboxes", src_inbox_id, e, errfile)

    return inbox_map

# =============================================================================
# FASE 2 — USERS (mapeia por email, nao duplica)
# =============================================================================

def map_users(sc, dc, src_acc_id, dest_acc_id):
    """Mapeia users por email. Retorna (user_map, default_assignee_id)."""
    user_map = {}

    with cur(sc) as c:
        c.execute("""
            SELECT u.id, u.email, au.role
            FROM public.users u
            JOIN public.account_users au ON au.user_id = u.id
            WHERE au.account_id=%s ORDER BY au.role DESC, u.id
        """, (src_acc_id,))
        src_users = c.fetchall()

    default_assignee_id = None

    for u in src_users:
        with cur(dc) as c:
            c.execute("SELECT id FROM public.users WHERE email=%s LIMIT 1", (u["email"],))
            dest_u = c.fetchone()

        if dest_u:
            user_map[u["id"]] = dest_u["id"]
            if default_assignee_id is None:
                default_assignee_id = dest_u["id"]

            # Garante vínculo account_user no DEST
            if not DRY_RUN:
                with cur(dc) as c:
                    c.execute("""
                        INSERT INTO public.account_users
                            (account_id, user_id, role, created_at, updated_at)
                        VALUES (%s,%s,%s,NOW(),NOW())
                        ON CONFLICT (account_id, user_id) DO NOTHING
                    """, (dest_acc_id, dest_u["id"], u["role"]))
                dc.commit()
        else:
            log(f"  AVISO: user {u['email']} nao encontrado no DEST — sera ignorado")

    log(f"Users mapeados: {len(user_map)} | assignee padrao: {default_assignee_id}")
    return user_map, default_assignee_id

# =============================================================================
# FASE 3 — CONTACTS
# =============================================================================

def migrate_contacts(sc, dc, src_acc_id, dest_acc_id, errfile):
    ins = dup = err = 0
    contact_map = {}

    with cur(sc) as c:
        c.execute("""
            SELECT id, name, email, phone_number, additional_attributes,
                   identifier, custom_attributes, last_activity_at,
                   contact_type, blocked, created_at, updated_at
            FROM public.contacts
            WHERE account_id=%s ORDER BY id
        """, (src_acc_id,))
        contacts = c.fetchall()

    log(f"Contacts SOURCE: {len(contacts):,}")

    for row in contacts:
        src_id = row["id"]

        # Idempotencia: ja migrado?
        with cur(dc) as c:
            c.execute("""
                SELECT id FROM public.contacts
                WHERE account_id=%s AND custom_attributes->>'src_id'=%s LIMIT 1
            """, (dest_acc_id, str(src_id)))
            existing = c.fetchone()
        if existing:
            contact_map[src_id] = existing["id"]
            dup += 1
            continue

        # Dedup por identifier
        identifier = (row["identifier"] or "").strip() or None
        if identifier:
            with cur(dc) as c:
                c.execute("""
                    SELECT id FROM public.contacts
                    WHERE account_id=%s AND identifier=%s LIMIT 1
                """, (dest_acc_id, identifier))
                existing = c.fetchone()
            if existing:
                contact_map[src_id] = existing["id"]
                dup += 1
                continue

        # Dedup por phone
        phone = (row["phone_number"] or "").strip() or None
        if phone:
            with cur(dc) as c:
                c.execute("""
                    SELECT id FROM public.contacts
                    WHERE account_id=%s AND phone_number=%s LIMIT 1
                """, (dest_acc_id, phone))
                existing = c.fetchone()
            if existing:
                contact_map[src_id] = existing["id"]
                dup += 1
                continue

        # Dedup por email
        email = (row["email"] or "").strip() or None
        if email:
            with cur(dc) as c:
                c.execute("""
                    SELECT id FROM public.contacts
                    WHERE account_id=%s AND email=%s LIMIT 1
                """, (dest_acc_id, email))
                existing = c.fetchone()
            if existing:
                contact_map[src_id] = existing["id"]
                dup += 1
                continue

        # Dedup por nome (fallback final — contact sem phone/email/identifier)
        if not phone and not email and not identifier:
            name_clean = (row["name"] or "").strip()
            if name_clean:
                with cur(dc) as c:
                    c.execute("""
                        SELECT id FROM public.contacts
                        WHERE account_id=%s AND name=%s LIMIT 1
                    """, (dest_acc_id, name_clean))
                    existing = c.fetchone()
                if existing:
                    contact_map[src_id] = existing["id"]
                    dup += 1
                    continue

        # Monta custom_attributes com src_id
        src_custom = row["custom_attributes"] or {}
        if isinstance(src_custom, str):
            try: src_custom = json.loads(src_custom)
            except: src_custom = {}
        src_custom["src_id"] = str(src_id)

        if DRY_RUN:
            contact_map[src_id] = -(src_id)
            ins += 1
            continue

        try:
            with cur(dc) as c:
                c.execute("""
                    INSERT INTO public.contacts (
                        name, email, phone_number, account_id,
                        additional_attributes, identifier,
                        custom_attributes, last_activity_at,
                        contact_type, blocked, created_at, updated_at
                    ) VALUES (%s,%s,%s,%s, %s,%s, %s,%s, %s,%s,%s,%s)
                    RETURNING id
                """, (
                    (row["name"] or "").strip(), email, phone, dest_acc_id,
                    jdumps(row["additional_attributes"]),
                    identifier,
                    jdumps(src_custom),
                    row["last_activity_at"],
                    row["contact_type"] or 0,
                    row["blocked"] or False,
                    row["created_at"], row["updated_at"],
                ))
                new_id = c.fetchone()["id"]
            dc.commit()
            contact_map[src_id] = new_id
            ins += 1
        except Exception as e:
            dc.rollback()
            log_err("contacts", src_id, e, errfile)
            err += 1

    log(f"Contacts: {ins:,} inseridos | {dup:,} dedup | {err} erros")
    return contact_map

# =============================================================================
# FASE 4 — CONVERSATIONS + MESSAGES
# =============================================================================

def migrate_messages_of_conv(sc, dc, src_conv_id, dest_conv_id,
                              dest_acc_id, dest_inbox_id,
                              contact_map, user_map,
                              default_assignee_id, msg_map, errfile):
    ins = dup = err = 0

    # Nova conexao SOURCE para cada conversation — evita timeout
    sc_msg = src()
    try:
        with cur(sc_msg) as c:
            c.execute("""
                SELECT id, content, message_type, created_at, updated_at,
                       private, status, content_type,
                       sender_type, sender_id, additional_attributes
                FROM public.messages
                WHERE conversation_id=%s ORDER BY id ASC
            """, (src_conv_id,))
            messages = c.fetchall()
    finally:
        sc_msg.close()

    for msg in messages:
        src_msg_id = msg["id"]

        if src_msg_id in msg_map:
            dup += 1
            continue

        # Idempotencia
        with cur(dc) as c:
            c.execute("""
                SELECT id FROM public.messages
                WHERE account_id=%s
                  AND additional_attributes->>'src_id'=%s
                LIMIT 1
            """, (dest_acc_id, str(src_msg_id)))
            existing = c.fetchone()
        if existing:
            msg_map[src_msg_id] = existing["id"]
            dup += 1
            continue

        # Resolve sender
        sender_type    = msg["sender_type"]
        dest_sender_id = None
        if sender_type == "Contact":
            dest_sender_id = contact_map.get(msg["sender_id"])
        elif sender_type == "User":
            dest_sender_id = user_map.get(msg["sender_id"]) or default_assignee_id

        # additional_attributes com src_id
        src_aa = msg["additional_attributes"] or {}
        if isinstance(src_aa, str):
            try: src_aa = json.loads(src_aa)
            except: src_aa = {}
        src_aa["src_id"] = str(src_msg_id)

        if DRY_RUN:
            msg_map[src_msg_id] = -(src_msg_id)
            ins += 1
            continue

        try:
            with cur(dc) as c:
                c.execute("""
                    INSERT INTO public.messages (
                        content, account_id, inbox_id, conversation_id,
                        message_type, created_at, updated_at,
                        private, status, source_id,
                        content_type,
                        content_attributes,
                        sender_type, sender_id,
                        external_source_ids,
                        additional_attributes,
                        processed_message_content,
                        sentiment
                    ) VALUES (
                        %s,%s,%s,%s,
                        %s,%s,%s,
                        %s,%s,NULL,
                        %s,
                        NULL,
                        %s,%s,
                        NULL,
                        %s,
                        %s,
                        '{}'
                    ) RETURNING id
                """, (
                    msg["content"],
                    dest_acc_id, dest_inbox_id, dest_conv_id,
                    msg["message_type"],
                    msg["created_at"], msg["updated_at"],
                    msg["private"] or False,
                    msg["status"] or 0,
                    msg["content_type"] or 0,
                    # content_attributes = NULL — SEMPRE — evita erro no Rails
                    sender_type, dest_sender_id,
                    # external_source_ids = NULL
                    jdumps(src_aa),
                    msg["content"],  # processed_message_content
                    # sentiment = '{}'
                ))
                new_id = c.fetchone()["id"]
            msg_map[src_msg_id] = new_id
            ins += 1
        except Exception as e:
            try: dc.rollback()
            except: pass
            log_err("messages", src_msg_id, e, errfile)
            err += 1

    # Commit de toda a conversation de uma vez
    if not DRY_RUN and ins > 0:
        dc.commit()

    return ins, dup, err


def migrate_conversations(sc, dc, src_acc_id, dest_acc_id,
                          inbox_map, contact_map, user_map,
                          default_assignee_id, errfile):
    conv_ins = conv_dup = conv_err = 0
    msg_ins  = msg_dup  = msg_err  = 0
    msg_map  = {}

    # Reconecta SOURCE — pode ter fechado durante a migracao de contacts
    try:
        with cur(sc) as c:
            c.execute("SELECT 1")
    except Exception:
        log("  [SOURCE] Reconectando antes das conversations...")
        try: sc.close()
        except: pass
        sc = src()

    # Reconecta DEST tambem por seguranca
    try:
        with cur(dc) as c:
            c.execute("SELECT 1")
    except Exception:
        log("  [DEST] Reconectando antes das conversations...")
        try: dc.close()
        except: pass
        dc = dst()

    # Cache display_id
    with cur(dc) as c:
        c.execute("""
            SELECT COALESCE(MAX(display_id),0)+1 AS n
            FROM public.conversations WHERE account_id=%s
        """, (dest_acc_id,))
        next_did = c.fetchone()["n"]

    # Conta total para progresso
    with cur(sc) as c:
        c.execute("SELECT COUNT(1) n FROM public.conversations WHERE account_id=%s",
                  (src_acc_id,))
        total_convs = c.fetchone()["n"]

    log(f"Conversations SOURCE: {total_convs:,}")
    checkpoint = 0

    # Busca IDs de todas as conversations (apenas IDs — conexao rapida e fecha logo)
    sc_tmp = src()
    try:
        with cur(sc_tmp) as c:
            c.execute("""
                SELECT id FROM public.conversations
                WHERE account_id=%s ORDER BY id ASC
            """, (src_acc_id,))
            all_conv_ids = [row["id"] for row in c.fetchall()]
    finally:
        sc_tmp.close()

    log(f"  IDs carregados: {len(all_conv_ids):,}")

    # pode aumentar porem corre o risco de termos timeout do banco podendo testar com 50 ou 100
    BATCH = 50  

    for batch_start in range(0, len(all_conv_ids), BATCH):
        batch_ids = all_conv_ids[batch_start:batch_start + BATCH]

        # Abre nova conexao SOURCE para cada lote — evita timeout por conexao longa
        sc_batch = None
        try:
            sc_batch = src()
            with cur(sc_batch) as c:
                c.execute("""
                    SELECT id, inbox_id, status, assignee_id,
                           created_at, updated_at, contact_id, display_id,
                           contact_last_seen_at, agent_last_seen_at,
                           additional_attributes, contact_inbox_id,
                           identifier, last_activity_at, team_id,
                           snoozed_until, custom_attributes, assignee_last_seen_at,
                           first_reply_created_at, priority, sla_policy_id, waiting_since
                    FROM public.conversations
                    WHERE id = ANY(%s) ORDER BY id ASC
                """, (batch_ids,))
                batch_convs = c.fetchall()
        except Exception as e:
            log(f"  [ERRO SOURCE batch] {e} — tentando reconectar...")
            if sc_batch:
                try: sc_batch.close()
                except: pass
            import time; time.sleep(3)
            try:
                sc_batch = src()
                with cur(sc_batch) as c:
                    c.execute("""
                        SELECT id, inbox_id, status, assignee_id,
                               created_at, updated_at, contact_id, display_id,
                               contact_last_seen_at, agent_last_seen_at,
                               additional_attributes, contact_inbox_id,
                               identifier, last_activity_at, team_id,
                               snoozed_until, custom_attributes, assignee_last_seen_at,
                               first_reply_created_at, priority, sla_policy_id, waiting_since
                        FROM public.conversations
                        WHERE id = ANY(%s) ORDER BY id ASC
                    """, (batch_ids,))
                    batch_convs = c.fetchall()
            except Exception as e2:
                log(f"  [ERRO] Lote pulado apos retry: {e2}")
                if sc_batch:
                    try: sc_batch.close()
                    except: pass
                continue
        finally:
            if sc_batch:
                try: sc_batch.close()
                except: pass

        for conv in batch_convs:
            src_conv_id = conv["id"]

            # Idempotencia
            with cur(dc) as c:
                c.execute("""
                    SELECT id FROM public.conversations
                    WHERE account_id=%s
                      AND custom_attributes->>'src_id'=%s
                    LIMIT 1
                """, (dest_acc_id, str(src_conv_id)))
                existing = c.fetchone()
            if existing:
                conv_dup += 1
                continue

            # Resolve FKs
            dest_inbox_id   = inbox_map.get(conv["inbox_id"])
            dest_contact_id = contact_map.get(conv["contact_id"])
            dest_assignee   = user_map.get(conv["assignee_id"]) or default_assignee_id

            if dest_inbox_id is None:
                log_err("conversations", src_conv_id,
                        f"inbox_id={conv['inbox_id']} nao mapeada", errfile)
                conv_err += 1
                continue

            if conv["contact_id"] and dest_contact_id is None:
                log_err("conversations", src_conv_id,
                        f"contact_id={conv['contact_id']} nao mapeado", errfile)
                conv_err += 1
                continue

            # custom_attributes com src_id
            src_custom = conv["custom_attributes"] or {}
            if isinstance(src_custom, str):
                try: src_custom = json.loads(src_custom)
                except: src_custom = {}
            src_custom["src_id"] = str(src_conv_id)

            if DRY_RUN:
                conv_ins += 1
                next_did += 1
                continue

            try:
                # 1. contact_inbox — busca existente ou cria novo
                dest_ci_id = None
                if dest_contact_id:
                    with cur(dc) as c:
                        c.execute("""
                            SELECT id FROM public.contact_inboxes
                            WHERE contact_id=%s AND inbox_id=%s LIMIT 1
                        """, (dest_contact_id, dest_inbox_id))
                        ci_existing = c.fetchone()
                    if ci_existing:
                        dest_ci_id = ci_existing["id"]

                if dest_ci_id is None:
                    with cur(dc) as c:
                        c.execute("""
                            INSERT INTO public.contact_inboxes
                                (contact_id, inbox_id, source_id,
                                 created_at, updated_at, hmac_verified, pubsub_token)
                            VALUES (%s,%s,%s,%s,%s,false,NULL)
                            ON CONFLICT (inbox_id, source_id) DO UPDATE
                                SET contact_id = EXCLUDED.contact_id
                            RETURNING id
                        """, (
                            dest_contact_id, dest_inbox_id,
                            str(uuid_lib.uuid4()),
                            conv["created_at"], conv["updated_at"],
                        ))
                        dest_ci_id = c.fetchone()["id"]

                # 2. conversation
                with cur(dc) as c:
                    c.execute("""
                        INSERT INTO public.conversations (
                            account_id, inbox_id, status, assignee_id,
                            created_at, updated_at,
                            contact_id, display_id,
                            contact_last_seen_at, agent_last_seen_at,
                            additional_attributes, contact_inbox_id,
                            uuid, identifier, last_activity_at,
                            team_id, campaign_id, snoozed_until,
                            custom_attributes, assignee_last_seen_at,
                            first_reply_created_at, priority,
                            sla_policy_id, waiting_since
                        ) VALUES (
                            %s,%s,%s,%s, %s,%s,
                            %s,%s, %s,%s,
                            %s,%s,
                            gen_random_uuid(),%s,%s,
                            NULL,NULL,%s,
                            %s,%s, %s,%s, NULL,%s
                        ) RETURNING id
                    """, (
                        dest_acc_id, dest_inbox_id,
                        conv["status"], dest_assignee,
                        conv["created_at"], conv["updated_at"],
                        dest_contact_id, next_did,
                        conv["contact_last_seen_at"], conv["agent_last_seen_at"],
                        '{}', dest_ci_id,
                        conv["identifier"], conv["last_activity_at"],
                        conv["snoozed_until"],
                        jdumps(src_custom), conv["assignee_last_seen_at"],
                        conv["first_reply_created_at"], conv["priority"],
                        conv["waiting_since"],
                    ))
                    dest_conv_id = c.fetchone()["id"]

                dc.commit()
                conv_ins += 1
                next_did += 1

                # 3. Messages desta conversation
                mi, md, me = migrate_messages_of_conv(
                    sc, dc, src_conv_id, dest_conv_id,
                    dest_acc_id, dest_inbox_id,
                    contact_map, user_map, default_assignee_id,
                    msg_map, errfile
                )
                msg_ins += mi
                msg_dup += md
                msg_err += me

                checkpoint += 1
                if checkpoint % 50 == 0:
                    pct = (conv_ins + conv_dup + conv_err) / total_convs * 100
                    log(f"  [{pct:5.1f}%] {conv_ins:,} convs inseridas | {msg_ins:,} msgs | {conv_err} erros")

            except psycopg2.OperationalError as e:
                print(f"\n  [CONEXAO CAIDA] conv={src_conv_id}: {e}")
                try: dc.close()
                except: pass
                dc = reconnect_dst()
                conv_err += 1
            except Exception as e:
                try: dc.rollback()
                except: pass
                log_err("conversations", src_conv_id, e, errfile)
                conv_err += 1

    log(f"Conversations: {conv_ins:,} inseridas | {conv_dup:,} dedup | {conv_err} erros")
    log(f"Messages:      {msg_ins:,} inseridas | {msg_dup:,} dedup | {msg_err} erros")
    return conv_ins, msg_ins

# =============================================================================
# ORQUESTRADOR
# =============================================================================

def run(account_name: str):
    os.makedirs("logs", exist_ok=True)
    errfile = f"logs/erros_{account_name.replace(' ','_')}.jsonl"

    print(f"\n{'='*65}")
    print(f"  MIGRACAO: '{account_name}'")
    print(f"  Modo: {'DRY-RUN' if DRY_RUN else 'REAL'}")
    print(f"{'='*65}\n")

    sc = src()
    dc = dst()

    with cur(sc) as c:
        c.execute("SELECT id FROM public.accounts WHERE name=%s", (account_name,))
        src_acc = c.fetchone()

    if not src_acc:
        print(f"  ERRO: account '{account_name}' nao encontrada no SOURCE.")
        return

    src_acc_id = src_acc["id"]
    log(f"SOURCE account_id={src_acc_id}")

    print(f"\n[0] Account...")
    dest_acc_id = migrate_account(sc, dc, src_acc_id, account_name, errfile)
    if dest_acc_id is None:
        return

    print(f"\n[1] Inboxes...")
    inbox_map = migrate_inboxes(sc, dc, src_acc_id, dest_acc_id, errfile)

    print(f"\n[2] Users...")
    user_map, default_assignee_id = map_users(sc, dc, src_acc_id, dest_acc_id)
    if default_assignee_id is None:
        log("ERRO: nenhum user mapeado — impossivel continuar.")
        return

    print(f"\n[3] Contacts...")
    contact_map = migrate_contacts(sc, dc, src_acc_id, dest_acc_id, errfile)

    print(f"\n[4] Conversations + Messages...")
    migrate_conversations(sc, dc, src_acc_id, dest_acc_id,
                          inbox_map, contact_map, user_map,
                          default_assignee_id, errfile)

    # Resequencia PKs
    if not DRY_RUN:
        print(f"\n[5] Resequenciando sequences...")
        # Encerra qualquer transacao pendente antes de mudar autocommit
        # (psycopg2 lança ProgrammingError se set_session usado dentro de tx)
        try:
            dc.commit()
        except Exception:
            pass
        # Reconecta DEST se necessario (pode ter caido durante a migracao)
        try:
            with cur(dc) as c:
                c.execute("SELECT 1")
            dc.commit()  # encerra o SELECT da verificacao
        except Exception:
            log("  Reconectando DEST para resequenciar...")
            try: dc.close()
            except: pass
            dc = dst()
        dc.autocommit = True
        for tbl, seq in [
            ("contacts",       "contacts_id_seq"),
            ("conversations",  "conversations_id_seq"),
            ("messages",       "messages_id_seq"),
            ("contact_inboxes","contact_inboxes_id_seq"),
            ("inboxes",        "inboxes_id_seq"),
            ("accounts",       "accounts_id_seq"),
        ]:
            try:
                with cur(dc) as c:
                    c.execute(f"""
                        SELECT setval('public.{seq}',
                            COALESCE((SELECT MAX(id) FROM public.{tbl}),1))
                    """)
                log(f"  {seq} OK")
            except Exception as e:
                log(f"  {seq} AVISO: {e}")
        dc.autocommit = False

    print(f"\n{'='*65}")
    print(f"  CONCLUIDO: '{account_name}'")
    print(f"  Erros em: {errfile}")
    if DRY_RUN:
        print(f"  Para migrar: python 01_migrar_account.py \"{account_name}\"")
    print(f"{'='*65}\n")

    sc.close()
    dc.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Uso: python 01_migrar_account.py "nome da account"')
        print('     python 01_migrar_account.py "nome da account" --dry-run')
        sys.exit(1)
    run(sys.argv[1])