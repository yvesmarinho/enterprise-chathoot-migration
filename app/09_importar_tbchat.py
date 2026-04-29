"""Importação das tabelas de staging TBChat → Chatwoot DEST.

:description: Adaptação dos scripts SQL originais
    ``scriptImportacaoChatToSynchat.sql`` /
    ``scriptImportacaoTbChatChatWoot.sql`` para uso com dois bancos
    distintos via SQLAlchemy.

    **SOURCE** (``chatwoot_dev1_db``): contém as tabelas de staging::

        contacts_tbchat      -- contatos importados do sistema TBChat
        conversations_tbchat -- conversas importadas do TBChat
        messages_tbchat      -- mensagens importadas do TBChat

    **DEST** (``chatwoot004_dev1_db``): banco Chatwoot de destino onde os
    dados serão inseridos nas tabelas nativas::

        contacts, contact_inboxes, conversations, messages

    **Regras de deduplicação** (preservadas dos SQLs originais):

    * ``contacts``      — pula se ``phone_number`` já existe no DEST
    * ``conversations`` — pula se ``custom_attributes->>'external_id'``
      já existe no DEST
    * ``messages``      — pula se ``additional_attributes->>'external_id'``
      já existe no DEST

    **Diferença para o SQL original**: o SQL fazia DELETE nas tabelas de
    staging após cada inserção (destrutivo e sem auditoria).  Este script
    **não apaga** os dados de staging por padrão; use ``--delete-staging``
    apenas se tiver certeza.

    Saída::

        .tmp/importar_tbchat_YYYYMMDD_HHMMSS.json
        .tmp/importar_tbchat_YYYYMMDD_HHMMSS.csv
        .tmp/importar_tbchat_YYYYMMDD_HHMMSS.log

Usage::

    python app/09_importar_tbchat.py [--dry-run] [--delete-staging] [--verbose]

Options::

    --dry-run         Lê e classifica, não insere nada no DEST.
    --delete-staging  Remove registros das tabelas de staging após
                      inserção bem-sucedida (IRREVERSÍVEL).
    --verbose         Nível de log DEBUG.
    --phase           contacts|conversations|messages (default: all)
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from src.factory.connection_factory import ConnectionFactory  # noqa: E402

# ---------------------------------------------------------------------------
# ── CONFIGURAÇÃO — edite antes de executar ──────────────────────────────────
# ---------------------------------------------------------------------------

# Nome da account no DEST que receberá os dados.
# O script busca o id automaticamente por name.
ACCOUNT_NAME: str = "Sol Copernico"

# UID do usuário (email) no DEST para assignee_id e sender_id (mensagens
# enviadas pelo operador).
USER_UID: str = "admin@vya.digital"

# Mapeamento id_empresa (valor na tabela de staging) → inbox_id no DEST.
# Verifique os IDs reais com:
#   SELECT id, name FROM inboxes WHERE account_id = <account_id>;
INBOX_MAP: dict[str, int] = {
    "2": 1,  # ex.: id_empresa='2' → inbox_id=1 no DEST
    # adicione outras entradas conforme necessário
}
# Inbox padrão caso id_empresa não esteja no mapa acima.
DEFAULT_INBOX_ID: int = 2

# Prefixo do telefone ao inserir contacts.
# Use "" se o campo phone já tiver o prefixo, ou "+" para adicionar.
PHONE_PREFIX: str = ""

# ---------------------------------------------------------------------------
# ── LOGGING ─────────────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------
_LOG_DIR = _ROOT / ".tmp"
_LOG_DIR.mkdir(parents=True, exist_ok=True)
_TS = datetime.now().strftime("%Y%m%d_%H%M%S")  # noqa: DTZ005

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            str(_LOG_DIR / f"importar_tbchat_{_TS}.log"),
            encoding="utf-8",
        ),
    ],
)
log = logging.getLogger("tbchat")

# ---------------------------------------------------------------------------
# ── DATA CLASSES ─────────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------


@dataclass
class PhaseResult:
    """Resultado de uma fase de importação."""

    phase: str
    total_source: int = 0
    inserted: int = 0
    skipped_dedup: int = 0
    failed: int = 0
    failed_ids: list[int] = field(default_factory=list)


# ---------------------------------------------------------------------------
# ── HELPERS ──────────────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------


def _table_exists(conn: Connection, table_name: str) -> bool:
    """Verifica se a tabela existe no schema public."""
    row = conn.execute(
        text(
            "SELECT EXISTS("
            "  SELECT 1 FROM information_schema.tables"
            "  WHERE table_schema='public'"
            "  AND table_name=:tname"
            ")"
        ),
        {"tname": table_name},
    ).fetchone()
    return bool(row[0]) if row else False


def _lookup_account_id(conn: Connection, account_name: str) -> int | None:
    """Busca account_id pelo nome no DEST."""
    row = conn.execute(
        text("SELECT id FROM accounts WHERE LOWER(name)=LOWER(:n)"),
        {"n": account_name},
    ).fetchone()
    return int(row[0]) if row else None


def _lookup_user_id(conn: Connection, uid: str) -> int | None:
    """Busca user_id pelo uid (email) no DEST."""
    row = conn.execute(
        text("SELECT id FROM users WHERE uid=:uid"),
        {"uid": uid},
    ).fetchone()
    return int(row[0]) if row else None


def _get_display_id_counter(conn: Connection, account_id: int) -> int:
    """Retorna o MAX(display_id) atual para account_id no DEST."""
    row = conn.execute(
        text("SELECT COALESCE(MAX(display_id), 0)" " FROM conversations WHERE account_id=:aid"),
        {"aid": account_id},
    ).fetchone()
    return int(row[0]) if row else 0


# ---------------------------------------------------------------------------
# ── PHASE 1 — CONTACTS ───────────────────────────────────────────────────────
# ---------------------------------------------------------------------------


def import_contacts(
    src_engine: Engine,
    dest_engine: Engine,
    account_id: int,
    dry_run: bool,
    delete_staging: bool,
) -> PhaseResult:
    """Importa contacts_tbchat (SOURCE) → contacts (DEST).

    Dedup: pula se phone_number já existe no DEST.

    :param src_engine: Engine do banco SOURCE.
    :param dest_engine: Engine do banco DEST.
    :param account_id: account_id no DEST.
    :param dry_run: Se True, não insere nada.
    :param delete_staging: Se True, remove registros inseridos da staging.
    :returns: Resultado da fase.
    """
    result = PhaseResult(phase="contacts")
    log.info("Phase 1 — contacts: iniciando")

    with src_engine.connect() as src:
        if not _table_exists(src, "contacts_tbchat"):
            log.warning("contacts_tbchat NÃO encontrada no SOURCE — fase ignorada")
            return result
        rows = [
            dict(r)
            for r in src.execute(text("SELECT * FROM contacts_tbchat ORDER BY id")).mappings().all()
        ]

    result.total_source = len(rows)
    log.info("contacts_tbchat: %d registros no SOURCE", result.total_source)

    if not rows:
        return result

    # Pré-carrega phones existentes no DEST para dedup em memória
    with dest_engine.connect() as dest:
        existing_phones: set[str] = {
            str(r[0])
            for r in dest.execute(
                text(
                    "SELECT phone_number FROM contacts"
                    " WHERE account_id=:aid AND phone_number IS NOT NULL"
                ),
                {"aid": account_id},
            ).fetchall()
        }

    inserted_staging_ids: list[int] = []

    with dest_engine.connect() as dest:
        with dest.begin():
            for row in rows:
                raw_phone = str(row.get("phone") or "").strip()
                phone = f"{PHONE_PREFIX}{raw_phone}" if raw_phone else None

                if phone and phone in existing_phones:
                    log.debug(
                        "contacts: id=%s skipped — phone %s já existe",
                        row.get("id"),
                        phone,
                    )
                    result.skipped_dedup += 1
                    continue

                if dry_run:
                    log.debug(
                        "DRY-RUN contacts: id=%s would insert phone=%s",
                        row.get("id"),
                        phone,
                    )
                    result.inserted += 1
                    if phone:
                        existing_phones.add(phone)
                    continue

                try:
                    dest.execute(
                        text(
                            "INSERT INTO contacts"
                            " (name, email, phone_number, account_id,"
                            "  created_at, updated_at, additional_attributes,"
                            "  identifier, custom_attributes, last_activity_at)"
                            " VALUES"
                            " (:name, :email, :phone, :account_id,"
                            "  :created_at, :updated_at,"
                            "  :additional_attributes::jsonb,"
                            "  null,"
                            "  :custom_attributes::jsonb,"
                            "  :last_activity_at)"
                        ),
                        {
                            "name": str(row.get("name_contact") or "").strip(),
                            "email": (str(row.get("email")).strip() if row.get("email") else None),
                            "phone": phone,
                            "account_id": account_id,
                            "created_at": row.get("created_at"),
                            "updated_at": row.get("updated_at"),
                            "additional_attributes": json.dumps(
                                row.get("additional_attributes") or {}
                            ),
                            "custom_attributes": json.dumps(
                                {
                                    "cpf": row.get("cpf"),
                                    "external_id": row.get("id"),
                                }
                            ),
                            "last_activity_at": row.get("last_activity_at"),
                        },
                    )
                    result.inserted += 1
                    if phone:
                        existing_phones.add(phone)
                    inserted_staging_ids.append(int(row["id"]))
                    log.debug(
                        "contacts: id=%s inserted phone=%s",
                        row.get("id"),
                        phone,
                    )
                except Exception as exc:  # noqa: BLE001
                    result.failed += 1
                    result.failed_ids.append(int(row.get("id", -1)))
                    log.error(
                        "contacts: id=%s FAILED — %s",
                        row.get("id"),
                        exc,
                    )

    if delete_staging and inserted_staging_ids and not dry_run:
        log.warning(
            "delete-staging: removendo %d registros de contacts_tbchat",
            len(inserted_staging_ids),
        )
        with src_engine.connect() as src:
            with src.begin():
                src.execute(
                    text("DELETE FROM contacts_tbchat" " WHERE id = ANY(:ids)"),
                    {"ids": inserted_staging_ids},
                )

    log.info(
        "Phase 1 contacts: total=%d inserted=%d skipped=%d failed=%d",
        result.total_source,
        result.inserted,
        result.skipped_dedup,
        result.failed,
    )
    return result


# ---------------------------------------------------------------------------
# ── PHASE 2 — CONVERSATIONS + CONTACT_INBOXES ────────────────────────────────
# ---------------------------------------------------------------------------


def import_conversations(
    src_engine: Engine,
    dest_engine: Engine,
    account_id: int,
    user_id: int,
    dry_run: bool,
    delete_staging: bool,
) -> PhaseResult:
    """Importa conversations_tbchat (SOURCE) → conversations + contact_inboxes.

    Dedup: pula se ``custom_attributes->>'external_id'`` já existe no DEST.

    :param src_engine: Engine do banco SOURCE.
    :param dest_engine: Engine do banco DEST.
    :param account_id: account_id no DEST.
    :param user_id: user_id do assignee no DEST.
    :param dry_run: Se True, não insere nada.
    :param delete_staging: Se True, remove staging após inserção.
    :returns: Resultado da fase.
    """
    result = PhaseResult(phase="conversations")
    log.info("Phase 2 — conversations: iniciando")

    with src_engine.connect() as src:
        if not _table_exists(src, "conversations_tbchat"):
            log.warning("conversations_tbchat NÃO encontrada no SOURCE — fase ignorada")
            return result
        rows = [
            dict(r)
            for r in src.execute(text("SELECT * FROM conversations_tbchat ORDER BY id ASC"))
            .mappings()
            .all()
        ]

    result.total_source = len(rows)
    log.info(
        "conversations_tbchat: %d registros no SOURCE",
        result.total_source,
    )

    if not rows:
        return result

    # Pré-carrega external_ids já existentes no DEST
    with dest_engine.connect() as dest:
        existing_ext_ids: set[str] = {
            str(r[0])
            for r in dest.execute(
                text(
                    "SELECT custom_attributes->>'external_id'"
                    " FROM conversations"
                    " WHERE account_id=:aid"
                    "   AND custom_attributes->>'external_id' IS NOT NULL"
                ),
                {"aid": account_id},
            ).fetchall()
        }
        # Pré-carrega contact external_id → contact_id no DEST
        contact_ext_map: dict[str, int] = {
            str(r[0]): int(r[1])
            for r in dest.execute(
                text(
                    "SELECT custom_attributes->>'external_id', id"
                    " FROM contacts"
                    " WHERE account_id=:aid"
                    "   AND custom_attributes->>'external_id' IS NOT NULL"
                ),
                {"aid": account_id},
            ).fetchall()
        }
        # Contador de display_id por account
        display_counter = _get_display_id_counter(dest, account_id)

    inserted_staging_ids: list[int] = []

    with dest_engine.connect() as dest:
        for row in rows:
            ext_id = str(row.get("id"))
            if ext_id in existing_ext_ids:
                log.debug(
                    "conversations: id=%s skipped — external_id já existe",
                    ext_id,
                )
                result.skipped_dedup += 1
                continue

            contact_id = contact_ext_map.get(str(row.get("id_contact")))
            if contact_id is None:
                log.warning(
                    "conversations: id=%s skipped —"
                    " contact external_id=%s não encontrado no DEST",
                    ext_id,
                    row.get("id_contact"),
                )
                result.skipped_dedup += 1
                continue

            inbox_id = INBOX_MAP.get(str(row.get("id_empresa")), DEFAULT_INBOX_ID)
            created_at = row.get("data_ini") or row.get("data_reg")

            if dry_run:
                display_counter += 1
                result.inserted += 1
                existing_ext_ids.add(ext_id)
                log.debug(
                    "DRY-RUN conversations: id=%s" " inbox=%d contact=%d display_id=%d",
                    ext_id,
                    inbox_id,
                    contact_id,
                    display_counter,
                )
                continue

            try:
                with dest.begin():
                    # 1. Insert contact_inbox
                    ci_row = dest.execute(
                        text(
                            "INSERT INTO contact_inboxes"
                            " (contact_id, inbox_id, source_id,"
                            "  created_at, updated_at,"
                            "  hmac_verified, pubsub_token)"
                            " VALUES"
                            " (:cid, :iid, :src,"
                            "  :cat, :uat, false, null)"
                            " RETURNING id"
                        ),
                        {
                            "cid": contact_id,
                            "iid": inbox_id,
                            "src": str(uuid.uuid4()),
                            "cat": created_at,
                            "uat": created_at,
                        },
                    ).fetchone()
                    contact_inbox_id = int(ci_row[0])

                    # 2. Increment display_id
                    display_counter += 1
                    last_activity = row.get("last_data_update") or row.get("data_reg")

                    # 3. Insert conversation
                    dest.execute(
                        text(
                            "INSERT INTO conversations"
                            " (account_id, inbox_id, status, assignee_id,"
                            "  created_at, updated_at, contact_id,"
                            "  display_id, contact_last_seen_at,"
                            "  agent_last_seen_at, additional_attributes,"
                            "  contact_inbox_id, uuid, identifier,"
                            "  last_activity_at, team_id, campaign_id,"
                            "  snoozed_until, custom_attributes,"
                            "  assignee_last_seen_at,"
                            "  first_reply_created_at, priority,"
                            "  sla_policy_id, waiting_since)"
                            " VALUES"
                            " (:account_id, :inbox_id, 1, :assignee_id,"
                            "  :created_at, :created_at, :contact_id,"
                            "  :display_id, :created_at,"
                            "  :created_at, :add_attr::jsonb,"
                            "  :ci_id, :uuid, null,"
                            "  :last_activity, null, null,"
                            "  null, :custom_attr::jsonb,"
                            "  :created_at,"
                            "  null, null,"
                            "  null, :created_at)"
                        ),
                        {
                            "account_id": account_id,
                            "inbox_id": inbox_id,
                            "assignee_id": user_id,
                            "created_at": created_at,
                            "contact_id": contact_id,
                            "display_id": display_counter,
                            "add_attr": "{}",
                            "ci_id": contact_inbox_id,
                            "uuid": str(uuid.uuid4()),
                            "last_activity": last_activity,
                            "custom_attr": json.dumps({"external_id": row.get("id")}),
                        },
                    )

                result.inserted += 1
                existing_ext_ids.add(ext_id)
                inserted_staging_ids.append(int(row["id"]))
                log.debug(
                    "conversations: id=%s inserted" " display_id=%d contact_inbox=%d",
                    ext_id,
                    display_counter,
                    contact_inbox_id,
                )
            except Exception as exc:  # noqa: BLE001
                result.failed += 1
                result.failed_ids.append(int(row.get("id", -1)))
                log.error(
                    "conversations: id=%s FAILED — %s",
                    ext_id,
                    exc,
                )

    if delete_staging and inserted_staging_ids and not dry_run:
        log.warning(
            "delete-staging: removendo %d registros de conversations_tbchat",
            len(inserted_staging_ids),
        )
        with src_engine.connect() as src:
            with src.begin():
                src.execute(
                    text("DELETE FROM conversations_tbchat" " WHERE id = ANY(:ids)"),
                    {"ids": inserted_staging_ids},
                )

    log.info(
        "Phase 2 conversations: total=%d inserted=%d" " skipped=%d failed=%d",
        result.total_source,
        result.inserted,
        result.skipped_dedup,
        result.failed,
    )
    return result


# ---------------------------------------------------------------------------
# ── PHASE 3 — MESSAGES ───────────────────────────────────────────────────────
# ---------------------------------------------------------------------------


def import_messages(
    src_engine: Engine,
    dest_engine: Engine,
    account_id: int,
    user_id: int,
    dry_run: bool,
    delete_staging: bool,
) -> PhaseResult:
    """Importa messages_tbchat (SOURCE) → messages (DEST).

    Dedup: pula se ``additional_attributes->>'external_id'`` já existe no DEST.

    Colunas relevantes em messages_tbchat:
        id, id_session, id_contact, id_empresa, message,
        message_type (text|image|video|...), type_in_message (RECEIVED|SENT),
        file_url, moment

    :param src_engine: Engine do banco SOURCE.
    :param dest_engine: Engine do banco DEST.
    :param account_id: account_id no DEST.
    :param user_id: user_id do operador no DEST.
    :param dry_run: Se True, não insere nada.
    :param delete_staging: Se True, remove staging após inserção.
    :returns: Resultado da fase.
    """
    result = PhaseResult(phase="messages")
    log.info("Phase 3 — messages: iniciando")

    with src_engine.connect() as src:
        if not _table_exists(src, "messages_tbchat"):
            log.warning("messages_tbchat NÃO encontrada no SOURCE — fase ignorada")
            return result
        rows = [
            dict(r)
            for r in src.execute(text("SELECT * FROM messages_tbchat ORDER BY id ASC"))
            .mappings()
            .all()
        ]

    result.total_source = len(rows)
    log.info("messages_tbchat: %d registros no SOURCE", result.total_source)

    if not rows:
        return result

    # Pré-carrega external_ids de messages já no DEST
    with dest_engine.connect() as dest:
        existing_msg_ext: set[str] = {
            str(r[0])
            for r in dest.execute(
                text(
                    "SELECT additional_attributes->>'external_id'"
                    " FROM messages"
                    " WHERE account_id=:aid"
                    "   AND additional_attributes->>'external_id'"
                    "       IS NOT NULL"
                ),
                {"aid": account_id},
            ).fetchall()
        }
        # conversation external_id → (conversation_id, inbox_id)
        conv_ext_map: dict[str, tuple[int, int]] = {
            str(r[0]): (int(r[1]), int(r[2]))
            for r in dest.execute(
                text(
                    "SELECT custom_attributes->>'external_id',"
                    "       id, inbox_id"
                    " FROM conversations"
                    " WHERE account_id=:aid"
                    "   AND custom_attributes->>'external_id'"
                    "       IS NOT NULL"
                ),
                {"aid": account_id},
            ).fetchall()
        }
        # contact external_id → contact_id
        contact_ext_map: dict[str, int] = {
            str(r[0]): int(r[1])
            for r in dest.execute(
                text(
                    "SELECT custom_attributes->>'external_id', id"
                    " FROM contacts"
                    " WHERE account_id=:aid"
                    "   AND custom_attributes->>'external_id'"
                    "       IS NOT NULL"
                ),
                {"aid": account_id},
            ).fetchall()
        }

    inserted_staging_ids: list[int] = []

    # Valores de message_type para o Chatwoot:
    #   0 = incoming (received from contact)
    #   1 = outgoing (sent by agent)
    _S3_BASE = "https://tbchatuploads.s3.sa-east-1.amazonaws.com/"

    with dest_engine.connect() as dest:
        for row in rows:
            ext_id = str(row.get("id"))
            if ext_id in existing_msg_ext:
                result.skipped_dedup += 1
                continue

            session_id = str(row.get("id_session"))
            conv_info = conv_ext_map.get(session_id)
            if conv_info is None:
                log.warning(
                    "messages: id=%s skipped —" " conversation external_id=%s não encontrado",
                    ext_id,
                    session_id,
                )
                result.skipped_dedup += 1
                continue

            conversation_id, inbox_id = conv_info

            # Conteúdo da mensagem (texto ou referência a arquivo)
            msg_type_raw = str(row.get("message_type") or "text")
            if msg_type_raw == "text":
                content = str(row.get("message") or "")
            else:
                file_url = str(row.get("file_url") or "")
                file_path = file_url.replace(_S3_BASE, "")
                content = f"{msg_type_raw.capitalize()}: {_S3_BASE}{file_path}"

            # Tipo e sender
            is_received = str(row.get("type_in_message") or "").upper() == "RECEIVED"
            cw_msg_type = 0 if is_received else 1  # 0=incoming, 1=outgoing

            if is_received:
                sender_type = "Contact"
                sender_id = contact_ext_map.get(str(row.get("id_contact")))
                if sender_id is None:
                    # sender desconhecido — aceita como mensagem sem sender
                    sender_id = None
            else:
                sender_type = "User"
                sender_id = user_id

            moment = row.get("moment")

            if dry_run:
                result.inserted += 1
                existing_msg_ext.add(ext_id)
                continue

            try:
                with dest.begin():
                    dest.execute(
                        text(
                            "INSERT INTO messages"
                            " (content, account_id, inbox_id,"
                            "  conversation_id, message_type,"
                            "  created_at, updated_at, private, status,"
                            "  source_id, content_type,"
                            "  content_attributes, sender_type, sender_id,"
                            "  external_source_ids,"
                            "  additional_attributes,"
                            "  processed_message_content, sentiment)"
                            " VALUES"
                            " (:content, :account_id, :inbox_id,"
                            "  :conv_id, :mtype,"
                            "  :created_at, :created_at,"
                            "  false, 0,"
                            "  null, 0,"
                            "  null, :sender_type, :sender_id,"
                            "  null,"
                            "  :add_attr::jsonb,"
                            "  :content, :sentiment::jsonb)"
                        ),
                        {
                            "content": content,
                            "account_id": account_id,
                            "inbox_id": inbox_id,
                            "conv_id": conversation_id,
                            "mtype": cw_msg_type,
                            "created_at": moment,
                            "sender_type": sender_type,
                            "sender_id": sender_id,
                            "add_attr": json.dumps({"external_id": row.get("id")}),
                            "sentiment": "{}",
                        },
                    )

                result.inserted += 1
                existing_msg_ext.add(ext_id)
                inserted_staging_ids.append(int(row["id"]))
                log.debug(
                    "messages: id=%s inserted conv=%d type=%d",
                    ext_id,
                    conversation_id,
                    cw_msg_type,
                )
            except Exception as exc:  # noqa: BLE001
                result.failed += 1
                result.failed_ids.append(int(row.get("id", -1)))
                log.error("messages: id=%s FAILED — %s", ext_id, exc)

    if delete_staging and inserted_staging_ids and not dry_run:
        log.warning(
            "delete-staging: removendo %d registros de messages_tbchat",
            len(inserted_staging_ids),
        )
        with src_engine.connect() as src:
            with src.begin():
                src.execute(
                    text("DELETE FROM messages_tbchat" " WHERE id = ANY(:ids)"),
                    {"ids": inserted_staging_ids},
                )

    log.info(
        "Phase 3 messages: total=%d inserted=%d skipped=%d failed=%d",
        result.total_source,
        result.inserted,
        result.skipped_dedup,
        result.failed,
    )
    return result


# ---------------------------------------------------------------------------
# ── MAIN ─────────────────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Importação TBChat staging → Chatwoot DEST")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Lê e classifica, não insere no DEST.",
    )
    parser.add_argument(
        "--delete-staging",
        action="store_true",
        help=(
            "Remove registros de staging após inserção bem-sucedida. "
            "IRREVERSÍVEL — use com cautela."
        ),
    )
    parser.add_argument(
        "--phase",
        choices=["contacts", "conversations", "messages", "all"],
        default="all",
        help="Fase a executar (default: all).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Log nível DEBUG.",
    )
    return parser.parse_args()


def main() -> int:
    """Ponto de entrada principal.

    :returns: Exit code (0=sucesso, 1=falhas parciais, 2=erro fatal).
    :rtype: int
    """
    args = _parse_args()
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    log.info(
        "=== Importação TBChat — %s%s ===",
        _TS,
        " [DRY-RUN]" if args.dry_run else "",
    )
    log.info(
        "Config: account='%s' user='%s' phase=%s delete_staging=%s",
        ACCOUNT_NAME,
        USER_UID,
        args.phase,
        args.delete_staging,
    )

    factory = ConnectionFactory()
    src_engine = factory.create_source_engine()
    dest_engine = factory.create_dest_engine()

    # ── Validação de pré-requisitos no DEST ──────────────────────────────
    with dest_engine.connect() as dest:
        account_id = _lookup_account_id(dest, ACCOUNT_NAME)
        if account_id is None:
            log.error(
                "Account '%s' não encontrada no DEST. Abortando.",
                ACCOUNT_NAME,
            )
            return 2

        user_id = _lookup_user_id(dest, USER_UID)
        if user_id is None:
            log.error(
                "User uid='%s' não encontrado no DEST. Abortando.",
                USER_UID,
            )
            return 2

    log.info(
        "Pré-requisitos OK — account_id=%d user_id=%d",
        account_id,
        user_id,
    )

    # ── Execução das fases ────────────────────────────────────────────────
    results: list[PhaseResult] = []

    if args.phase in ("contacts", "all"):
        results.append(
            import_contacts(
                src_engine,
                dest_engine,
                account_id,
                dry_run=args.dry_run,
                delete_staging=args.delete_staging,
            )
        )

    if args.phase in ("conversations", "all"):
        results.append(
            import_conversations(
                src_engine,
                dest_engine,
                account_id,
                user_id,
                dry_run=args.dry_run,
                delete_staging=args.delete_staging,
            )
        )

    if args.phase in ("messages", "all"):
        results.append(
            import_messages(
                src_engine,
                dest_engine,
                account_id,
                user_id,
                dry_run=args.dry_run,
                delete_staging=args.delete_staging,
            )
        )

    # ── Persistência dos resultados ───────────────────────────────────────
    report = {
        "timestamp": _TS,
        "dry_run": args.dry_run,
        "account_name": ACCOUNT_NAME,
        "account_id": account_id,
        "user_uid": USER_UID,
        "user_id": user_id,
        "phases": [
            {
                "phase": r.phase,
                "total_source": r.total_source,
                "inserted": r.inserted,
                "skipped_dedup": r.skipped_dedup,
                "failed": r.failed,
                "failed_ids_sample": r.failed_ids[:20],
            }
            for r in results
        ],
    }

    json_path = _LOG_DIR / f"importar_tbchat_{_TS}.json"
    json_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    log.info("JSON salvo: %s", json_path)

    csv_path = _LOG_DIR / f"importar_tbchat_{_TS}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "phase",
                "total_source",
                "inserted",
                "skipped_dedup",
                "failed",
            ],
        )
        writer.writeheader()
        for r in results:
            writer.writerow(
                {
                    "phase": r.phase,
                    "total_source": r.total_source,
                    "inserted": r.inserted,
                    "skipped_dedup": r.skipped_dedup,
                    "failed": r.failed,
                }
            )
    log.info("CSV salvo: %s", csv_path)

    # ── Resumo ────────────────────────────────────────────────────────────
    log.info("=== RESUMO FINAL ===")
    total_failed = 0
    for r in results:
        log.info(
            "  %-15s total=%-6d inserted=%-6d" " skipped=%-6d failed=%-6d",
            r.phase,
            r.total_source,
            r.inserted,
            r.skipped_dedup,
            r.failed,
        )
        total_failed += r.failed

    if total_failed:
        log.warning("%d registros falharam no total", total_failed)
        return 1

    log.info("Importação concluída sem falhas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
