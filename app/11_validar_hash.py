"""Validação de integridade de conteúdo pós-migração via hash MD5.

Estratégia
----------
Para cada tabela (contacts, conversations, messages, attachments), executa
**uma query por banco** que calcula ``MD5()`` dos campos de negócio diretamente
no servidor PostgreSQL. Os hashes são transferidos para a máquina local (~12 MB
para 239k mensagens) e comparados com Pandas.

Métricas produzidas por tabela
------------------------------
- ``missing``   — hashes presentes no SOURCE mas ausentes no DEST (perda de dado)
- ``extra``     — hashes presentes no DEST mas ausentes no SOURCE (duplicação/espúrio)
- ``src_total`` / ``dest_total`` — contagens brutas para referência

Chaves de negócio por tabela (campos incluídos no hash)
--------------------------------------------------------
- contacts      : ``phone_number``, ``email``, ``name``
- conversations : ``display_id``, ``status``, ``created_at``
- messages      : ``content``, ``message_type``, ``content_type``, ``created_at``
- attachments   : ``external_url``, ``file_type``

Exit codes
----------
- 0  Nenhum hash faltando em nenhuma tabela
- 2  Pelo menos uma tabela com ``missing > 0`` (perda de dados)
- 3  Apenas extras (dados no DEST sem correspondência no SOURCE — provável dedup OK)

Usage::

    # Validação completa (todas as tabelas, todos os accounts)
    python app/11_validar_hash.py

    # Apenas mensagens, accounts específicos
    python app/11_validar_hash.py --tables messages --accounts 1 4

    # Salvar DataFrames em parquet para análise offline
    python app/11_validar_hash.py --save-parquet

Saída::

    .tmp/validacao_hash_YYYYMMDD_HHMMSS.json   — resumo por tabela
    .tmp/validacao_hash_YYYYMMDD_HHMMSS.csv    — divergências (hashes ausentes)
    .tmp/validacao_hash_YYYYMMDD_HHMMSS.log    — log DEBUG completo
    .tmp/hashes_<tabela>_src_YYYYMMDD.parquet  — (opcional, --save-parquet)
    .tmp/hashes_<tabela>_dest_YYYYMMDD.parquet — (opcional, --save-parquet)
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import text

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from src.factory.connection_factory import ConnectionFactory  # noqa: E402

# ---------------------------------------------------------------------------
# Paths e constantes
# ---------------------------------------------------------------------------
_LOG_DIR = _ROOT / ".tmp"
_LOG_DIR.mkdir(parents=True, exist_ok=True)
_TS = datetime.now().strftime("%Y%m%d_%H%M%S")  # noqa: DTZ005

_fmt = logging.Formatter(
    "%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
_sh = logging.StreamHandler(sys.stdout)
_sh.setLevel(logging.INFO)
_sh.setFormatter(_fmt)
_fh = logging.FileHandler(str(_LOG_DIR / f"validacao_hash_{_TS}.log"), encoding="utf-8")
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(_fmt)
logging.getLogger().setLevel(logging.DEBUG)
logging.getLogger().addHandler(_sh)
logging.getLogger().addHandler(_fh)

log = logging.getLogger("validacao_hash")

# ---------------------------------------------------------------------------
# SQL — uma query por tabela, MD5 calculado no servidor
# ---------------------------------------------------------------------------

# Contacts: chave de negócio = phone_number + email + name
# account_id passado como filtro (SOURCE: src_ids; DEST: dest_ids)
_SQL_CONTACTS_HASHES = """
SELECT
    MD5(CONCAT_WS(
        E'\\x1F',
        COALESCE(LOWER(TRIM(phone_number)), ''),
        COALESCE(LOWER(TRIM(email)), ''),
        COALESCE(TRIM(name), '')
    )) AS row_hash,
    account_id
