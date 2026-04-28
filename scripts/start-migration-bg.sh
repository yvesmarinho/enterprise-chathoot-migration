#!/bin/bash
# scripts/start-migration-bg.sh
# Inicia a migração completa em background no wfdb01.
#
# Execute DIRETAMENTE no wfdb01 (sem depender do computador de origem):
#   cd ~/chatwoot-migration
#   bash scripts/start-migration-bg.sh
#
# O processo Docker continua rodando mesmo após fechar o terminal SSH.
# O log é escrito em: logs/migration_all_YYYYMMDD_HHMMSS.log
#
# Para acompanhar após iniciar:
#   tail -f ~/chatwoot-migration/logs/migration_all_*.log
#
# Para verificar se ainda está rodando:
#   ps aux | grep migrat
#   docker ps

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REMOTE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOGFILE="${REMOTE_DIR}/logs/migration_all_${TIMESTAMP}.log"
PIDFILE="${REMOTE_DIR}/.tmp/migrator.pid"
LATEST_LINK="${REMOTE_DIR}/logs/migration_all_latest.log"

mkdir -p "${REMOTE_DIR}/logs" "${REMOTE_DIR}/.tmp"

# ── Verificar se já existe migração rodando ──────────────────────────────────
if [[ -f "${PIDFILE}" ]]; then
    EXISTING_PID="$(cat "${PIDFILE}")"
    if kill -0 "${EXISTING_PID}" 2>/dev/null; then
        echo "⚠️  Migração já está rodando (PID: ${EXISTING_PID})"
        echo "   Log atual: ${LATEST_LINK}"
        echo "   Para acompanhar: tail -f ${LATEST_LINK}"
        echo "   Para forçar novo início: rm ${PIDFILE} && bash $0"
        exit 1
    else
        echo "→ PID ${EXISTING_PID} não está ativo — iniciando nova execução..."
        rm -f "${PIDFILE}"
    fi
fi

echo "======================================================================"
echo "  Migração COMPLETA — background (wfdb01)"
echo "  Host    : $(hostname)"
echo "  Dir     : ${REMOTE_DIR}"
echo "  Início  : $(date '+%Y-%m-%d %H:%M:%S')"
echo "  Log     : ${LOGFILE}"
echo "======================================================================"

# ── Lançar em background com nohup ──────────────────────────────────────────
nohup bash -c "
    cd '${REMOTE_DIR}'
    ALL_ACCOUNTS=true docker compose -f docker/docker-compose.yml run --rm migrator
    echo ''
    echo '=== PROCESSO ENCERRADO: \$(date \"+%Y-%m-%d %H:%M:%S\") ==='
" > "${LOGFILE}" 2>&1 &

PID=$!
echo "${PID}" > "${PIDFILE}"

# Symlink para "latest"
ln -sf "${LOGFILE}" "${LATEST_LINK}"

echo ""
echo "✅ Migração iniciada em background"
echo "   PID      : ${PID}"
echo "   Log      : ${LOGFILE}"
echo "   PID file : ${PIDFILE}"
echo ""
echo "Para acompanhar em tempo real:"
echo "  tail -f ${LATEST_LINK}"
echo ""
echo "Para verificar processo:"
echo "  ps aux | grep ${PID}"
echo "  docker ps"
echo ""
echo "Relatório JSON (após concluir):"
echo "  ls -lt ${REMOTE_DIR}/.tmp/migrate_all_*.json | head -1"
