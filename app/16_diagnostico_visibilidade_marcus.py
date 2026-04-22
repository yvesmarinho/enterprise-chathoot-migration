"""Diagnóstico de visibilidade — por que Marcus não consegue ver as conversas migradas.

Contexto
--------
A análise anterior (15_diagnostico_inbox125.py) confirmou:
- inbox_id=125 (SOURCE) foi migrado → id_destino=521 (status=ok)
- DEST inbox_id=521 tem 3 conversas (mesmo número que SOURCE inbox_id=125)
- MAS: app/14 reportou "MIGRATION_GAP" porque buscava src_id em
  additional_attributes — e o ConversationsMigrator NÃO escreve esse campo.

Portanto: as conversas PODEM estar no DEST. O problema é outro — visibilidade.

Este script investiga:
  1. migration_state para conv_ids 62361, 62362, 62363 (SOURCE inbox_id=125)
  2. Conversas no DEST inbox_id=521 — display_id, assignee_id, created_at
  3. Role de Marcus (user_id=88) em DEST: admin ou agent?
  4. inbox_members de Marcus no DEST (quais inboxes ele acessa)
  5. Cruzamento: assignee_id nas conversas migradas = user_id de Marcus no DEST?
  6. Se não visível por role/inbox: qual ação corretiva mínima?

Saída
-----
.tmp/diagnostico_visibilidade_marcus_YYYYMMDD_HHMMSS.json
.tmp/diagnostico_visibilidade_marcus_YYYYMMDD_HHMMSS.log

Usage::

    python app/16_diagnostico_visibilidade_marcus.py
    python app/16_diagnostico_visibilidade_marcus.py \\
        --source-conv-ids 62361,62362,62363 \\
        --dest-inbox-id 521 \\
        --dest-user-id 88
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
_fh = logging.FileHandler(
    str(_TMP / f"diagnostico_visibilidade_marcus_{_TS}.log"), encoding="utf-8"
)
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(_fmt)
logging.getLogger().setLevel(logging.DEBUG)
logging.getLogger().addHandler(_sh)
logging.getLogger().addHandler(_fh)

log = logging.getLogger("diagnostico_visibilidade")


@dataclass
class Result:
    source_conv_ids: list[int] = field(default_factory=list)
    dest_inbox_id: int = 521
    dest_user_id: int = 88

    # 1. migration_state para as 3 conversas
    migration_state_convs: list[dict[str, Any]] = field(default_factory=list)
    convs_migrated: bool = False

    # 2. Conversas no DEST inbox_id=521
    dest_convs_inbox521: list[dict[str, Any]] = field(default_factory=list)

    # 3. Role de Marcus no DEST
    dest_marcus_role: str = "unknown"
    dest_marcus_account_users: list[dict[str, Any]] = field(default_factory=list)

    # 4. inbox_members de Marcus no DEST
    dest_marcus_inbox_members: list[dict[str, Any]] = field(default_factory=list)
    dest_marcus_inbox_ids: list[int] = field(default_factory=list)

    # 5. Cruzamento assignee_id
    migrated_convs_assignee_ids: list[int | None] = field(default_factory=list)
    marcus_is_assignee: bool = False

    # 6. Diagnóstico final
    root_cause: str = ""
    corrective_action: str = ""
    corrective_sql: str = ""


def run(
    source_conv_ids: list[int],
    dest_inbox_id: int,
    dest_user_id: int,
) -> Result:
    r = Result(
        source_conv_ids=source_conv_ids,
        dest_inbox_id=dest_inbox_id,
        dest_user_id=dest_user_id,
    )

    factory = ConnectionFactory(secrets_path=_SECRETS_PATH)
    src_engine = factory.create_source_engine()
    dst_engine = factory.create_dest_engine()

    # ── 1. migration_state para os conv_ids SOURCE ───────────────────────────
    log.info("=== 1. migration_state para conv_ids %s ===", source_conv_ids)
    with dst_engine.connect() as conn:
        ids_placeholder = ", ".join(str(i) for i in source_conv_ids)
        rows = (
            conn.execute(
                text(
                    f"""
                SELECT id_origem, id_destino, status, migrated_at::text
                FROM migration_state
                WHERE tabela='conversations' AND id_origem IN ({ids_placeholder})
                ORDER BY id_origem;
            """
                )  # noqa: S608
            )
            .mappings()
            .all()
        )
        r.migration_state_convs = [dict(row) for row in rows]
        if r.migration_state_convs:
            r.convs_migrated = all(row["status"] == "ok" for row in r.migration_state_convs)
            log.info("Encontradas %d entradas em migration_state:", len(r.migration_state_convs))
            for ms in r.migration_state_convs:
                log.info(
                    "  id_origem=%d → id_destino=%s status=%s",
                    ms["id_origem"],
                    ms["id_destino"],
                    ms["status"],
                )
            if r.convs_migrated:
                log.info("✅ Todas as conversas foram MIGRADAS com status=ok")
            else:
                log.warning("⚠️ Algumas conversas com status != ok")
        else:
            log.warning(
                "❌ Nenhuma entrada em migration_state para conv_ids %s — "
                "CONFIRMED MIGRATION GAP: conversas não foram migradas",
                source_conv_ids,
            )

    # ── 2. Conversas no DEST inbox_id=521 ────────────────────────────────────
    log.info("=== 2. Conversas no DEST inbox_id=%d ===", dest_inbox_id)
    with dst_engine.connect() as conn:
        rows = (
            conn.execute(
                text(
                    """
                SELECT id, display_id, account_id, inbox_id,
                       assignee_id, status, created_at::text
                FROM conversations
                WHERE inbox_id = :inbox_id
                ORDER BY created_at;
            """
                ),
                {"inbox_id": dest_inbox_id},
            )
            .mappings()
            .all()
        )
        r.dest_convs_inbox521 = [dict(row) for row in rows]
        if r.dest_convs_inbox521:
            log.info("DEST inbox_id=%d: %d conversas:", dest_inbox_id, len(r.dest_convs_inbox521))
            for cv in r.dest_convs_inbox521:
                log.info(
                    "  dest_conv_id=%d display_id=%d assignee_id=%s status=%s created=%s",
                    cv["id"],
                    cv["display_id"],
                    cv.get("assignee_id"),
                    cv.get("status"),
                    cv["created_at"][:10],
                )
        else:
            log.warning("DEST: nenhuma conversa em inbox_id=%d", dest_inbox_id)

    # ── 3. Role de Marcus (user_id=88) no DEST ───────────────────────────────
    log.info("=== 3. Role de Marcus (user_id=%d) no DEST ===", dest_user_id)
    with dst_engine.connect() as conn:
        rows = (
            conn.execute(
                text(
                    """
                SELECT au.user_id, au.account_id, au.role,
                       a.name AS account_name
                FROM account_users au
                LEFT JOIN accounts a ON a.id = au.account_id
                WHERE au.user_id = :user_id
                ORDER BY au.account_id;
            """
                ),
                {"user_id": dest_user_id},
            )
            .mappings()
            .all()
        )
        r.dest_marcus_account_users = [dict(row) for row in rows]
        for au in r.dest_marcus_account_users:
            # Chatwoot stores role as integer: 0=agent, 1=administrator
            role_val = au["role"]
            role_str = (
                "administrator"
                if int(role_val) == 1
                else "agent" if int(role_val) == 0 else str(role_val)
            )
            log.info(
                "  account_id=%d(%s): role=%s (%s)",
                au["account_id"],
                au.get("account_name", "?"),
                role_val,
                role_str,
            )
            if au["account_id"] == 1:
                r.dest_marcus_role = role_str

    if r.dest_marcus_role == "unknown":
        log.warning("Marcus NÃO encontrado em account_users para account_id=1 no DEST")
    else:
        log.info("Marcus role em account_id=1: %s", r.dest_marcus_role)

    # ── 4. inbox_members de Marcus no DEST ───────────────────────────────────
    log.info("=== 4. inbox_members de Marcus no DEST ===")
    with dst_engine.connect() as conn:
        rows = (
            conn.execute(
                text(
                    """
                SELECT im.inbox_id, i.name AS inbox_name, i.channel_type
                FROM inbox_members im
                LEFT JOIN inboxes i ON i.id = im.inbox_id
                WHERE im.user_id = :user_id
                ORDER BY im.inbox_id;
            """
                ),
                {"user_id": dest_user_id},
            )
            .mappings()
            .all()
        )
        r.dest_marcus_inbox_members = [dict(row) for row in rows]
        r.dest_marcus_inbox_ids = [int(m["inbox_id"]) for m in r.dest_marcus_inbox_members]
        if r.dest_marcus_inbox_members:
            log.info("Marcus é membro de %d inboxes no DEST:", len(r.dest_marcus_inbox_members))
            for m in r.dest_marcus_inbox_members:
                log.info(
                    "  inbox_id=%d name='%s' channel=%s",
                    m["inbox_id"],
                    m.get("inbox_name", "?"),
                    m.get("channel_type", "?"),
                )
        else:
            log.info("Marcus NÃO tem entradas em inbox_members no DEST")

    # ── 5. Cruzamento: Marcus é assignee nas conversas migradas? ────────────
    log.info("=== 5. Assignee das conversas migradas vs Marcus ===")
    r.migrated_convs_assignee_ids = [cv.get("assignee_id") for cv in r.dest_convs_inbox521]
    r.marcus_is_assignee = dest_user_id in [
        a for a in r.migrated_convs_assignee_ids if a is not None
    ]
    log.info(
        "Assignees nas conversas DEST inbox %d: %s",
        dest_inbox_id,
        r.migrated_convs_assignee_ids,
    )
    log.info("Marcus (user_id=%d) é assignee em alguma? %s", dest_user_id, r.marcus_is_assignee)

    # ── 6. Diagnóstico final ─────────────────────────────────────────────────
    log.info("=== 6. Diagnóstico final ===")

    if not r.migration_state_convs:
        r.root_cause = "CONFIRMED_MIGRATION_GAP: conversas não registradas em migration_state"
        r.corrective_action = (
            "Criar script de re-migração específico para conv_ids "
            + ", ".join(str(i) for i in source_conv_ids)
            + " usando ConversationsMigrator ou inserção direta"
        )
    elif not r.convs_migrated:
        r.root_cause = "MIGRATION_FAILED: conversas em migration_state mas status != ok"
        r.corrective_action = "Re-executar migração para essas conversas"
    elif not r.dest_convs_inbox521:
        r.root_cause = "CONVERSATIONS_MISSING_FROM_INBOX: migration_state ok mas inbox vazio"
        r.corrective_action = "Investigar integridade: possível deleção pós-migração"
    elif r.dest_marcus_role == "administrator":
        if not r.marcus_is_assignee:
            r.root_cause = (
                "ADMIN_BUT_NOT_ASSIGNEE: Marcus é admin, vê tudo, mas convs não têm assignee=Marcus"
            )
            r.corrective_action = (
                f"Reatribuir conversas em inbox_id={dest_inbox_id} para Marcus (user_id={dest_user_id}) via API ou SQL. "
                "Verificar também se o display_id resequenciado aparece corretamente na UI."
            )
            dest_conv_ids = [cv["id"] for cv in r.dest_convs_inbox521]
            r.corrective_sql = (
                f"UPDATE conversations SET assignee_id = {dest_user_id} "
                f"WHERE id IN ({', '.join(str(i) for i in dest_conv_ids)}) "
                f"AND account_id = 1;"
            )
        else:
            r.root_cause = (
                "ADMIN_AND_ASSIGNEE: Marcus deveria ver as conversas — verificar UI/filtro"
            )
            r.corrective_action = "Verificar se Marcus está filtrando por inbox ou período na UI"
    elif r.dest_marcus_role == "agent":
        if dest_inbox_id not in r.dest_marcus_inbox_ids:
            r.root_cause = (
                f"AGENT_NOT_MEMBER_OF_INBOX_{dest_inbox_id}: Marcus é agent e não é "
                f"membro do inbox migrado {dest_inbox_id}"
            )
            r.corrective_action = (
                f"Adicionar Marcus (user_id={dest_user_id}) como membro do "
                f"inbox_id={dest_inbox_id} via API ou SQL:  "
                f"INSERT INTO inbox_members(user_id, inbox_id) VALUES "
                f"({dest_user_id}, {dest_inbox_id}) ON CONFLICT DO NOTHING;"
            )
            r.corrective_sql = (
                f"INSERT INTO inbox_members(user_id, inbox_id) "
                f"VALUES ({dest_user_id}, {dest_inbox_id}) "
                f"ON CONFLICT DO NOTHING;"
            )
        elif not r.marcus_is_assignee:
            r.root_cause = f"AGENT_MEMBER_BUT_NOT_ASSIGNEE: Marcus é membro de inbox {dest_inbox_id} mas não é assignee"
            r.corrective_action = "Reatribuir conversas para Marcus via Chatwoot API ou UPDATE SQL"
        else:
            r.root_cause = (
                "AGENT_MEMBER_AND_ASSIGNEE: Marcus deveria ver as conversas — verificar UI"
            )
            r.corrective_action = "Verificar configurações de UI e filtros ativos"
    else:
        r.root_cause = "UNKNOWN_ROLE: Marcus não encontrado em account_users para account_id=1"
        r.corrective_action = "Verificar se Marcus está no account_id correto no DEST"

    log.info("ROOT CAUSE: %s", r.root_cause)
    log.info("CORRECTIVE ACTION: %s", r.corrective_action)
    if r.corrective_sql:
        log.info("CORRECTIVE SQL: %s", r.corrective_sql)

    return r


def _save(r: Result) -> Path:
    out = _TMP / f"diagnostico_visibilidade_marcus_{_TS}.json"
    out.write_text(json.dumps(asdict(r), ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Resultado salvo em: %s", out)
    return out


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Diagnóstico de visibilidade: por que Marcus não vê as conversas migradas"
    )
    p.add_argument(
        "--source-conv-ids",
        default="62361,62362,62363",
        help="SOURCE conv_ids das conversas de inbox 125 (default: 62361,62362,62363)",
    )
    p.add_argument("--dest-inbox-id", type=int, default=521)
    p.add_argument("--dest-user-id", type=int, default=88)
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    conv_ids = [int(x.strip()) for x in args.source_conv_ids.split(",")]
    try:
        r = run(
            source_conv_ids=conv_ids,
            dest_inbox_id=args.dest_inbox_id,
            dest_user_id=args.dest_user_id,
        )
        out = _save(r)
        print("\n" + "=" * 70)
        print(
            f"CONVS MIGRADAS: {r.convs_migrated} ({len(r.migration_state_convs)}/{len(conv_ids)} em migration_state)"
        )
        print(f"DEST inbox_id={r.dest_inbox_id}: {len(r.dest_convs_inbox521)} conversas")
        print(f"MARCUS ROLE (DEST): {r.dest_marcus_role}")
        print(f"MARCUS INBOX MEMBERSHIPS: {r.dest_marcus_inbox_ids}")
        print(f"MARCUS É ASSIGNEE: {r.marcus_is_assignee}")
        print(f"ROOT CAUSE: {r.root_cause}")
        print(f"CORRECTIVE ACTION: {r.corrective_action}")
        if r.corrective_sql:
            print(f"CORRECTIVE SQL: {r.corrective_sql}")
        print(f"Resultado completo: {out}")
        print("=" * 70)
        sys.exit(0)
    except KeyboardInterrupt:
        sys.exit(1)
    except Exception:
        log.exception("Falha crítica")
        sys.exit(1)
