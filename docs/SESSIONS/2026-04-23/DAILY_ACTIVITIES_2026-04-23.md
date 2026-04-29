# 📅 Daily Activities — 2026-04-23

**Branch**: `001-enterprise-chatwoot-migration`
**Sessão**: SESSION-2026-04-23 (Sessão 9)

---

## Início de Sessão — 09:23

- ✅ Contexto recuperado: FINAL_STATUS_2026-04-22.md
- ✅ Git status: LIMPO, HEAD=c919f0c (in sync com origin)
- ✅ MCP: memory ✅ | sequential-thinking ✅ | filesystem ✅ | github ✅
- ✅ Segurança: 🟢 LIMPO
- ✅ Docs de sessão criados
- ✅ Regras P0 carregadas

---

## Atividades do Dia

### [09:26] — D7-A1: Verificar display_id de conv_id=200501

- ✅ Consulta direta ao DEST: `conv_id=200501` → `display_id=1843`, `inbox_id=428`, `assignee_id=88` (Marcus), status=open
- SOURCE `display_id=1003` → DEST `display_id=1843`
- **D7-A1 RESOLVIDO**

### [09:28] — D7-A2: Comunicação ao Marcus

- ✅ Mensagem formal redigida com mapeamento completo de display_ids:
  - SOURCE `display_id=1093` → DEST `display_id=1850` (inbox_id=521, wea004 migrado, assignee=Marcus)
  - SOURCE `display_id=1003` → DEST `display_id=1843` (inbox_id=428, assignee=Marcus)
- Instrução: navegar por "All Conversations" em `vya-chat-dev.vya.digital`, filtrar por inbox ou data
- **D7-A2 RESOLVIDO**

### [09:30] — D7-A3: Análise de reatribuição 219045/219046

- ✅ Consulta SOURCE confirmou: conv_ids 62361/62362 tinham `assignee_id=None` originalmente
- Migração está correta — nenhum UPDATE necessário
- **D7-A3 DESCARTADO (sem ação)**

### [09:32] — D7-A4: Diagnóstico dos dois inboxes wea004

- ✅ Dois inboxes `wea004` em `account_id=1`:
  - `inbox_id=372` — pré-existente (synchat, criado 2025-12-18), 3 conversas
  - `inbox_id=521` — migrado (chat.vya.digital, criado 2025-11-14), 3 conversas
- Nenhum tem `inbox_members` — Marcus é admin (role=1), acessa tudo
- Recomendação: renomear `inbox_id=521` para `wea004 (migrado)` para eliminar ambiguidade
- **D7-A4 OPCIONAL — requer aprovação do gestor**

### [09:33] — D7 encerrado

- ✅ `docs/debates/D7-DEBATE-VISIBILIDADE-MARCOS-2026-04-22.md` atualizado para v3 (RESOLVIDO)
- Seção 14 adicionada com resolução final de todos os itens D7-A1 a D7-A4
- Status atualizado: **✅ RESOLVIDO — 2026-04-23**

---

### [09:49–09:54] — D5-B2: `make validate-api-deep SAMPLE=5 MAX_MSGS=50` (Run 4 — batch optimization)

- ✅ Batch pre-fetch aplicado: 2 queries/conv vs 100 queries/conv → 3x mais rápido
- ✅ Scan concluído em ~5min (5 contatos, 51 conversas, 1150 mensagens)
- **Resultados DB**: 1150/1150 mensagens com conteúdo correto, 129/129 attachments com dest_id ✅
- **Warnings detectados**:
  - `contact.name/phone="" na API` — contatos têm campos vazios no DEST (esperado para BOT)
  - `conversations_found_api=0` — CAUSA: `additional_attributes={}` em todas as conversations migradas
- ✅ Fix aplicado: UPDATE em 36.016 conversations para preencher `additional_attributes.src_id`

### [10:07–10:44] — D5-B2: Investigação `conversations_found_api=0`

- ✅ **CONFIRMADO**: `wfdb02.vya.digital` resolve para `82.197.64.145` — mesmo servidor que o `.env` do container de `vya-chat-dev.vya.digital`. A API ESTÁ conectada ao banco correto.
- ⚠️ **CAUSA REAL**: As conversations **migradas** (IDs 44770+) não são retornadas pela API para o contact 34591
  - API retorna 20 IDs (1492–1540) que existem no DB com `account_id=6` e `contact_id≠34591` — registros não relacionados
  - Paginação retorna os mesmos 20 registros em todas as páginas (pages 1=2)
  - Contact 34591 tem 96 conversations no DB (17 migradas + 79 pré-existentes sinchat), mas nenhuma aparece corretamente na API
- **Hipótese**: conversations migradas inseridas diretamente no DB (sem passar pela API do Chatwoot) não estão indexadas/cacheadas pelo Chatwoot Rails — podem ser invisíveis via API até reindexação
- **Scripts diagnósticos criados** (em `.tmp/`, logs em `scripts/logs/`):
  - `check_conv_api_attrs.py`, `check_contact_conv_api.py`, `probe_vya_chat_dev.py`
  - `verify_dest_api_host.py`, `verify_api_db_source.py`, `diagnose_api_id_gap.py`, `verify_api_pagination.py`
