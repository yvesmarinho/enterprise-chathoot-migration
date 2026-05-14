#!/usr/bin/env python3
"""Utilitário CLI para validação de attachments S3 pós-migração.

Valida a acessibilidade de URLs de attachments (active_storage → S3) via HTTP HEAD,
gerando relatórios em JSON e Markdown.

:description: CLI tool para validar attachments S3 de uma account específica
:author: GitHub Copilot
:created: 2026-05-14
:session: SESSION-14
:source: Baseado em .tmp/19_validar_attachments_s3.py

Usage:
    python scripts/check_s3_attachments.py \\
        --instance chatwoot004_dev \\
        --account-id 1 \\
        --limit 100 \\
        --date-start 2026-01-01 \\
        --date-end 2026-05-14
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

# =============================================================================
# Configuração de Logging
# =============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# =============================================================================
# SQL Query — Baseada em docs/message.txt
# =============================================================================
QUERY_ATTACHMENTS = """
SELECT
    c.account_id,
    a.name AS account_name,
    c.inbox_id,
    i.name AS inbox_name,
    c.id AS conversation_id,
    c.display_id AS conversation_display,
    m.id AS message_id,
    att.id AS attachment_id,
    asb.key AS blob_key,
    asb.filename,
    asb.content_type,
    asb.byte_size,
    m.created_at AS message_created_at,
    CASE
        WHEN (asb.key IS NOT NULL) THEN
            CONCAT('https://assets-chat-vya-digital.s3.amazonaws.com/', asb.key)
        ELSE NULL
    END AS attachment_link

FROM conversations c
INNER JOIN accounts a ON a.id = c.account_id
INNER JOIN inboxes i ON i.account_id = c.account_id AND i.id = c.inbox_id
INNER JOIN messages m ON m.account_id = c.account_id AND m.conversation_id = c.id
INNER JOIN attachments att ON att.account_id = m.account_id AND att.message_id = m.id
INNER JOIN active_storage_attachments ast ON att.id = ast.record_id
INNER JOIN active_storage_blobs asb ON asb.id = ast.blob_id

WHERE c.account_id = :account_id
  AND asb.key IS NOT NULL  -- Apenas attachments com blob válido
  AND m.created_at BETWEEN :date_start AND :date_end

ORDER BY m.created_at DESC  -- Mais recentes primeiro

