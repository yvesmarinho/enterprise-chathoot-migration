"""Diagnóstico de inbox_id=125 (SOURCE) — por que suas conversas não foram migradas.

Hipótese central
----------------
O ``ConversationsMigrator`` descarta silenciosamente toda conversa cujo
``inbox_id_origin not in migrated_inboxes``.  Se o ``InboxesMigrator``
**não registrou** inbox_id=125 em ``migration_state``, todas as conversas
desse inbox foram puladas — sem erro visível, apenas "skipped".

Este script verifica:
  1. Inbox 125 no SOURCE (nome, canal, account)
  2. migration_state para inboxes no DEST (inbox 125 foi registrado?)
  3. Se foi migrado → qual é o dest_inbox_id (id_origem + offset)?
  4. Se NÃO foi → qual foi o motivo provável (conflict? account orphan?)
  5. Todas as conversas de inbox 125 no SOURCE (total do gap)
  6. Conversas específicas: display_id 1093 e 1003 (relatadas pelo usuário)
  7. Inboxes do DEST com nome similar (possível migração com conflito)

Saída
-----
.tmp/diagnostico_inbox125_YYYYMMDD_HHMMSS.json
.tmp/diagnostico_inbox125_YYYYMMDD_HHMMSS.log

Exit codes
----------
0   Diagnóstico concluído
1   Falha crítica

Usage::

    python app/15_diagnostico_inbox125.py
    python app/15_diagnostico_inbox125.py --inbox-id 125
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from src.factory.connection_factory import ConnectionFactory  # noqa: E402

_SECRETS_PATH = _ROOT / ".secrets" / "generate_erd.json"
_TMP = _ROOT / ".tmp"
_TMP.mkdir(parents=True, exist_ok=True)
_TS = datetime.now().strftime("%Y%m%d_%H%M%S")  # noqa: DTZ005

_fmt = logging.Formatter(
    "%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
_sh = logging.StreamHandler(sys.stdout)
_sh.setLevel(logging.INFO)
_sh.setFormatter(_fmt)
_fh = logging.FileHandler(str(_TMP / f"diagnostico_inbox125_{_TS}.log"), encoding="utf-8")
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(_fmt)
logging.getLogger().setLevel(logging.DEBUG)
logging.getLogger().addHandler(_sh)
logging.getLogger().addHandler(_fh)

log = logging.getLogger("diagnostico_inbox125")


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class InboxInfo:
    inbox_id: int = 0
    name: str = ""
    channel_type: str = ""
    account_id: int = 0
    account_name: str = ""
    found: bool = False


@dataclass
class MigrationStateEntry:
    found: bool = False
    id_origem: int = 0
    id_destino: int | None = None
    status: str = ""
    migrated_at: str = ""


@dataclass
class ConversationSummary:
    conv_id: int = 0
    display_id: int = 0
    account_id: int = 0
    status: str = ""
    assignee_id: int | None = None
    created_at: str = ""
    message_count: int = 0


@dataclass
class DiagnosticoInbox125Result:
    src_inbox_id: int
    source_inbox: InboxInfo = field(default_factory=InboxInfo)
    migration_state_inbox: MigrationStateEntry = field(default_factory=MigrationStateEntry)
    dest_inbox_by_src_id: InboxInfo = field(default_factory=InboxInfo)
    dest_inboxes_by_name: list[dict[str, Any]] = field(default_factory=list)
    dest_offset_inboxes: int = 0
    dest_expected_inbox_id: int = 0
    dest_inbox_by_offset: InboxInfo = field(default_factory=InboxInfo)
    source_conversations_total: int = 0
    source_conversations_sample: list[ConversationSummary] = field(default_factory=list)
    specific_display_ids: dict[str, Any] = field(default_factory=dict)
    dest_conversations_from_inbox125: int = 0
    conclusion: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

_SQL_SOURCE_INBOX = text(
    """
    SELECT i.id, i.name, i.channel_type, i.account_id, a.name AS account_name
    FROM inboxes i
    LEFT JOIN accounts a ON a.id = i.account_id
    WHERE i.id = :inbox_id;
