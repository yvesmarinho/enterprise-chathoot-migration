"""Migração da tabela ``inbox_members`` SOURCE → DEST.

Contexto
--------
``inbox_members`` não estava na pipeline original de migração.  A ausência
desta tabela no DEST significa que os agentes não são membros de nenhum inbox
no destino e, portanto, não vêem as conversas correspondentes na UI.

Estratégia
----------
1. Carregar ``migration_state`` para ``users`` e ``inboxes`` (src_id → dest_id).
2. Para cada linha de ``inbox_members`` no SOURCE:
   a. Resolver ``user_id`` (src → dest) via ``migration_state``.
   b. Resolver ``inbox_id`` (src → dest) via ``migration_state``.
   c. Verificar se o par ``(inbox_id, user_id)`` já existe no DEST
      (ON CONFLICT DO NOTHING garante idempotência).
3. Inserir em lotes de 500, dentro de transações únicas por lote.
4. Salvar relatório em ``.tmp/migrar_inbox_members_YYYYMMDD_HHMMSS.json``.

Exit codes
----------
0   Migração concluída com sucesso
1   Falha crítica (DB inacessível, migration_state ausente)
3   Nenhuma linha a migrar (SOURCE vazio ou todos já existem no DEST)

Usage::

    python app/13_migrar_inbox_members.py
    python app/13_migrar_inbox_members.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import MetaData, Table, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
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
_BATCH_SIZE = 500

_fmt = logging.Formatter(
    "%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
_sh = logging.StreamHandler(sys.stdout)
_sh.setLevel(logging.INFO)
_sh.setFormatter(_fmt)
_fh = logging.FileHandler(str(_TMP / f"migrar_inbox_members_{_TS}.log"), encoding="utf-8")
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(_fmt)
logging.getLogger().setLevel(logging.DEBUG)
logging.getLogger().addHandler(_sh)
logging.getLogger().addHandler(_fh)

log = logging.getLogger("migrar_inbox_members")

# ---------------------------------------------------------------------------
# Resultado da migração
# ---------------------------------------------------------------------------


@dataclass
class SkipReason:
    orphan_user_id: int = 0
    orphan_inbox_id: int = 0
    already_exists_in_dest: int = 0


@dataclass
class InboxMembersMigrationResult:
    total_source: int = 0
    migrated: int = 0
    skipped: int = 0
    failed: int = 0
    skip_reasons: SkipReason = field(default_factory=SkipReason)
    failed_pairs: list[dict[str, int]] = field(default_factory=list)
    dry_run: bool = False


# ---------------------------------------------------------------------------
# Carregamento do mapeamento src → dest via migration_state
# ---------------------------------------------------------------------------


def _load_id_map(conn: Connection, tabela: str) -> dict[int, int]:
    """Retorna {id_origem: id_destino} para `tabela` com status='ok'."""
    rows = conn.execute(
        text(
            "SELECT id_origem, id_destino FROM migration_state "
            "WHERE tabela = :t AND status = 'ok' AND id_destino IS NOT NULL"
        ),
        {"t": tabela},
    ).fetchall()
    return {int(r[0]): int(r[1]) for r in rows}


def _load_existing_dest_pairs(conn: Connection) -> set[tuple[int, int]]:
    """Retorna o conjunto de (inbox_id, user_id) já presentes no DEST."""
    rows = conn.execute(text("SELECT inbox_id, user_id FROM inbox_members")).fetchall()
    return {(int(r[0]), int(r[1])) for r in rows}


# ---------------------------------------------------------------------------
# Migração
# ---------------------------------------------------------------------------


def _migrate_batch(
    conn: Connection,
    dest_table: Table,
    batch: list[dict[str, Any]],
) -> int:
    """Insere um lote no DEST com ON CONFLICT DO NOTHING.

    :returns: Número de linhas efetivamente inseridas.
    """
    stmt = pg_insert(dest_table).values(batch).on_conflict_do_nothing()
    result = conn.execute(stmt)
    conn.commit()
    # rowcount pode ser -1 em alguns drivers; usar len(batch) como upper bound
    return result.rowcount if result.rowcount >= 0 else len(batch)


def run_migration(dry_run: bool = False) -> InboxMembersMigrationResult:
    result = InboxMembersMigrationResult(dry_run=dry_run)

    # ── Engines ──────────────────────────────────────────────────────────────
    try:
        factory = ConnectionFactory(secrets_path=_SECRETS_PATH)
        src_engine: Engine = factory.create_source_engine()
        dest_engine: Engine = factory.create_dest_engine()
    except Exception as exc:
        log.error("Falha ao criar engines: %s", exc)
        sys.exit(1)

    # ── Refletir tabela DEST ──────────────────────────────────────────────────
    dest_meta = MetaData()
    try:
        dest_table = Table("inbox_members", dest_meta, autoload_with=dest_engine)
    except Exception as exc:
        log.error("Falha ao refletir tabela inbox_members no DEST: %s", exc)
        sys.exit(1)

    # ── Carregar mapeamentos do migration_state ───────────────────────────────
    with dest_engine.connect() as conn:
        user_map: dict[int, int] = _load_id_map(conn, "users")
        inbox_map: dict[int, int] = _load_id_map(conn, "inboxes")
        existing_pairs: set[tuple[int, int]] = _load_existing_dest_pairs(conn)

    log.info(
        "Mapeamentos carregados: users=%d inboxes=%d pares_existentes_dest=%d",
        len(user_map),
        len(inbox_map),
        len(existing_pairs),
    )

    if not user_map:
        log.error(
            "migration_state não tem registros para 'users'. "
            "Execute a migração de users antes deste script."
        )
        sys.exit(1)
    if not inbox_map:
        log.error(
            "migration_state não tem registros para 'inboxes'. "
            "Execute a migração de inboxes antes deste script."
        )
        sys.exit(1)

    # ── Fetch SOURCE rows ─────────────────────────────────────────────────────
    with src_engine.connect() as conn:
        src_rows = conn.execute(
            text("SELECT inbox_id, user_id FROM inbox_members ORDER BY inbox_id, user_id")
        ).fetchall()

    result.total_source = len(src_rows)
    log.info("SOURCE inbox_members: %d linhas", result.total_source)

    if result.total_source == 0:
        log.warning("SOURCE inbox_members está vazio — nada a migrar")
        sys.exit(3)

    # ── Remapear e classificar ────────────────────────────────────────────────
    to_insert: list[dict[str, Any]] = []
    _now = datetime.now(tz=timezone.utc)

    for src_inbox_id, src_user_id in src_rows:
        src_inbox_id = int(src_inbox_id)
        src_user_id = int(src_user_id)

        dest_user_id = user_map.get(src_user_id)
        if dest_user_id is None:
            log.debug(
                "inbox_members: src_user_id=%d não migrado — skip (orphan user)",
                src_user_id,
            )
            result.skip_reasons.orphan_user_id += 1
            result.skipped += 1
            continue

        dest_inbox_id = inbox_map.get(src_inbox_id)
        if dest_inbox_id is None:
            log.debug(
                "inbox_members: src_inbox_id=%d não migrado — skip (orphan inbox)",
                src_inbox_id,
            )
            result.skip_reasons.orphan_inbox_id += 1
            result.skipped += 1
            continue

        if (dest_inbox_id, dest_user_id) in existing_pairs:
            log.debug(
                "inbox_members: (dest_inbox=%d, dest_user=%d) já existe — skip",
                dest_inbox_id,
                dest_user_id,
            )
            result.skip_reasons.already_exists_in_dest += 1
            result.skipped += 1
            continue

        to_insert.append(
            {
                "inbox_id": dest_inbox_id,
                "user_id": dest_user_id,
                "created_at": _now,
                "updated_at": _now,
            }
        )
        # Adicionar ao set local para evitar duplicatas dentro deste run
        existing_pairs.add((dest_inbox_id, dest_user_id))

    log.info(
        "Classificação: a_inserir=%d skipped=%d " "(orphan_user=%d orphan_inbox=%d ja_existe=%d)",
        len(to_insert),
        result.skipped,
        result.skip_reasons.orphan_user_id,
        result.skip_reasons.orphan_inbox_id,
        result.skip_reasons.already_exists_in_dest,
    )

    if not to_insert:
        log.info("Nenhuma linha nova a inserir")
        return result

    if dry_run:
        log.info("DRY-RUN ativado — nenhum INSERT será executado")
        result.migrated = len(to_insert)
        return result

    # ── Inserir em lotes ──────────────────────────────────────────────────────
    total_batches = (len(to_insert) + _BATCH_SIZE - 1) // _BATCH_SIZE

    with dest_engine.connect() as conn:
        for batch_idx, start in enumerate(range(0, len(to_insert), _BATCH_SIZE), 1):
            batch = to_insert[start : start + _BATCH_SIZE]
            try:
                inserted = _migrate_batch(conn, dest_table, batch)
                result.migrated += inserted
                log.debug(
                    "Lote %d/%d: inseridos=%d",
                    batch_idx,
                    total_batches,
                    inserted,
                )
            except Exception as exc:
                log.error("Falha no lote %d/%d: %s", batch_idx, total_batches, exc)
                result.failed += len(batch)
                result.failed_pairs.extend(
                    {"inbox_id": r["inbox_id"], "user_id": r["user_id"]} for r in batch
                )

    log.info(
        "Migração concluída: migrated=%d skipped=%d failed=%d",
        result.migrated,
        result.skipped,
        result.failed,
    )
    return result


# ---------------------------------------------------------------------------
# Verificação de segurança de re-run
# ---------------------------------------------------------------------------


def check_rerun_safety(dest_engine: Engine) -> dict[str, Any]:
    """Verifica se um re-run de inbox_members seria seguro (sem duplicações).

    Executa queries de diagnóstico no DEST sem escrever nada.

    :returns: Dict com informações de segurança para logar/salvar.
    """
    with dest_engine.connect() as conn:
        # Verificar se há unique constraint em inbox_members
        constraints = (
            conn.execute(
                text(
                    "SELECT conname, contype "
                    "FROM pg_constraint "
                    "WHERE conrelid = 'inbox_members'::regclass AND contype IN ('u', 'p')"
                )
            )
            .mappings()
            .all()
        )

        current_count = conn.execute(text("SELECT COUNT(*) FROM inbox_members")).scalar() or 0

        user_map_size = (
            conn.execute(
                text(
                    "SELECT COUNT(*) FROM migration_state "
                    "WHERE tabela = 'users' AND status = 'ok'"
                )
            ).scalar()
            or 0
        )

        inbox_map_size = (
            conn.execute(
                text(
                    "SELECT COUNT(*) FROM migration_state "
                    "WHERE tabela = 'inboxes' AND status = 'ok'"
                )
            ).scalar()
            or 0
        )

    has_unique = any(str(c["contype"]) in ("u", "p") for c in constraints)

    return {
        "has_unique_constraint": has_unique,
        "constraints": [dict(c) for c in constraints],
        "current_inbox_members_in_dest": current_count,
        "user_map_entries": user_map_size,
        "inbox_map_entries": inbox_map_size,
        "rerun_safe": has_unique,
        "note": (
            "ON CONFLICT DO NOTHING garante idempotência SE existir unique constraint. "
            "Verificar também: script filtra pares já existentes antes de inserir."
        ),
    }


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migra inbox_members SOURCE → DEST remapeando user_id e inbox_id"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Classifica e reporta sem executar INSERTs",
    )
    parser.add_argument(
        "--check-safety",
        action="store_true",
        default=False,
        help="Apenas verifica se um re-run seria seguro, sem migrar",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    if args.check_safety:
        try:
            factory = ConnectionFactory(secrets_path=_SECRETS_PATH)
            dest_engine = factory.create_dest_engine()
        except Exception as exc:
            log.error("Falha ao criar dest engine: %s", exc)
            sys.exit(1)

        safety = check_rerun_safety(dest_engine)
        log.info("Segurança de re-run: %s", json.dumps(safety, indent=2))
        out = _TMP / f"rerun_safety_inbox_members_{_TS}.json"
        out.write_text(json.dumps(safety, indent=2, ensure_ascii=False))
        log.info("Relatório salvo em: %s", out)
        return

    result = run_migration(dry_run=args.dry_run)

    out_path = _TMP / f"migrar_inbox_members_{_TS}.json"
    out_path.write_text(json.dumps(asdict(result), indent=2, ensure_ascii=False))
    log.info("Relatório salvo em: %s", out_path)

    if result.failed > 0:
        sys.exit(1)
    if result.total_source > 0 and result.migrated == 0 and result.skipped == result.total_source:
        sys.exit(3)


if __name__ == "__main__":
    main()