LIMIT :limit OFFSET :offset;
"""

QUERY_COUNT_TOTAL = """
SELECT COUNT(*)
FROM attachments
WHERE account_id = :account_id
"""

QUERY_COUNT_WITH_BLOB = """
SELECT COUNT(*)
FROM attachments att
INNER JOIN active_storage_attachments ast ON att.id = ast.record_id
INNER JOIN active_storage_blobs asb ON asb.id = ast.blob_id
WHERE att.account_id = :account_id AND asb.key IS NOT NULL
"""


# =============================================================================
# Data Classes
# =============================================================================
@dataclass
class AttachmentValidation:
    """Resultado de validação de um attachment."""

    account_id: int
    account_name: str
    inbox_id: int
    inbox_name: str
    conversation_id: int
    conversation_display: int
    message_id: int
    attachment_id: int
    blob_key: str
    filename: str
    content_type: str
    byte_size: int
    message_created_at: str
    attachment_link: str
    http_status: int | None
    http_ok: bool
    error_message: str | None
    response_time_ms: float | None


@dataclass
class ValidationReport:
    """Relatório consolidado de validação."""

    timestamp: str
    instance_name: str
    account_id: int
    account_name: str
    date_range: tuple[str, str]
    limit: int
    offset: int
    total_attachments_account: int | None
    total_with_blob: int | None
    validated_count: int
    success_count: int
    failed_count: int
    success_rate: float
    validations: list[dict[str, Any]]
    failed_attachments: list[dict[str, Any]]


# =============================================================================
# Funções de Conexão
# =============================================================================
def load_connection_config(instance_name: str) -> dict[str, Any]:
    """Carrega configuração de conexão do arquivo .secrets/generate_erd.json.

    :param instance_name: Nome da instância (chave no JSON)
    :return: Dicionário com config de conexão
    :raises FileNotFoundError: Se arquivo não existe
    :raises KeyError: Se instance_name não encontrada
    :raises ValueError: Se configuração inválida
    """
    secrets_file = Path(".secrets/generate_erd.json")

    if not secrets_file.exists():
        raise FileNotFoundError(
            f"Arquivo de configuração não encontrado: {secrets_file}\n"
            "Certifique-se de que .secrets/generate_erd.json existe."
        )

    with secrets_file.open("r", encoding="utf-8") as f:
        config = json.load(f)

    if instance_name not in config:
        available = [k for k in config.keys() if not k.startswith("_")]
        raise KeyError(
            f"Instância '{instance_name}' não encontrada em {secrets_file}\n"
            f"Instâncias disponíveis: {', '.join(available)}"
        )

    instance_config = config[instance_name]

    # Validar campos obrigatórios
    required_fields = ["engine", "host", "database", "username", "password"]
    missing = [f for f in required_fields if not instance_config.get(f)]

    if missing:
        raise ValueError(
            f"Configuração incompleta para '{instance_name}': "
            f"campos ausentes: {', '.join(missing)}"
        )

    return instance_config


def create_engine_from_config(config: dict[str, Any]) -> Engine:
    """Cria SQLAlchemy Engine a partir da configuração.

    :param config: Dicionário com config de conexão
    :return: Engine SQLAlchemy
    :raises ValueError: Se engine type não suportado
    """
    engine_type = config["engine"]
    host = config["host"]
    port = config.get("port", 5432)
    database = config["database"]
    username = config["username"]
    password = config["password"]
    ssl = config.get("SSL", False)

    if engine_type != "postgresql":
        raise ValueError(f"Engine '{engine_type}' não suportado. Apenas 'postgresql' é aceito.")

    # Construir connection string
    sslmode = "require" if ssl else "disable"
    conn_str = f"postgresql://{username}:{password}@{host}:{port}/{database}" f"?sslmode={sslmode}"

    log.info(f"Conectando a: postgresql://{username}:***@{host}:{port}/{database}")

    engine = create_engine(
        conn_str,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        echo=False,
    )

    return engine


# =============================================================================
# Funções de Validação
# =============================================================================
def fetch_account_stats(engine: Engine, account_id: int) -> tuple[str, int, int]:
    """Busca estatísticas de attachments da account.

    :param engine: Engine SQLAlchemy
    :param account_id: ID da account
    :return: Tupla (account_name, total_attachments, total_with_blob)
    """
    with engine.connect() as conn:
        # Nome do account
        account_result = conn.execute(
            text("SELECT name FROM accounts WHERE id = :account_id"),
            {"account_id": account_id},
        )
        account_name = account_result.scalar()

        if not account_name:
            raise ValueError(f"Account ID {account_id} não encontrado no banco de dados")

        # Total de attachments
        count_total = conn.execute(
            text(QUERY_COUNT_TOTAL),
            {"account_id": account_id},
        )
        total_attachments = count_total.scalar() or 0

        # Total com blob S3
        count_blob = conn.execute(
            text(QUERY_COUNT_WITH_BLOB),
            {"account_id": account_id},
        )
        total_with_blob = count_blob.scalar() or 0

    return account_name, total_attachments, total_with_blob


def fetch_attachments(
    engine: Engine,
    account_id: int,
    date_start: str,
    date_end: str,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Busca attachments do banco de dados.

    :param engine: Engine SQLAlchemy
    :param account_id: ID da account a validar
    :param date_start: Data inicial (YYYY-MM-DD)
    :param date_end: Data final (YYYY-MM-DD)
    :param limit: Máximo de registros a retornar
    :param offset: Offset para paginação
    :return: Lista de dicts com dados de attachments
    """
    with engine.connect() as conn:
        result = conn.execute(
            text(QUERY_ATTACHMENTS),
            {
                "account_id": account_id,
                "date_start": date_start,
                "date_end": date_end,
                "limit": limit,
                "offset": offset,
            },
        )
        rows = result.mappings().all()
        return [dict(row) for row in rows]


def validate_attachment_url(
    url: str, timeout: int = 10
) -> tuple[int | None, bool, str | None, float | None]:
    """Valida acessibilidade de URL via HTTP HEAD.

    :param url: URL completa do attachment (S3)
    :param timeout: Timeout em segundos
    :return: Tupla (status_code, is_ok, error_message, response_time_ms)
    """
    try:
        start = datetime.now()
        response = requests.head(url, timeout=timeout, allow_redirects=True)
        elapsed_ms = (datetime.now() - start).total_seconds() * 1000

        is_ok = response.status_code == 200
        error_msg = None if is_ok else f"HTTP {response.status_code}"

        return response.status_code, is_ok, error_msg, elapsed_ms

    except requests.exceptions.Timeout:
        return None, False, "Timeout", None
    except requests.exceptions.RequestException as e:
        return None, False, f"RequestError: {type(e).__name__}", None
    except Exception as e:
        return None, False, f"UnexpectedError: {type(e).__name__}", None


