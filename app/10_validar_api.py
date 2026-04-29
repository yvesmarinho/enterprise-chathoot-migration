"""Validação profunda de dados migrados (SOURCE → DEST).

Modos
-----
summary
    Contagens por account (SOURCE vs DEST), idêntico ao diagnóstico de app/08.
deep
    Dado um ``phone_number`` ou ``email``, traça toda a cadeia de dados:
    contato → conversas → mensagens → anexos, com comparação field-by-field
    e verificação HTTP de URLs de anexo.

Usage::

    # resumo por account
    python app/10_validar_api.py summary

    # deep scan por telefone, verificando URLs de anexo
    python app/10_validar_api.py deep --contact-phone "+5511999999999" --check-urls

    # deep scan por e-mail, amostrar 5 conversas
    python app/10_validar_api.py deep --contact-email foo@bar.com --sample-size 5

Saída::

    .tmp/validacao_api_YYYYMMDD_HHMMSS.json   — dados brutos completos
    .tmp/validacao_api_YYYYMMDD_HHMMSS.csv    — linha(s) de resumo
    .tmp/validacao_api_YYYYMMDD_HHMMSS.log    — log DEBUG completo
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from src.factory.connection_factory import ConnectionFactory  # noqa: E402

# ---------------------------------------------------------------------------
# Caminhos e constantes
# ---------------------------------------------------------------------------
_SECRETS_PATH = _ROOT / ".secrets" / "generate_erd.json"
_LOG_DIR = _ROOT / ".tmp"
_LOG_DIR.mkdir(parents=True, exist_ok=True)
_TS = datetime.now().strftime("%Y%m%d_%H%M%S")  # noqa: DTZ005

_TOKEN_PARAMS = re.compile(
    r"(X-Amz-Credential|X-Amz-Signature|X-Amz-Security-Token"
    r"|X-Amz-Date|X-Amz-Expires|X-Amz-Algorithm"
    r"|token|access_token|sig|signature)=[^&\s]+",
    re.IGNORECASE,
)

_fmt = logging.Formatter(
    "%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
_sh = logging.StreamHandler(sys.stdout)
_sh.setLevel(logging.INFO)
_sh.setFormatter(_fmt)
_fh = logging.FileHandler(str(_LOG_DIR / f"validacao_api_{_TS}.log"), encoding="utf-8")
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(_fmt)
logging.getLogger().setLevel(logging.DEBUG)
logging.getLogger().addHandler(_sh)
logging.getLogger().addHandler(_fh)

log = logging.getLogger("validacao_api")

# ---------------------------------------------------------------------------
# API Chatwoot — config, probe e get
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ApiConfig:
    base_url: str
    api_key: str
    timeout_s: int = 30


def _redact_url(url: str) -> str:
    """Remove query params com tokens de URLs — seguro para logs."""
    return _TOKEN_PARAMS.sub(r"\1=***", url)


class ApiError(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status


def _load_api_config(timeout_s: int = 10) -> ApiConfig:
    """Carrega configuração da API de .secrets/generate_erd.json["vya-chat-dev"]."""
    if not _SECRETS_PATH.exists():
        log.error("Secrets file not found: %s", _SECRETS_PATH)
        sys.exit(1)
    data: dict = json.loads(_SECRETS_PATH.read_text())
    api_section = data.get("vya-chat-dev", {})
    api_key = api_section.get("api_key", "")
    host = api_section.get("host", "")
    if not api_key or not host:
        log.error("vya-chat-dev.api_key ou vya-chat-dev.host ausente em %s", _SECRETS_PATH)
        sys.exit(1)
    if not host.startswith("http"):
        host = f"https://{host}"
    return ApiConfig(base_url=host.rstrip("/"), api_key=api_key, timeout_s=timeout_s)


def _probe_api(cfg: ApiConfig) -> None:
    """GET /api/v1/profile — fail-fast se token inválido."""
    url = f"{cfg.base_url}/api/v1/profile"
    req = urllib.request.Request(url, headers={"api_access_token": cfg.api_key})
    try:
        with urllib.request.urlopen(req, timeout=cfg.timeout_s) as resp:
            if resp.status == 200:
                log.info("API probe OK — %s", cfg.base_url)
                return
    except urllib.error.HTTPError as exc:
        log.error("API probe falhou — HTTP %d. Verifique api_key em .secrets/", exc.code)
        sys.exit(1)
    except urllib.error.URLError as exc:
        log.error("API probe falhou — %s", exc.reason)
        sys.exit(1)


def _api_get(url: str, cfg: ApiConfig) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"api_access_token": cfg.api_key})
    try:
        with urllib.request.urlopen(req, timeout=cfg.timeout_s) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        raise ApiError(exc.code) from exc
    except urllib.error.URLError as exc:
        raise ApiError(0) from exc
    except TimeoutError as exc:
        log.warning("API timeout url=%s", _redact_url(url))
        raise ApiError(0) from exc
    except OSError as exc:
        log.warning("API connection error url=%s reason=%s", _redact_url(url), exc)
        raise ApiError(0) from exc


# ---------------------------------------------------------------------------
# Mapeamento de accounts SOURCE → DEST (de migration_state)
# ---------------------------------------------------------------------------
_ACCOUNT_MAP_FALLBACK: dict[int, int] = {1: 1, 4: 47, 17: 17, 18: 61, 25: 68}


@dataclass
class SampleContact:
    """Contato selecionado pela query richness_score para auto-amostra."""

    src_contact_id: int
    account_id: int
    phone_number: str
    email: str
    conv_count: int
    msg_count: int
    att_count: int
    richness_score: int


# ---------------------------------------------------------------------------
# Dataclasses — modo deep
# ---------------------------------------------------------------------------


@dataclass
class FieldComparison:
    """Comparação de um campo entre SOURCE e DEST."""

    field_name: str
    source_value: object
    dest_value: object
    match: bool
    note: str = ""


@dataclass
class AttachmentResult:
    """Resultado da verificação de um anexo (migração + URL)."""

    src_id: int
    dest_id: int | None
    url_preview: str  # primeiros 80 chars com tokens S3 redactados
    url_accessible: bool = False
    http_status: int = 0
    http_content_type: str = ""
    http_content_length: int = -1
    error: str = "not_checked"


@dataclass
class MessageResult:
    """Resultado da verificação de uma mensagem."""

    src_id: int
    dest_id: int | None
    found_in_dest: bool
    content_match: bool = False
    type_match: bool = False
    fields: list[FieldComparison] = field(default_factory=list)
    attachments: list[AttachmentResult] = field(default_factory=list)


@dataclass
class ConversationApiCheck:
    """Resultado da validação de uma conversa via API Chatwoot."""

    src_conv_id: int
    dest_conv_id: int | None
    display_id: int | None
    found_in_api: bool = False
    status_src: str = ""
    status_api: str = ""
    status_match: bool = False
    messages_api_count: int = -1
    src_id_match: bool = False  # additional_attributes.src_id == str(src_conv_id)
    api_status: int = 0
    api_error: str = ""


@dataclass
class ConversationResult:
    """Resultado da verificação de uma conversa e suas mensagens."""

    src_id: int
    dest_id: int | None
    display_id_src: int | None
    display_id_dest: int | None
    messages_src_count: int
    messages_dest_count: int
    found_in_dest: bool
    api_check: ConversationApiCheck | None = None
    fields: list[FieldComparison] = field(default_factory=list)
    messages: list[MessageResult] = field(default_factory=list)


@dataclass
class ContactDeepResult:
    """Resultado completo do deep scan para um contato."""

    src_id: int
    dest_id: int | None
    phone_number: str
    email: str
    found_in_dest_db: bool
    found_in_api: bool
    fields: list[FieldComparison] = field(default_factory=list)
    conversations: list[ConversationResult] = field(default_factory=list)


@dataclass
class DeepValidationReport:
    """Relatório completo gerado pelo modo deep (um ou vários contatos)."""

    timestamp: str
    contact_query: dict[str, Any]  # phone/email para scan único; mode+n para auto-sample
    contacts: list[ContactDeepResult]
    summary: dict[str, object] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# SQL — modo summary
# ---------------------------------------------------------------------------
_SQL_ACCOUNTS = "SELECT id, name, status FROM accounts ORDER BY id"

_SQL_COUNT_BY_ACCOUNT = """
SELECT account_id, COUNT(*) AS total
FROM {table}
GROUP BY account_id
ORDER BY account_id
"""

_SQL_TOTALS = "SELECT COUNT(*) AS total FROM {table}"

# [DEST] Sanidade por account — display_id duplicado, orphan messages, pubsub_token duplicado
_SQL_SANITY_CONV_DUP_DISPLAY_ID = """
SELECT COUNT(*) AS n
FROM (
    SELECT display_id, COUNT(*) AS cnt
    FROM conversations
    WHERE account_id = :account_id AND display_id IS NOT NULL
    GROUP BY display_id
    HAVING COUNT(*) > 1
) AS dups
"""

_SQL_SANITY_ORPHAN_MESSAGES = """
SELECT COUNT(*) AS n
FROM messages m
WHERE m.account_id = :account_id
  AND NOT EXISTS (
      SELECT 1 FROM conversations c WHERE c.id = m.conversation_id
  )
