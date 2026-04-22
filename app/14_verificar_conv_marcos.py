"""Verifica a conversa de Marcos (14/11/2025) — SOURCE vs DEST.

Arquitetura de referência
--------------------------
  chatwoot_dev1_db   = export de chat.vya.digital   (SOURCE, read-only)
  chatwoot004_dev1_db = export de synchat.vya.digital (DEST, alvo de migração)

  API SOURCE : chat.vya.digital          — valida visibilidade na origem
  API DEST   : vya-chat-dev.vya.digital  — valida visibilidade pós-migração

Etapas
------
1. Busca no SOURCE (chatwoot_dev1_db) conversas do Marcos em torno da data alvo:
   a) onde ele é assignee
   b) onde ele enviou mensagens
2. Para cada conversa encontrada, verifica se existe no DEST (chatwoot004_dev1_db)
   via ``additional_attributes->>'src_id'``.
3. Proba a API do DEST (vya-chat-dev.vya.digital) para confirmar visibilidade
   das conversas encontradas via admin token.
4. Gera relatório com gap analysis: conversas no SOURCE ausentes no DEST.

Saída
-----
.tmp/verificacao_conv_marcos_YYYYMMDD_HHMMSS.json  — relatório completo
.tmp/verificacao_conv_marcos_YYYYMMDD_HHMMSS.log   — log detalhado

Exit codes
----------
0   Sucesso (pode conter gaps)
1   Falha crítica (sem credenciais ou DB inacessível)

Usage::

    python app/14_verificar_conv_marcos.py
    python app/14_verificar_conv_marcos.py --date 2025-11-14
    python app/14_verificar_conv_marcus.py --date 2025-11-14 --window-days 7
    python app/14_verificar_conv_marcos.py --user-id 88 --date 2025-11-14
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import text

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from src.factory.connection_factory import ConnectionFactory  # noqa: E402

# ---------------------------------------------------------------------------
# Constantes e logging
# ---------------------------------------------------------------------------
_SECRETS_PATH = _ROOT / ".secrets" / "generate_erd.json"
_TMP = _ROOT / ".tmp"
_TMP.mkdir(parents=True, exist_ok=True)
_TS = datetime.now().strftime("%Y%m%d_%H%M%S")  # noqa: DTZ005

# Mapeamento de account_id SOURCE → DEST (confirmado pelo diagn. 2026-04-22)
_ACCOUNT_MAP_SRC_TO_DST: dict[int, int] = {1: 1, 17: 17, 18: 61, 25: 68}

_fmt = logging.Formatter(
    "%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
_sh = logging.StreamHandler(sys.stdout)
_sh.setLevel(logging.INFO)
_sh.setFormatter(_fmt)
_fh = logging.FileHandler(str(_TMP / f"verificacao_conv_marcos_{_TS}.log"), encoding="utf-8")
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(_fmt)
logging.getLogger().setLevel(logging.DEBUG)
logging.getLogger().addHandler(_sh)
logging.getLogger().addHandler(_fh)

log = logging.getLogger("verificacao_conv_marcos")


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ConversationEntry:
    """Conversa encontrada no SOURCE ou DEST."""

    db: str  # "source" | "dest"
    conv_id: int = 0
    display_id: int = 0
    account_id: int = 0
    inbox_id: int = 0
    assignee_id: int | None = None
    created_at: str = ""
    updated_at: str = ""
    src_id_in_attrs: str | None = None  # additional_attributes->>'src_id'
    found_via: str = ""  # "assignee" | "message_sender"
    inbox_name: str = ""
    account_name: str = ""


@dataclass
class MigrationGap:
    """Conversa presente no SOURCE mas ausente no DEST."""

    src_conv_id: int
    src_display_id: int
    src_account_id: int
    src_account_name: str
    src_inbox_id: int
    src_created_at: str
    dest_account_id: int  # esperado no DEST
    reason: str = "not_found_in_dest"


@dataclass
class ApiProbe:
    host: str = ""
    reachable: bool = False
    profile_name: str = ""
    error: str = ""


@dataclass
class ApiConversationCheck:
    host: str = ""
    account_id: int = 0
    conv_id: int = 0
    found: bool = False
    http_status: int = 0
    error: str = ""


@dataclass
class VerificationResult:
    user_id: int
    target_date: str
    window_days: int
    source_conversations: list[ConversationEntry] = field(default_factory=list)
    dest_conversations: list[ConversationEntry] = field(default_factory=list)
    migration_gaps: list[MigrationGap] = field(default_factory=list)
    api_source_probe: ApiProbe = field(default_factory=ApiProbe)
    api_dest_probe: ApiProbe = field(default_factory=ApiProbe)
    api_dest_checks: list[ApiConversationCheck] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers de banco de dados
# ---------------------------------------------------------------------------

_SQL_SOURCE_BY_ASSIGNEE = text(
    """
    SELECT
        c.id               AS conv_id,
        c.display_id,
        c.account_id,
        c.inbox_id,
        c.assignee_id,
        c.created_at::text AS created_at,
        c.updated_at::text AS updated_at,
        i.name             AS inbox_name,
        a.name             AS account_name,
        (c.additional_attributes->>'src_id') AS src_id_in_attrs
    FROM conversations c
    LEFT JOIN inboxes  i ON i.id = c.inbox_id
    LEFT JOIN accounts a ON a.id = c.account_id
    WHERE c.assignee_id = :uid
      AND c.created_at >= :date_from
      AND c.created_at <  :date_to
    ORDER BY c.created_at;
    """
)

_SQL_SOURCE_BY_MESSAGE_SENDER = text(
    """
    SELECT DISTINCT
        c.id               AS conv_id,
        c.display_id,
        c.account_id,
        c.inbox_id,
        c.assignee_id,
        c.created_at::text AS created_at,
        c.updated_at::text AS updated_at,
        i.name             AS inbox_name,
        a.name             AS account_name,
        (c.additional_attributes->>'src_id') AS src_id_in_attrs
    FROM messages m
    JOIN conversations c ON c.id = m.conversation_id
    LEFT JOIN inboxes   i ON i.id = c.inbox_id
    LEFT JOIN accounts  a ON a.id = c.account_id
    WHERE m.sender_id   = :uid
      AND m.sender_type = 'User'
      AND m.created_at >= :date_from
      AND m.created_at <  :date_to
    ORDER BY c.created_at::text;
    """
)

_SQL_DEST_BY_SRC_ID = text(
    """
    SELECT
        id                 AS conv_id,
        display_id,
        account_id,
        inbox_id,
        assignee_id,
        created_at::text   AS created_at,
        updated_at::text   AS updated_at,
        (additional_attributes->>'src_id') AS src_id_in_attrs
    FROM conversations
    WHERE (additional_attributes->>'src_id') = :src_id;
    """
)

_SQL_DEST_BY_ACCOUNT_AND_DATE = text(
    """
    SELECT
        c.id                AS conv_id,
        c.display_id,
        c.account_id,
        c.inbox_id,
        c.assignee_id,
        c.created_at::text  AS created_at,
        c.updated_at::text  AS updated_at,
        i.name              AS inbox_name,
        a.name              AS account_name,
        (c.additional_attributes->>'src_id') AS src_id_in_attrs
    FROM conversations c
    LEFT JOIN inboxes  i ON i.id = c.inbox_id
    LEFT JOIN accounts a ON a.id = c.account_id
    WHERE c.assignee_id = :uid
      AND c.created_at >= :date_from
      AND c.created_at <  :date_to
    ORDER BY c.created_at;
    """
)


def _query_source_conversations(
    conn: Any, uid: int, date_from: str, date_to: str
) -> list[ConversationEntry]:
    """Busca conversas do usuário no SOURCE (por assignee + sender)."""
    results: list[ConversationEntry] = []
    seen_ids: set[int] = set()

    params = {"uid": uid, "date_from": date_from, "date_to": date_to}

    # Por assignee
    rows = conn.execute(_SQL_SOURCE_BY_ASSIGNEE, params).mappings().all()
    for r in rows:
        entry = ConversationEntry(
            db="source",
            conv_id=r["conv_id"],
            display_id=r["display_id"],
            account_id=r["account_id"],
            inbox_id=r["inbox_id"],
            assignee_id=r["assignee_id"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
            src_id_in_attrs=r["src_id_in_attrs"],
            found_via="assignee",
            inbox_name=r["inbox_name"] or "",
            account_name=r["account_name"] or "",
        )
        results.append(entry)
        seen_ids.add(r["conv_id"])
        log.debug("SOURCE assignee — conv_id=%d display_id=%d", r["conv_id"], r["display_id"])

    # Por mensagem enviada (evita duplicatas)
    rows_msg = conn.execute(_SQL_SOURCE_BY_MESSAGE_SENDER, params).mappings().all()
    for r in rows_msg:
        if r["conv_id"] in seen_ids:
            continue
        entry = ConversationEntry(
            db="source",
            conv_id=r["conv_id"],
            display_id=r["display_id"],
            account_id=r["account_id"],
            inbox_id=r["inbox_id"],
            assignee_id=r["assignee_id"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
            src_id_in_attrs=r["src_id_in_attrs"],
            found_via="message_sender",
            inbox_name=r["inbox_name"] or "",
            account_name=r["account_name"] or "",
        )
        results.append(entry)
        seen_ids.add(r["conv_id"])
        log.debug("SOURCE msg — conv_id=%d display_id=%d", r["conv_id"], r["display_id"])

    log.info(
        "SOURCE: %d conversas encontradas (%d assignee + %d só por msg)",
        len(results),
        len([r for r in results if r.found_via == "assignee"]),
        len([r for r in results if r.found_via == "message_sender"]),
    )
    return results


def _query_dest_by_src_id(conn: Any, src_id: int) -> ConversationEntry | None:
    """Busca conversa no DEST pelo src_id (tracing de migração)."""
    row = conn.execute(_SQL_DEST_BY_SRC_ID, {"src_id": str(src_id)}).mappings().first()
    if row is None:
        return None
    return ConversationEntry(
        db="dest",
        conv_id=row["conv_id"],
        display_id=row["display_id"],
        account_id=row["account_id"],
        inbox_id=row["inbox_id"],
        assignee_id=row["assignee_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        src_id_in_attrs=row["src_id_in_attrs"],
        found_via="src_id_trace",
        inbox_name="",
        account_name="",
    )


def _query_dest_all_marcus(
    conn: Any, uid: int, date_from: str, date_to: str
) -> list[ConversationEntry]:
    """Busca conversas do usuário no DEST pela mesma janela de data."""
    rows = (
        conn.execute(
            _SQL_DEST_BY_ACCOUNT_AND_DATE,
            {"uid": uid, "date_from": date_from, "date_to": date_to},
        )
        .mappings()
        .all()
    )
    results = []
    for r in rows:
        entry = ConversationEntry(
            db="dest",
            conv_id=r["conv_id"],
            display_id=r["display_id"],
            account_id=r["account_id"],
            inbox_id=r["inbox_id"],
            assignee_id=r["assignee_id"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
            src_id_in_attrs=r["src_id_in_attrs"],
            found_via="date_range_dest",
            inbox_name=r["inbox_name"] or "",
            account_name=r["account_name"] or "",
        )
        results.append(entry)
    log.info("DEST: %d conversas com assignee=%d na janela de data", len(results), uid)
    return results


# ---------------------------------------------------------------------------
# Helpers de API
# ---------------------------------------------------------------------------


def _load_api_key() -> tuple[str, str]:
    """Retorna (api_key, synchat_host) de .secrets/generate_erd.json."""
    if not _SECRETS_PATH.exists():
        log.error("Secrets file not found: %s", _SECRETS_PATH)
        sys.exit(1)
    data: dict = json.loads(_SECRETS_PATH.read_text())
    synchat = data.get("synchat", {})
    api_key = synchat.get("api_key", "")
    if not api_key:
        log.error("synchat.api_key ausente em %s", _SECRETS_PATH)
        sys.exit(1)
    return api_key, synchat.get("host", "synchat.vya.digital")


def _api_probe(host: str, api_key: str, timeout_s: int = 10) -> ApiProbe:
    """Verifica se o host está acessível e o token é válido."""
    url = f"https://{host}/api/v1/profile"
    req = urllib.request.Request(url, headers={"api_access_token": api_key})
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            if resp.status == 200:
                body = json.loads(resp.read().decode())
                name = body.get("name", "")
                log.info("API probe OK — %s (profile: %s)", host, name)
                return ApiProbe(host=host, reachable=True, profile_name=name)
    except urllib.error.HTTPError as exc:
        msg = f"HTTP {exc.code}"
        log.warning("API probe falhou — %s — %s", host, msg)
        return ApiProbe(host=host, reachable=False, error=msg)
    except urllib.error.URLError as exc:
        msg = str(exc.reason)
        log.warning("API probe falhou — %s — %s", host, msg)
        return ApiProbe(host=host, reachable=False, error=msg)
    return ApiProbe(host=host, reachable=False, error="unexpected_status")


def _api_get_conversation(
    host: str, api_key: str, account_id: int, conv_id: int, timeout_s: int = 10
) -> ApiConversationCheck:
    """GET /api/v1/accounts/{account_id}/conversations/{conv_id}."""
    url = f"https://{host}/api/v1/accounts/{account_id}/conversations/{conv_id}"
    req = urllib.request.Request(url, headers={"api_access_token": api_key})
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            log.debug("API GET conv OK — %s account=%d conv=%d", host, account_id, conv_id)
            return ApiConversationCheck(
                host=host,
                account_id=account_id,
                conv_id=conv_id,
                found=True,
                http_status=resp.status,
            )
    except urllib.error.HTTPError as exc:
        log.debug("API GET conv %s — %d", url, exc.code)
        return ApiConversationCheck(
            host=host,
            account_id=account_id,
            conv_id=conv_id,
            found=False,
            http_status=exc.code,
            error=f"HTTP {exc.code}",
        )
    except urllib.error.URLError as exc:
        return ApiConversationCheck(
            host=host,
            account_id=account_id,
            conv_id=conv_id,
            found=False,
            http_status=0,
            error=str(exc.reason),
        )


# ---------------------------------------------------------------------------
# Fluxo principal
# ---------------------------------------------------------------------------


def run_verification(
    user_id: int,
    target_date: str,
    window_days: int,
    api_timeout: int,
) -> VerificationResult:
    """Executa a verificação completa."""
    td = date.fromisoformat(target_date)
    date_from = (td - timedelta(days=window_days)).isoformat()
    date_to = (td + timedelta(days=window_days + 1)).isoformat()

    log.info("=== Verificação conversa Marcos === date=%s window=%d days", target_date, window_days)
    log.info("Janela de busca: %s → %s (user_id=%d)", date_from, date_to, user_id)

    result = VerificationResult(
        user_id=user_id,
        target_date=target_date,
        window_days=window_days,
    )

    # 1. Conecta aos bancos
    factory = ConnectionFactory(secrets_path=_SECRETS_PATH)
    src_engine = factory.create_source_engine()
    dst_engine = factory.create_dest_engine()

    # 2. Busca no SOURCE
    with src_engine.connect() as src_conn:
        result.source_conversations = _query_source_conversations(
            src_conn, user_id, date_from, date_to
        )

    if not result.source_conversations:
        log.warning(
            "Nenhuma conversa encontrada no SOURCE para user_id=%d na janela %s→%s",
            user_id,
            date_from,
            date_to,
        )

    # 3. Para cada conversa do SOURCE, verifica no DEST
    dest_found_ids: set[int] = set()
    with dst_engine.connect() as dst_conn:
        for src_conv in result.source_conversations:
            # 3a. Busca por src_id (tracing de migração)
            dest_entry = _query_dest_by_src_id(dst_conn, src_conv.conv_id)
            if dest_entry:
                log.info(
                    "ENCONTRADA no DEST via src_id — src_conv_id=%d → dest_conv_id=%d "
                    "dest_display_id=%d dest_account=%d",
                    src_conv.conv_id,
                    dest_entry.conv_id,
                    dest_entry.display_id,
                    dest_entry.account_id,
                )
                result.dest_conversations.append(dest_entry)
                dest_found_ids.add(src_conv.conv_id)
            else:
                # 3b. Não encontrou por src_id → gap
                expected_dest_account = _ACCOUNT_MAP_SRC_TO_DST.get(
                    src_conv.account_id, src_conv.account_id
                )
                log.warning(
                    "GAP — src_conv_id=%d display_id=%d account=%d(%s) inbox=%d "
                    "created=%s — NOT found in DEST (expected dest account=%d)",
                    src_conv.conv_id,
                    src_conv.display_id,
                    src_conv.account_id,
                    src_conv.account_name,
                    src_conv.inbox_id,
                    src_conv.created_at,
                    expected_dest_account,
                )
                result.migration_gaps.append(
                    MigrationGap(
                        src_conv_id=src_conv.conv_id,
                        src_display_id=src_conv.display_id,
                        src_account_id=src_conv.account_id,
                        src_account_name=src_conv.account_name,
                        src_inbox_id=src_conv.inbox_id,
                        src_created_at=src_conv.created_at,
                        dest_account_id=expected_dest_account,
                        reason="src_id_not_found_in_dest",
                    )
                )

        # 3c. Busca adicional: conversas do DEST na mesma janela (pode incluir pré-existentes synchat)
        result.dest_conversations += _query_dest_all_marcus(dst_conn, user_id, date_from, date_to)

    # 4. API probes
    api_key, _synchat_host = _load_api_key()
    src_api_host = "chat.vya.digital"
    dst_api_host = "vya-chat-dev.vya.digital"

    log.info("=== API probes ===")
    result.api_source_probe = _api_probe(src_api_host, api_key, api_timeout)
    result.api_dest_probe = _api_probe(dst_api_host, api_key, api_timeout)

    # 5. Verifica conversas DEST via API (usa conv_id do DEST)
    if result.api_dest_probe.reachable:
        checked_ids: set[int] = set()
        for dest_conv in result.dest_conversations:
            if dest_conv.conv_id in checked_ids:
                continue
            checked_ids.add(dest_conv.conv_id)
            # Usa account_id do DEST (pode ser remapeado)
            check = _api_get_conversation(
                dst_api_host, api_key, dest_conv.account_id, dest_conv.conv_id, api_timeout
            )
            result.api_dest_checks.append(check)
            status = "VISÍVEL" if check.found else f"INVISÍVEL ({check.error})"
            log.info(
                "API DEST — account=%d conv_id=%d display_id=%d — %s",
                dest_conv.account_id,
                dest_conv.conv_id,
                dest_conv.display_id,
                status,
            )
    else:
        log.warning("API DEST inacessível — pulando verificação de visibilidade via API")

    # 6. Monta sumário
    result.summary = {
        "source_conversations_found": len(result.source_conversations),
        "dest_conversations_found_by_trace": len(
            [d for d in result.dest_conversations if d.found_via == "src_id_trace"]
        ),
        "dest_conversations_found_by_date_range": len(
            [d for d in result.dest_conversations if d.found_via == "date_range_dest"]
        ),
        "migration_gaps": len(result.migration_gaps),
        "api_dest_visible": len([c for c in result.api_dest_checks if c.found]),
        "api_dest_invisible": len([c for c in result.api_dest_checks if not c.found]),
        "source_api_reachable": result.api_source_probe.reachable,
        "dest_api_reachable": result.api_dest_probe.reachable,
        "verdict": (
            "MIGRATION_GAP"
            if result.migration_gaps
            else (
                "VISIBILITY_BUG"
                if result.dest_conversations and any(not c.found for c in result.api_dest_checks)
                else (
                    "NO_SOURCE_CONVERSATIONS" if not result.source_conversations else "OK_VISIBLE"
                )
            )
        ),
    }

    log.info("=== SUMÁRIO ===")
    for k, v in result.summary.items():
        log.info("  %-40s %s", k, v)

    return result


def _save(result: VerificationResult) -> Path:
    out = _TMP / f"verificacao_conv_marcos_{_TS}.json"
    out.write_text(json.dumps(asdict(result), ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Resultado salvo em: %s", out)
    return out


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Verifica conversa de 14/11/2025 de Marcos.")
    p.add_argument("--user-id", type=int, default=88, help="user_id de Marcos (default: 88)")
    p.add_argument("--date", default="2025-11-14", help="Data alvo ISO (default: 2025-11-14)")
    p.add_argument(
        "--window-days",
        type=int,
        default=3,
        help="Dias de janela antes/depois da data (default: 3)",
    )
    p.add_argument(
        "--api-timeout", type=int, default=15, help="Timeout API em segundos (default: 15)"
    )
    return p.parse_args()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    args = _parse_args()
    try:
        res = run_verification(
            user_id=args.user_id,
            target_date=args.date,
            window_days=args.window_days,
            api_timeout=args.api_timeout,
        )
        out = _save(res)

        print("\n" + "=" * 70)
        print(f"VEREDICTO: {res.summary.get('verdict', 'N/A')}")
        print(f"SOURCE conversas encontradas : {res.summary['source_conversations_found']}")
        print(f"DEST encontradas (src_id)    : {res.summary['dest_conversations_found_by_trace']}")
        print(
            f"DEST encontradas (data)      : {res.summary['dest_conversations_found_by_date_range']}"
        )
        print(f"Gaps de migração             : {res.summary['migration_gaps']}")
        print(f"Visíveis via API DEST        : {res.summary['api_dest_visible']}")
        print(f"Invisíveis via API DEST      : {res.summary['api_dest_invisible']}")
        print(f"Resultado completo           : {out}")
        print("=" * 70)

        sys.exit(0)
    except KeyboardInterrupt:
        log.warning("Interrompido pelo usuário")
        sys.exit(1)
    except Exception:
        log.exception("Falha crítica inesperada")
        sys.exit(1)
