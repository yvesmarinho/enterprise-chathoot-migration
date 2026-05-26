#!/usr/bin/env bash
# scripts/migration-status.sh — Mostra status da migração daemon
#
# Uso:
#   ./scripts/migration-status.sh

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

PIDFILE=".tmp/migration.pid"
STATUSFILE=".tmp/migration.status"

echo "═══════════════════════════════════════════════════════════════════"
echo "📊 STATUS DA MIGRAÇÃO"
echo "═══════════════════════════════════════════════════════════════════"
echo ""

if [[ ! -f "$PIDFILE" ]]; then
    echo "❌ Nenhuma migração em execução"
    echo ""

    # Procurar logs recentes
    RECENT_LOGS=$(ls -t .tmp/migration_*.log 2>/dev/null | head -3)
    if [[ -n "$RECENT_LOGS" ]]; then
        echo "📄 Logs recentes encontrados:"
        echo "$RECENT_LOGS" | while read -r log; do
            SIZE=$(du -h "$log" | cut -f1)
            MODIFIED=$(stat -c %y "$log" | cut -d'.' -f1)
            echo "   - $log ($SIZE, modificado: $MODIFIED)"
        done
    fi

    echo ""
    echo "═══════════════════════════════════════════════════════════════════"
    exit 0
fi

PID=$(cat "$PIDFILE")

if ! ps -p "$PID" > /dev/null 2>&1; then
    echo "⚠️  Processo $PID não está rodando (PID file órfão)"
    rm -f "$PIDFILE" "$STATUSFILE"
    exit 1
fi

echo "✅ Migração em execução"
echo ""

# Mostrar info do status file
if [[ -f "$STATUSFILE" ]]; then
    source "$STATUSFILE"
    echo "PID:           $PID"
    echo "Iniciado em:   $STARTED"
    echo "Log:           $LOGFILE"
    echo "Comando:       $COMMAND"
    echo ""
fi

# Mostrar info do processo
echo "───────────────────────────────────────────────────────────────────"
echo "PROCESSO"
echo "───────────────────────────────────────────────────────────────────"
ps -p "$PID" -o pid,ppid,%cpu,%mem,vsz,rss,etime,cmd --no-headers | \
    awk '{printf "PID:       %s\nPPID:      %s\nCPU:       %s%%\nMEM:       %s%%\nVSZ:       %s KB\nRSS:       %s KB\nTempo:     %s\nComando:   %s\n", $1,$2,$3,$4,$5,$6,$7,$8}'

echo ""

# Analisar log para mostrar progresso
if [[ -f "$LOGFILE" ]]; then
    echo "───────────────────────────────────────────────────────────────────"
    echo "PROGRESSO"
    echo "───────────────────────────────────────────────────────────────────"

    # Última tabela iniciada
    CURRENT_TABLE=$(grep ">>> Iniciando migração:" "$LOGFILE" | tail -1 | awk -F': ' '{print $2}' || echo "N/A")
    echo "Tabela atual:  $CURRENT_TABLE"

    # Contar tabelas completas
    COMPLETED=$(grep -c "complete — migrated=" "$LOGFILE" || echo "0")
    echo "Completas:     $COMPLETED"

    # Erros e warnings
    ERRORS=$(grep -c "ERROR" "$LOGFILE" || echo "0")
    WARNINGS=$(grep -c "WARNING" "$LOGFILE" || echo "0")
    echo "Erros:         $ERRORS"
    echo "Warnings:      $WARNINGS"

    echo ""
    echo "Última atividade:"
    grep -E "INFO|ERROR|WARNING" "$LOGFILE" | tail -3 | sed 's/^/   /'

    echo ""
    echo "Tamanho do log: $(du -h "$LOGFILE" | cut -f1)"
fi

echo ""
echo "═══════════════════════════════════════════════════════════════════"
echo ""
echo "📊 Comandos úteis:"
echo "   Monitorar:  ./scripts/monitor-migration.sh"
echo "   Parar:      ./scripts/stop-migration.sh"
echo ""
