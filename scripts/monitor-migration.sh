#!/usr/bin/env bash
# scripts/monitor-migration.sh — Monitora log de migração em tempo real
#
# Uso:
#   ./scripts/monitor-migration.sh [LOGFILE]
#
# Se LOGFILE não fornecido, usa o mais recente em .tmp/migration_*.log

set -euo pipefail

LOGFILE="${1:-}"

# Se não fornecido, pegar o mais recente
if [[ -z "$LOGFILE" ]]; then
    LOGFILE=$(ls -t .tmp/migration_*.log 2>/dev/null | head -1)
    if [[ -z "$LOGFILE" ]]; then
        echo "❌ Nenhum log de migração encontrado em .tmp/migration_*.log"
        exit 1
    fi
    echo "📄 Monitorando: $LOGFILE"
fi

if [[ ! -f "$LOGFILE" ]]; then
    echo "❌ Arquivo não encontrado: $LOGFILE"
    exit 1
fi

echo "═══════════════════════════════════════════════════════════════════"
echo "🔍 MONITOR DE MIGRAÇÃO — $(date '+%Y-%m-%d %H:%M:%S')"
echo "═══════════════════════════════════════════════════════════════════"
echo ""

# Função para exibir resumo do status
show_status() {
    echo ""
    echo "───────────────────────────────────────────────────────────────────"
    echo "📊 STATUS ATUAL ($(date '+%H:%M:%S'))"
    echo "───────────────────────────────────────────────────────────────────"

    # Última linha significativa
    LAST_LINE=$(grep -E "INFO|ERROR|WARNING" "$LOGFILE" | tail -1)
    echo "Última atividade: $LAST_LINE"

    # Contar erros
    ERROR_COUNT=$(grep -c "ERROR" "$LOGFILE" || echo "0")
    WARNING_COUNT=$(grep -c "WARNING" "$LOGFILE" || echo "0")

    echo ""
    echo "Erros:    $ERROR_COUNT"
    echo "Warnings: $WARNING_COUNT"

    # Tabela atual (se disponível)
    CURRENT_TABLE=$(grep ">>> Iniciando migração:" "$LOGFILE" | tail -1 | awk -F': ' '{print $2}')
    if [[ -n "$CURRENT_TABLE" ]]; then
        echo "Tabela:   $CURRENT_TABLE"
    fi

    echo "───────────────────────────────────────────────────────────────────"
}

# Mostrar status inicial
show_status

echo ""
echo "🔄 Acompanhando log em tempo real (Ctrl+C para sair)..."
echo ""

# Seguir log, filtrando apenas linhas importantes e destacando erros
tail -f "$LOGFILE" | while IFS= read -r line; do
    # Colorir erros em vermelho
    if echo "$line" | grep -q "ERROR"; then
        echo -e "\033[1;31m$line\033[0m"  # Vermelho bold
    # Colorir warnings em amarelo
    elif echo "$line" | grep -q "WARNING"; then
        echo -e "\033[1;33m$line\033[0m"  # Amarelo bold
    # Colorir sucessos em verde
    elif echo "$line" | grep -q "complete — migrated="; then
        echo -e "\033[1;32m$line\033[0m"  # Verde bold
    # Mostrar progresso de batches
    elif echo "$line" | grep -qE "batch [0-9]+/[0-9]+"; then
        echo "$line"
    # Mostrar início de tabelas
    elif echo "$line" | grep -q ">>> Iniciando migração:"; then
        echo -e "\033[1;36m$line\033[0m"  # Ciano bold
    # Filtrar DEBUG (não mostrar)
    elif echo "$line" | grep -q "DEBUG"; then
        : # Ignorar DEBUG
    # Mostrar INFO importantes
    elif echo "$line" | grep -qE "INFO.*starting|INFO.*fetched|INFO.*complete"; then
        echo "$line"
    fi
done
