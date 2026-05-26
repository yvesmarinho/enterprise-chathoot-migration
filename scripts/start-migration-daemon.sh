#!/usr/bin/env bash
# scripts/start-migration-daemon.sh — Inicia migração em background (daemon)
#
# Uso:
#   ./scripts/start-migration-daemon.sh --env dev --account "Nome da Account"
#
# Cria PID file em .tmp/migration.pid
# Log salvo em .tmp/migration_daemon_YYYYMMDD_HHMMSS.log

set -euo pipefail

# Diretório raiz do projeto
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# Diretório de arquivos temporários
TMP_DIR="$PROJECT_ROOT/.tmp"
mkdir -p "$TMP_DIR"

# Arquivos de controle
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOGFILE="$TMP_DIR/migration_daemon_${TIMESTAMP}.log"
PIDFILE="$TMP_DIR/migration.pid"
STATUSFILE="$TMP_DIR/migration.status"

# Função de limpeza
cleanup() {
    rm -f "$PIDFILE"
}

# Verificar se já está rodando
if [[ -f "$PIDFILE" ]]; then
    OLD_PID=$(cat "$PIDFILE")
    if ps -p "$OLD_PID" > /dev/null 2>&1; then
        echo "❌ Migração já está rodando (PID: $OLD_PID)"
        echo "   Use './scripts/stop-migration.sh' para parar"
        exit 1
    else
        echo "⚠️  PID file antigo encontrado (processo morto) — removendo"
        rm -f "$PIDFILE"
    fi
fi

# Validar argumentos
if [[ $# -lt 2 ]]; then
    echo "❌ Uso: $0 --env <dev|prod> --account \"Nome da Account\""
    exit 1
fi

echo "═══════════════════════════════════════════════════════════════════"
echo "🚀 INICIANDO MIGRAÇÃO EM MODO DAEMON"
echo "═══════════════════════════════════════════════════════════════════"
echo ""
echo "Comando: uv run python -m src.migrar $*"
echo "Log:     $LOGFILE"
echo "PID:     $PIDFILE"
echo ""

# Executar em background com nohup
nohup uv run python -m src.migrar "$@" > "$LOGFILE" 2>&1 &
MIGRATION_PID=$!

# Salvar PID
echo "$MIGRATION_PID" > "$PIDFILE"

# Aguardar 2 segundos para verificar se iniciou corretamente
sleep 2

if ps -p "$MIGRATION_PID" > /dev/null 2>&1; then
    echo "✅ Migração iniciada com sucesso!"
    echo ""
    echo "   PID:        $MIGRATION_PID"
    echo "   Log:        $LOGFILE"
    echo ""
    echo "📊 Comandos úteis:"
    echo "   Monitorar:  ./scripts/monitor-migration.sh $LOGFILE"
    echo "   Status:     ps -p $MIGRATION_PID -o pid,cmd,%cpu,%mem,etime"
    echo "   Parar:      ./scripts/stop-migration.sh"
    echo ""

    # Salvar status
    cat > "$STATUSFILE" <<EOF
PID=$MIGRATION_PID
LOGFILE=$LOGFILE
STARTED=$(date -Iseconds)
COMMAND="uv run python -m src.migrar $*"
EOF

    echo "═══════════════════════════════════════════════════════════════════"
else
    echo "❌ Migração falhou ao iniciar!"
    echo ""
    echo "📄 Últimas 20 linhas do log:"
    tail -20 "$LOGFILE"
    cleanup
    exit 1
fi