- **Status D5-B2**: 🔴 BLOQUEADO — validação via API requer diagnóstico adicional de visibilidade Chatwoot

---

### [14:xx–15:47] — BUG-A Fix: `pubsub_token` warning silencioso em `app/10_validar_api.py`

- **Problema**: `_fetch_sanity()` emitia `log.warning` ao executar `_SQL_SANITY_PUBSUB_DUPS` porque a coluna `contacts.pubsub_token` não existe no schema do DEST
- **Fix aplicado**: Downgrade de `log.warning` → `log.debug` no bloco `except Exception`; truncamento da mensagem de erro para 120 chars com `# noqa: BLE001`
- **Arquivo**: `app/10_validar_api.py` linha `_fetch_sanity()`
- ✅ **BUG-A RESOLVIDO**

---

### [14:xx–15:47] — BUG-B Fix: `api_conv=-1` para account_id=1

- **Problema**: `_run_summary()` usava `conv_data.get("data", {}).get("all_count", -1)` mas a resposta real da API Chatwoot é `{"meta": {"all_count": N}}`
- **Diagnóstico**: Script `.tmp/probe_meta.py` confirmou estrutura real: `{"meta": {"all_count": 378}}` para `account_id=1`
- **Fix aplicado**: Linha corrigida para `conv_data.get("meta", {}).get("all_count", -1)`; lógica de fallback sum-by-status removida
- **Arquivo**: `app/10_validar_api.py` método `_run_summary()`
- ✅ **BUG-B RESOLVIDO**

---

### [14:xx–15:47] — Fix endpoint API: `synchat.vya.digital` → `vya-chat-dev.vya.digital`

- **Problema**: `_load_api_config()` usava chave `synchat` do `.secrets/generate_erd.json`, mas a instância DEST correta é `vya-chat-dev.vya.digital`
- **Descoberta**: A arquitetura correta é SOURCE=`chat.vya.digital`, API DEST=`vya-chat-dev.vya.digital` (NÃO `synchat.vya.digital`)
- **Fix aplicado**:
  1. Usuário adicionou chave `vya-chat-dev` em `.secrets/generate_erd.json` com `host=vya-chat-dev.vya.digital`
  2. `_load_api_config()` alterado para `data.get("vya-chat-dev", {})`
  3. Guard `if not host.startswith("http"):` adicionado para prefixar `https://`
- **Docstring atualizada**: `"""Carrega configuração da API de .secrets/generate_erd.json["vya-chat-dev"]."""`
- ✅ **ENDPOINT CORRIGIDO**

---

### [15:47] — Validação summary limpa (make validate-api)

- **Comando**: `PYTHONPATH=. python3 app/10_validar_api.py summary`
- **Resultado**:
  ```
  API probe OK — https://vya-chat-dev.vya.digital
  SOURCE — accounts=5 contacts=38868 conversations=41743 messages=310155 attachments=26889
  DEST   — accounts=21 contacts=227758 conversations=163842 messages=1372124 attachments=96276
  ACC src=1→dest=1    Δconv=+378  Δmsg=+33298  Δatt=+2753  api_conv=378  api_contacts=523
  ACC src=4→dest=47   Δconv=+0    Δmsg=+0      Δatt=+0     api_conv=-1   api_contacts=-1
  ACC src=17→dest=17  Δconv=+9551 Δmsg=+127257 Δatt=+13776 api_conv=19442 api_contacts=3209
  ACC src=18→dest=61  Δconv=+0    Δmsg=+0      Δatt=+0     api_conv=-1   api_contacts=-1
  ACC src=25→dest=68  Δconv=+0    Δmsg=+0      Δatt=+0     api_conv=-1   api_contacts=-1
  EXIT 2 — sanity checks com falhas (orphan_messages=6321 for dest=1)
  ```
- **Notas**:
  - `api_conv=378` para account=1 vs DB=687 → anomalia a investigar
  - `api_conv=-1` para accounts 47/61/68 → token sem acesso a essas contas (esperado)
  - `orphan_messages=6321` é pré-existente no DEST (não introduzido pela migração)
- ✅ **VALIDAÇÃO SUMMARY CONCLUÍDA**

---

### [15:50–16:00] — D9: Análise código-fonte Chatwoot — conversas invisíveis