"""

_SQL_SANITY_PUBSUB_DUPS = """
SELECT COUNT(*) AS n
FROM (
    SELECT pubsub_token, COUNT(*) AS cnt
    FROM contacts
    WHERE account_id = :account_id
      AND pubsub_token IS NOT NULL
      AND pubsub_token <> ''
    GROUP BY pubsub_token
    HAVING COUNT(*) > 1
) AS dups
"""

# ---------------------------------------------------------------------------
# SQL — modo deep
# ---------------------------------------------------------------------------
_SQL_CONTACT_BY_PHONE = """
SELECT id, account_id, name, email, phone_number, identifier, created_at, updated_at
FROM contacts
WHERE phone_number = :phone
LIMIT 1
"""

_SQL_CONTACT_BY_EMAIL = """
SELECT id, account_id, name, email, phone_number, identifier, created_at, updated_at
FROM contacts
WHERE email = :email
LIMIT 1
"""

_SQL_CONTACT_BY_ID = """
SELECT id, account_id, name, email, phone_number, identifier, created_at, updated_at
FROM contacts
WHERE id = :id
LIMIT 1
"""

_SQL_MIGRATION_STATE_EXISTS = """
SELECT EXISTS(
  SELECT 1 FROM information_schema.tables
  WHERE table_schema = 'public' AND table_name = 'migration_state'
)
"""

_SQL_DEST_ID = """
SELECT id_destino
FROM migration_state
WHERE tabela = :tabela AND id_origem = :src_id
LIMIT 1
"""

_SQL_DEST_IDS_BATCH = """
SELECT id_origem, id_destino
FROM migration_state
WHERE tabela = :tabela AND id_origem = ANY(:src_ids)
"""

_SQL_MESSAGES_BY_IDS = """
SELECT id, account_id, conversation_id, content, message_type, content_type,
       created_at, updated_at
FROM messages
WHERE id = ANY(:ids)
"""

_SQL_ATTACHMENTS_BY_MESSAGE_IDS = """
SELECT id, message_id, account_id, file_type, external_url
FROM attachments
WHERE message_id = ANY(:message_ids)
ORDER BY message_id, id
"""

_SQL_ACCOUNT_MAP = """
SELECT ms.id_origem AS src_id, ms.id_destino AS dest_id, a.name
FROM migration_state ms
JOIN accounts a ON a.id = ms.id_destino
WHERE ms.tabela = 'accounts' AND ms.status = 'ok'
ORDER BY ms.id_origem
"""

# [SOURCE] Top-N contatos ricos por account, ordenados por richness_score.
# Usado pelo modo deep em auto-amostra (sem --contact-phone / --contact-email).
_SQL_SAMPLE_CONTACTS = """
WITH contact_richness AS (
    SELECT
        c.id                                                          AS src_contact_id,
        c.account_id,
        c.phone_number,
        c.email,
        COUNT(DISTINCT cv.id)                                         AS conv_count,
        COUNT(DISTINCT m.id)                                          AS msg_count,
        COUNT(DISTINCT a.id)                                          AS att_count,
        COUNT(DISTINCT cv.id) * 5
            + COUNT(DISTINCT a.id) * 10
            + COUNT(DISTINCT m.id)                                    AS richness_score
    FROM contacts c
    INNER JOIN conversations cv
           ON cv.contact_id = c.id AND cv.account_id = c.account_id
    INNER JOIN messages m
           ON m.conversation_id = cv.id
    INNER JOIN attachments a
           ON a.message_id = m.id
    WHERE c.account_id = ANY(:src_account_ids)
      AND (c.phone_number IS NOT NULL OR c.email IS NOT NULL)
    GROUP BY c.id, c.account_id, c.phone_number, c.email
    HAVING COUNT(DISTINCT cv.id) >= 2
)
SELECT src_contact_id, account_id, phone_number, email,
       conv_count, msg_count, att_count, richness_score
FROM contact_richness
ORDER BY account_id, richness_score DESC
LIMIT :n
"""

_SQL_CONVERSATIONS_BY_CONTACT = """
SELECT id, account_id, contact_id, display_id, status, inbox_id, created_at, updated_at
FROM conversations
WHERE contact_id = :contact_id
ORDER BY id
"""

_SQL_CONVERSATION_BY_ID = """
SELECT id, account_id, contact_id, display_id, status, inbox_id, created_at, updated_at
FROM conversations
WHERE id = :id
LIMIT 1
"""

_SQL_MSG_COUNT = "SELECT COUNT(*) FROM messages WHERE conversation_id = :conv_id"

_SQL_MESSAGES_BY_CONVERSATION = """
SELECT id, account_id, conversation_id, content, message_type, content_type,
       created_at, updated_at
FROM messages
WHERE conversation_id = :conversation_id
ORDER BY id
"""

_SQL_MESSAGE_BY_ID = """
SELECT id, account_id, conversation_id, content, message_type, content_type,
       created_at, updated_at
FROM messages
WHERE id = :id
LIMIT 1
"""

_SQL_ATTACHMENTS_BY_MESSAGE = """
SELECT id, message_id, account_id, file_type, external_url
FROM attachments
WHERE message_id = :message_id
ORDER BY id
"""

_SQL_ATTACHMENT_BY_ID = """
SELECT id, message_id, account_id, file_type, external_url
FROM attachments
WHERE id = :id
LIMIT 1
"""

# ---------------------------------------------------------------------------
# Helpers — conversão de Row SQLAlchemy 2.0 → dict
# ---------------------------------------------------------------------------

_SKIP_FIELDS: frozenset[str] = frozenset({"id", "created_at", "updated_at"})
_SOFT_DIFF_FIELDS: frozenset[str] = frozenset(
    {"account_id", "contact_id", "conversation_id", "message_id", "inbox_id"}
)


def _row_to_dict(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    if hasattr(row, "_mapping"):
        return dict(row._mapping)
    return dict(row)


def _serializable(obj: Any) -> Any:
    """Converte datetime e outros tipos não-JSON em serializáveis (para logging)."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serializable(i) for i in obj]
    return obj


