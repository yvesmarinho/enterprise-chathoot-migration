#!/bin/bash
# scripts/start-migration-bg.sh
# Inicia a migração completa em background no wfdb01.
#
# Execute DIRETAMENTE no wfdb01 (não depende do computador de origem):
#   cd ~/chatwoot-migration
#   bash scripts/start-migration-bg.sh
#
# O container Docker roda de forma independente — fechar o terminal não para
# a migração. Para acompanhar: docker logs -f chatwoot-migrator-all
#
# Pré-requisito: docker build já executado (./docker/deploy-to-wfdb01.sh --build)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REMOTE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONTAINER="chatwoot-migrator-all"
COMPOSE_FILE="${REMOTE_DIR}/docker/docker-compose.yml"

echo "======================================================================"
echo "  Migração COMPLETA — container detached"
echo "  Host      : $(hostname)"
echo "  Dir       : ${REMOTE_DIR}"
echo "  Container : ${CONTAINER}"
echo "  Início    : $(date '+%Y-%m-%d %H:%M:%S')"
echo "======================================================================"

# ── Verificar se já está rodando ────────────────────────────────────────────
if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    echo "⚠️  Container '${CONTAINER}' já está rodando."
    echo "   Para acompanhar: docker logs -f ${CONTAINER}"
    echo "   Para parar: docker stop ${CONTAINER}"
    exit 1
fi

# ── Remover container anterior parado (se houver) ───────────────────────────
docker rm -f "${CONTAINER}" 2>/dev/null || true

# ── Iniciar container em background ─────────────────────────────────────────
cd "${REMOTE_DIR}"
docker compose -f "${COMPOSE_FILE}" run \
    -d \
    --name "${CONTAINER}" \
    -e ALL_ACCOUNTS=true \
    -e DRY_RUN=false \
    migrator

echo ""
echo "✅ Container '${CONTAINER}' iniciado"
echo ""
echo "Acompanhar log em tempo real:"
echo "  docker logs -f ${CONTAINER}"
echo ""
echo "Log em arquivo (volume montado):"
echo "  tail -f ${REMOTE_DIR}/app/logs/migration_all_latest.log"
echo ""
echo "Verificar status:"
echo "  docker ps --filter name=${CONTAINER}"
echo ""
echo "Relatório final (após concluir):"
echo "  ls -lh ${REMOTE_DIR}/.tmp/migrate_all_*.json"