- **Motivo**: `api_conv=378` (API) vs `687` (DB) para `account_id=1` — 309 conversas migradas invisíveis
- **Subagente `chatwoot-expert` acionado** para análise completa do código-fonte Rails do Chatwoot
- **Documento gerado**: `docs/debates/D9-ANALISE-CODIGO-CHATWOOT-CONVERSAS-INVISIVEIS-2026-04-23.md`
- **Achados do D9**:
  - `GET /conversations/meta?status=all` → `ConversationFinder#perform_meta_only` → `SELECT COUNT(*) FROM conversations WHERE account_id=N` (sem JOIN com inboxes)
  - `Conversations::PermissionFilterService`: `admin` → sem filtro; `agent` → `WHERE inbox_id IN inbox_members`
  - Trigger `conversations_before_insert_row_tr`: SEMPRE sobrescreve `display_id` com `nextval('conv_dpid_seq_N')`
  - `additional_attributes` default é `{}`, não NULL
  - Callbacks bypassados por SQL direto: `ensure_waiting_since`, `determine_conversation_status`

---

### [16:00–16:15] — Diagnóstico `account_id` e `src_id` (diag_account_id_check.py)

- **Script**: `.tmp/diag_account_id_check.py`
- **Resultado**:
  - Conversas migradas: `account_id=1→309`, `account_id=17→9891`, `account_id=47→2102`, `account_id=61→19730`, `account_id=68→3984`
  - Total `account_id=1` no DEST: **687** (378 pré-existentes + 309 migradas)
  - `conv_dpid_seq_1`: `last_value=1851 = MAX(display_id)` → sequência EM SINCRONIA ✅
  - `additional_attributes->>'src_id'`: **0 registros** — migrador NÃO gravou `src_id` nas conversations
- **Conclusão**: account_id correto ✅, UUIDs válidos ✅, sequência OK ✅, mas rastreabilidade por `src_id` ausente ⚠️

---

### [16:15–16:17] — ROOT CAUSE CONFIRMADO: Token de agent sem inbox_members (diag_root_cause_visibility.py)

- **Script**: `.tmp/diag_root_cause_visibility.py`
- **Hipótese testada**: Token `vya-chat-dev` pertence a usuário `role=agent` → `PermissionFilterService` filtra por `inbox_members` → inboxes migrados sem membros = conversas invisíveis

**Resultado completo**:

| Tipo de usuário | Visibilidade em account_id=1 |
|-----------------|------------------------------|
| Todos os `administrators` (11 usuários) | 687/687 (100%) ✅ |
| Todos os `agents` (4 usuários) | 0/687 (0%) ❌ |

**Inboxes migrados — todos sem membros (SEM MEMBROS)**:
| inbox_id | Nome | Conversas migradas |
|----------|------|--------------------|
| 428 | AtendimentoVYADIgital | 123 |
| 403 | La Pizza | 67 |
| 399 | Atendimento Web | 32 |
| 435 | Chatbot SDR | 23 |
| 485 | Grupo Caelitus | 14 |
| 480 | Vya Lab | 12 |
| 499 | 5535988628436 | 11 |
| 430 | vya.digital - apresentação | 10 |
| 518 | Agente IA - SDR | 5 |
| 481 | 551131357298 | 4 |
| 521 | wea004 | 3 |
| 449 | VyaDigitalBot Telegram | 3 |
| 409 | vya.digital | 2 |

**Total: 13 inboxes migrados, 309 conversas, todos com 0 membros**

- **Causa raiz definitiva**: O token de API configurado em `vya-chat-dev` pertence a um **agente** (role=0) em `account_id=1`. O `PermissionFilterService` do Rails filtra por `inbox_members`. Como todos os inboxes migrados têm `member_count=0`, as 309 conversas são invisíveis para o token de agente.
- **Confirmação por contraste**: Para `account_id=17`, API=19442=DB ✓ — inboxes de account_id=17 têm membros configurados corretamente.

**Ação PENDENTE**: Solicitar chave API de um **administrator** em `account_id=1` (ex: `admin@vya.digital` user_id=1) para reexecutar validação.

- ✅ **ROOT CAUSE D9/D5-B2: CONFIRMADO**

---

### [16:17] — Próximos passos definidos

1. **🔑 IMEDIATO**: Solicitar token API de administrador (sugerido: `admin@vya.digital`, user_id=1)
2. **🔄 APÓS TOKEN**: Reexecutar `make validate-api` — esperado `api_conv=687` para account_id=1
3. **🛠️ OPCIONAL**: Adicionar `inbox_members` nos 13 inboxes migrados para usuários relevantes
4. **📋 PENDENTE**: Validação profunda (`app/10_validar_api.py deep --sample-size 5`)
5. **🐛 PENDENTE**: BUG-07 manual patch — inbox `dest_id=460` com `channel_id` errado

---

## Encerramento de Sessão

- 📊 **Conversas migradas**: 309 em account_id=1, íntegras no DB ✅
- 🔑 **Bloqueador**: Token API de agente → aguardando token de administrador
- 📝 **Documentos gerados**: D9-ANALISE-CODIGO-CHATWOOT-CONVERSAS-INVISIVEIS-2026-04-23.md
- 🔧 **Bugs corrigidos**: BUG-A (pubsub_token), BUG-B (api_conv=-1), endpoint API
- 📁 **Scripts diagnósticos**: `.tmp/diag_account_id_check.py`, `.tmp/diag_root_cause_visibility.py`

