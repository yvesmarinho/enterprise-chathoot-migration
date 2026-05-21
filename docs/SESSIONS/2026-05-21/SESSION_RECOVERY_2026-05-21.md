# 🔄 Session Recovery — 2026-05-21

**Sessão anterior**: 2026-05-20
**Branch**: master
**Status dos IMPs**: D16-F1 ✅ concluído; S21-LEGACY-DEFAULT ✅; S21-LEGACY-SCOPE ✅; D16-F3 🔄 em progresso; MIG-PROD-VALID 🔄 em progresso

## Contexto Recuperado
Na sessão de 2026-05-20 foi confirmada a causa raiz do HTTP 500 pós-migração (attachments sem vínculo em ActiveStorage), e o fluxo all-accounts legado foi consolidado no wfdb01 com deploy validado em daemon. O runner legado foi corrigido para migrar todas as accounts por padrão (whitelist opcional), com ajustes de `PYTHONPATH=/app` e correção de `import os`.

## Itens P0 para Esta Sessão
1. Acompanhar conclusão do daemon `chatwoot-migrator-all` no wfdb01 e consolidar relatório `.tmp/migrate_all_*.json`.
2. Executar validações pós-migração por account (`app/02_verificar.py`, `app/06_verificar_erros.py`, validações API/hash).
3. Definir e aplicar estratégia para gap de ActiveStorage antes da homologação final.
