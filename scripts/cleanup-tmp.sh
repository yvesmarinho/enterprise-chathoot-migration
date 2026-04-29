#!/usr/bin/env bash
# =============================================================================
# cleanup-tmp.sh — Limpa o diretório .tmp/ ao final de uma sessão
# =============================================================================
# Uso:
#   ./scripts/cleanup-tmp.sh              # remove os arquivos (padrão)
#   ./scripts/cleanup-tmp.sh --dry-run    # apenas lista o que seria removido
#   ./scripts/cleanup-tmp.sh --verbose    # remove e lista cada arquivo removido
#
# Preserva: .tmp/.gitkeep  (âncora para git)
# Remove:   todos os demais arquivos e subdiretórios em .tmp/
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
TMP_DIR="$ROOT_DIR/.tmp"

DRY_RUN=false
VERBOSE=false

for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=true ;;
        --verbose) VERBOSE=true ;;
        *)
            echo "Uso: $0 [--dry-run] [--verbose]" >&2
            exit 1
            ;;
    esac
done

if [[ ! -d "$TMP_DIR" ]]; then
    echo ".tmp/ não encontrado em $ROOT_DIR — nada a limpar."
    exit 0
fi

# Coleta arquivos/dirs a remover (exclui .gitkeep)
mapfile -t targets < <(
    find "$TMP_DIR" -mindepth 1 ! -name ".gitkeep" | sort
)

if [[ ${#targets[@]} -eq 0 ]]; then
    echo ".tmp/ já está limpo."
    exit 0
fi

if $DRY_RUN; then
    echo "=== DRY RUN — os seguintes itens seriam removidos de .tmp/ ==="
    for t in "${targets[@]}"; do
        echo "  ${t#$ROOT_DIR/}"
    done
    echo "Total: ${#targets[@]} item(s)"
    exit 0
fi

removed=0
for t in "${targets[@]}"; do
    if [[ -e "$t" ]]; then
        rm -rf "$t"
        (( removed++ )) || true
        $VERBOSE && echo "  removido: ${t#$ROOT_DIR/}"
    fi
done

echo "✅ .tmp/ limpo — $removed item(s) removido(s)."
