# 🔄 Session Recovery — 2026-05-15

**Sessão anterior**: 2026-05-14 (Sessão 14)
**Branch**: `001-enterprise-chatwoot-migration`
**Status**: 🔴 INVESTIGAÇÃO D15 — Migração S3 incompleta e account 46 sem attachments

---

## Contexto Recuperado

### Última Sessão (2026-05-14)

**Foco**: Ferramental S3 — criação de CLI profissional para validação de attachments

**Realizações**:
1. ✅ **Utilitário CLI criado**: `scripts/check_s3_attachments.py`
   - Conexão via `.secrets/generate_erd.json`
   - Parâmetros flexíveis: `--instance`, `--account-id`, `--limit`, `--offset`, `--date-start`, `--date-end`
   - Validação HTTP completa (status, response time)
   - Relatório JSON detalhado

2. ✅ **Teste e validação**:
   - Account 1 (Vya Digital): **10/10 attachments acessíveis** (100% success rate)
   - Account 46 (Unimed Guaxupé): **0 attachments** no DEST (problema crítico confirmado)
   - Bucket identificado: `assets-chat-vya-digital.s3.amazonaws.com`

3. ✅ **Organização de evidências**:
   - 10 evidências S3 movidas para `docs/evidencias/`
   - 14 scripts obsoletos excluídos de `.tmp/`
   - 47 scripts de diagnóstico preservados

**Artefatos Gerados**:
- `scripts/check_s3_attachments.py` (281 linhas)
- `docs/evidencias/check_s3_attachments_*.json` (relatórios de validação)

---

## 🔴 Itens P0 para Esta Sessão

Prioridades do [TODO.md](../../TODO.md):

### D15 — Investigação S3 (Crítico)

1. **D15-T1.1** 🚨 **ALTA PRIORIDADE** — Investigar por que Unimed Guaxupé NÃO tem attachments no DEST
   - **Situação**: SOURCE (account_id=25) tem **1.847 attachments**, DEST (account_id=46) tem **0 attachments**
   - **Evidência**: `.tmp/verificar_source_guaxupe.py` — 1.837 attachments com blob S3 válido no SOURCE
   - **Ações necessárias**:
     - [ ] Verificar logs de migração do account 25 → 46
     - [ ] Verificar se migration script `01_migrar_account.py` inclui attachments
     - [ ] Decidir se é necessário re-executar migração de attachments para este account

2. **D15-T2** Identificar bucket SOURCE correto
   - Consultar ops: qual bucket `chat.vya.digital` usa?
   - Testar blob_keys contra buckets candidatos
   - Verificar `config/storage.yml` no ambiente SOURCE

3. **D15-T3** Contar attachments órfãos no SOURCE
   ```sql
   SELECT COUNT(*) FROM attachments att
   LEFT JOIN messages m ON m.id = att.message_id
   WHERE att.account_id = 17 AND m.id IS NULL;
   ```

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
| Validação de attachments S3 | 🔴 **BLOQUEADOR CRÍTICO** (98% recentes OK, 26% histórico, account 46 = 0) |
| Ferramental S3 | ✅ CLI profissional criado |

**Accounts Migrados**:
- ✅ Vya Digital (1→1): 2.753 attachments (100% acessíveis no teste)
- ✅ Sol Copernico (4→44)
- ✅ Unimed Poços PJ (17→17): 13.776 attachments
- ✅ Unimed Poços PF (18→45)
- ❌ Unimed Guaxupé (25→46): **0 attachments** (BUG CRÍTICO)

---

## Git Status

```
Branch: 001-enterprise-chatwoot-migration (up to date with origin)
Working tree: clean
Last commits:
- e7e76eb: add files from session end
- b2c3b2e: docs: Adicionar nota sobre .tmp/ não limpo na Session 13
- 17af862: docs: Session 13 — Descoberta crítica de migração S3 incompleta
```

---

*Recuperação automática — Session Start Ritual v1.0*
