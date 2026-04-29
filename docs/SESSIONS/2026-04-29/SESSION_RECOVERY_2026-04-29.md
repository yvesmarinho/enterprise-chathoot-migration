# 🔄 Session Recovery — 2026-04-29

**Sessão anterior**: 2026-04-27 (Sessão 11)
**Branch**: `001-enterprise-chatwoot-migration`
**Last Commit**: `bf0ab98` — refactor(docker): execução autônoma com docker run -d

---

## Contexto Recuperado

### Sessão 11 (2026-04-27) — Estado Final

**Pipeline Vya Digital completado:**
- ✅ Fases 0-5 executadas com sucesso (banco restaurado pelo ops)
- ✅ 6 sequences resequenciadas via `.tmp/fix_sequences.py`
- ✅ Infra Docker criada (`docker/` completo) — commits `2619dd9`, `0ed9d4f`
- ❌ Fase 6 (inbox_members) **bloqueada** — requer refatoração (sem `migration_state`)

**BUG-06 Corrigido:**
- Formatação black aplicada em `app/01_migrar_account.py` — commit `e57faa8`

**Docker Infrastructure:**
- Scripts `deploy-to-wfdb01.sh` configurados (fwknop + porta 5010 + user archaris)
- Objetivo: executar migração no wfdb01 (mesma rede que wfdb02) para eliminar latência
- Status: **não testado em produção** — aguarda validação ops

---

## Estado Atual do Projeto

### Pipeline de Migração — Account "Vya Digital" (account_id=1)

| Fase | Descrição | Status | Observações |
|------|-----------|--------|-------------|
| 0 | Account | ✅ Completo | account_id=1 reutilizado |
| 1 | Inboxes | ✅ Completo | 13 inboxes criadas (397-409) + wea004 (372) |
| 2 | Users | ✅ Completo | 8 mapeados, 2 not-found ignorados |
| 3 | Contacts | ✅ Completo | ~226k migrados (confirmado ops) |
| 4 | Conversations + Messages + Attachments | ✅ Completo | Confirmado ops |
| 5 | Sequences | ✅ Completo | 6 sequences resequenciadas |
| 6 | Inbox Members | ❌ **BLOQUEADO** | Script depende de `migration_state` (não existe) |

### Tecnologias em Uso

- **Databases**: PostgreSQL 16.10 (wfdb02.vya.digital:5432)
  - SOURCE: `chatwoot_dev1_db` (read-only)
  - DEST: `chatwoot004_dev1_db` (read-write)
- **Stack**: Python 3.12+, SQLAlchemy 2.0.49, psycopg2-binary 2.9.11
- **Estratégia**: MERGE com deduplicação (não incremental)

### Arquitetura Corrigida (D7, confirmada 2026-04-22)

- **SOURCE**: `chatwoot_dev1_db` → site `chat.vya.digital`
- **DEST**: `chatwoot004_dev1_db` → site `vya-chat-dev.vya.digital`
- ⚠️ **Nota**: `synchat.vya.digital` é site de produção separado (não é DEST)

### Critical Finding (2026-04-24 — D11)

- Container `vya-chat-dev.vya.digital` estava apontando para DB errado: `chatwoot004_dev_db` (antigo)
- Deveria apontar para: `chatwoot004_dev1_db` (correto)
- **Correção aplicada**: Container reiniciado após `.env` ajustado
- **Evidência**: API `/profile` retornava `account_id=44` (existe em DB errado, não no correto)

---

## Itens P0 Pendentes para Esta Sessão

### D12 — Ações Obrigatórias Antes de Ligar Container

#### Concluídos ✅
- [x] **D12-P0-1** Regenerar tokens autenticação SOURCE vs DEST (2026-04-24)
- [x] **D12-P0-2** Verificar conversas `snoozed` com prazo vencido (0 encontradas)
- [x] **D12-P0-3** Verificar conversas `open` > 30 dias (124 encontradas — manter status)

#### Pendentes 🔵
- [ ] **D12-P1-1** Verificar FK dangling `contact_inbox_id` (SQL no TODO.md)
- [ ] **D12-P1-2** Verificar colisões de phone no SOURCE (SQL no TODO.md)
- [ ] **D12-P1-3** Verificar contatos `contact_id = NULL` herdados (SQL no TODO.md)
- [ ] **D12-P1-4** Avaliar relevância de `conversation_participants`
- [ ] **D12-P1-5** Confirmar webhooks/integrações DEST não apontam para SOURCE

### Sessão 11 — Pendências Herdadas

#### P0 — Crítico
- [ ] **S11-P0-1** Migrar `inbox_members` (requer refatoração — dispensar `migration_state`)
- [ ] **S11-P0-2** Executar `make validate-api` com token admin → esperado `api_conv=687`
- [ ] **S11-P0-3** Validar inboxes visíveis no frontend para usuários não-admin