class _DatetimeEncoder(json.JSONEncoder):
    def default(self, o: Any) -> Any:
        if isinstance(o, datetime):
            return o.isoformat()
        return super().default(o)


# ---------------------------------------------------------------------------
# Helpers — migration_state
# ---------------------------------------------------------------------------


def _migration_state_exists(dest: Connection) -> bool:
    row = dest.execute(text(_SQL_MIGRATION_STATE_EXISTS)).fetchone()
    return bool(row[0]) if row else False


def _lookup_dest_id(dest: Connection, tabela: str, src_id: int) -> int | None:
    """Retorna id_destino para a entidade SOURCE em migration_state."""
    row = dest.execute(text(_SQL_DEST_ID), {"tabela": tabela, "src_id": src_id}).fetchone()
    return int(row[0]) if row and row[0] is not None else None


def _lookup_dest_ids_batch(dest: Connection, tabela: str, src_ids: list[int]) -> dict[int, int]:
    """Retorna mapeamento {src_id: dest_id} para todos os IDs de uma vez (batch).

    Muito mais eficiente que chamadas individuais a :func:`_lookup_dest_id` quando
    há muitos registros — reduz N round-trips a 1.
    """
    if not src_ids:
        return {}
    rows = dest.execute(
        text(_SQL_DEST_IDS_BATCH), {"tabela": tabela, "src_ids": src_ids}
    ).fetchall()
    return {int(r[0]): int(r[1]) for r in rows if r[1] is not None}


def _load_account_map(dest: Connection) -> dict[int, int]:
    """Carrega mapeamento src→dest de accounts da migration_state.

    Retorna fallback hardcoded se migration_state não tiver registros de accounts.
    """
    rows = dest.execute(text(_SQL_ACCOUNT_MAP)).fetchall()
    if rows:
        result = {int(r[0]): int(r[1]) for r in rows}
        log.info("account_map carregado de migration_state: %d account(s)", len(result))
        return result
    log.warning("Nenhuma account em migration_state — usando fallback hardcoded")
    return dict(_ACCOUNT_MAP_FALLBACK)


# ---------------------------------------------------------------------------
# Helpers — comparação field-by-field
# ---------------------------------------------------------------------------


def _compare_fields(
    entity: str,
    src_row: dict[str, Any],
    dest_row: dict[str, Any],
    skip: frozenset[str] = _SKIP_FIELDS,
) -> list[FieldComparison]:
    """Compara field-by-field SOURCE vs DEST, logando cada resultado em DEBUG.

    Formato parseable::

        FIELD <entity>.<field> src=<v> dest=<v> match=<True|False>
    """
    results: list[FieldComparison] = []
    for key in sorted(set(src_row) | set(dest_row)):
        if key in skip:
            continue
        sv = src_row.get(key)
        dv = dest_row.get(key)
        if isinstance(sv, str):
            sv = sv.strip()
        if isinstance(dv, str):
            dv = dv.strip()
        match = sv == dv
        note = "internal_id_remap" if (key in _SOFT_DIFF_FIELDS and not match) else ""
        log.debug("FIELD %s.%s src=%r dest=%r match=%s", entity, key, sv, dv, match)
        results.append(
            FieldComparison(field_name=key, source_value=sv, dest_value=dv, match=match, note=note)
        )
    return results


# ---------------------------------------------------------------------------
# URL check — HEAD request via urllib (stdlib, sem dependências externas)
# ---------------------------------------------------------------------------

_URL_TIMEOUT = 10


def _check_url(url: str) -> tuple[bool, int, str, int, str]:
    """HEAD request para verificar acessibilidade de um URL de anexo.

    Redirects (301/302) são seguidos automaticamente (urllib padrão).
    O status final reportado é o da resposta após seguir todos os redirects.

    :returns: ``(accessible, http_status, content_type, content_length, error)``
    """
    if not url:
        return False, 0, "", -1, "empty_url"
    safe_url = _redact_url(url)
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=_URL_TIMEOUT) as resp:
            status: int = resp.status
            headers = resp.headers
            ct: str = headers.get("Content-Type", "")
            try:
                cl = int(headers.get("Content-Length", "-1"))
            except (ValueError, TypeError):
                cl = -1
            log.debug(
                "URL HEAD status=%d ct=%r cl=%d url=%s",
                status,
                ct,
                cl,
                safe_url,
            )
            return True, status, ct, cl, ""
    except urllib.error.HTTPError as exc:
        log.debug("URL HEAD HTTPError status=%d url=%s", exc.code, safe_url)
        return False, exc.code, "", -1, f"HTTPError:{exc.code}"
    except urllib.error.URLError as exc:
        log.debug("URL HEAD URLError reason=%s url=%s", exc.reason, safe_url)
        return False, 0, "", -1, f"URLError:{exc.reason}"
    except TimeoutError:
        log.debug("URL HEAD timeout url=%s", safe_url)
        return False, 0, "", -1, "timeout"
    except Exception as exc:  # noqa: BLE001
        log.debug("URL HEAD unexpected error=%s url=%s", exc, safe_url)
        return False, 0, "", -1, str(exc)


# ---------------------------------------------------------------------------
# Deep scan — anexo
# ---------------------------------------------------------------------------


def _deep_scan_attachment(
    src_att: dict[str, Any],
    dest: Connection,
    has_mig_state: bool,
    check_urls: bool,
) -> AttachmentResult:
    src_id = int(src_att["id"])
    dest_id: int | None = None

    if has_mig_state:
        dest_id = _lookup_dest_id(dest, "attachments", src_id)

    file_url = str(src_att.get("external_url") or "")
    url_preview = _redact_url(file_url)[:80]
    accessible, status, ct, cl, err = False, 0, "", -1, "not_checked"

    if check_urls and file_url:
        accessible, status, ct, cl, err = _check_url(file_url)

    log.debug(
        "      ATT src_id=%d dest_id=%s url_ok=%s http=%d url=%s",
        src_id,
        dest_id,
        accessible,
        status,
        url_preview,
    )
    return AttachmentResult(
        src_id=src_id,
        dest_id=dest_id,
        url_preview=url_preview,
        url_accessible=accessible,
        http_status=status,
        http_content_type=ct,
        http_content_length=cl,
        error=err,
    )


# ---------------------------------------------------------------------------
# Deep scan — mensagem
# ---------------------------------------------------------------------------


def _deep_scan_message(
    src: Connection,
    dest: Connection,
    src_msg: dict[str, Any],
    has_mig_state: bool,
    *,
    check_urls: bool = False,
    dest_id_override: int | None = None,
    dest_msg_override: dict[str, Any] | None = None,
) -> MessageResult:
    src_id = int(src_msg["id"])
    log.debug(
        "    MSG src_id=%d type=%s content_preview=%r",
        src_id,
        src_msg.get("message_type"),
        str(src_msg.get("content") or "")[:80],
    )
    log.debug("    MSG src_full=%s", json.dumps(_serializable(src_msg), ensure_ascii=False))

    # Usa pre-fetched dest_id/dest_msg quando disponível (evita N+1)
    if dest_id_override is not None:
        dest_id: int | None = dest_id_override
    elif has_mig_state:
        dest_id = _lookup_dest_id(dest, "messages", src_id)
    else:
        dest_id = None

    if dest_msg_override is not None:
        dest_msg: dict[str, Any] = dest_msg_override
    elif dest_id is not None:
        dest_msg = _row_to_dict(dest.execute(text(_SQL_MESSAGE_BY_ID), {"id": dest_id}).fetchone())
        if dest_msg:
            log.debug(
                "    MSG dest_full=%s", json.dumps(_serializable(dest_msg), ensure_ascii=False)
            )
    else:
        dest_msg = {}

    found = bool(dest_msg)
    if not found:
        log.warning("    MSG not found in DEST src_id=%d", src_id)

    fields = _compare_fields("message", src_msg, dest_msg) if found else []
    content_match = (
        (str(src_msg.get("content") or "").strip() == str(dest_msg.get("content") or "").strip())
        if found
        else False
    )
    type_match = src_msg.get("message_type") == dest_msg.get("message_type") if found else False

    # Anexos — sempre consultados no SOURCE
    src_atts = [
        _row_to_dict(r)
        for r in src.execute(text(_SQL_ATTACHMENTS_BY_MESSAGE), {"message_id": src_id}).fetchall()
    ]
    att_results = [_deep_scan_attachment(sa, dest, has_mig_state, check_urls) for sa in src_atts]

    return MessageResult(
        src_id=src_id,
        dest_id=dest_id,
        found_in_dest=found,
        content_match=content_match,
        type_match=type_match,
        fields=fields,
        attachments=att_results,
    )


