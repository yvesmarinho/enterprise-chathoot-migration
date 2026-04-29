#!/usr/bin/env bash
# git-commit-with-file.sh — Realiza git commit usando arquivo de mensagem.
#
# Uso:
#   ./scripts/git-commit-with-file.sh /tmp/commit.txt
#
# Regra P0 do projeto: git commit -m "..." direto é PROIBIDO.
# Sempre use este script com um arquivo de mensagem.

set -euo pipefail

MSG_FILE="${1:-}"

if [[ -z "$MSG_FILE" ]]; then
    echo "ERRO: informe o arquivo de mensagem de commit."
    echo "Uso: $0 <arquivo>"
    exit 1
fi

if [[ ! -f "$MSG_FILE" ]]; then
    echo "ERRO: arquivo não encontrado: $MSG_FILE"
    exit 1
fi

git commit -F "$MSG_FILE"