#### P1 — Outros Accounts
- [ ] **S11-P1-1** Migrar account "Sol Copernico" (account_id=4)
- [ ] **S11-P1-2** Migrar account "Unimed Poços PJ" (account_id=17)
- [ ] **S11-P1-3** Migrar account "Unimed Poços PF" (account_id=18)
- [ ] **S11-P1-4** Migrar account "Unimed Guaxupé" (account_id=25)

#### P2 — Docker Infra
- [ ] **S11-DOCKER-TEST** Testar build e execução completa no wfdb01

### TOKEN-ADMIN — Bloqueador Ativo

- [ ] Obter token API de `administrator` em `account_id=1`
  - Sugestão: user `admin@vya.digital`, `user_id=1`
  - Adicionar em `.secrets/generate_erd.json` sob chave `"vya-chat-dev-admin"`
  - Reexecutar `make validate-api` → esperado `api_conv=687` para account_id=1

---

## Arquivos Modificados (Não Commitados)

```
Changes not staged for commit:
  modified:   app/migrate_all_accounts.py
  modified:   docs/SESSIONS/2026-04-27/DAILY_ACTIVITIES_2026-04-27.md

Untracked files:
  docs/SESSIONS/2026-04-27/CHAT-14-00.md
```

**Recomendação**: Verificar e commitar mudanças antes de iniciar trabalho novo.

---

## Decisões Técnicas Recentes

### D-SEQ-STANDALONE (2026-04-27)
- Fase 5 (sequences) executada via script avulso `.tmp/fix_sequences.py`
- Razão: Pipeline não suporta re-run isolado de fase

### D-DOCKER-WFDB01 (2026-04-27)
- Infra Docker criada para executar no wfdb01 (mesma rede wfdb02)
- Objetivo: Eliminar latência de rede local → wfdb02

### D-INBOX-MEMBERS-NOSTATE (2026-04-27)
- `13_migrar_inbox_members.py` deve ser refatorado
- Dispensar `migration_state` — resolver mapeamentos por nome inbox + email user direto no DEST

---

## Riscos e Bloqueadores

### Bloqueadores Ativos
1. **inbox_members** não migrados → usuários não terão agentes atribuídos aos inboxes
2. **Token admin** `account_id=1` precisa ser confirmado antes de validação API
3. **Outros 4 accounts** bloqueados até validação completa do account 1

### Riscos Identificados
- Docker infra não testada em produção — pode haver problemas de configuração de rede/autenticação
- Scripts temporários em `.tmp/` podem conter dados sensíveis — verificar antes de próximo commit

---

## Segurança — Status

- 🟢 **LIMPO** — Nenhum arquivo sensível fora de `.secrets/`
- ✅ `.secrets/` presente no `.gitignore`
- ✅ Nenhum `.env`, `.key`, `.pem` encontrado no workspace
- ✅ `docker/Dockerfile` usa `.dockerignore` — `.secrets/` excluído da imagem

---

## Setup para Retomar Trabalho

```bash
# Navegar para projeto
cd /home/yves_marinho/Documentos/DevOps/Vya-Jobs/enterprise-chatwoot-migration

# Verificar estado git
git status
git log --oneline -5

# Commitar mudanças pendentes (se necessário)
# [usar git-commit-with-file.sh para mensagens multi-linha]

# Opções de trabalho:
# 1. Refatorar inbox_members migrator
# 2. Executar validação API (precisa token admin)
# 3. Testar Docker infra no wfdb01
# 4. Executar queries D12-P1-1 a P1-5 (verificações pré-liberação)
```

---

## Contexto MCP

**Servidores configurados** (`.vscode/mcp.json`):
- ✅ `memory` — Memória persistente entre sessões
- ✅ `sequential-thinking` — Raciocínio estruturado
- ✅ `filesystem` — Operações de arquivo
- ✅ `github` — Integração GitHub (token via env)

---

## Próximas Ações Sugeridas

1. **Commitar mudanças pendentes** em `app/migrate_all_accounts.py` e docs de sessão 2026-04-27
2. **Escolher foco da sessão**:
   - Refatorar `inbox_members` migrator (S11-P0-1)
   - Executar queries D12-P1 (verificações pré-liberação)
   - Testar Docker no wfdb01 (S11-DOCKER-TEST)
   - Obter token admin e validar API (S11-P0-2)
3. **Carregar domain profile** adequado (PROGRAMMING | INFRASTRUCTURE | ANALYSIS)

---

*Sessão inicializada em: 2026-04-29*
*Agente: session-manager*
*Modo: Recuperação de contexto completa*