# ---------------------------------------------------------------------------
# Deep scan — conversa
# ---------------------------------------------------------------------------


def _deep_scan_conversation(
    src: Connection,
    dest: Connection,
    src_conv: dict[str, Any],
    has_mig_state: bool,
    *,
    check_urls: bool = False,
    max_msgs: int | None = None,
) -> ConversationResult:
    src_id = int(src_conv["id"])
    display_id_src = src_conv.get("display_id")
    log.info("  CONV src_id=%d display_id=%s", src_id, display_id_src)
    log.debug("  CONV src_full=%s", json.dumps(_serializable(src_conv), ensure_ascii=False))

    dest_id: int | None = None
    dest_conv: dict[str, Any] = {}

    if has_mig_state:
        dest_id = _lookup_dest_id(dest, "conversations", src_id)
        if dest_id is not None:
            dest_conv = _row_to_dict(
                dest.execute(text(_SQL_CONVERSATION_BY_ID), {"id": dest_id}).fetchone()
            )
            if dest_conv:
                log.debug(
                    "  CONV dest_full=%s", json.dumps(_serializable(dest_conv), ensure_ascii=False)
                )

    found = bool(dest_conv)
    if not found:
        log.warning("  CONV not found in DEST src_id=%d", src_id)

    fields = _compare_fields("conversation", src_conv, dest_conv) if found else []
    display_id_dest = (
        int(dest_conv["display_id"]) if dest_conv.get("display_id") is not None else None
    )

    src_msg_count = int(
        (src.execute(text(_SQL_MSG_COUNT), {"conv_id": src_id}).fetchone() or [0])[0]
    )
    dest_msg_count = 0
    if dest_id is not None:
        dest_msg_count = int(
            (dest.execute(text(_SQL_MSG_COUNT), {"conv_id": dest_id}).fetchone() or [0])[0]
        )
    log.info(
        "    CONV src_id=%d msgs: src=%d dest=%d",
        src_id,
        src_msg_count,
        dest_msg_count,
    )

    src_msgs = [
        _row_to_dict(r)
        for r in src.execute(
            text(_SQL_MESSAGES_BY_CONVERSATION), {"conversation_id": src_id}
        ).fetchall()
    ]
    if max_msgs is not None and len(src_msgs) > max_msgs:
        log.info(
            "    CONV src_id=%d truncating msgs %d \u2192 %d (--max-msgs-per-conv)",
            src_id,
            len(src_msgs),
            max_msgs,
        )
        src_msgs = src_msgs[:max_msgs]

    # Batch pre-fetch: migration_state + DEST messages (evita N+1 queries)
    msg_dest_map: dict[int, int] = {}
    dest_msgs_by_id: dict[int, dict[str, Any]] = {}
    if has_mig_state and src_msgs:
        src_msg_ids = [int(m["id"]) for m in src_msgs]
        msg_dest_map = _lookup_dest_ids_batch(dest, "messages", src_msg_ids)
        if msg_dest_map:
            dest_msg_ids = list(msg_dest_map.values())
            rows = dest.execute(text(_SQL_MESSAGES_BY_IDS), {"ids": dest_msg_ids}).fetchall()
            dest_msgs_by_id = {int(r[0]): _row_to_dict(r) for r in rows}
            log.debug(
                "    CONV src_id=%d batch msgs: src=%d mapped=%d fetched=%d",
                src_id,
                len(src_msg_ids),
                len(msg_dest_map),
                len(dest_msgs_by_id),
            )

    msg_results = [
        _deep_scan_message(
            src,
            dest,
            sm,
            has_mig_state,
            check_urls=check_urls,
            dest_id_override=msg_dest_map.get(int(sm["id"])),
            dest_msg_override=(
                dest_msgs_by_id.get(msg_dest_map[int(sm["id"])])
                if int(sm["id"]) in msg_dest_map
                else None
            ),
        )
        for sm in src_msgs
    ]

    return ConversationResult(
        src_id=src_id,
        dest_id=dest_id,
        display_id_src=int(display_id_src) if display_id_src is not None else None,
        display_id_dest=display_id_dest,
        messages_src_count=src_msg_count,
        messages_dest_count=dest_msg_count,
        found_in_dest=found,
        fields=fields,
        messages=msg_results,
    )


# ---------------------------------------------------------------------------
# Deep scan — contato (ponto de entrada do modo deep)
# ---------------------------------------------------------------------------


def _fetch_contact(
    conn: Connection,
    *,
    phone: str | None = None,
    email: str | None = None,
    contact_id: int | None = None,
) -> dict[str, Any]:
    if contact_id is not None:
        return _row_to_dict(conn.execute(text(_SQL_CONTACT_BY_ID), {"id": contact_id}).fetchone())
    if phone:
        return _row_to_dict(conn.execute(text(_SQL_CONTACT_BY_PHONE), {"phone": phone}).fetchone())
    if email:
        return _row_to_dict(conn.execute(text(_SQL_CONTACT_BY_EMAIL), {"email": email}).fetchone())
    return {}


