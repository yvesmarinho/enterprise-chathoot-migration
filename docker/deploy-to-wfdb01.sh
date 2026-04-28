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
#   ./docker/deploy-to-wfdb01.sh --build --all        # rsync + build + inicia migração em BACKGROUND no wfdb01
#   ./docker/deploy-to-wfdb01.sh --build --run        # rsync + build + run interativo (bloqueia SSH)
#
# Com --all, o processo de migração é iniciado em background no wfdb01 e NÃO
# depende desta máquina. O SSH é aberto apenas para lançar o nohup e retorna
# imediatamente. Para acompanhar:
#   fwknop --rc-file ~/.fwknoprc -n wfdb01 && sleep 3
#   ssh -p 5010 archaris@wfdb01.vya.digital 'tail -f ~/chatwoot-migration/logs/migration_all_latest.log'
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

# --- run (uma account específica) — foreground OK para tarefas curtas --------
if [[ "${RUN}" == "true" ]]; then
    knock
    echo "→ Executando migração em ${WFDB01_HOST} (account: ${ACCOUNT_NAME})..."
    ssh_run "cd ${REMOTE_DIR} && ACCOUNT_NAME='${ACCOUNT_NAME}' docker compose -f docker/docker-compose.yml run --rm migrator"
    echo "✅ Migração executada"
fi

# --- run all — container DETACHED (independente do SSH) -----------------------
# Usa docker compose run -d para que o processo continue após fechar o SSH.
# Logs: docker logs -f <container> | arquivo em app/logs/ (volume montado)
if [[ "${RUN_ALL}" == "true" ]]; then
    CONTAINER="chatwoot-migrator-all"
    knock
    echo "→ Iniciando migração COMPLETA em ${WFDB01_HOST}..."
    echo "  Container: ${CONTAINER}"
    echo "  Modo: detached (independente do SSH)"

    # Remove container anterior (se existir parado) e inicia novo em background
    ssh_run "
        cd ${REMOTE_DIR}
        docker rm -f '${CONTAINER}' 2>/dev/null || true
        docker compose -f docker/docker-compose.yml run \
            -d \
            --name '${CONTAINER}' \
            -e ALL_ACCOUNTS=true \
            -e DRY_RUN=false \
            migrator
    "
    echo ""
    echo "✅ Container iniciado: ${CONTAINER}"
    echo ""
    echo "Para acompanhar (abra nova conexão SSH):"
    echo "  fwknop --rc-file ${WFDB01_FWKNOP_RC} -n ${WFDB01_FWKNOP_N} && sleep ${FWKNOP_SLEEP}"
    echo "  ssh -p ${WFDB01_PORT} ${WFDB01_USER}@${WFDB01_HOST}"
    echo "  docker logs -f ${CONTAINER}"
    echo ""
    echo "Log em arquivo (volume montado):"
    echo "  tail -f ${REMOTE_DIR}/app/logs/migration_all_latest.log"
fi

# --- hints de uso -------------------------------------------------------
echo ""
echo "Comandos úteis no wfdb01:"
echo "  fwknop --rc-file ~/.fwknoprc -n wfdb01 && sleep 3"
echo "  ssh -p ${WFDB01_PORT} ${WFDB01_USER}@${WFDB01_HOST}"
echo "  cd ${REMOTE_DIR}"
echo ""
echo "  docker ps                                           # ver containers rodando"
echo "  docker logs -f chatwoot-migrator-all               # seguir log migração"
echo "  tail -f app/logs/migration_all_latest.log          # log em arquivo"
echo "  ls -lh .tmp/migrate_all_*.json                     # relatório final"
echo ""
echo "  # Build manual:"
echo "  docker compose -f docker/docker-compose.yml build"
echo ""
echo "  # Migrar um account específico (interativo):"
echo "  ACCOUNT_NAME='Sol Copernico' docker compose -f docker/docker-compose.yml run --rm migrator"
echo ""
echo "  # Dry-run completo:"
echo "  docker compose -f docker/docker-compose.yml run --rm -e ALL_ACCOUNTS=true -e DRY_RUN=true migrator"
echo ""
echo "  # Script avulso:"
echo "  docker compose -f docker/docker-compose.yml run --rm -e SCRIPT=13_migrar_inbox_members.py migrator"
