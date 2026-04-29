"""
Script para verificar versões do Chatwoot em ambas as instâncias.

:description: Consulta as tabelas ``schema_migrations`` e ``ar_internal_metadata``
    de chatwoot_dev1_db e chatwoot004_dev1_db para identificar a versão de schema
    (migration version) de cada instância. Não altera nenhum dado.

:usage:
    python scripts/check_chatwoot_versions.py

:prerequisite: Credenciais em ``.secrets/generate_erd.json``

:doctest:
    >>> import json
    >>> from pathlib import Path
    >>> Path('.secrets/generate_erd.json').exists()
    True
"""

import json
import sys
from pathlib import Path

try:
    import psycopg2
    from psycopg2 import sql
except ImportError:
    print("❌ psycopg2 não encontrado. Execute: pip install psycopg2-binary")
    sys.exit(1)


SECRETS_FILE = Path(__file__).parent.parent / ".secrets" / "generate_erd.json"

INSTANCES = ["chatwoot_dev", "chatwoot004_dev"]


def load_credentials(secrets_path: Path) -> dict:
    """
    Carrega credenciais do arquivo de segredos.

    :param secrets_path: Caminho para o arquivo JSON de credenciais.
    :type secrets_path: Path
    :returns: Dicionário com credenciais por instância.
    :rtype: dict
    :raises FileNotFoundError: Se o arquivo não existir.
    :raises KeyError: Se campos obrigatórios estiverem ausentes.
    """
    if not secrets_path.exists():
        raise FileNotFoundError(
            f"Arquivo de credenciais não encontrado: {secrets_path}\n"
            "Consulte .secrets/README.md para instruções."
        )
    with secrets_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data


def get_connection(creds: dict):
    """
    Cria conexão PostgreSQL a partir das credenciais.

    :param creds: Dicionário com host, port, database, username, password.
    :type creds: dict
    :returns: Conexão psycopg2.
    """
    ssl_enabled = creds.get("SSL", True)
    sslmode = "disable" if not ssl_enabled else "require"

    return psycopg2.connect(
        host=creds["host"],
        port=int(creds["port"]),
        dbname=creds["database"],
        user=creds["username"],
        password=creds["password"],
        connect_timeout=10,
        sslmode=sslmode,
    )


def get_schema_version(conn) -> dict:
    """
    Consulta a versão de schema e metadados da instância.

    :param conn: Conexão psycopg2 ativa.
    :returns: Dicionário com versão do schema e metadados.
    :rtype: dict
    """
    result = {}
    cur = conn.cursor()

    # 1) schema_migrations — última versão aplicada
    try:
        cur.execute(
            "SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1;"
        )
        row = cur.fetchone()
        result["last_migration_version"] = row[0] if row else "tabela vazia"
    except Exception as e:
        result["last_migration_version"] = f"erro: {e}"

    # 2) count de migrations aplicadas
    try:
        cur.execute("SELECT COUNT(*) FROM schema_migrations;")
        row = cur.fetchone()
        result["total_migrations"] = row[0] if row else 0
    except Exception as e:
        result["total_migrations"] = f"erro: {e}"

    # 3) ar_internal_metadata — versão da aplicação (Rails app version)
    try:
        cur.execute(
            "SELECT key, value FROM ar_internal_metadata WHERE key IN ('schema_sha1','environment','app_version') LIMIT 10;"
        )
        rows = cur.fetchall()
        result["ar_internal_metadata"] = {k: v for k, v in rows} if rows else {}
    except Exception as e:
        result["ar_internal_metadata"] = f"tabela não encontrada ou erro: {e}"

    # 4) Contagem de registros em tabelas principais
    tables = [
        "accounts",
        "contacts",
        "conversations",
        "messages",
        "inboxes",
        "users",
        "teams",
        "labels",
        "attachments",
    ]
    counts = {}
    for table in tables:
        try:
            cur.execute(
                sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(table))
            )
            row = cur.fetchone()
            counts[table] = row[0] if row else 0
        except Exception:
            counts[table] = "N/A"
    result["record_counts"] = counts

    cur.close()
    return result


def print_report(instance_name: str, db_name: str, data: dict) -> None:
    """
    Imprime relatório da instância sem expor dados sensíveis.

    :param instance_name: Nome da instância (ex: chatwoot_dev).
    :param db_name: Nome do banco de dados.
    :param data: Dicionário com dados coletados.
    """
    print(f"\n{'=' * 60}")
    print(f"  Instância : {instance_name}")
    print(f"  Banco     : {db_name}")
    print(f"{'=' * 60}")
    print(f"  Última migration : {data.get('last_migration_version', 'N/A')}")
    print(f"  Total migrations : {data.get('total_migrations', 'N/A')}")

    meta = data.get("ar_internal_metadata", {})
    if isinstance(meta, dict):
        for k, v in meta.items():
            print(f"  {k:<22}: {v}")
    else:
        print(f"  ar_internal_metadata: {meta}")

    print("\n  Contagem de registros:")
    counts = data.get("record_counts", {})
    for table, count in counts.items():
        print(f"    {table:<20}: {count:>10}")


def main() -> None:
    """
    Entrada principal do script de verificação de versões.

    :raises SystemExit: Em caso de falha de conexão ou credenciais ausentes.
    """
    print("🔍 Verificando versões do Chatwoot nas instâncias DEV...")
    print(f"   Credenciais: {SECRETS_FILE}")

    try:
        all_creds = load_credentials(SECRETS_FILE)
    except FileNotFoundError as e:
        print(f"\n❌ {e}")
        sys.exit(1)

    for instance_name in INSTANCES:
        if instance_name not in all_creds:
            print(f"\n⚠️  Instância '{instance_name}' não encontrada em {SECRETS_FILE}")
            continue

        creds = all_creds[instance_name]
        db_name = creds.get("database", instance_name)

        try:
            conn = get_connection(creds)
            data = get_schema_version(conn)
            conn.close()
            print_report(instance_name, db_name, data)
        except psycopg2.OperationalError as e:
            print(f"\n❌ Falha ao conectar em '{instance_name}': {e}")
        except Exception as e:
            print(f"\n❌ Erro inesperado em '{instance_name}': {type(e).__name__}: {e}")

    print(f"\n{'=' * 60}")
    print("  Verificação concluída.")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