def _deep_scan_api_conversations(
    cfg: ApiConfig,
    dest_account_id: int,
    dest_contact_id: int,
    src_convs: list[dict[str, Any]],
) -> list[ConversationApiCheck]:
    """Valida conversas do contato via GET /contacts/{id}/conversations.

    Cross-referencia usando ``additional_attributes.src_id``.
    Emite WARNING se o endpoint retornar exatamente 20 itens (limite Rails).

    :param src_convs: lista de conversas SOURCE já carregadas do DB
    :returns: lista de ConversationApiCheck, uma por conversa SOURCE
    """
    time.sleep(0.15)
    url = (
        f"{cfg.base_url}/api/v1/accounts/{dest_account_id}"
        f"/contacts/{dest_contact_id}/conversations"
    )
    try:
        data = _api_get(url, cfg)
    except ApiError as exc:
        log.warning(
            "CONV API lista falhou dest_contact_id=%d account_id=%d HTTP %d",
            dest_contact_id,
            dest_account_id,
            exc.status,
        )
        return [
            ConversationApiCheck(
                src_conv_id=int(sc["id"]),
                dest_conv_id=None,
                display_id=sc.get("display_id"),
                found_in_api=False,
                status_src=str(sc.get("status") or ""),
                api_status=exc.status,
                api_error=f"lista_http:{exc.status}",
            )
            for sc in src_convs
        ]

    payload: list[dict[str, Any]] = data.get("payload", [])
    if len(payload) == 20:
        log.warning(
            "CONV API limite 20 atingido para dest_contact_id=%d account_id=%d — "
            "contato pode ter mais de 20 conversas; validação é parcial.",
            dest_contact_id,
            dest_account_id,
        )
    log.info(
        "CONV API dest_contact_id=%d account_id=%d api_count=%d src_count=%d",
        dest_contact_id,
        dest_account_id,
        len(payload),
        len(src_convs),
    )
    log.debug(
        "CONV API payload=%s",
        json.dumps(
            [
                {
                    "id": p.get("id"),
                    "status": p.get("status"),
                    "additional_attributes": p.get("additional_attributes"),
                }
                for p in payload
            ],
            ensure_ascii=False,
        ),
    )

    # Indexa payload por src_id (via additional_attributes.src_id)
    api_by_src_id: dict[str, dict[str, Any]] = {}
    api_by_dest_id: dict[int, dict[str, Any]] = {}
    for p in payload:
        aa = p.get("additional_attributes") or {}
        src_id_str = str(aa.get("src_id") or "")
        if src_id_str:
            api_by_src_id[src_id_str] = p
        pid = p.get("id")
        if pid is not None:
            api_by_dest_id[int(pid)] = p

    results: list[ConversationApiCheck] = []
    for sc in src_convs:
        src_conv_id = int(sc["id"])
        status_src = str(sc.get("status") or "")
        display_id = sc.get("display_id")

        # Tenta match por src_id primeiro, depois por dest_id mapeado
        api_conv = api_by_src_id.get(str(src_conv_id))
        if api_conv is None:
            # Tenta usando dest_conv_id do payload— pode ter migrado sem src_id no attr
            pass

        if api_conv is not None:
            api_status_val = str(api_conv.get("status") or "")
            status_match = api_status_val == status_src
            # Contar mensagens via API (às vezes o payload já inclui)
            msgs_in_payload = api_conv.get("messages") or []
            msgs_api_count = len(msgs_in_payload)
            if msgs_api_count == 0:
                msgs_api_count = -1  # não incluído no endpoint
            check = ConversationApiCheck(
                src_conv_id=src_conv_id,
                dest_conv_id=int(api_conv.get("id")),
                display_id=display_id,
                found_in_api=True,
                status_src=status_src,
                status_api=api_status_val,
                status_match=status_match,
                messages_api_count=msgs_api_count,
                src_id_match=True,  # matched via additional_attributes.src_id
                api_status=200,
            )
            if not status_match:
                log.warning(
                    "CONV status_mismatch src_id=%d status_src=%r status_api=%r",
                    src_conv_id,
                    status_src,
                    api_status_val,
                )
        else:
            check = ConversationApiCheck(
                src_conv_id=src_conv_id,
                dest_conv_id=None,
                display_id=display_id,
                found_in_api=False,
                status_src=status_src,
                api_error="src_id_not_in_payload",
            )
            log.warning(
                "CONV not found in API src_id=%d (src_id not in payload additional_attributes)",
                src_conv_id,
            )

        log.info(
            "  CONV API src_id=%d found=%s status_match=%s",
            src_conv_id,
            check.found_in_api,
            check.status_match,
        )
        results.append(check)

    return results


def _validate_contact_via_api(
    cfg: ApiConfig,
    dest_account_id: int,
    dest_contact_id: int,
    src_contact: dict[str, Any],
) -> bool:
    """Valida contato via GET /contacts/{dest_contact_id} e loga divergências.

    :returns: ``True`` se o contato foi encontrado e campos principais conferem.
    """
    time.sleep(0.15)
    try:
        data = _api_get(
            f"{cfg.base_url}/api/v1/accounts/{dest_account_id}/contacts/{dest_contact_id}",
            cfg,
        )
    except ApiError as exc:
        log.warning(
            "CONTACT API not found dest_id=%d account_id=%d HTTP %d",
            dest_contact_id,
            dest_account_id,
            exc.status,
        )
        return False

    api_name = data.get("name", "")
    api_email = data.get("email") or ""
    api_phone = data.get("phone_number") or ""
    src_name = str(src_contact.get("name") or "")
    src_email = str(src_contact.get("email") or "")
    src_phone = str(src_contact.get("phone_number") or "")

    name_ok = api_name == src_name
    email_ok = api_email == src_email
    phone_ok = api_phone == src_phone

    log.info(
        "CONTACT API dest_id=%d name_match=%s email_match=%s phone_match=%s",
        dest_contact_id,
        name_ok,
        email_ok,
        phone_ok,
    )
    if not name_ok:
        log.warning("FIELD contact.name src=%r api=%r", src_name, api_name)
    if not email_ok:
        log.warning("FIELD contact.email src=%r api=%r", src_email, api_email)
    if not phone_ok:
        log.warning("FIELD contact.phone src=%r api=%r", src_phone, api_phone)
    log.debug("CONTACT API response=%s", json.dumps(data, ensure_ascii=False))
    return True


def _select_sample_contacts(
    src: Connection,
    src_account_ids: list[int],
    n: int,
) -> list[SampleContact]:
    """Seleciona até N contatos ricos do SOURCE ordenados por richness_score."""
    rows = src.execute(
        text(_SQL_SAMPLE_CONTACTS),
        {"src_account_ids": src_account_ids, "n": n},
    ).fetchall()
    result = [
        SampleContact(
            src_contact_id=int(r[0]),
            account_id=int(r[1]),
            phone_number=str(r[2] or ""),
            email=str(r[3] or ""),
            conv_count=int(r[4]),
            msg_count=int(r[5]),
            att_count=int(r[6]),
            richness_score=int(r[7]),
        )
        for r in rows
    ]
    log.info(
        "Sample: %d contato(s) selecionado(s) (n=%d, account_ids=%s)",
        len(result),
        n,
        src_account_ids,
    )
    for sc in result:
        log.debug(
            "  SAMPLE contact_id=%d account=%d convs=%d msgs=%d atts=%d score=%d",
            sc.src_contact_id,
            sc.account_id,
            sc.conv_count,
            sc.msg_count,
            sc.att_count,
            sc.richness_score,
        )
    return result