"""
)

_SQL_MIGRATION_STATE_INBOX = text(
    """
    SELECT id_origem, id_destino, status, migrated_at::text
    FROM migration_state
    WHERE tabela = 'inboxes' AND id_origem = :inbox_id;
"""
)

_SQL_DEST_INBOX_BY_ID = text(
    """
    SELECT i.id, i.name, i.channel_type, i.account_id, a.name AS account_name
    FROM inboxes i
    LEFT JOIN accounts a ON a.id = i.account_id
    WHERE i.id = :inbox_id;
"""
)

_SQL_DEST_INBOX_BY_NAME = text(
    """
    SELECT i.id, i.name, i.channel_type, i.account_id, a.name AS account_name
    FROM inboxes i
    LEFT JOIN accounts a ON a.id = i.account_id
    WHERE i.name ILIKE :name_pattern
    ORDER BY i.id;
"""
)

_SQL_DEST_MAX_INBOX_ID = text(
    """
    SELECT COALESCE(MAX(id), 0) AS max_inbox_id FROM inboxes;
"""
)

_SQL_SOURCE_CONVERSATIONS = text(
    """
    SELECT
        c.id, c.display_id, c.account_id, c.status,
        c.assignee_id, c.created_at::text,
        COUNT(m.id) AS message_count
    FROM conversations c
    LEFT JOIN messages m ON m.conversation_id = c.id
    WHERE c.inbox_id = :inbox_id
    GROUP BY c.id, c.display_id, c.account_id, c.status,
             c.assignee_id, c.created_at
    ORDER BY c.created_at DESC;
"""
)

_SQL_SOURCE_CONV_BY_DISPLAY_ID = text(
    """
    SELECT
        c.id, c.display_id, c.account_id, c.inbox_id,
        c.assignee_id, c.status, c.created_at::text,
        COUNT(m.id) AS message_count
    FROM conversations c
    LEFT JOIN messages m ON m.conversation_id = c.id
    WHERE c.display_id = :display_id
      AND c.account_id = :account_id
    GROUP BY c.id, c.display_id, c.account_id, c.inbox_id,
             c.assignee_id, c.status, c.created_at;
"""
)

_SQL_DEST_CONV_BY_SRC_ID = text(
    """
    SELECT id, display_id, account_id, inbox_id, assignee_id, created_at::text
    FROM conversations
    WHERE additional_attributes->>'src_id' = :src_id;
"""
)

_SQL_DEST_CONVERSATIONS_FROM_INBOX = text(
    """
    SELECT COUNT(*) AS total
    FROM conversations
    WHERE inbox_id = :inbox_id;
"""
)

_SQL_DEST_MIGRATION_STATE_CONV = text(
    """
    SELECT id_origem, id_destino, status, migrated_at::text
    FROM migration_state
    WHERE tabela = 'conversations' AND id_origem = :conv_id;