FROM contacts
WHERE account_id = ANY(:account_ids)
"""

# Conversations: chave = created_at + status
# NOTA: display_id é sempre renumerado no DEST (inválido como BK).
# created_at é preservado bit-a-bit e único (0 duplicatas em 36k rows).
_SQL_CONVERSATIONS_HASHES = """
SELECT
    MD5(CONCAT_WS(
        E'\\x1F',
        TO_CHAR(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS.US'),
        COALESCE(status::text, '')
    )) AS row_hash,
    account_id
FROM conversations
WHERE account_id = ANY(:account_ids)
"""

# Messages: chave = content + message_type + content_type + created_at
_SQL_MESSAGES_HASHES = """
SELECT
    MD5(CONCAT_WS(
        E'\\x1F',
        COALESCE(content, ''),
        COALESCE(message_type::text, ''),
        COALESCE(content_type::text, ''),
        TO_CHAR(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS.US')
    )) AS row_hash,
    account_id
FROM messages
WHERE account_id = ANY(:account_ids)
"""

# Attachments: chave = file_type + created_at
# NOTA: external_url é NULL em 100% dos registros (inválida como BK).
# created_at é preservado bit-a-bit e, combinado com file_type, produz hashes únicos.
_SQL_ATTACHMENTS_HASHES = """
SELECT
    MD5(CONCAT_WS(
        E'\\x1F',
        COALESCE(file_type::text, ''),
        TO_CHAR(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS.US')
    )) AS row_hash,
    account_id
FROM attachments
WHERE account_id = ANY(:account_ids)
"""

# Mapeamento de account ids SOURCE → DEST
_SQL_ACCOUNT_MAP = """
SELECT ms.id_origem AS src_id, ms.id_destino AS dest_id
FROM migration_state ms
WHERE ms.tabela = 'accounts' AND ms.status = 'ok'
ORDER BY ms.id_origem
"""

_TABLE_QUERIES: dict[str, str] = {
    "contacts": _SQL_CONTACTS_HASHES,
    "conversations": _SQL_CONVERSATIONS_HASHES,
    "messages": _SQL_MESSAGES_HASHES,
    "attachments": _SQL_ATTACHMENTS_HASHES,
}

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class TableHashResult:
    table: str
    src_total: int
    dest_total: int
    missing: int  # em src, ausente no dest — possível perda de dado
    extra: int  # em dest, ausente no src — duplicação/espúrio
    missing_pct: float  # missing / src_total * 100
    extra_pct: float  # extra / dest_total * 100 (0 se dest_total == 0)
    status: str  # "ok" | "missing" | "extra" | "missing+extra"


@dataclass
class HashValidationReport:
    timestamp: str
    src_account_ids: list[int]
    dest_account_ids: list[int]
    tables: list[TableHashResult]
    summary: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Carregamento de hashes (bulk, uma query por banco por tabela)
# ---------------------------------------------------------------------------


def _load_hashes(
    engine: Any,
    table: str,
    account_ids: list[int],
    label: str,
) -> pd.DataFrame:
    """Carrega hashes de uma tabela para uma lista de account_ids.

    Retorna DataFrame com colunas ``[row_hash, account_id]``.
    """
    sql = _TABLE_QUERIES[table]
    log.info("Carregando hashes %s.%s account_ids=%s ...", label, table, account_ids)
    with engine.connect() as conn:
        rows = conn.execute(text(sql), {"account_ids": account_ids}).fetchall()
    df = pd.DataFrame(rows, columns=["row_hash", "account_id"])
    log.info("  %s.%s: %d linhas carregadas", label, table, len(df))
    return df


# ---------------------------------------------------------------------------
# Comparação de hashes
# ---------------------------------------------------------------------------


def _compare_hashes(
    df_src: pd.DataFrame,
    df_dest: pd.DataFrame,
    table: str,
) -> TableHashResult:
    """Compara dois DataFrames de hashes e retorna métricas de integridade."""
    src_set = set(df_src["row_hash"].dropna())
    dest_set = set(df_dest["row_hash"].dropna())

    src_total = len(src_set)
    dest_total = len(dest_set)
    missing = len(src_set - dest_set)
    extra = len(dest_set - src_set)

    missing_pct = missing / src_total * 100 if src_total else 0.0
    extra_pct = extra / dest_total * 100 if dest_total else 0.0

    if missing > 0 and extra > 0:
        status = "missing+extra"
    elif missing > 0:
        status = "missing"
    elif extra > 0:
        status = "extra"
    else:
        status = "ok"

    log.info(
        "  %s → src=%d dest=%d missing=%d (%.2f%%) extra=%d (%.2f%%) status=%s",
        table,
        src_total,
        dest_total,
        missing,
        missing_pct,
        extra,
        extra_pct,
        status,
    )
    if missing > 0:
        log.warning("PERDA DE DADOS detectada em '%s': %d hashes ausentes no DEST", table, missing)
    if extra > 0:
        log.warning(
            "DADOS EXTRAS no DEST para '%s': %d hashes sem correspondência no SOURCE", table, extra
        )

    return TableHashResult(
        table=table,
        src_total=src_total,
        dest_total=dest_total,
        missing=missing,
        extra=extra,
        missing_pct=missing_pct,
        extra_pct=extra_pct,
        status=status,
    )


# ---------------------------------------------------------------------------
# Persistência — hashes divergentes para drill-down
# ---------------------------------------------------------------------------


def _collect_divergences(
    df_src: pd.DataFrame,
    df_dest: pd.DataFrame,
    table: str,
) -> list[dict[str, Any]]:
    """Retorna linhas divergentes (missing + extra) para o CSV de saída."""
    src_set = set(df_src["row_hash"].dropna())
    dest_set = set(df_dest["row_hash"].dropna())

    rows: list[dict[str, Any]] = []
    for h in src_set - dest_set:
        rows.append({"table": table, "type": "missing_in_dest", "hash": h})
    for h in dest_set - src_set:
        rows.append({"table": table, "type": "extra_in_dest", "hash": h})
    return rows


def _save_outputs(
    report: HashValidationReport,
    divergences: list[dict[str, Any]],
) -> None:
    json_path = _LOG_DIR / f"validacao_hash_{_TS}.json"
    csv_path = _LOG_DIR / f"validacao_hash_{_TS}.csv"

    json_path.write_text(
        json.dumps(asdict(report), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info("JSON salvo: %s", json_path)

    if divergences:
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=["table", "type", "hash"])
            writer.writeheader()
            writer.writerows(divergences)
        log.info("CSV de divergências salvo: %s (%d linhas)", csv_path, len(divergences))
    else:
        log.info("Nenhuma divergência — CSV não gerado")


def _save_parquet(
    df: pd.DataFrame,
    label: str,
    table: str,
) -> None:
    path = _LOG_DIR / f"hashes_{table}_{label}_{_TS[:8]}.parquet"
    df.to_parquet(path, index=False)
    log.info("Parquet salvo: %s (%d linhas)", path, len(df))


# ---------------------------------------------------------------------------
# Orquestrador principal
# ---------------------------------------------------------------------------


def _run(
    factory: ConnectionFactory,
    tables: list[str],
    src_account_ids: list[int],
    dest_account_ids: list[int],
    *,
    save_parquet: bool = False,
) -> HashValidationReport:
    src_engine = factory.create_source_engine()
    dest_engine = factory.create_dest_engine()

    results: list[TableHashResult] = []
    all_divergences: list[dict[str, Any]] = []

    for table in tables:
        log.info("=== Tabela: %s ===", table)
        df_src = _load_hashes(src_engine, table, src_account_ids, "SOURCE")
        df_dest = _load_hashes(dest_engine, table, dest_account_ids, "DEST")

        if save_parquet:
            _save_parquet(df_src, "src", table)
            _save_parquet(df_dest, "dest", table)

        result = _compare_hashes(df_src, df_dest, table)
        results.append(result)

        divs = _collect_divergences(df_src, df_dest, table)
        all_divergences.extend(divs)

    summary = {
        "tables_ok": sum(1 for r in results if r.status == "ok"),
        "tables_with_missing": sum(1 for r in results if "missing" in r.status),
        "tables_with_extra": sum(1 for r in results if "extra" in r.status),
        "total_missing": sum(r.missing for r in results),
        "total_extra": sum(r.extra for r in results),
    }
    log.info("Resumo final: %s", json.dumps(summary, ensure_ascii=False))

    report = HashValidationReport(
        timestamp=_TS,
        src_account_ids=src_account_ids,
        dest_account_ids=dest_account_ids,
        tables=results,
        summary=summary,
    )
    _save_outputs(report, all_divergences)
    return report


# ---------------------------------------------------------------------------
# Exit code
# ---------------------------------------------------------------------------


def _exit_code(report: HashValidationReport) -> int:
    has_missing = any(r.missing > 0 for r in report.tables)
    has_extra = any(r.extra > 0 for r in report.tables)
    if has_missing:
        log.warning("EXIT 2 — perda de dados detectada")
        return 2
    if has_extra:
        log.warning("EXIT 3 — dados extras no DEST sem correspondência no SOURCE")
        return 3
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

_ALL_TABLES = list(_TABLE_QUERIES.keys())
_ACCOUNT_MAP_FALLBACK: dict[int, int] = {1: 1, 4: 47, 17: 17, 18: 61, 25: 68}


def _load_account_map(factory: ConnectionFactory) -> dict[int, int]:
    dest_engine = factory.create_dest_engine()
    with dest_engine.connect() as conn:
        rows = conn.execute(text(_SQL_ACCOUNT_MAP)).fetchall()
    if rows:
        result = {int(r[0]): int(r[1]) for r in rows}
        log.info("account_map carregado de migration_state: %s", result)
        return result
    log.warning("migration_state vazia para accounts — usando fallback: %s", _ACCOUNT_MAP_FALLBACK)
    return dict(_ACCOUNT_MAP_FALLBACK)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="11_validar_hash.py",
        description="Validação de integridade pós-migração por hash MD5 de conteúdo",
    )
    parser.add_argument(
        "--tables",
        nargs="+",
        choices=_ALL_TABLES,
        default=_ALL_TABLES,
        metavar="TABLE",
        help=f"Tabelas a validar (padrão: todas). Opções: {', '.join(_ALL_TABLES)}",
    )
    parser.add_argument(
        "--accounts",
        nargs="+",
        type=int,
        default=None,
        metavar="SRC_ACCOUNT_ID",
        help="IDs de account no SOURCE a incluir (padrão: todos do migration_state)",
    )
    parser.add_argument(
        "--save-parquet",
        action="store_true",
        dest="save_parquet",
        help="Salvar DataFrames de hashes em .tmp/*.parquet para análise offline",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    factory = ConnectionFactory()

    account_map = _load_account_map(factory)

    if args.accounts:
        # Filtra pelo subconjunto solicitado
        filtered = {k: v for k, v in account_map.items() if k in args.accounts}
        if not filtered:
            log.error(
                "Nenhum dos accounts %s encontrado no mapeamento %s",
                args.accounts,
                list(account_map.keys()),
            )
            sys.exit(1)
        account_map = filtered

    src_ids = list(account_map.keys())
    dest_ids = list(account_map.values())

    log.info("=== Validação por hash — %s ===", _TS)
    log.info("Tabelas: %s", args.tables)
    log.info("Accounts SOURCE: %s", src_ids)
    log.info("Accounts DEST:   %s", dest_ids)

    report = _run(
        factory,
        tables=args.tables,
        src_account_ids=src_ids,
        dest_account_ids=dest_ids,
        save_parquet=args.save_parquet,
    )

    exit_code = _exit_code(report)
    log.info("Concluído. Outputs em %s/ — exit_code=%d", _LOG_DIR, exit_code)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
