#!/bin/bash
# entrypoint.sh — executa o pipeline de migração ou um comando customizado
#
# Variáveis de ambiente:
#   ACCOUNT_NAME   Nome da account a migrar (obrigatório)
#   DRY_RUN        Se "true", executa em modo dry-run (padrão: false)
#   SCRIPT         Script alternativo em app/ a executar (opcional)
#                  Ex: SCRIPT=13_migrar_inbox_members.py
#
# Uso típico (via docker-compose run):
#   docker compose run --rm migrator
#   docker compose run --rm -e ACCOUNT_NAME="Vya Digital" migrator
#   docker compose run --rm -e SCRIPT=13_migrar_inbox_members.py migrator

set -euo pipefail

ACCOUNT_NAME="${ACCOUNT_NAME:-Vya Digital}"
DRY_RUN="${DRY_RUN:-false}"
SCRIPT="${SCRIPT:-}"

cd /app

echo "========================================================"
echo "  enterprise-chathoot-migration — Docker Runner"
echo "  ACCOUNT : ${ACCOUNT_NAME}"
echo "  DRY_RUN : ${DRY_RUN}"
echo "  SCRIPT  : ${SCRIPT:-01_migrar_account.py (default)}"
echo "========================================================"

if [[ -n "${SCRIPT}" ]]; then
    echo "→ Executando script customizado: app/${SCRIPT}"
    exec python "app/${SCRIPT}" "$@"
fi

# Pipeline principal
ARGS=("${ACCOUNT_NAME}")
if [[ "${DRY_RUN}" == "true" ]]; then
    ARGS+=("--dry-run")
fi

exec python app/01_migrar_account.py "${ARGS[@]}"