"""
)


# ---------------------------------------------------------------------------
# Lógica principal
# ---------------------------------------------------------------------------


def run_diagnostico(src_inbox_id: int) -> DiagnosticoInbox125Result:
    result = DiagnosticoInbox125Result(src_inbox_id=src_inbox_id)

    factory = ConnectionFactory(secrets_path=_SECRETS_PATH)
    src_engine = factory.create_source_engine()
    dst_engine = factory.create_dest_engine()

    # ── 1. Inbox no SOURCE ───────────────────────────────────────────────────
    log.info("=== 1. Inbox %d no SOURCE ===", src_inbox_id)
    with src_engine.connect() as conn:
        row = conn.execute(_SQL_SOURCE_INBOX, {"inbox_id": src_inbox_id}).mappings().first()
        if row:
            result.source_inbox = InboxInfo(
                inbox_id=row["id"],
                name=row["name"],
                channel_type=row["channel_type"],
                account_id=row["account_id"],
                account_name=row["account_name"] or "",
                found=True,
            )
            log.info(
                "SOURCE inbox %d: name='%s' channel=%s account=%d(%s)",
                src_inbox_id,
                row["name"],
                row["channel_type"],
                row["account_id"],
                row["account_name"],
            )
        else:
            log.warning("SOURCE: inbox %d NÃO encontrado", src_inbox_id)

    # ── 2. migration_state para inbox 125 no DEST ────────────────────────────
    log.info("=== 2. migration_state para inbox %d ===", src_inbox_id)
    with dst_engine.connect() as conn:
        row = (
            conn.execute(_SQL_MIGRATION_STATE_INBOX, {"inbox_id": src_inbox_id}).mappings().first()
        )
        if row:
            result.migration_state_inbox = MigrationStateEntry(
                found=True,
                id_origem=row["id_origem"],
                id_destino=row["id_destino"],
                status=row["status"],
                migrated_at=row["migrated_at"],
            )
            log.info(
                "migration_state inbox %d: id_destino=%s status=%s migrated_at=%s",
                src_inbox_id,
                row["id_destino"],
                row["status"],
                row["migrated_at"],
            )
        else:
            log.warning(
                "migration_state: inbox %d NÃO registrado — "
                "todas as conversas deste inbox foram SKIPPED pelo pipeline",
                src_inbox_id,
            )

    # ── 3. Offset de inboxes no DEST + inbox esperado ────────────────────────
    log.info("=== 3. Offset inboxes no DEST ===")
    with dst_engine.connect() as conn:
        # O offset é calculado antes da migração (MAX(id) da tabela DEST antes dos inserts)
        # Para entender o offset atual, verificamos o MAX(id) no migration_state
        offset_row = (
            conn.execute(
                text(
                    """
                SELECT COALESCE(MIN(id_destino - id_origem), 0) AS offset_val
                FROM migration_state
                WHERE tabela = 'inboxes' AND id_destino IS NOT NULL
                  AND status = 'ok'
                LIMIT 1;
            """
                )
            )
            .mappings()
            .first()
        )
        offset_val = offset_row["offset_val"] if offset_row and offset_row["offset_val"] else 0
        result.dest_offset_inboxes = int(offset_val)
        result.dest_expected_inbox_id = src_inbox_id + result.dest_offset_inboxes
        log.info(
            "Offset inboxes (calculado): %d → inbox %d esperado como %d no DEST",
            result.dest_offset_inboxes,
            src_inbox_id,
            result.dest_expected_inbox_id,
        )

        # Verifica se o ID esperado existe no DEST
        row_by_offset = (
            conn.execute(_SQL_DEST_INBOX_BY_ID, {"inbox_id": result.dest_expected_inbox_id})
            .mappings()
            .first()
        )
        if row_by_offset:
            result.dest_inbox_by_offset = InboxInfo(
                inbox_id=row_by_offset["id"],
                name=row_by_offset["name"],
                channel_type=row_by_offset["channel_type"],
                account_id=row_by_offset["account_id"],
                account_name=row_by_offset["account_name"] or "",
                found=True,
            )
            log.info(
                "DEST inbox_id=%d: name='%s' channel=%s account=%d",
                result.dest_expected_inbox_id,
                row_by_offset["name"],
                row_by_offset["channel_type"],
                row_by_offset["account_id"],
            )
        else:
            log.warning(
                "DEST: inbox_id=%d (id esperado pelo offset) NÃO existe",
                result.dest_expected_inbox_id,
            )

    # ── 4. Busca no DEST por nome similar ────────────────────────────────────
    log.info("=== 4. Inboxes no DEST com nome similar ===")
    if result.source_inbox.found:
        src_name = result.source_inbox.name
        with dst_engine.connect() as conn:
            rows = (
                conn.execute(
                    _SQL_DEST_INBOX_BY_NAME,
                    {"name_pattern": f"%{src_name[:20]}%"},
                )
                .mappings()
                .all()
            )
            result.dest_inboxes_by_name = [dict(r) for r in rows]
            if result.dest_inboxes_by_name:
                log.info("Inboxes no DEST com nome similar a '%s':", src_name)
                for r in result.dest_inboxes_by_name:
                    log.info(
                        "  id=%d name='%s' channel=%s account=%d",
                        r["id"],
                        r["name"],
                        r["channel_type"],
                        r["account_id"],
                    )
            else:
                log.warning("Nenhum inbox no DEST com nome similar a '%s'", src_name)

    # ── 5. Todas as conversas de inbox 125 no SOURCE ─────────────────────────
    log.info("=== 5. Conversas de inbox %d no SOURCE ===", src_inbox_id)
    with src_engine.connect() as conn:
        rows = conn.execute(_SQL_SOURCE_CONVERSATIONS, {"inbox_id": src_inbox_id}).mappings().all()
        result.source_conversations_total = len(rows)
        result.source_conversations_sample = [
            ConversationSummary(
                conv_id=r["id"],
                display_id=r["display_id"],
                account_id=r["account_id"],
                status=r["status"],
                assignee_id=r["assignee_id"],
                created_at=r["created_at"],
                message_count=int(r["message_count"]),
            )
            for r in rows
        ]
        log.info(
            "SOURCE: %d conversas no inbox %d",
            result.source_conversations_total,
            src_inbox_id,
        )
        for conv in result.source_conversations_sample[:10]:
            log.info(
                "  conv_id=%d display_id=%d status=%s created=%s msgs=%d",
                conv.conv_id,
                conv.display_id,
                conv.status,
                conv.created_at[:10],
                conv.message_count,
            )
        if result.source_conversations_total > 10:
            log.info(
                "  ... e mais %d conversas (exibindo top 10 mais recentes)",
                result.source_conversations_total - 10,
            )

    # ── 6. Conversas específicas (display_id 1093 e 1003) ────────────────────
    log.info("=== 6. Conversas específicas (display_id 1093 e 1003 em account_id=1) ===")
    specific = {}
    # NOTE: display_ids are per-account sequential — MUST filter by account_id=1
    src_account_id = result.source_inbox.account_id if result.source_inbox.found else 1
    for did in [1093, 1003]:
        entry: dict[str, Any] = {"display_id": did}
        with src_engine.connect() as conn:
            row = (
                conn.execute(
                    _SQL_SOURCE_CONV_BY_DISPLAY_ID,
                    {"display_id": did, "account_id": src_account_id},
                )
                .mappings()
                .first()
            )
            if row:
                entry["source"] = {
                    "conv_id": row["id"],
                    "display_id": row["display_id"],
                    "account_id": row["account_id"],
                    "inbox_id": row["inbox_id"],
                    "assignee_id": row["assignee_id"],
                    "status": row["status"],
                    "created_at": row["created_at"],
                    "message_count": int(row["message_count"]),
                }
                log.info(
                    "SOURCE display_id=%d → conv_id=%d inbox=%d account=%d created=%s msgs=%d",
                    did,
                    row["id"],
                    row["inbox_id"],
                    row["account_id"],
                    row["created_at"][:10],
                    row["message_count"],
                )
            else:
                entry["source"] = None
                log.warning("SOURCE: display_id=%d NÃO encontrado", did)

        if entry.get("source"):
            src_conv_id = entry["source"]["conv_id"]
            with dst_engine.connect() as conn:
                # Verifica por src_id no DEST
                row = (
                    conn.execute(_SQL_DEST_CONV_BY_SRC_ID, {"src_id": str(src_conv_id)})
                    .mappings()
                    .first()
                )
                if row:
                    entry["dest_by_src_id"] = dict(row)
                    log.info(
                        "DEST: display_id=%d ENCONTRADA via src_id=%d → dest_conv_id=%d",
                        did,
                        src_conv_id,
                        row["id"],
                    )
                else:
                    entry["dest_by_src_id"] = None
                    log.warning(
                        "DEST: display_id=%d NÃO encontrada (src_id=%d sem match)", did, src_conv_id
                    )

                # Verifica migration_state para a conversa
                ms_row = (
                    conn.execute(_SQL_DEST_MIGRATION_STATE_CONV, {"conv_id": src_conv_id})
                    .mappings()
                    .first()
                )
                if ms_row:
                    entry["migration_state_conv"] = dict(ms_row)
                    log.info(
                        "migration_state conv %d: id_destino=%s status=%s",
                        src_conv_id,
                        ms_row["id_destino"],
                        ms_row["status"],
                    )
                else:
                    entry["migration_state_conv"] = None
                    log.warning(
                        "migration_state: conv %d NÃO registrada → confirma que foi skipped",
                        src_conv_id,
                    )

        specific[str(did)] = entry

    result.specific_display_ids = specific

    # ── 7. Contagem de conversas do DEST com inbox_id esperado ───────────────
    if result.dest_expected_inbox_id > 0:
        log.info("=== 7. Conversas no DEST com inbox_id=%d ===", result.dest_expected_inbox_id)
        with dst_engine.connect() as conn:
            row = (
                conn.execute(
                    _SQL_DEST_CONVERSATIONS_FROM_INBOX,
                    {"inbox_id": result.dest_expected_inbox_id},
                )
                .mappings()
                .first()
            )
            result.dest_conversations_from_inbox125 = int(row["total"]) if row else 0
            log.info(
                "DEST: %d conversas com inbox_id=%d",
                result.dest_conversations_from_inbox125,
                result.dest_expected_inbox_id,
            )

    # ── 8. Conclusão ─────────────────────────────────────────────────────────
    log.info("=== 8. Conclusão ===")
    ms = result.migration_state_inbox
    if not ms.found:
        cause = "inbox_not_in_migration_state"
        if result.dest_inbox_by_offset.found:
            detail = (
                f"inbox_id={result.dest_expected_inbox_id} existe no DEST mas não está "
                f"em migration_state — possível conflito ON_CONFLICT_DO_NOTHING durante upsert"
            )
        else:
            detail = (
                f"inbox_id={result.dest_expected_inbox_id} NÃO existe no DEST e não está "
                f"em migration_state — inbox foi skipped (account orphan ou outro filtro)"
            )
    elif ms.status != "ok":
        cause = f"inbox_migration_failed_status={ms.status}"
        detail = f"inbox registrado mas com status={ms.status}"
    else:
        cause = "inbox_migrated_ok_but_conversations_not_found"
        detail = (
            f"inbox foi migrado (id_destino={ms.id_destino}) mas conversas ainda ausentes — "
            f"verificar se ConversationsMigrator usou o mesmo id_origem como referência"
        )

    result.conclusion = {
        "cause": cause,
        "detail": detail,
        "total_gap_conversations": result.source_conversations_total,
        "specific_gaps": ", ".join(
            f"display_id={k}"
            for k, v in result.specific_display_ids.items()
            if v.get("dest_by_src_id") is None
        ),
        "corrective_action": (
            "Executar app/16_migrar_conv_gaps.py para migrar todas as "
            f"{result.source_conversations_total} conversas do inbox {src_inbox_id} "
            "que foram skipped"
        ),
    }

    log.info("CAUSA: %s", result.conclusion["cause"])
    log.info("DETALHE: %s", result.conclusion["detail"])
    log.info(
        "GAP TOTAL: %d conversas do inbox %d NÃO migradas",
        result.source_conversations_total,
        src_inbox_id,
    )

    return result


def _save(result: DiagnosticoInbox125Result) -> Path:
    out = _TMP / f"diagnostico_inbox125_{_TS}.json"
    out.write_text(json.dumps(asdict(result), ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Resultado salvo em: %s", out)
    return out


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Diagnóstico de inbox_id=125 (SOURCE) — gap de migração"
    )
    p.add_argument(
        "--inbox-id", type=int, default=125, help="SOURCE inbox_id a diagnosticar (default: 125)"
    )
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    try:
        res = run_diagnostico(args.inbox_id)
        out = _save(res)
        print("\n" + "=" * 70)
        print(f"CAUSA: {res.conclusion.get('cause', 'N/A')}")
        print(f"DETALHE: {res.conclusion.get('detail', '')}")
        print(f"GAP TOTAL (conversas não migradas): {res.source_conversations_total}")
        print(f"Gaps específicos: {res.conclusion.get('specific_gaps', '')}")
        print(f"Resultado completo: {out}")
        print("=" * 70)
        sys.exit(0)
    except KeyboardInterrupt:
        sys.exit(1)
    except Exception:
        log.exception("Falha crítica inesperada")
        sys.exit(1)