def validate_attachments(attachments: list[dict[str, Any]]) -> list[AttachmentValidation]:
    """Valida lista de attachments via HTTP requests.

    :param attachments: Lista de attachments do DB
    :return: Lista de AttachmentValidation com resultados
    """
    validations: list[AttachmentValidation] = []

    for idx, att in enumerate(attachments, 1):
        url = att["attachment_link"]
        log.info(
            f"[{idx}/{len(attachments)}] Validando attachment_id={att['attachment_id']} — {att['filename']}"
        )

        status, is_ok, error, elapsed = validate_attachment_url(url)

        validation = AttachmentValidation(
            account_id=att["account_id"],
            account_name=att["account_name"],
            inbox_id=att["inbox_id"],
            inbox_name=att["inbox_name"],
            conversation_id=att["conversation_id"],
            conversation_display=att["conversation_display"],
            message_id=att["message_id"],
            attachment_id=att["attachment_id"],
            blob_key=att["blob_key"],
            filename=att["filename"],
            content_type=att["content_type"],
            byte_size=att["byte_size"],
            message_created_at=str(att["message_created_at"]),
            attachment_link=url,
            http_status=status,
            http_ok=is_ok,
            error_message=error,
            response_time_ms=elapsed,
        )

        validations.append(validation)

    return validations


def generate_report(
    validations: list[AttachmentValidation],
    instance_name: str,
    account_id: int,
    account_name: str,
    date_range: tuple[str, str],
    limit: int,
    offset: int,
    total_attachments: int | None,
    total_with_blob: int | None,
) -> ValidationReport:
    """Gera relatório consolidado.

    :param validations: Lista de validações realizadas
    :param instance_name: Nome da instância
    :param account_id: ID da account validada
    :param account_name: Nome da account
    :param date_range: Tupla (date_start, date_end)
    :param limit: Limite aplicado
    :param offset: Offset aplicado
    :param total_attachments: Total de attachments na account
    :param total_with_blob: Total com blob S3
    :return: ValidationReport com métricas
    """
    success_count = sum(1 for v in validations if v.http_ok)
    failed_count = len(validations) - success_count
    success_rate = (success_count / len(validations) * 100) if validations else 0.0

    failed_attachments = [asdict(v) for v in validations if not v.http_ok]

    return ValidationReport(
        timestamp=datetime.now().isoformat(),
        instance_name=instance_name,
        account_id=account_id,
        account_name=account_name,
        date_range=date_range,
        limit=limit,
        offset=offset,
        total_attachments_account=total_attachments,
        total_with_blob=total_with_blob,
        validated_count=len(validations),
        success_count=success_count,
        failed_count=failed_count,
        success_rate=round(success_rate, 2),
        validations=[asdict(v) for v in validations],
        failed_attachments=failed_attachments,
    )


