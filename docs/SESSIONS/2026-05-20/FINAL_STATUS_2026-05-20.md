# 📊 Final Status — 2026-05-20

**Branch**: `master`
**Sessão**: S21

## IMPs Concluídos Esta Sessão
- ✅ D16-F1: investigação do HTTP 500 pós-migração DEV concluída com causa raiz confirmada.
- ✅ S21-LEGACY-DEFAULT: `ALL_ACCOUNTS=true` passou a priorizar fluxo legado por default.
- ✅ S21-LEGACY-SCOPE: runner legado atualizado para migrar todas as accounts do SOURCE por default.
- ✅ S21-CONTAINER-IMPORTS: correção de import no container com `PYTHONPATH=/app`.
- ✅ S21-NAMEERROR-OS: correção de `NameError` com `import os` no `migrate_all_accounts.py`.
- ✅ S21-DEPLOY-WFDB01: deploy remoto com build e validação de execução em daemon no wfdb01.

## Estado Geral dos IMPs
| IMP | Título | Status |
|-----|--------|--------|
| D16-F1 | Diagnóstico HTTP500 pós-migração | ✅ Concluído |
| S21-LEGACY-DEFAULT | Default legado para all-accounts | ✅ Concluído |
| S21-LEGACY-SCOPE | Runner legado para todas as accounts | ✅ Concluído |
| D16-F3 | Correção de ActiveStorage no destino | 🔄 Em progresso |
| MIG-PROD-VALID | Validação pós-migração em produção | 🔄 Em progresso |

## Próximas Ações (P0 para próxima sessão)
1. Acompanhar conclusão do container daemon `chatwoot-migrator-all` no wfdb01 e consolidar relatório `.tmp/migrate_all_*.json`.
2. Executar validações pós-migração por account (`app/02_verificar.py`, `app/06_verificar_erros.py`, API/hash).
3. Definir estratégia para gap de ActiveStorage (script de correção ou ajuste de pipeline) antes de homologação final.

## Decisões Técnicas desta Sessão
- D-21-01: Em `ALL_ACCOUNTS=true`, priorizar fluxo legado para maximizar compatibilidade com comportamento histórico.
- D-21-02: Manter whitelist somente como override opcional (`ACCOUNTS_WHITELIST`) e não como hardcode.
- D-21-03: Definir `PYTHONPATH=/app` na imagem para imports consistentes de módulos `src`.

## Qualidade e Segurança
- `make test` ✅
- `make lint` ✅
- `python -m py_compile app/migrate_all_accounts.py` ✅
- Security review em `docs/SESSIONS/2026-05-20/*.md` sem exposição de credenciais/tokens/chaves.

## Limpeza de Temporários
- `./scripts/cleanup-tmp.sh --dry-run` executado.
- Limpeza real não aplicada para preservar artefatos D16 e logs de execução ainda relevantes.

## Contexto para Recuperação
- O container em daemon já inicia com `PIPELINE: legacy` e lista todas as 6 accounts do SOURCE.
- O campo `ACCOUNT` no cabeçalho do runner é cosmético em modo all-accounts e não afeta a execução.
- Causa do HTTP500 D16 permanece confirmada: ausência de vínculos ActiveStorage para attachments migrados.
