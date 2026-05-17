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

MIGRATION_SOURCE_KEY="${MIGRATION_SOURCE_KEY:-}"
MIGRATION_DEST_KEY="${MIGRATION_DEST_KEY:-}"
ACCOUNT_NAME="${ACCOUNT_NAME:-Unimed Guaxupé}"
ALL_ACCOUNTS="${ALL_ACCOUNTS:-false}"
DRY_RUN="${DRY_RUN:-false}"
SCRIPT="${SCRIPT:-}"
# PIPELINE: "full" (src/migrar.py — teams, labels, attachments, etc.)
#         | "legacy" (app/01_migrar_account.py — contacts+conversations only)
# Padrão: "full" — pipeline completo e idempotente
PIPELINE="${PIPELINE:-full}"
# MIGRATION_ENV: "prod" | "dev" — atalho para as chaves SOURCE/DEST
# Ignorado se MIGRATION_SOURCE_KEY e MIGRATION_DEST_KEY já estiverem definidas.
MIGRATION_ENV="${MIGRATION_ENV:-}"

# Validação antecipada das keys obrigatórias
if [[ -z "${MIGRATION_SOURCE_KEY}" || -z "${MIGRATION_DEST_KEY}" ]]; then
    echo "[ERRO] MIGRATION_SOURCE_KEY e MIGRATION_DEST_KEY são obrigatórias."
    echo "  Produção : MIGRATION_SOURCE_KEY=chat-vya-digital  MIGRATION_DEST_KEY=synchat-vya-digital"
    echo "  Dev/teste: MIGRATION_SOURCE_KEY=chatwoot_dev       MIGRATION_DEST_KEY=chatwoot004_dev"
    exit 1
fi

cd /app

echo "========================================================"
echo "  enterprise-chatwoot-migration — Docker Runner"
echo "  SOURCE KEY   : ${MIGRATION_SOURCE_KEY}"
echo "  DEST KEY     : ${MIGRATION_DEST_KEY}"
echo "  ACCOUNT      : ${ACCOUNT_NAME}"
echo "  ALL_ACCOUNTS : ${ALL_ACCOUNTS}"
echo "  DRY_RUN      : ${DRY_RUN}"
echo "  PIPELINE     : ${PIPELINE}"
echo "  SCRIPT       : ${SCRIPT:-<padrão pelo PIPELINE>}"
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
    if [[ "${PIPELINE}" == "full" ]]; then
        echo "→ Migrando TODOS os accounts — pipeline completo (src/migrar.py)"
        echo "→ Log salvo em: ${LOG_FILE}"
        ARGS=()
        [[ "${DRY_RUN}" == "true" ]] && ARGS+=("--dry-run")
        [[ -n "${MIGRATION_ENV}" ]] && ARGS+=("--env" "${MIGRATION_ENV}")
        python src/migrar.py "${ARGS[@]}" 2>&1 | tee "${LOG_FILE}"
    else
        echo "→ Migrando TODOS os accounts — pipeline legado (migrate_all_accounts.py)"
        echo "→ Log salvo em: ${LOG_FILE}"
        ARGS=()
        [[ "${DRY_RUN}" == "true" ]] && ARGS+=("--dry-run")
        python app/migrate_all_accounts.py "${ARGS[@]}" 2>&1 | tee "${LOG_FILE}"
    fi
    exit ${PIPESTATUS[0]}
fi

# Pipeline de uma account específica
if [[ "${PIPELINE}" == "full" ]]; then
    echo "→ Pipeline completo: src/migrar.py (account: ${ACCOUNT_NAME})"
    ARGS=("--account" "${ACCOUNT_NAME}")
    [[ "${DRY_RUN}" == "true" ]] && ARGS+=("--dry-run")
    [[ -n "${MIGRATION_ENV}" ]] && ARGS+=("--env" "${MIGRATION_ENV}")
    exec python src/migrar.py "${ARGS[@]}"
else
    echo "→ Pipeline legado: app/01_migrar_account.py (account: ${ACCOUNT_NAME})"
    ARGS=("${ACCOUNT_NAME}")
    [[ "${DRY_RUN}" == "true" ]] && ARGS+=("--dry-run")
    exec python app/01_migrar_account.py "${ARGS[@]}"
fi