# =============================================================================
# Funções de Output
# =============================================================================
def save_json_report(report: ValidationReport, output_dir: Path) -> Path:
    """Salva relatório em formato JSON.

    :param report: ValidationReport a salvar
    :param output_dir: Diretório de saída
    :return: Path do arquivo criado
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"check_s3_attachments_{timestamp}.json"
    output_dir.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(asdict(report), f, indent=2, ensure_ascii=False, default=str)

    return output_path


def save_markdown_report(report: ValidationReport, output_dir: Path) -> Path:
    """Salva relatório em formato Markdown.

    :param report: ValidationReport a salvar
    :param output_dir: Diretório de saída
    :return: Path do arquivo criado
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"check_s3_attachments_{timestamp}.md"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Gerar conteúdo Markdown
    content = f"""# Relatório de Validação S3 Attachments

**Timestamp**: {report.timestamp}
**Instância**: `{report.instance_name}`
**Account**: {report.account_name} (ID: {report.account_id})

---

## 📊 Estatísticas Gerais

| Métrica | Valor |
|---------|-------|
| Total attachments na account | {report.total_attachments_account or "N/A"} |
| Total com blob S3 válido | {report.total_with_blob or "N/A"} |
| Range de datas | {report.date_range[0]} → {report.date_range[1]} |
| Limite aplicado | {report.limit} |
| Offset | {report.offset} |

---

## ✅ Resultados da Validação

| Métrica | Valor |
|---------|-------|
| **Total validado** | **{report.validated_count}** |
| ✅ Sucesso (HTTP 200) | {report.success_count} |
| ❌ Falhas | {report.failed_count} |
| **Taxa de sucesso** | **{report.success_rate}%** |

---
"""

    # Adicionar seção de falhas se existirem
    if report.failed_count > 0:
        content += f"""## ❌ Attachments com Falha ({report.failed_count})

| Attachment ID | Filename | Content Type | Error | Blob Key |
|--------------|----------|--------------|-------|----------|
"""
        for failed in report.failed_attachments[:50]:  # Limitar a 50 para não poluir
            content += (
                f"| {failed['attachment_id']} | "
                f"{failed['filename'][:40]} | "
                f"{failed['content_type']} | "
                f"{failed['error_message']} | "
                f"`{failed['blob_key'][:40]}...` |\n"
            )

        if len(report.failed_attachments) > 50:
            content += (
                f"\n*... e mais {len(report.failed_attachments) - 50} falhas (ver JSON completo)*\n"
            )

    else:
        content += """## ✅ Homologação Aprovada

**Todos os attachments validados estão acessíveis via HTTP 200!**

"""

    content += f"""
---

## 📁 Arquivos Gerados

- **JSON completo**: `check_s3_attachments_{timestamp}.json`
- **Markdown (este arquivo)**: `check_s3_attachments_{timestamp}.md`

---

*Gerado por `scripts/check_s3_attachments.py` em {report.timestamp}*
"""

    with output_path.open("w", encoding="utf-8") as f:
        f.write(content)

    return output_path


