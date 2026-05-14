# 🔄 Session Recovery — 2026-05-14

**Sessão anterior**: 2026-05-13 (Sessão 13)
**Branch**: `001-enterprise-chatwoot-migration`
**Status**: 🔴 BLOQUEADOR — Validação de attachments S3 incompleta

---

## Contexto Recuperado

### Última Sessão (2026-05-13)

**Foco**: Validação de attachments S3 pós-migração

**Descobertas Críticas (D15)**:
1. **Migração S3 temporal**: Taxa de sucesso é **98% para attachments recentes** (2025-2026) vs **26% para amostra aleatória** (histórico 2020-2026)
   - Evidência: `.tmp/validacao_attachments_s3_20260513_120012.json`
   - Conclusão: Arquivos antigos foram deletados do S3 ou nunca existiram (política de retenção?)

2. **Unimed Guaxupé sem attachments**: SOURCE (account_id=25) tem **1.847 attachments**, DEST (account_id=46) tem **0 attachments**
   - Possível bug no pipeline de migração — attachments não foram migrados para este account

**Tarefas Concluídas**:
- ✅ D15-T1: Análise temporal de attachments (98% sucesso recentes vs 26% aleatórios)
- ✅ Debate D15 documentado: [D15-DEBATE-MIGRACAO-S3-INCOMPLETA-2026-05-13.md](../../debates/D15-DEBATE-MIGRACAO-S3-INCOMPLETA-2026-05-13.md)

**Artefatos Gerados**:
- `.tmp/validacao_attachments_s3_20260513_120012.json` (100 recentes, 98 OK)
- `.tmp/verificar_source_guaxupe.py` (1.837 attachments SOURCE)

---

## 🔴 Itens P0 para Esta Sessão

Prioridades do [TODO.md](../../TODO.md):

### D15 — Investigação S3 (Crítico)

1. **D15-T1.1** 🆕 Investigar por que Unimed Guaxupé NÃO tem attachments no DEST
   - Verificar logs de migração do account 25 → 46
   - Verificar se migration script `01_migrar_account.py` inclui attachments
   - Decidir se é necessário re-executar migração de attachments

2. **D15-T2** Identificar bucket SOURCE correto
   - Consultar ops: qual bucket `chat.vya.digital` usa?
   - Testar blob_keys contra buckets candidatos
   - Verificar `config/storage.yml` no ambiente SOURCE

3. **D15-T3** Contar attachments órfãos no SOURCE

### D12 — Pré-liberação Container (Bloqueador)

1. **TOKEN-ADMIN**: Obter token API de `administrator` em `account_id=1`
   - Adicionar em `.secrets/generate_erd.json` sob chave `"vya-chat-dev-admin"`
   - Reexecutar `make validate-api` → esperado `api_conv=687`

2. **D12-P1-1** a **D12-P1-5**: Verificações de integridade antes de ligar o container

### S11 — Pipeline Accounts Restantes

1. **S11-P0-1** Migrar `inbox_members` para novos inboxes (397-409)
2. **S11-P1-1** a **S11-P1-4**: Migração de outros accounts SOURCE

---

## Estado Geral do Projeto

| Fase | Status |
|------|--------|
| Migração de metadados (DB) | ✅ Concluída (5 accounts) |
| Validação de API | ✅ Aprovada (80% sucesso) |
| Validação de attachments S3 | 🔴 **BLOQUEADOR CRÍTICO** (98% recentes, 26% histórico) |

**Accounts Migrados**:
- ✅ Vya Digital (1→1): 2.753 attachments
- ✅ Sol Copernico (4→44)
- ✅ Unimed Poços PJ (17→17): 13.776 attachments
- ✅ Unimed Poços PF (18→45)
- ❌ Unimed Guaxupé (25→46): **0 attachments** (BUG)

---

## Git Status

```
Branch: 001-enterprise-chatwoot-migration (up to date with origin)
Modified: 1 file (FINAL_STATUS_2026-05-13.md)
Last commits:
- b2c3b2e: docs: Adicionar nota sobre .tmp/ não limpo na Session 13
- 17af862: docs: Session 13 — Descoberta crítica de migração S3 incompleta
```

---

*Recuperação automática — Session Start Ritual v1.0*
