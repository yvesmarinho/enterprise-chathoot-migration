#!/usr/bin/env bash
# scripts/stop-migration.sh — Para migração daemon em execução
#
# Uso:
#   ./scripts/stop-migration.sh

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

PIDFILE=".tmp/migration.pid"
STATUSFILE=".tmp/migration.status"

if [[ ! -f "$PIDFILE" ]]; then
    echo "❌ Nenhuma migração em execução (PID file não encontrado)"
    exit 1
fi

PID=$(cat "$PIDFILE")

if ! ps -p "$PID" > /dev/null 2>&1; then
    echo "⚠️  Processo $PID não está rodando (PID file órfão)"
    rm -f "$PIDFILE" "$STATUSFILE"
    exit 1
fi

echo "═══════════════════════════════════════════════════════════════════"
echo "🛑 PARANDO MIGRAÇÃO"
echo "═══════════════════════════════════════════════════════════════════"
echo ""

# Mostrar info do processo
ps -p "$PID" -o pid,cmd,%cpu,%mem,etime

echo ""
read -p "Confirmar parada do processo $PID? (y/N) " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelado pelo usuário"
    exit 0
fi

# Tentar SIGTERM primeiro (graceful)
echo "Enviando SIGTERM para PID $PID..."
kill -TERM "$PID" || true

# Aguardar 5 segundos
sleep 5

# Verificar se ainda está rodando
if ps -p "$PID" > /dev/null 2>&1; then
    echo "⚠️  Processo ainda ativo — enviando SIGKILL..."
    kill -KILL "$PID" || true
    sleep 1
fi

# Verificar novamente
if ps -p "$PID" > /dev/null 2>&1; then
    echo "❌ Falha ao parar processo $PID"
    exit 1
else
    echo "✅ Processo $PID parado com sucesso"
    rm -f "$PIDFILE" "$STATUSFILE"
    echo ""
    echo "═══════════════════════════════════════════════════════════════════"
fi
