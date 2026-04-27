#!/bin/bash
# docker/deploy-to-wfdb01.sh
# Sincroniza o código para wfdb01 e (opcionalmente) executa o build.
#
# Usa fwknop (Single Packet Authorization) para abrir a porta SSH antes de
# cada conexão — obrigatório pois a porta não fica exposta permanentemente.
#
# Uso:
#   ./docker/deploy-to-wfdb01.sh                      # só rsync
#   ./docker/deploy-to-wfdb01.sh --build              # rsync + docker build
#   ./docker/deploy-to-wfdb01.sh --build --run        # rsync + build + run
#
# Variáveis customizáveis:
#   WFDB01_HOST      Host de destino    (padrão: wfdb01.vya.digital)
#   WFDB01_USER      Usuário SSH        (padrão: archaris)
#   WFDB01_PORT      Porta SSH          (padrão: 5010)
#   WFDB01_FWKNOP_RC Arquivo rc fwknop  (padrão: ~/.fwknoprc)
#   WFDB01_FWKNOP_N  Nome da entrada rc (padrão: wfdb01)
#   FWKNOP_SLEEP     Segundos de espera após SPA (padrão: 3)
#   REMOTE_DIR       Diretório remoto   (padrão: ~/chatwoot-migration)
#   ACCOUNT_NAME     Account a migrar   (padrão: "Vya Digital")

set -euo pipefail

WFDB01_HOST="${WFDB01_HOST:-wfdb01.vya.digital}"
WFDB01_USER="${WFDB01_USER:-archaris}"
WFDB01_PORT="${WFDB01_PORT:-5010}"
WFDB01_FWKNOP_RC="${WFDB01_FWKNOP_RC:-${HOME}/.fwknoprc}"
WFDB01_FWKNOP_N="${WFDB01_FWKNOP_N:-wfdb01}"
FWKNOP_SLEEP="${FWKNOP_SLEEP:-3}"
REMOTE_DIR="${REMOTE_DIR:-~/chatwoot-migration}"
ACCOUNT_NAME="${ACCOUNT_NAME:-Vya Digital}"

SSH_OPTS="-p ${WFDB01_PORT} -o StrictHostKeyChecking=no -o ConnectTimeout=15"

BUILD=false
RUN=false
RUN_ALL=false

for arg in "$@"; do
    case "$arg" in
        --build) BUILD=true ;;
        --run)   RUN=true ;;
        --all)   RUN_ALL=true ;;
    esac
done

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Envia pacote SPA via fwknop e aguarda a porta abrir
knock() {
    echo "→ fwknop SPA para ${WFDB01_HOST} (entrada: ${WFDB01_FWKNOP_N})..."
    fwknop --rc-file "${WFDB01_FWKNOP_RC}" -n "${WFDB01_FWKNOP_N}"
    sleep "${FWKNOP_SLEEP}"
}

ssh_run() {
    # ssh_run "comando remoto"
    ssh ${SSH_OPTS} "${WFDB01_USER}@${WFDB01_HOST}" "$1"
}

# ---------------------------------------------------------------------------

echo "===================================================="
echo "  Deploy → ${WFDB01_USER}@${WFDB01_HOST}:${WFDB01_PORT}  dir:${REMOTE_DIR}"
echo "===================================================="

# --- rsync código --------------------------------------------------------
knock
echo "→ Sincronizando código..."
rsync -avz --progress \
    -e "ssh ${SSH_OPTS}" \
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
echo "✅ rsync código concluído"

# --- rsync .secrets ------------------------------------------------------
knock
echo "→ Sincronizando .secrets (chmod 600)..."
rsync -avz --chmod=D700,F600 \
    -e "ssh ${SSH_OPTS}" \
    "${REPO_ROOT}/.secrets/" \
    "${WFDB01_USER}@${WFDB01_HOST}:${REMOTE_DIR}/.secrets/"
echo "✅ .secrets sincronizado"

# --- build ---------------------------------------------------------------
if [[ "${BUILD}" == "true" ]]; then
    knock
    echo "→ Build da imagem Docker em ${WFDB01_HOST}..."
    ssh_run "cd ${REMOTE_DIR} && docker compose -f docker/docker-compose.yml build"
    echo "✅ Build concluído"
fi

# --- run (uma account específica) ----------------------------------------
if [[ "${RUN}" == "true" ]]; then
    knock
    echo "→ Executando migração em ${WFDB01_HOST} (account: ${ACCOUNT_NAME})..."
    ssh_run "cd ${REMOTE_DIR} && ACCOUNT_NAME='${ACCOUNT_NAME}' docker compose -f docker/docker-compose.yml run --rm migrator"
    echo "✅ Migração executada"
fi

# --- run all (todos os accounts em sequência) ----------------------------
if [[ "${RUN_ALL}" == "true" ]]; then
    knock
    echo "→ Executando migração COMPLETA em ${WFDB01_HOST} (TODOS os accounts)..."
    ssh_run "cd ${REMOTE_DIR} && ALL_ACCOUNTS=true docker compose -f docker/docker-compose.yml run --rm migrator"
    echo "✅ Migração completa executada"
fi

echo ""
echo "Comandos úteis no wfdb01 (após fwknop):"
echo "  fwknop --rc-file ~/.fwknoprc -n wfdb01 && sleep 3"
echo "  ssh -p ${WFDB01_PORT} ${WFDB01_USER}@${WFDB01_HOST}"
echo "  cd ${REMOTE_DIR}"
echo "  # Build:"
echo "  docker compose -f docker/docker-compose.yml build"
echo "  # Migrar TODOS os accounts (uso principal):"
echo "  ALL_ACCOUNTS=true docker compose -f docker/docker-compose.yml run --rm migrator"
echo "  # Migrar uma account específica:"
echo "  ACCOUNT_NAME='Sol Copernico' docker compose -f docker/docker-compose.yml run --rm migrator"
echo "  # Dry-run completo (sem gravar nada):"
echo "  ALL_ACCOUNTS=true DRY_RUN=true docker compose -f docker/docker-compose.yml run --rm migrator"
echo "  # Script avulso:"
echo "  docker compose -f docker/docker-compose.yml run --rm -e SCRIPT=13_migrar_inbox_members.py migrator"