# =============================================================================
# CLI Parser
# =============================================================================
def create_parser() -> argparse.ArgumentParser:
    """Cria parser de argumentos CLI.

    :return: ArgumentParser configurado
    """
    parser = argparse.ArgumentParser(
        description="Valida acessibilidade de attachments S3 pós-migração",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos de uso:

  # Validar 100 attachments da account 1 (últimos 30 dias)
  python scripts/check_s3_attachments.py \\
      --instance chatwoot004_dev \\
      --account-id 1 \\
      --limit 100 \\
      --date-start 2026-04-14 \\
      --date-end 2026-05-14

  # Validar 1000 attachments de 2026 com offset
  python scripts/check_s3_attachments.py \\
      --instance chatwoot004_dev \\
      --account-id 46 \\
      --limit 1000 \\
      --offset 1000 \\
      --date-start 2026-01-01 \\
      --date-end 2026-12-31

Instâncias disponíveis (definidas em .secrets/generate_erd.json):
  - chatwoot_dev (SOURCE DB)
  - chatwoot004_dev (DEST DB)
  - chat.vya.digital (PROD SOURCE)
        """,
    )

    parser.add_argument(
        "--instance",
        required=True,
        help="Nome da instância em .secrets/generate_erd.json (ex: chatwoot004_dev)",
    )

    parser.add_argument(
        "--account-id",
        type=int,
        required=True,
        help="ID da account a validar",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Número de attachments a validar (default: 100)",
    )

    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Offset para paginação (default: 0)",
    )

    parser.add_argument(
        "--date-start",
        required=True,
        help="Data inicial do range (formato: YYYY-MM-DD)",
    )

    parser.add_argument(
        "--date-end",
        required=True,
        help="Data final do range (formato: YYYY-MM-DD)",
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".tmp"),
        help="Diretório de saída para relatórios (default: .tmp)",
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=10,
        help="Timeout HTTP em segundos (default: 10)",
    )

    return parser


# =============================================================================
# Main
# =============================================================================
def main() -> int:
    """Executa validação de attachments S3.

    :return: Exit code (0=success, 1=error, 2=validation_failed)
    """
    parser = create_parser()
    args = parser.parse_args()

    log.info("=" * 80)
    log.info("CHECK S3 ATTACHMENTS — Validação de Acessibilidade")
    log.info("=" * 80)
    log.info(f"Instância: {args.instance}")
    log.info(f"Account ID: {args.account_id}")
    log.info(f"Limit: {args.limit} | Offset: {args.offset}")
    log.info(f"Date Range: {args.date_start} → {args.date_end}")
    log.info("")

    # 1. Carregar configuração de conexão
    log.info("1/5 — Carregando configuração de conexão...")
    try:
        config = load_connection_config(args.instance)
        log.info(f"✅ Configuração carregada: {config['database']} @ {config['host']}")
    except (FileNotFoundError, KeyError, ValueError) as e:
        log.error(f"❌ Erro ao carregar configuração: {e}")
        return 1

    # 2. Criar engine
    log.info("")
    log.info("2/5 — Criando engine de conexão...")
    try:
        engine = create_engine_from_config(config)
        # Test connection
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        log.info("✅ Conexão estabelecida")
    except Exception as e:
        log.error(f"❌ Erro ao conectar ao banco: {e}")
        return 1

    # 3. Buscar estatísticas da account
    log.info("")
    log.info("3/5 — Buscando estatísticas da account...")
    try:
        account_name, total_attachments, total_with_blob = fetch_account_stats(
            engine, args.account_id
        )
        log.info(f"📊 Account: {account_name} (ID {args.account_id})")
        log.info(f"📊 Total attachments: {total_attachments}")
        log.info(f"📊 Total com blob S3: {total_with_blob}")
    except ValueError as e:
        log.error(f"❌ {e}")
        return 1
    except Exception as e:
        log.error(f"❌ Erro ao buscar estatísticas: {e}")
        total_attachments = None
        total_with_blob = None
        account_name = f"Account {args.account_id}"

    # 4. Buscar attachments
    log.info("")
    log.info("4/5 — Buscando attachments do banco de dados...")
    try:
        attachments = fetch_attachments(
            engine,
            args.account_id,
            args.date_start,
            args.date_end,
            args.limit,
            args.offset,
        )
        log.info(f"✅ {len(attachments)} attachments encontrados no range especificado")

        if not attachments:
            log.warning("⚠️ Nenhum attachment encontrado no range. Encerrando.")
            return 0
    except Exception as e:
        log.error(f"❌ Erro ao buscar attachments: {e}")
        return 1

    # 5. Validar URLs
    log.info("")
    log.info("5/5 — Validando URLs de attachments via HTTP HEAD...")
    validations = validate_attachments(attachments)

    # 6. Gerar relatório
    log.info("")
    log.info("6/6 — Gerando relatórios...")
    report = generate_report(
        validations,
        args.instance,
        args.account_id,
        account_name,
        (args.date_start, args.date_end),
        args.limit,
        args.offset,
        total_attachments,
        total_with_blob,
    )

    # Salvar JSON
    json_path = save_json_report(report, args.output_dir)
    log.info(f"✅ JSON salvo: {json_path}")

    # Salvar Markdown
    md_path = save_markdown_report(report, args.output_dir)
    log.info(f"✅ Markdown salvo: {md_path}")

    # Resumo final
    log.info("")
    log.info("=" * 80)
    log.info("RESUMO DA VALIDAÇÃO")
    log.info("=" * 80)
    log.info(f"Account: {account_name} (ID {args.account_id})")
    log.info(f"Total validados:  {report.validated_count}")
    log.info(f"✅ Sucesso (200): {report.success_count}")
    log.info(f"❌ Falhas:        {report.failed_count}")
    log.info(f"📊 Taxa sucesso:  {report.success_rate}%")
    log.info("")

    if report.failed_count > 0:
        log.warning("⚠️ ATENÇÃO: Attachments com falha detectados!")
        log.warning(f"Detalhes completos em: {json_path}")
        log.warning(f"Resumo executivo em: {md_path}")
        log.warning("")
        log.warning("Primeiras 5 falhas:")
        for idx, failed in enumerate(report.failed_attachments[:5], 1):
            log.warning(
                f"  [{idx}] ID={failed['attachment_id']} | "
                f"{failed['filename']} | Error: {failed['error_message']}"
            )
        if len(report.failed_attachments) > 5:
            log.warning(f"  ... e mais {len(report.failed_attachments) - 5} falhas")
    else:
        log.info("✅ HOMOLOGAÇÃO APROVADA: Todos os attachments acessíveis!")

    log.info("=" * 80)

    # Exit code: 0=success, 2=validation_failed
    return 0 if report.success_rate == 100.0 else 2


if __name__ == "__main__":
    sys.exit(main())