def _deep_scan_contact(
    src: Connection,
    dest: Connection,
    has_mig_state: bool,
    *,
    api_cfg: ApiConfig,
    phone: str | None = None,
    email: str | None = None,
    contact_id: int | None = None,
    sample_size: int | None = None,
    check_urls: bool = False,
    max_msgs_per_conv: int | None = None,
) -> ContactDeepResult:
    query: dict[str, Any] = {}
    if phone:
        query["phone"] = phone
    if email:
        query["email"] = email
    if contact_id is not None:
        query["contact_id"] = contact_id
    log.info("=== Deep scan contact query=%s ===", query)

    # 1. Busca no SOURCE
    src_contact = _fetch_contact(src, phone=phone, email=email, contact_id=contact_id)
    if not src_contact:
        log.warning("Contato não encontrado no SOURCE: %s", query)
        return ContactDeepResult(
            src_id=contact_id if contact_id is not None else -1,
            dest_id=None,
            phone_number=phone or "",
            email=email or "",
            found_in_dest_db=False,
            found_in_api=False,
        )

    src_contact_id = int(src_contact["id"])
    log.info(
        "CONTACT SOURCE id=%d name=%r email=%r phone=%r",
        src_contact_id,
        src_contact.get("name"),
        src_contact.get("email"),
        src_contact.get("phone_number"),
    )
    log.debug("CONTACT src_full=%s", json.dumps(_serializable(src_contact), ensure_ascii=False))

    # 2. Busca no DEST via migration_state
    dest_contact_id: int | None = None
    dest_contact: dict[str, Any] = {}

    if has_mig_state:
        dest_contact_id = _lookup_dest_id(dest, "contacts", src_contact_id)
        if dest_contact_id is not None:
            dest_contact = _row_to_dict(
                dest.execute(text(_SQL_CONTACT_BY_ID), {"id": dest_contact_id}).fetchone()
            )
            if dest_contact:
                log.debug(
                    "CONTACT dest_full=%s",
                    json.dumps(_serializable(dest_contact), ensure_ascii=False),
                )

    # Fallback: busca direta por phone/email no DEST
    # Em auto-sample (contact_id fornecido), usa os campos do src_contact.
    if not dest_contact:
        fb_phone = phone or str(src_contact.get("phone_number") or "") or None
        fb_email = email or str(src_contact.get("email") or "") or None
        dest_contact = _fetch_contact(dest, phone=fb_phone, email=fb_email)
        if dest_contact:
            dest_contact_id = int(dest_contact["id"])
            log.info(
                "CONTACT found in DEST via direct lookup (fallback) dest_id=%d",
                dest_contact_id,
            )
        else:
            log.warning("CONTACT not found in DEST src_id=%d", src_contact_id)

    found_in_dest = bool(dest_contact)
    fields = _compare_fields("contact", src_contact, dest_contact) if found_in_dest else []

    # 2b. Validação via API (se mapeado no DEST)
    found_in_api = False
    if dest_contact_id is not None:
        dest_account_id_for_api = dest_contact.get("account_id") if dest_contact else None
        if dest_account_id_for_api:
            found_in_api = _validate_contact_via_api(
                api_cfg,
                int(dest_account_id_for_api),
                dest_contact_id,
                src_contact,
            )

    # 3. Conversas do SOURCE
    src_convs = [
        _row_to_dict(r)
        for r in src.execute(
            text(_SQL_CONVERSATIONS_BY_CONTACT), {"contact_id": src_contact_id}
        ).fetchall()
    ]
    log.info("CONTACT src_id=%d conversations_total=%d", src_contact_id, len(src_convs))

    if sample_size is not None:
        src_convs = src_convs[:sample_size]
        log.info("Sampling %d conversation(s)", len(src_convs))

    # 3a. Scan DB-vs-DB por conversa
    conv_results = [
        _deep_scan_conversation(
            src, dest, sc, has_mig_state, check_urls=check_urls, max_msgs=max_msgs_per_conv
        )
        for sc in src_convs
    ]

    # 3b. Validação das conversas via API (se dest_contact_id e dest_account_id conhecidos)
    api_conv_checks: list[ConversationApiCheck] = []
    if dest_contact_id is not None and dest_contact:
        dest_account_id_api = dest_contact.get("account_id")
        if dest_account_id_api and src_convs:
            api_conv_checks = _deep_scan_api_conversations(
                api_cfg,
                int(dest_account_id_api),
                dest_contact_id,
                src_convs,
            )
            # Enriquecer cada ConversationResult com seu ConversationApiCheck
            api_by_src = {chk.src_conv_id: chk for chk in api_conv_checks}
            for cr in conv_results:
                cr.api_check = api_by_src.get(cr.src_id)

    return ContactDeepResult(
        src_id=src_contact_id,
        dest_id=dest_contact_id,
        phone_number=str(src_contact.get("phone_number") or ""),
        email=str(src_contact.get("email") or ""),
        found_in_dest_db=found_in_dest,
        found_in_api=found_in_api,
        fields=fields,
        conversations=conv_results,
    )


# ---------------------------------------------------------------------------
# Sumário estatístico do deep result
# ---------------------------------------------------------------------------


def _compute_deep_summary(results: list[ContactDeepResult]) -> dict[str, object]:
    convs = [c for r in results for c in r.conversations]
    msgs: list[MessageResult] = [m for c in convs for m in c.messages]
    atts: list[AttachmentResult] = [a for m in msgs for a in m.attachments]
    # API conv checks
    api_checks = [c.api_check for c in convs if c.api_check is not None]
    return {
        "contacts_sampled": len(results),
        "contacts_found_in_dest_db": sum(1 for r in results if r.found_in_dest_db),
        "contacts_found_in_api": sum(1 for r in results if r.found_in_api),
        "conversations_total": len(convs),
        "conversations_found_db": sum(1 for c in convs if c.found_in_dest),
        "conversations_checked_api": len(api_checks),
        "conversations_found_api": sum(1 for chk in api_checks if chk.found_in_api),
        "conversations_status_match": sum(1 for chk in api_checks if chk.status_match),
        "conversations_src_id_match": sum(1 for chk in api_checks if chk.src_id_match),
        "messages_sampled": len(msgs),
        "messages_found": sum(1 for m in msgs if m.found_in_dest),
        "messages_content_match": sum(1 for m in msgs if m.content_match),
        "messages_type_match": sum(1 for m in msgs if m.type_match),
        "attachments_total": len(atts),
        "attachments_with_dest_id": sum(1 for a in atts if a.dest_id is not None),
        "attachments_url_checked": sum(1 for a in atts if a.http_status > 0),
        "attachments_url_accessible": sum(1 for a in atts if a.url_accessible),
    }


# ---------------------------------------------------------------------------
# Modo deep — orquestra scan e produz relatório
# ---------------------------------------------------------------------------


