"""Diagnóstico focado em marcos.andrade@vya.digital — visibilidade pós-migração.

Camadas diagnosticadas
----------------------
1. user        — existe no SOURCE e no DEST? migration_state correto?
2. conversations — quantas, assignee_id remapeado corretamente?
3. messages    — órfãos por conversation_id ou account_id?
4. inbox_members — marcus membro dos inboxes corretos no SOURCE e no DEST?
5. API         — testa synchat.vya.digital E vya-chat-dev.vya.digital

Saída
-----
.tmp/diagnostico_marcos_YYYYMMDD_HHMMSS.json   — diagnóstico estruturado completo
.tmp/diagnostico_marcos_YYYYMMDD_HHMMSS.log    — log DEBUG completo (sem credenciais)

Exit codes
----------
0   Diagnóstico concluído (pode haver problemas encontrados)
1   Falha crítica (credenciais, DB inacessível)

Usage::

    python app/12_diagnostico_marcos.py
    python app/12_diagnostico_marcos.py --email outro.user@vya.digital
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

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

_fmt = logging.Formatter(
    "%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
_sh = logging.StreamHandler(sys.stdout)
_sh.setLevel(logging.INFO)
_sh.setFormatter(_fmt)
_fh = logging.FileHandler(str(_TMP / f"diagnostico_marcos_{_TS}.log"), encoding="utf-8")
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(_fmt)
logging.getLogger().setLevel(logging.DEBUG)
logging.getLogger().addHandler(_sh)
logging.getLogger().addHandler(_fh)

log = logging.getLogger("diagnostico_marcos")

# ---------------------------------------------------------------------------
# Dataclasses de resultado
# ---------------------------------------------------------------------------


@dataclass
class UserInfo:
    found: bool = False
    user_id: int | None = None
    email: str | None = None
    name: str | None = None
    role: str | None = None
    availability_status: str | None = None
    confirmed: bool | None = None
    account_users: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class MigrationStateInfo:
    found: bool = False
    tabela: str = ""
    id_origem: int | None = None
    id_destino: int | None = None
    status: str | None = None
    migrated_at: str | None = None


@dataclass
class ConversationStats:
    total_in_dest: int = 0
    with_assignee: int = 0
    without_assignee: int = 0
    per_inbox: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class MessageStats:
    total_in_dest: int = 0
    as_sender: int = 0
    in_marcus_conversations: int = 0


@dataclass
class InboxMemberInfo:
    source_inboxes: list[dict[str, Any]] = field(default_factory=list)
    dest_inboxes: list[dict[str, Any]] = field(default_factory=list)
    missing_in_dest: list[dict[str, Any]] = field(default_factory=list)
    extra_in_dest: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ApiProbeResult:
    host: str = ""
    reachable: bool = False
    http_status: int = 0
    error: str = ""
    user_found_in_api: bool = False
    api_user_id: int | None = None
    api_user_role: str | None = None


@dataclass
class DiagnosticoResult:
    email_diagnosticado: str
    timestamp: str
    source_user: UserInfo = field(default_factory=UserInfo)
    dest_user: UserInfo = field(default_factory=UserInfo)
    migration_state: MigrationStateInfo = field(default_factory=MigrationStateInfo)
    alias_correct: bool | None = None
    conversations_dest: ConversationStats = field(default_factory=ConversationStats)
    messages_dest: MessageStats = field(default_factory=MessageStats)
    inbox_members: InboxMemberInfo = field(default_factory=InboxMemberInfo)
    api_probes: list[ApiProbeResult] = field(default_factory=list)
    summary: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers de banco
# ---------------------------------------------------------------------------


def _fetch_user(conn: Connection, email: str) -> UserInfo:
    # Chatwoot users table: role está em account_users, não em users
    # availability_status em users é 'availability'; confirmed via confirmed_at
    row = (
        conn.execute(
            text(
                "SELECT id, email, name, availability, "
                "(confirmed_at IS NOT NULL) AS confirmed "
                "FROM users WHERE email ILIKE :email LIMIT 1"
            ),
            {"email": email},
        )
        .mappings()
        .first()
    )

    if row is None:
        return UserInfo(found=False)

    au_rows = (
        conn.execute(
            text("SELECT account_id, role " "FROM account_users WHERE user_id = :uid"),
            {"uid": row["id"]},
        )
        .mappings()
        .all()
    )

    # role primário = da primeira account_users (conta mais relevante)
    first_role = str(au_rows[0]["role"]) if au_rows else None

    return UserInfo(
        found=True,
        user_id=int(row["id"]),
        email=str(row["email"]),
        name=str(row["name"]),
        role=first_role,
        availability_status=str(row["availability"]) if row["availability"] else None,
        confirmed=bool(row["confirmed"]),
        account_users=[dict(r) for r in au_rows],
    )


def _fetch_migration_state(conn: Connection, src_user_id: int) -> MigrationStateInfo:
    row = (
        conn.execute(
            text(
                "SELECT tabela, id_origem, id_destino, status, "
                "to_char(migrated_at, 'YYYY-MM-DD HH24:MI:SS') AS migrated_at "
                "FROM migration_state "
                "WHERE tabela = 'users' AND id_origem = :uid LIMIT 1"
            ),
            {"uid": src_user_id},
        )
        .mappings()
        .first()
    )

    if row is None:
        return MigrationStateInfo(found=False)

    return MigrationStateInfo(
        found=True,
        tabela=str(row["tabela"]),
        id_origem=int(row["id_origem"]),
        id_destino=int(row["id_destino"]) if row["id_destino"] is not None else None,
        status=str(row["status"]),
        migrated_at=str(row["migrated_at"]),
    )


def _fetch_conversation_stats(conn: Connection, dest_user_id: int) -> ConversationStats:
    # Conversations onde marcus é assignee
    assigned = (
        conn.execute(
            text("SELECT COUNT(*) AS n FROM conversations WHERE assignee_id = :uid"),
            {"uid": dest_user_id},
        ).scalar()
        or 0
    )

    # Conversations em inboxes que marcus é membro (via inbox_members)
    accessible = (
        conn.execute(
            text(
                "SELECT COUNT(DISTINCT c.id) FROM conversations c "
                "JOIN inbox_members im ON im.inbox_id = c.inbox_id "
                "WHERE im.user_id = :uid"
            ),
            {"uid": dest_user_id},
        ).scalar()
        or 0
    )

    per_inbox = (
        conn.execute(
            text(
                "SELECT i.id AS inbox_id, i.name AS inbox_name, "
                "COUNT(c.id) AS conversation_count "
                "FROM inbox_members im "
                "JOIN inboxes i ON i.id = im.inbox_id "
                "LEFT JOIN conversations c ON c.inbox_id = i.id "
                "WHERE im.user_id = :uid "
                "GROUP BY i.id, i.name ORDER BY conversation_count DESC"
            ),
            {"uid": dest_user_id},
        )
        .mappings()
        .all()
    )

    return ConversationStats(
        total_in_dest=int(accessible),
        with_assignee=int(assigned),
        without_assignee=int(accessible) - int(assigned),
        per_inbox=[dict(r) for r in per_inbox],
    )


def _fetch_message_stats(conn: Connection, dest_user_id: int) -> MessageStats:
    as_sender = (
        conn.execute(
            text("SELECT COUNT(*) FROM messages WHERE sender_id = :uid"),
            {"uid": dest_user_id},
        ).scalar()
        or 0
    )

    in_convs = (
        conn.execute(
            text(
                "SELECT COUNT(*) FROM messages "
                "WHERE conversation_id IN ("
                "  SELECT id FROM conversations WHERE assignee_id = :uid"
                ")"
            ),
            {"uid": dest_user_id},
        ).scalar()
        or 0
    )

    total = (
        conn.execute(
            text(
                "SELECT COUNT(*) FROM messages WHERE sender_id = :uid OR account_id IN ("
                "  SELECT account_id FROM account_users WHERE user_id = :uid"
                ")"
            ),
            {"uid": dest_user_id},
        ).scalar()
        or 0
    )

    return MessageStats(
        total_in_dest=int(total),
        as_sender=int(as_sender),
        in_marcus_conversations=int(in_convs),
    )


def _fetch_inbox_members(conn: Connection, user_id: int) -> list[dict[str, Any]]:
    rows = (
        conn.execute(
            text(
                "SELECT im.inbox_id, i.name AS inbox_name, i.channel_type "
                "FROM inbox_members im "
                "JOIN inboxes i ON i.id = im.inbox_id "
                "WHERE im.user_id = :uid "
                "ORDER BY im.inbox_id"
            ),
            {"uid": user_id},
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# API probe
# ---------------------------------------------------------------------------


def _probe_api_host(host: str, api_key: str, email: str, timeout: int = 10) -> ApiProbeResult:
    base_url = f"https://{host}"
    result = ApiProbeResult(host=host, reachable=False)

    profile_url = f"{base_url}/api/v1/profile"
    req = urllib.request.Request(profile_url, headers={"api_access_token": api_key})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result.http_status = resp.status
            if resp.status == 200:
                result.reachable = True
                log.info("API probe OK — https://%s", host)
    except urllib.error.HTTPError as exc:
        result.http_status = exc.code
        result.error = f"HTTP {exc.code}"
        log.warning("API probe falhou — https://%s HTTP %d", host, exc.code)
        return result
    except urllib.error.URLError as exc:
        result.error = str(exc.reason)
        log.warning("API probe falhou — https://%s: %s", host, exc.reason)
        return result

    if not result.reachable:
        return result

    # Tentar encontrar o user pelo email via search API
    search_url = f"{base_url}/api/v1/profile"
    try:
        req2 = urllib.request.Request(search_url, headers={"api_access_token": api_key})
        with urllib.request.urlopen(req2, timeout=timeout) as resp:
            profile = json.loads(resp.read().decode())
            if str(profile.get("email", "")).lower() == email.lower():
                result.user_found_in_api = True
                result.api_user_id = profile.get("id")
                result.api_user_role = profile.get("role")
                log.info("API user match — id=%s role=%s", result.api_user_id, result.api_user_role)
    except Exception as exc:  # noqa: BLE001
        log.debug("API user search falhou em https://%s: %s", host, exc)

    return result


# ---------------------------------------------------------------------------
# Lógica principal
# ---------------------------------------------------------------------------


def _load_api_configs() -> list[tuple[str, str]]:
    """Carrega configurações de API do arquivo de segredos.

    Retorna lista de (host, api_key) para cada entrada "synchat", "chatwoot",
    "vya_chat_dev" etc. que tenha os campos necessários.
    """
    if not _SECRETS_PATH.exists():
        log.warning("Secrets file não encontrado: %s", _SECRETS_PATH)
        return []

    data: dict[str, Any] = json.loads(_SECRETS_PATH.read_text())
    configs: list[tuple[str, str]] = []
    api_section_keys = ("synchat", "vya_chat_dev", "vya-chat-dev", "chatwoot", "api")

    for key in api_section_keys:
        if key in data and isinstance(data[key], dict):
            entry = data[key]
            host = entry.get("host", "")
            api_key = entry.get("api_key", "")
            if host and api_key:
                configs.append((host, api_key))
                log.debug("API config carregada para chave '%s' host=%s", key, host)

    # Adicionar vya-chat-dev como candidato extra se não estiver na lista
    known_hosts = {h for h, _ in configs}
    extra_candidates = ["vya-chat-dev.vya.digital", "synchat.vya.digital"]
    for candidate in extra_candidates:
        if candidate not in known_hosts:
            # Tentar reutilizar a api_key da primeira config disponível
            if configs:
                configs.append((candidate, configs[0][1]))
                log.debug("API candidato extra adicionado: %s (api_key reutilizada)", candidate)

    return configs


def run_diagnostico(email: str) -> DiagnosticoResult:
    result = DiagnosticoResult(
        email_diagnosticado=email,
        timestamp=datetime.now().isoformat(),  # noqa: DTZ005
    )

    # ── Engines ──────────────────────────────────────────────────────────────
    try:
        factory = ConnectionFactory(secrets_path=_SECRETS_PATH)
        src_engine: Engine = factory.create_source_engine()
        dest_engine: Engine = factory.create_dest_engine()
    except Exception as exc:
        log.error("Falha ao criar engines: %s", exc)
        sys.exit(1)

    # ── Camada 1: User no SOURCE ──────────────────────────────────────────────
    log.info("=== CAMADA 1: User no SOURCE ===")
    with src_engine.connect() as conn:
        result.source_user = _fetch_user(conn, email)

    if not result.source_user.found:
        log.warning("Usuário '%s' NÃO encontrado no SOURCE", email)
        result.summary.append(
            f"CRÍTICO: '{email}' não existe no SOURCE — pode ser um contato, não um agente"
        )
    else:
        log.info(
            "SOURCE user_id=%d name=%s role=%s account_users=%d",
            result.source_user.user_id,
            result.source_user.name,
            result.source_user.role,
            len(result.source_user.account_users),
        )

    # ── Camada 1b: migration_state ────────────────────────────────────────────
    if result.source_user.found:
        log.info("=== CAMADA 1b: migration_state ===")
        with dest_engine.connect() as conn:
            result.migration_state = _fetch_migration_state(conn, result.source_user.user_id)

        if not result.migration_state.found:
            log.warning(
                "migration_state NÃO tem registro para users id_origem=%d",
                result.source_user.user_id,
            )
            result.summary.append(
                f"CRÍTICO: migration_state sem registro para src_user_id={result.source_user.user_id}"
            )
        else:
            log.info(
                "migration_state: id_origem=%d → id_destino=%d status=%s",
                result.migration_state.id_origem,
                result.migration_state.id_destino,
                result.migration_state.status,
            )

    # ── Camada 1c: User no DEST ───────────────────────────────────────────────
    log.info("=== CAMADA 1c: User no DEST ===")
    with dest_engine.connect() as conn:
        result.dest_user = _fetch_user(conn, email)

    if not result.dest_user.found:
        log.warning("Usuário '%s' NÃO encontrado no DEST", email)
        result.summary.append(f"CRÍTICO: '{email}' não existe no DEST")
    else:
        log.info(
            "DEST user_id=%d role=%s account_users=%d",
            result.dest_user.user_id,
            result.dest_user.role,
            len(result.dest_user.account_users),
        )

        # Verificar se o alias do migration_state aponta para o dest_user_id correto
        if result.migration_state.found and result.migration_state.id_destino is not None:
            result.alias_correct = result.migration_state.id_destino == result.dest_user.user_id
            if not result.alias_correct:
                result.summary.append(
                    f"ALERTA: migration_state.id_destino={result.migration_state.id_destino} "
                    f"!= dest_user_id={result.dest_user.user_id} — alias incorreto!"
                )
                log.error(
                    "Alias INCORRETO: migration_state.id_destino=%d != dest.user.id=%d",
                    result.migration_state.id_destino,
                    result.dest_user.user_id,
                )
            else:
                log.info(
                    "Alias correto: migration_state → dest_user_id=%d", result.dest_user.user_id
                )

    # ── Camada 2: Conversations no DEST ──────────────────────────────────────
    if result.dest_user.found:
        log.info("=== CAMADA 2: Conversations no DEST ===")
        with dest_engine.connect() as conn:
            result.conversations_dest = _fetch_conversation_stats(conn, result.dest_user.user_id)

        log.info(
            "Conversations: total=%d with_assignee=%d without_assignee=%d inbox_count=%d",
            result.conversations_dest.total_in_dest,
            result.conversations_dest.with_assignee,
            result.conversations_dest.without_assignee,
            len(result.conversations_dest.per_inbox),
        )

        if result.conversations_dest.with_assignee == 0:
            result.summary.append(
                "ALERTA: nenhuma conversa tem assignee_id = dest_user_id "
                f"({result.dest_user.user_id}) — assignee_id provavelmente NULL-out"
            )

    # ── Camada 3: Messages no DEST ────────────────────────────────────────────
    if result.dest_user.found:
        log.info("=== CAMADA 3: Messages no DEST ===")
        with dest_engine.connect() as conn:
            result.messages_dest = _fetch_message_stats(conn, result.dest_user.user_id)

        log.info(
            "Messages: as_sender=%d in_marcus_conversations=%d",
            result.messages_dest.as_sender,
            result.messages_dest.in_marcus_conversations,
        )

    # ── Camada 4: inbox_members ────────────────────────────────────────────
    log.info("=== CAMADA 4: inbox_members ===")

    if result.source_user.found:
        with src_engine.connect() as conn:
            result.inbox_members.source_inboxes = _fetch_inbox_members(
                conn, result.source_user.user_id
            )
        log.info(
            "SOURCE inbox_members: %d inboxes — %s",
            len(result.inbox_members.source_inboxes),
            [r["inbox_name"] for r in result.inbox_members.source_inboxes],
        )

    if result.dest_user.found:
        with dest_engine.connect() as conn:
            result.inbox_members.dest_inboxes = _fetch_inbox_members(conn, result.dest_user.user_id)
        log.info(
            "DEST inbox_members: %d inboxes — %s",
            len(result.inbox_members.dest_inboxes),
            [r["inbox_name"] for r in result.inbox_members.dest_inboxes],
        )

    # Calcular missing/extra por nome de inbox (chave de negócio estável)
    if result.inbox_members.source_inboxes or result.inbox_members.dest_inboxes:
        src_names = {r["inbox_name"] for r in result.inbox_members.source_inboxes}
        dest_names = {r["inbox_name"] for r in result.inbox_members.dest_inboxes}

        result.inbox_members.missing_in_dest = [
            r for r in result.inbox_members.source_inboxes if r["inbox_name"] not in dest_names
        ]
        result.inbox_members.extra_in_dest = [
            r for r in result.inbox_members.dest_inboxes if r["inbox_name"] not in src_names
        ]

        if result.inbox_members.missing_in_dest:
            names = [r["inbox_name"] for r in result.inbox_members.missing_in_dest]
            result.summary.append(
                f"CRÍTICO (H3): inbox_members ausentes no DEST para {len(names)} inboxes: {names}"
            )
            result.recommendations.append(
                "Executar app/13_migrar_inbox_members.py para corrigir H3"
            )
            log.error("inbox_members FALTANDO no DEST: %s", names)
        else:
            log.info("inbox_members OK — todos os inboxes do SOURCE presentes no DEST")

    # ── Camada 5: API probe ───────────────────────────────────────────────────
    log.info("=== CAMADA 5: API probe ===")
    api_configs = _load_api_configs()
    if not api_configs:
        log.warning("Nenhuma configuração de API encontrada em %s", _SECRETS_PATH)
        result.summary.append("ALERTA: Configuração de API não encontrada — H6 não verificado")
    else:
        for host, api_key in api_configs:
            probe = _probe_api_host(host, api_key, email)
            result.api_probes.append(probe)

        reachable_hosts = [p.host for p in result.api_probes if p.reachable]
        unreachable_hosts = [p.host for p in result.api_probes if not p.reachable]

        if unreachable_hosts:
            result.summary.append(f"ALERTA (H6): API inacessível em: {unreachable_hosts}")
        if reachable_hosts:
            log.info("API acessível em: %s", reachable_hosts)

    # ── Recomendações finais ─────────────────────────────────────────────────
    if not result.source_user.found:
        result.recommendations.append(
            "Verificar se marcos é um contact (não user) via SELECT em contacts"
        )

    if result.alias_correct is False:
        result.recommendations.append(
            "Corrigir migration_state: UPDATE migration_state SET id_destino=<dest_id> "
            "WHERE tabela='users' AND id_origem=<src_id>"
        )

    if (
        result.dest_user.found
        and result.conversations_dest.with_assignee == 0
        and result.source_user.found
    ):
        result.recommendations.append(
            "Verificar se conversations de marcos têm assignee_id correto no DEST: "
            "SELECT COUNT(*) FROM conversations WHERE assignee_id = <dest_user_id>"
        )

    return result


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Diagnostica visibilidade de um agente pós-migração"
    )
    parser.add_argument(
        "--email",
        default="marcos.andrade@vya.digital",
        help="E-mail do agente a diagnosticar (padrão: marcos.andrade@vya.digital)",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    email = args.email.strip().lower()
    log.info("Iniciando diagnóstico para: %s", email)

    result = run_diagnostico(email)

    out_path = _TMP / f"diagnostico_marcos_{_TS}.json"

    def _default(obj: object) -> object:
        if hasattr(obj, "__dataclass_fields__"):
            return asdict(obj)  # type: ignore[arg-type]
        return str(obj)

    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(asdict(result), fh, ensure_ascii=False, indent=2, default=_default)

    log.info("Diagnóstico salvo em: %s", out_path)

    if result.summary:
        log.info("=== RESUMO DOS PROBLEMAS ENCONTRADOS ===")
        for item in result.summary:
            log.info("  • %s", item)

    if result.recommendations:
        log.info("=== RECOMENDAÇÕES ===")
        for rec in result.recommendations:
            log.info("  → %s", rec)


if __name__ == "__main__":
    main()
