#!/bin/bash
# entrypoint.sh — executa o pipeline de migração ou um comando customizado
#
# Variáveis de ambiente:
#   ACCOUNT_NAME   Nome da account a migrar (padrão: "Vya Digital")
#   ALL_ACCOUNTS   Se "true", migra TODOS os accounts em sequência (ignora ACCOUNT_NAME)
#   DRY_RUN        Se "true", executa em modo dry-run (padrão: false)
#   SCRIPT         Script alternativo em app/ a executar (opcional)
#                  Ex: SCRIPT=13_migrar_inbox_members.py
#
# Uso típico (via docker-compose run):
#   docker compose run --rm migrator                                          # Vya Digital
#   docker compose run --rm -e ACCOUNT_NAME="Sol Copernico" migrator          # uma account
#   docker compose run --rm -e ALL_ACCOUNTS=true migrator                     # todos
#   docker compose run --rm -e ALL_ACCOUNTS=true -e DRY_RUN=true migrator     # todos dry-run
#   docker compose run --rm -e SCRIPT=13_migrar_inbox_members.py migrator     # script avulso

set -euo pipefail

ACCOUNT_NAME="${ACCOUNT_NAME:-Vya Digital}"
ALL_ACCOUNTS="${ALL_ACCOUNTS:-false}"
DRY_RUN="${DRY_RUN:-false}"
SCRIPT="${SCRIPT:-}"

cd /app

echo "========================================================"
echo "  enterprise-chathoot-migration — Docker Runner"
echo "  ACCOUNT      : ${ACCOUNT_NAME}"
echo "  ALL_ACCOUNTS : ${ALL_ACCOUNTS}"
echo "  DRY_RUN      : ${DRY_RUN}"
echo "  SCRIPT       : ${SCRIPT:-01_migrar_account.py (default)}"
echo "========================================================"

# Script customizado tem prioridade máxima
if [[ -n "${SCRIPT}" ]]; then
    echo "→ Executando script customizado: app/${SCRIPT}"
    exec python "app/${SCRIPT}" "$@"
fi

# Migração de TODOS os accounts
if [[ "${ALL_ACCOUNTS}" == "true" ]]; then
    LOG_FILE="/app/app/logs/migration_all_$(date +%Y%m%d_%H%M%S).log"
    mkdir -p /app/app/logs
    # Symlink "latest" para facilitar tail -f
    ln -sf "${LOG_FILE}" /app/app/logs/migration_all_latest.log
    echo "→ Migrando TODOS os accounts (migrate_all_accounts.py)"
    echo "→ Log salvo em: ${LOG_FILE}"
    ARGS=()
    [[ "${DRY_RUN}" == "true" ]] && ARGS+=("--dry-run")
    # tee: exibe no stdout (docker logs) e salva em arquivo no volume montado
    python app/migrate_all_accounts.py "${ARGS[@]}" 2>&1 | tee "${LOG_FILE}"
    exit ${PIPESTATUS[0]}
fi

# Pipeline de uma account específica
ARGS=("${ACCOUNT_NAME}")
[[ "${DRY_RUN}" == "true" ]] && ARGS+=("--dry-run")
exec python app/01_migrar_account.py "${ARGS[@]}"