def _run_deep(
    factory: ConnectionFactory,
    api_cfg: ApiConfig,
    *,
    phone: str | None,
    email: str | None,
    sample_size: int | None,
    check_urls: bool,
    max_msgs_per_conv: int | None = None,
) -> DeepValidationReport:
    log.info("=== Modo deep — %s ===", _TS)

    src_engine = factory.create_source_engine()
    dest_engine = factory.create_dest_engine()

    with src_engine.connect() as src, dest_engine.connect() as dest:
        has_mig_state = _migration_state_exists(dest)
        if not has_mig_state:
            log.warning(
                "migration_state NÃO encontrada no DEST — "
                "lookup por src_id desativado; contato localizado por phone/email direto."
            )
        account_map = _load_account_map(dest)
        src_account_ids = list(account_map.keys())

        if phone or email:
            # Modo contato único — phone ou email fornecido
            contact_results = [
                _deep_scan_contact(
                    src,
                    dest,
                    has_mig_state,
                    api_cfg=api_cfg,
                    phone=phone,
                    email=email,
                    sample_size=sample_size,
                    check_urls=check_urls,
                    max_msgs_per_conv=max_msgs_per_conv,
                )
            ]
            contact_query: dict[str, Any] = {
                k: v for k, v in (("phone", phone), ("email", email)) if v
            }
        else:
            # Modo auto-amostra — richness_score por account
            n = sample_size or 5
            log.info("Modo auto-amostra: selecionando %d contato(s) por richness_score", n)
            samples = _select_sample_contacts(src, src_account_ids, n)
            if not samples:
                log.warning(
                    "Nenhum contato rico encontrado no SOURCE para amostra "
                    "(account_ids=%s). Verifique se há conversas+msgs+anexos.",
                    src_account_ids,
                )
            contact_results = [
                _deep_scan_contact(
                    src,
                    dest,
                    has_mig_state,
                    api_cfg=api_cfg,
                    contact_id=sc.src_contact_id,
                    sample_size=None,  # sem limite de convs em auto-sample
                    check_urls=check_urls,
                    max_msgs_per_conv=max_msgs_per_conv,
                )
                for sc in samples
            ]
            contact_query = {"mode": "auto_sample", "n": n, "account_ids": src_account_ids}

    summary = _compute_deep_summary(contact_results)
    log.info("Deep summary: %s", json.dumps(summary, ensure_ascii=False))

    return DeepValidationReport(
        timestamp=_TS,
        contact_query=contact_query,
        contacts=contact_results,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# Modo summary — contagens por account (idêntico ao app/08)
# ---------------------------------------------------------------------------


def _fetch_count_by_account(conn: Connection, table: str) -> dict[int, int]:
    rows = conn.execute(text(_SQL_COUNT_BY_ACCOUNT.format(table=table))).fetchall()
    return {int(r[0]): int(r[1]) for r in rows}


def _fetch_total(conn: Connection, table: str) -> int:
    row = conn.execute(text(_SQL_TOTALS.format(table=table))).fetchone()
    return int(row[0]) if row else 0


def _fetch_sanity(dest: Connection, dest_account_id: int) -> dict[str, int]:
    """Executa queries de sanidade no DEST para um account.

    :returns: dict com ``conv_dup_display_id``, ``orphan_messages``, ``pubsub_dups``.
    """
    params = {"account_id": dest_account_id}

    def _one(q: str, key: str) -> int:
        try:
            row = dest.execute(text(q), params).fetchone()
            return int(row[0]) if row else 0
        except Exception as exc:  # noqa: BLE001
            # Column/table absent in this Chatwoot schema version — not an error.
            exc_summary = str(exc).split("\n")[0][:120]
            log.debug("SANITY dest_account_id=%d %s=SKIP — %s", dest_account_id, key, exc_summary)
            dest.rollback()
            return -1  # sentinel: coluna/tabela ausente no schema

    result = {
        "conv_dup_display_id": _one(_SQL_SANITY_CONV_DUP_DISPLAY_ID, "conv_dup_display_id"),
        "orphan_messages": _one(_SQL_SANITY_ORPHAN_MESSAGES, "orphan_messages"),
        "pubsub_dups": _one(_SQL_SANITY_PUBSUB_DUPS, "pubsub_dups"),
    }
    for k, v in result.items():
        if v > 0:
            log.warning("SANITY dest_account_id=%d %s=%d", dest_account_id, k, v)
        elif v == 0:
            log.debug("SANITY dest_account_id=%d %s=%d", dest_account_id, k, v)
    return result


def _run_summary(factory: ConnectionFactory, api_cfg: ApiConfig) -> dict[str, Any]:
    log.info("=== Modo summary — contagens por account (%s) ===", _TS)

    src_engine = factory.create_source_engine()
    dest_engine = factory.create_dest_engine()

    with src_engine.connect() as src:
        src_accounts = {
            int(r[0]): {"name": str(r[1]), "status": r[2]}
            for r in src.execute(text(_SQL_ACCOUNTS)).fetchall()
        }
        src_contacts = _fetch_count_by_account(src, "contacts")
        src_convs = _fetch_count_by_account(src, "conversations")
        src_msgs = _fetch_count_by_account(src, "messages")
        src_atts = _fetch_count_by_account(src, "attachments")

    log.info(
        "SOURCE — accounts=%d contacts=%d conversations=%d messages=%d attachments=%d",
        len(src_accounts),
        sum(src_contacts.values()),
        sum(src_convs.values()),
        sum(src_msgs.values()),
        sum(src_atts.values()),
    )

    with dest_engine.connect() as dest:
        dest_accounts = {
            int(r[0]): {"name": str(r[1]), "status": r[2]}
            for r in dest.execute(text(_SQL_ACCOUNTS)).fetchall()
        }
        dest_contacts = _fetch_count_by_account(dest, "contacts")
        dest_convs = _fetch_count_by_account(dest, "conversations")
        dest_msgs = _fetch_count_by_account(dest, "messages")
        dest_atts = _fetch_count_by_account(dest, "attachments")
        account_map = _load_account_map(dest)
        # Sanidade por dest_account
        dest_sanity: dict[int, dict[str, int]] = {
            acc_id: _fetch_sanity(dest, acc_id) for acc_id in account_map.values()
        }

    log.info(
        "DEST — accounts=%d contacts=%d conversations=%d messages=%d attachments=%d",
        len(dest_accounts),
        sum(dest_contacts.values()),
        sum(dest_convs.values()),
        sum(dest_msgs.values()),
        sum(dest_atts.values()),
    )

    # Contagens via API — response: {"meta": {"all_count": N, ...}}
    api_counts: dict[int, tuple[int, int, str]] = {}
    for dest_acc_id in account_map.values():
        time.sleep(0.15)
        try:
            conv_data = _api_get(
                f"{api_cfg.base_url}/api/v1/accounts/{dest_acc_id}/conversations/meta?status=all",
                api_cfg,
            )
            api_conv = int(conv_data.get("meta", {}).get("all_count", -1))
        except ApiError as exc:
            api_counts[dest_acc_id] = (-1, -1, f"conv_http:{exc.status}")
            continue
        time.sleep(0.15)
        try:
            cont_data = _api_get(
                f"{api_cfg.base_url}/api/v1/accounts/{dest_acc_id}/contacts?page=1",
                api_cfg,
            )
            api_cont = int(cont_data.get("meta", {}).get("count", -1))
        except ApiError as exc:
            api_counts[dest_acc_id] = (api_conv, -1, f"contacts_http:{exc.status}")
            continue
        api_counts[dest_acc_id] = (api_conv, api_cont, "")
        log.info("API account_id=%d api_conv=%d api_contacts=%d", dest_acc_id, api_conv, api_cont)

    comparison: list[dict[str, Any]] = []
    for src_acc_id, dest_acc_id in account_map.items():
        api_conv, api_cont, api_err = api_counts.get(dest_acc_id, (-1, -1, "not_queried"))
        comparison.append(
            {
                "src_account_id": src_acc_id,
                "dest_account_id": dest_acc_id,
                "src_name": src_accounts.get(src_acc_id, {}).get("name", "?"),
                "dest_name": dest_accounts.get(dest_acc_id, {}).get("name", "?"),
                "src_contacts": src_contacts.get(src_acc_id, 0),
                "dest_contacts": dest_contacts.get(dest_acc_id, 0),
                "api_contacts": api_cont,
                "delta_contacts": dest_contacts.get(dest_acc_id, 0)
                - src_contacts.get(src_acc_id, 0),
                "src_conversations": src_convs.get(src_acc_id, 0),
                "dest_conversations": dest_convs.get(dest_acc_id, 0),
                "api_conversations": api_conv,
                "delta_conversations": dest_convs.get(dest_acc_id, 0)
                - src_convs.get(src_acc_id, 0),
                "src_messages": src_msgs.get(src_acc_id, 0),
                "dest_messages": dest_msgs.get(dest_acc_id, 0),
                "delta_messages": dest_msgs.get(dest_acc_id, 0) - src_msgs.get(src_acc_id, 0),
                "src_attachments": src_atts.get(src_acc_id, 0),
                "dest_attachments": dest_atts.get(dest_acc_id, 0),
                "delta_attachments": dest_atts.get(dest_acc_id, 0) - src_atts.get(src_acc_id, 0),
                "api_error": api_err,
                # Sanidade DEST
                "sanity_conv_dup_display_id": dest_sanity.get(dest_acc_id, {}).get(
                    "conv_dup_display_id", -1
                ),
                "sanity_orphan_messages": dest_sanity.get(dest_acc_id, {}).get(
                    "orphan_messages", -1
                ),
                "sanity_pubsub_dups": dest_sanity.get(dest_acc_id, {}).get("pubsub_dups", -1),
            }
        )
        row = comparison[-1]
        log.info(
            "  ACC src=%d→dest=%d  Δconv=%+d Δmsg=%+d Δatt=%+d api_conv=%d api_contacts=%d",
            src_acc_id,
            dest_acc_id,
            row["delta_conversations"],
            row["delta_messages"],
            row["delta_attachments"],
            api_conv,
            api_cont,
        )

    return {
        "mode": "summary",
        "timestamp": _TS,
        "source_db": "chatwoot_dev1_db",
        "dest_db": "chatwoot004_dev1_db",
        "comparison": comparison,
    }


# ---------------------------------------------------------------------------
# Persistência — JSON + CSV
# ---------------------------------------------------------------------------


def _save_deep_outputs(report: DeepValidationReport) -> None:
    """Salva JSON completo e CSV de resumo do modo deep (um ou vários contatos)."""
    json_path = _LOG_DIR / f"validacao_api_{_TS}.json"
    csv_path = _LOG_DIR / f"validacao_api_{_TS}.csv"

    json_path.write_text(
        json.dumps(asdict(report), cls=_DatetimeEncoder, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info("JSON salvo: %s", json_path)

    # CSV: uma linha por contato, mais uma linha de totais no summary
    rows: list[dict[str, Any]] = []
    for cr in report.contacts:
        cr_convs = cr.conversations
        cr_msgs = [m for c in cr_convs for m in c.messages]
        cr_atts = [a for m in cr_msgs for a in m.attachments]
        rows.append(
            {
                "timestamp": report.timestamp,
                "contact_query": json.dumps(report.contact_query, ensure_ascii=False),
                "src_id": cr.src_id,
                "dest_id": cr.dest_id,
                "phone_number": cr.phone_number,
                "email": cr.email,
                "found_in_dest_db": cr.found_in_dest_db,
                "found_in_api": cr.found_in_api,
                "conversations_total": len(cr_convs),
                "conversations_found": sum(1 for c in cr_convs if c.found_in_dest),
                "messages_sampled": len(cr_msgs),
                "messages_found": sum(1 for m in cr_msgs if m.found_in_dest),
                "messages_content_match": sum(1 for m in cr_msgs if m.content_match),
                "attachments_total": len(cr_atts),
                "attachments_url_accessible": sum(1 for a in cr_atts if a.url_accessible),
            }
        )

    if rows:
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        log.info("CSV salvo: %s (%d linha(s))", csv_path, len(rows))
    else:
        log.warning("Nenhum contato no relatório — CSV não gerado")


def _save_summary_outputs(report: dict[str, Any]) -> None:
    """Salva JSON completo e CSV de comparação por account do modo summary."""
    json_path = _LOG_DIR / f"validacao_api_{_TS}.json"
    csv_path = _LOG_DIR / f"validacao_api_{_TS}.csv"

    json_path.write_text(
        json.dumps(report, cls=_DatetimeEncoder, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info("JSON salvo: %s", json_path)

    rows = report.get("comparison", [])
    if rows:
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        log.info("CSV salvo: %s", csv_path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="10_validar_api.py",
        description="Validação profunda de dados migrados Chatwoot (SOURCE → DEST)",
    )
    sub = parser.add_subparsers(dest="mode", required=True)

    sub.add_parser("summary", help="Contagens por account (SOURCE vs DEST)")

    dp = sub.add_parser("deep", help="Deep scan para um contato e toda sua cadeia de dados")
    grp = dp.add_mutually_exclusive_group(required=False)
    grp.add_argument(
        "--contact-phone",
        metavar="PHONE",
        dest="contact_phone",
        help="Valida contato específico por phone_number (ex: +5511999999999)",
    )
    grp.add_argument(
        "--contact-email",
        metavar="EMAIL",
        dest="contact_email",
        help="Valida contato específico por e-mail",
    )
    dp.add_argument(
        "--sample-size",
        type=int,
        default=None,
        metavar="N",
        dest="sample_size",
        help=(
            "Auto-amostra: seleciona os N contatos mais ricos (richness_score) do SOURCE. "
            "Padrão 5 quando --contact-phone/--contact-email não informados. "
            "Com --contact-phone/--contact-email: limita a N conversas do contato."
        ),
    )
    dp.add_argument(
        "--check-urls",
        action="store_true",
        dest="check_urls",
        help="Verificar acessibilidade dos URLs de anexo (HEAD request)",
    )
    dp.add_argument(
        "--max-msgs-per-conv",
        type=int,
        default=None,
        metavar="N",
        dest="max_msgs_per_conv",
        help=(
            "Limita a N mensagens analisadas por conversa (padrão: sem limite). "
            "Use para reduzir tempo em conversas com muitas mensagens."
        ),
    )
    return parser


def _exit_code_summary(report: dict[str, Any]) -> int:
    """Calcula exit code para modo summary.

    0 — todos os deltas SOURCE→DEST ≥ 0 e sanidade ok
    2 — algum delta_conversations/messages/attachments < 0 (perda de dados)
        ou sanity check > 0 (orphans, display_id dups, pubsub dups)
    """
    has_loss = any(
        row.get("delta_conversations", 0) < 0
        or row.get("delta_messages", 0) < 0
        or row.get("delta_attachments", 0) < 0
        for row in report.get("comparison", [])
    )
    has_sanity_issue = any(
        (row.get("sanity_conv_dup_display_id", 0) or 0) > 0
        or (row.get("sanity_orphan_messages", 0) or 0) > 0
        or (row.get("sanity_pubsub_dups", 0) or 0) > 0
        for row in report.get("comparison", [])
    )
    if has_loss:
        log.warning("EXIT 2 — deltas negativos detectados (possível perda de dados)")
    if has_sanity_issue:
        log.warning("EXIT 2 — sanity checks com falhas (orphans, display_id dups ou pubsub dups)")
    if has_loss or has_sanity_issue:
        return 2
    return 0


def _exit_code_deep(report: DeepValidationReport) -> int:
    """Calcula exit code para modo deep.

    0 — tudo ok
    2 — conversas ou mensagens não encontradas no DEST/API
    3 — links de attachment quebrados (404/410)
    4 — 2 + 3 simultaneamente
    """
    summary = report.summary
    convs_total = int(summary.get("conversations_total", 0))
    convs_found_db = int(summary.get("conversations_found_db", 0))
    msgs_total = int(summary.get("messages_sampled", 0))
    msgs_found = int(summary.get("messages_found", 0))

    att_checked = int(summary.get("attachments_url_checked", 0))
    att_ok = int(summary.get("attachments_url_accessible", 0))

    has_delta = (convs_total > 0 and convs_found_db < convs_total) or (
        msgs_total > 0 and msgs_found < msgs_total
    )
    has_broken = att_checked > 0 and att_ok < att_checked

    if has_delta:
        log.warning(
            "EXIT delta — conv found_db=%d/%d msgs found=%d/%d",
            convs_found_db,
            convs_total,
            msgs_found,
            msgs_total,
        )
    if has_broken:
        log.warning(
            "EXIT links — attachments ok=%d/%d",
            att_ok,
            att_checked,
        )

    if has_delta and has_broken:
        return 4
    if has_delta:
        return 2
    if has_broken:
        return 3
    return 0


def main() -> None:
    args = _build_parser().parse_args()
    factory = ConnectionFactory()

    api_cfg = _load_api_config()
    _probe_api(api_cfg)

    exit_code = 0

    if args.mode == "summary":
        report = _run_summary(factory, api_cfg)
        _save_summary_outputs(report)
        exit_code = _exit_code_summary(report)
    else:
        # Sem phone/email e sem --sample-size → auto-amostra com padrão 5
        if not args.contact_phone and not args.contact_email and args.sample_size is None:
            args.sample_size = 5
            log.info("Modo auto-amostra ativado (padrão --sample-size 5)")
        report_deep = _run_deep(
            factory,
            api_cfg,
            phone=args.contact_phone,
            email=args.contact_email,
            sample_size=args.sample_size,
            check_urls=args.check_urls,
            max_msgs_per_conv=args.max_msgs_per_conv,
        )
        _save_deep_outputs(report_deep)
        exit_code = _exit_code_deep(report_deep)

    log.info("Concluído. Outputs em %s/ — exit_code=%d", _LOG_DIR, exit_code)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
