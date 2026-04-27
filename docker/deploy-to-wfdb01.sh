#!/bin/bash
# docker/deploy-to-wfdb01.sh
# Sincroniza o código para wfdb01 e (opcionalmente) executa o build.
#
# Uso:
#   ./docker/deploy-to-wfdb01.sh                      # só rsync
#   ./docker/deploy-to-wfdb01.sh --build              # rsync + docker build
#   ./docker/deploy-to-wfdb01.sh --build --run        # rsync + build + run
#
# Variáveis customizáveis:
#   WFDB01_HOST   Host de destino (padrão: wfdb01.vya.digital)
#   WFDB01_USER   Usuário SSH       (padrão: deploy)
#   REMOTE_DIR    Diretório remoto  (padrão: ~/chatwoot-migration)
#   ACCOUNT_NAME  Account a migrar  (padrão: "Vya Digital")

set -euo pipefail

WFDB01_HOST="${WFDB01_HOST:-wfdb01.vya.digital}"
WFDB01_USER="${WFDB01_USER:-deploy}"
REMOTE_DIR="${REMOTE_DIR:-~/chatwoot-migration}"
ACCOUNT_NAME="${ACCOUNT_NAME:-Vya Digital}"

BUILD=false
RUN=false

for arg in "$@"; do
    case "$arg" in
        --build) BUILD=true ;;
        --run)   RUN=true ;;
    esac
done

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "===================================================="
echo "  Deploy → ${WFDB01_USER}@${WFDB01_HOST}:${REMOTE_DIR}"
echo "===================================================="

# Sincroniza código (excluindo .venv, .git, __pycache__, .tmp)
rsync -avz --progress \
    --exclude='.venv/' \
    --exclude='.git/' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='.tmp/' \
    --exclude='.secrets/' \
    --exclude='app/logs/' \
    --exclude='node_modules/' \
    "${REPO_ROOT}/" \
    "${WFDB01_USER}@${WFDB01_HOST}:${REMOTE_DIR}/"

echo "✅ rsync concluído"

# Copia .secrets separadamente (permissão restrita)
echo "→ Sincronizando .secrets (chmod 600)..."
rsync -avz --chmod=D700,F600 \
    "${REPO_ROOT}/.secrets/" \
    "${WFDB01_USER}@${WFDB01_HOST}:${REMOTE_DIR}/.secrets/"

echo "✅ .secrets sincronizado"

if [[ "${BUILD}" == "true" ]]; then
    echo "→ Build da imagem Docker em ${WFDB01_HOST}..."
    ssh "${WFDB01_USER}@${WFDB01_HOST}" \
        "cd ${REMOTE_DIR} && docker compose -f docker/docker-compose.yml build"
    echo "✅ Build concluído"
fi

if [[ "${RUN}" == "true" ]]; then
    echo "→ Executando migração em ${WFDB01_HOST} (account: ${ACCOUNT_NAME})..."
    ssh "${WFDB01_USER}@${WFDB01_HOST}" \
        "cd ${REMOTE_DIR} && ACCOUNT_NAME='${ACCOUNT_NAME}' docker compose -f docker/docker-compose.yml run --rm migrator"
    echo "✅ Migração executada"
fi

echo ""
echo "Comandos úteis no wfdb01:"
echo "  cd ${REMOTE_DIR}"
echo "  docker compose -f docker/docker-compose.yml build"
echo "  docker compose -f docker/docker-compose.yml run --rm migrator"
echo "  docker compose -f docker/docker-compose.yml run --rm -e SCRIPT=13_migrar_inbox_members.py migrator"
