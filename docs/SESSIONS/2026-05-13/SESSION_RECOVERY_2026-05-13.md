# 🔄 Session Recovery — 2026-05-13

**Sessão anterior**: 2026-04-29
**Branch**: `001-enterprise-chatwoot-migration`
**Status dos IMPs**: 4/5 accounts migrados (80% validação), inbox_members bloqueado

## Contexto Recuperado

### Última Sessão (2026-04-29 — Sessão 12)

**Atividades principais**:
1. ✅ Validação completa de migração multi-account (500 registros)
2. ✅ Correção de token API inválido (novo token gerado)
3. ✅ Correção de exposição de credenciais (refatorado para Python scripts)
4. ✅ Análise de accounts migrados: SOURCE→DEST (1→1, 4→44, 17→17, 18→45, 25→46)
5. ✅ Criação de relatório executivo e guia técnico
6. ✅ Atualização de README.md com fluxo de validação
7. ✅ PR #3 criado para master
8. ✅ Correção de typo "chathoot" → "chatwoot" (37 arquivos)

**Resultados da validação**:
- Account 1 (Vya Digital): **4%** ⚠️ — MERGE com 378 convs pré-existentes
- Account 4→44 (Sol Copernico): **97%** ✅
- Account 17 (Unimed Poços PJ): **100%** ✅
- Account 18→45 (Unimed Poços PF): **99%** ✅
- Account 25→46 (Unimed Guaxupé): **100%** ✅
- **Taxa geral**: 400/500 (80%)

### Estado Atual do Pipeline

| Fase | Status | Observações |
|------|--------|-------------|
| 0 — Account | ✅ | account_id=1 reutilizado (MERGE) |
| 1 — Inboxes | ✅ | 13 criadas (ids 397-409) + wea004 (372) |
| 2 — Users | ✅ | 8 mapeados, 2 not-found ignorados |
| 3 — Contacts | ✅ | ~226k migrados |
| 4 — Conversations + Messages + Attachments | ✅ | 309 convs + 13.164 msgs (Vya Digital) |
| 5 — Sequences | ✅ | 6 sequences resequenciadas |
| 6 — Inbox Members | ❌ | BLOQUEADO — `migration_state` inexistente |

### Banco de Dados

**SOURCE**: `chatwoot_dev1_db` (read-only) — `wfdb02.vya.digital:5432`
**DEST**: `chatwoot004_dev1_db` (read-write) — `wfdb02.vya.digital:5432`

**Container DEST**: `chat-vya-digital` @ `vya-chat-dev.vya.digital`
- POSTGRES_DATABASE=chatwoot004_dev1_db ✅ (validado via SSH)

### Token API Ativo

**DEST**: `<REDACTED>` (user_id=1, admin@vya.digital)
- Gerado em 2026-04-29
- Armazenado em `.secrets/generate_erd.json`
- ✅ Validado funcionando

## Itens P0 para Esta Sessão

1. **S11-P0-1** — Adaptar e executar migração de `inbox_members` (397-409)
   - Script: `app/13_migrar_inbox_members.py`
   - Bloqueio: tabela `migration_state` inexistente
   - Solução: resolver mapeamentos por nome inbox + email user

2. **S11-P0-2** — Executar `make validate-api` com token admin
   - Token: `<REDACTED>`
   - Esperado: `api_conv=687` para account_id=1

3. **S11-P0-3** — Validar inboxes visíveis no frontend para usuários não-admin
   - Depende: inbox_members migrados

4. **D12-P1-1 a P1-5** — Verificações pré-liberação
   - FK dangling `contact_inbox_id`
   - Colisões de phone no SOURCE
   - `contact_id = NULL` do legado
   - `conversation_participants`
   - Webhooks/integrações DEST vs SOURCE

5. **S11-P1-1..4** — Outros 4 accounts
   - Sol Copernico (4→44)
   - Unimed Poços PJ (17)
   - Unimed Poços PF (18→45)
   - Unimed Guaxupé (25→46)

## Arquivos Modificados Não Commitados

⚠️ **18 arquivos modificados** + **4 não monitorados**:
- Scaffolding/spec templates (.github/agents/, .github/prompts/, .specify/)
- `.copilot-rules-enterprise-chathoot-migration.md` (typo não corrigido)
- `docs/message.txt`
- `.specify/scripts/bash/setup-tasks.sh`
- `.specify/workflows/`

**Ação sugerida**: Commitar ou descartar antes de iniciar trabalho efetivo.

---

*Session Recovery criado em 2026-05-13*
