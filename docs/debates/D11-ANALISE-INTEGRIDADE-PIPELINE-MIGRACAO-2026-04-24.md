# D11 — Análise de Integridade do Pipeline de Migração

**Data**: 2026-04-24
**Autor**: DBA & SQL Expert (GitHub Copilot)
**Versão**: 1.0
**Tipo**: Análise técnica de código — sem geração de código; apenas documentação.
**Status**: RASCUNHO — requer validação do time antes de executar a migração de produção

---

## Sumário Executivo

A análise do código-fonte dos 10 migrators (mais o script `app/13`) identificou:

| Severidade | Qtd | Tipo |
|---|---|---|
| 🔴 CRÍTICO | 3 | Bugs confirmados que produzem dados corrompidos silenciosamente |
| 🟠 ALTO | 4 | Riscos de dados semanticamente incorretos (sem erro de runtime) |
| 🟡 MÉDIO | 4 | Lacunas de validação e entidades faltando na pipeline |
| 🟢 BAIXO | 3 | Riscos operacionais / idempotência parcial |

A migração **NÃO deve ser executada em produção** antes de corrigir os 3 itens críticos.

---

## 1. Análise de Integridade Referencial por Entidade

### 1.1 `accounts`

| FK / Constraint | Status | Análise |
|---|---|---|
| Merge por nome (case-insensitive) | ✅ Implementado | `strip().lower()` correto |
| UNIQUE por nome | ⚠️ Risco residual | Se dois accounts SOURCE têm nomes distintos que normalizam para o mesmo string (e.g., "Vya Digital" / "VYA DIGITAL"), apenas o primeiro é merged; o segundo é inserido como novo account em DEST com offset ID. O DEST terá dois accounts com nomes distintos que representam a mesma entidade. |
| Falha catastrófica | ✅ Correto | `sys.exit(3)` se qualquer batch falhar |

**Riscos de NULL-out vs skip**: N/A — accounts é entidade raiz, sem FK upstream.

---

### 1.2 `inboxes`

| FK / Constraint | Status | Análise |
|---|---|---|
| `account_id` → `accounts` | ✅ Skip orphan | Correto |
| `channel_id` (polimórfico) | 🔴 **CRÍTICO** | Ver BUG-A abaixo |
| Dedup para contas merged | 🔴 **CRÍTICO** | Ver BUG-B abaixo |

#### 🔴 BUG-A — channel_id dangling FK para channel_types desconhecidos

Se `channel_type` não está em `_CHANNEL_CFG` (e.g., algum tipo customizado ou novo), `_migrate_channels` emite apenas `WARNING` e mantém o `channel_id` com o valor SOURCE. Esse ID **não existe** na tabela de channel do DEST. Resultado: `inboxes.channel_id` aponta para um ID inexistente — violação de integridade referencial silenciosa. A inbox ficará invisível ou retornará 404 na API do Chatwoot.

> **Lista de channel_types suportados**: WebWidget, Api, FacebookPage, Telegram, Email, TwilioSms, Whatsapp, Line, Sms. Qualquer variação (e.g., `Channel::EmailBounce`, `Channel::VoIP`) cai neste bug.

#### 🔴 BUG-B — InboxesMigrator não tem dedup para contas merged

Ao contrário de `TeamsMigrator`, `LabelsMigrator` e `ContactsMigrator`, o `InboxesMigrator` **não possui etapa de dedup** para inboxes de contas merged. Isso significa:

1. Se a conta Vya Digital (account_id=1) está merged (src_id=1 → dest_id=1), e o DEST já possui 18 inboxes para account_id=1 (provenientes da instalação original do synchat.vya.digital), **todos os inboxes SOURCE para account_id=1 serão reinseridos** com IDs `src_inbox_id + offset_inboxes`.
2. O DEST terá inboxes duplicados para a mesma conta: os 18 originais + todos os SOURCE (potencialmente os mesmos inboxes com nomes idênticos).
3. Todas as conversas migradas serão associadas aos **novos** inbox IDs (offset), não aos IDs pré-existentes. Agentes que monitoram os inboxes originais não verão as conversas migradas.
4. `inbox_members` (app/13) também mapeia para os novos inbox IDs, criando membros nos inboxes-duplicata e não nos inboxes originais.

**Impacto estimado**: 100% das conversas de Vya Digital (account_id=1) ligadas a inboxes errados.

---

### 1.3 `users` e `account_users`

| FK / Constraint | Status | Análise |
|---|---|---|
| Merge por email (case-insensitive) | ✅ Correto | Alias registrado |
| `users.pubsub_token` UNIQUE | ✅ Correto | `secrets.token_hex(32)` regenerado |
| `users.authentication_token` | 🟠 **ALTO** | Copiado verbatim — ver RISCO-A |
| `account_users` dedup | ✅ Correto | `ON CONFLICT DO NOTHING` |
| Within-batch email collision | ⚠️ Silent skip | Segundo usuário com mesmo email é dropado silenciosamente (WARNING apenas). Seu `src_id` não entra em `migrated_user_ids`, então `account_users` e `conversations.assignee_id` são orfanados. |

#### 🟠 RISCO-A — `authentication_token` (Devise) copiado verbatim

O código NULLa `reset_password_token`, `confirmation_token` e `reset_password_sent_at`, mas **não NULLa `authentication_token`** (campo de autenticação HTTP da API do Chatwoot). Se o DEST usa o mesmo `secret_key_base` do Rails que o SOURCE (cenário improvável mas possível em ambientes de dev), tokens SOURCE autenticam contra o DEST, criando risco de acesso cruzado entre sistemas.

> **Recomendação**: Verificar se DEST e SOURCE compartilham `secret_key_base`. Se sim, adicionar `new_row["authentication_token"] = secrets.token_hex(20)` no `remap_fn` de `UsersMigrator`.

---

### 1.4 `contacts`

| FK / Constraint | Status | Análise |
|---|---|---|
| `account_id` → `accounts` | ✅ Skip orphan | Correto |
| Dedup (phone OR email OR identifier) | ⚠️ Parcialmente correto | Ver RISCO-B |
| `contacts` sem nenhuma chave de dedup | ⚠️ Sem dedup | Contatos sem phone, email e identifier são sempre inseridos, mesmo que sejam duplicatas. |
| Normalização de phone_number | 🟠 **ALTO** | Ver RISCO-B |

#### 🟠 RISCO-B — Phone number sem E.164 → falha de dedup silenciosa

O dedup compara `str(phone).strip().lower()`. Se SOURCE tem `+5511999990000` e DEST tem `5511999990000` (ou `11999990000`), as strings são diferentes → dedup falha → **contato duplicado inserido**. Com ~38.868 contatos, a probabilidade de ao menos algumas dezenas de duplicatas é alta.

**Impacto**: contact_inboxes e conversations para o contato duplicado ficam fragmentados entre dois IDs de contato em DEST.

---

### 1.5 `contact_inboxes`

| FK / Constraint | Status | Análise |
|---|---|---|
| `contact_id` → `contacts` | ✅ Skip orphan | Correto |
| `inbox_id` → `inboxes` | ✅ Skip orphan | Correto |
| UNIQUE (contact_id, inbox_id) | ✅ Dedup por pair | Correto |
| `pubsub_token` UNIQUE | ✅ NULL na insert | Correto |
| `source_id` UNIQUE | ✅ Regenerado UUID | Correto |
| `pubsub_token` permanece NULL | 🟡 **MÉDIO** | Ver RISCO-C |

#### 🟡 RISCO-C — `pubsub_token` permanentemente NULL

`contact_inboxes.pubsub_token` é NULL em todos os registros migrados. O Chatwoot usa esse token para subscriptions WebSocket em tempo real. O Rails normalmente gera esse token via `before_create :generate_pubsub_token`. Como o registro não passa pelo lifecycle Rails, o token nunca é gerado. Isso pode causar falha silenciosa de notificações em tempo real para todos os contact_inboxes migrados.

> **Recomendação**: Executar `UPDATE contact_inboxes SET pubsub_token = gen_random_uuid()::text WHERE pubsub_token IS NULL` após a migração principal.

---

### 1.6 `conversations`

| FK / Constraint | Status | Análise |
|---|---|---|
| `account_id` → `accounts` | ✅ Skip orphan | Correto |
| `inbox_id` → `inboxes` | ✅ Skip orphan | Correto |
| `contact_id` → `contacts` | ✅ NULL-out orphan | Aceitável (manual repair) |
| `assignee_id` → `users` | ✅ NULL-out orphan | Correto |
| `team_id` → `teams` | ✅ NULL-out orphan | Correto |
| `contact_inbox_id` → `contact_inboxes` | ✅ Triplo fallback + NULL-out | Razoável |
| `uuid` UNIQUE | ✅ Regenerado | Correto |
| `display_id` por account | ⚠️ Race condition | Ver RISCO-D |
| `status` copiado verbatim | 🟠 **ALTO** | Ver RISCO-E |

**Decisão NULL-out vs skip para `contact_id`**: correto. Skipar a conversa inteira por contact_id orfão causaria perda em cascata de todas as mensagens e attachments daquela conversa.

**Decisão NULL-out para `contact_inbox_id`**: o fallback triplo é bem-engenheirado. No entanto, o fallback de `(contact_id, inbox_id)` pair falha se `contact_id` também foi NULL-outed (contact orfão). Nesse caso, `dest_contact_id = None` → o fallback retorna `None` → `contact_inbox_id = None`. Uma conversa com tanto `contact_id=NULL` quanto `contact_inbox_id=NULL` está operacionalmente anônima (sem vínculo com canal nem com contato).

#### 🟡 RISCO-D — Race condition no contador `display_id`

`MAX(display_id)` é calculado **uma única vez** antes do loop, em memória. Se qualquer conversa for criada via API do Chatwoot durante a execução da migração (sistema em produção parcialmente ativo), o contador in-memory conflitará com o novo `display_id` gerado pelo Rails. O resultado é violação do UNIQUE constraint `index_conversations_on_display_id_and_account_id`, causando falha do batch inteiro.

> **Mitigação**: Executar migração com o Chatwoot pausado (sem novas conversas sendo criadas).

#### 🟠 RISCO-E — Conversas `status='open'` contaminam filas de agentes

Conversas com `status=0 (open)` do SOURCE são inseridas em DEST como `open`. Para a conta Vya Digital (account_id=1), onde já existem 378 conversas pré-existentes em DEST, a adição de um lote de conversas abertas antigas pode contaminar as filas de atendimento, ativando SLA timers, notificações de agentes e relatórios com dados históricos.

> **Recomendação**: Definir politicamente se conversas SOURCE serão migradas como `status='resolved'` (status=1), excetuando apenas as conversas com `updated_at > (data corte)`.

---

### 1.7 `messages`

| FK / Constraint | Status | Análise |
|---|---|---|
| `account_id` → `accounts` | ✅ Skip orphan | Correto |
| `conversation_id` → `conversations` | ✅ Skip orphan | Correto |
| `sender_id` → `users` | ✅ NULL-out orphan | Aceitável |
| `content` com URLs antigas | 🟠 **ALTO** | Ver RISCO-F |

#### 🟠 RISCO-F — S3 URLs embutidas em `messages.content`

`content` (TEXT) é copiado verbatim. Mensagens que contêm URLs de arquivos do storage do chat.vya.digital (S3 ou ActiveStorage) serão exibidas em DEST mas os links apontarão para o storage do sistema SOURCE. Se:
- Os buckets S3 SOURCE forem privados → arquivos inacessíveis (broken links)
- O SOURCE for descomissionado após a migração → todos os links do `content` quebram
- Mensagens do legado TBChat contêm URLs do schema antigo → UX degradada

**Impacto**: ~310.155 mensagens. Estima-se que qualquer mensagem com imagem inline ou link de attachment embutido seja afetada.

---

### 1.8 `attachments`

| FK / Constraint | Status | Análise |
|---|---|---|
| `message_id` → `messages` | ✅ Skip orphan | Correto |
| `account_id` → `accounts` | ✅ Skip orphan | Correto |
| `external_url` copiado verbatim | 🟡 **MÉDIO** | Ver RISCO-G |

#### 🟡 RISCO-G — `external_url` aponta para storage SOURCE

Mesmo risco que messages.content. O registro de attachment é migrado corretamente, mas o arquivo físico permanece no storage SOURCE. Se SOURCE for descomissionado, todos os attachments migrados ficam com URL quebrada.

**Ausência de FK para `conversations`**: `attachments` tem FK apenas para `messages` e `accounts`. Não há FK direta para `conversations`. Isso é correto pelo schema Chatwoot.

---

### 1.9 `inbox_members` (app/13)

| FK / Constraint | Status | Análise |
|---|---|---|
| `user_id` → `users` | ✅ Skip orphan | Correto via migration_state |
| `inbox_id` → `inboxes` | ✅ Skip orphan | Correto via migration_state |
| ON CONFLICT DO NOTHING | ✅ Idempotente | Correto |
| Dependência de inboxes pré-existentes | 🔴 **BUG-B cascade** | `inbox_map` usa migration_state, que mapeia src_inbox_id para o NOVO inbox_id (offset). Se BUG-B não for corrigido, membros são mapeados para os inboxes-duplicata, não para os inboxes originais do DEST. |

---

## 2. Riscos de Dados Silenciosos (sem erro, dados errados)

### 2.1 Tabela resumo

| ID | Entidade afetada | Campo | Comportamento silencioso | Impacto |
|---|---|---|---|---|
| S-01 | `contacts` | `phone_number` | Dedup falha se formato difere de E.164 | Contatos duplicados, histórico fragmentado |
| S-02 | `conversations` | `status` | Conversas `open` SOURCE ativam filas em DEST imediatamente | Filas de atendimento contaminadas |
| S-03 | `messages` | `content` | URLs S3 SOURCE embutidas no texto | Links quebrados após descomissionamento SOURCE |
| S-04 | `inboxes` | `page_access_token`, `app_secret` (Facebook/WhatsApp) | Credenciais copiadas verbatim | Conflito de webhook com SOURCE |
| S-05 | `inboxes` | (duplicação inteira) | Inboxes duplicados para contas merged | Conversas visíveis no inbox errado |
| S-06 | `users` | `authentication_token` | Token de API copiado verbatim | Tokens SOURCE funcionam em DEST |
| S-07 | `contact_inboxes` | `pubsub_token` | NULL permanente | Real-time WebSocket silenciosamente quebrado |
| S-08 | `conversations` | `contact_inbox_id` | NULL quando contact_id e inbox_id ambos orfãos | Conversa sem vínculo de canal |
| S-09 | `teams` / `labels` | dedup condition | Dedup falha para merged accounts com src_id ≠ dest_id | Duplicação de teams/labels |

### 2.2 Detalhamento de S-04 — Credenciais Facebook/Telegram/WhatsApp verbatim

`_CHANNEL_CFG` define `{}` (sem campos para regenerar) para `Channel::FacebookPage`, `Channel::Telegram`, `Channel::Whatsapp`, `Channel::TwilioSms`, `Channel::Line`, `Channel::Sms`. Isso significa:

- `channel_facebook_pages.page_access_token` → copiado verbatim
- `channel_facebook_pages.app_secret` → copiado verbatim
- `channel_whatsapp.api_key` / `channel_whatsapp.phone_number` → copiados verbatim

Se o SOURCE (chat.vya.digital) ainda está ativo com esses canais, o DEST (vya-chat-dev.vya.digital) terá as mesmas credenciais. Dependendo da plataforma:
- **Facebook**: apenas um webhook ativo por app/page ao mesmo tempo. DEST pode "roubar" o webhook do SOURCE ou ambos ficam em conflito.
- **WhatsApp (Business API)**: sessões duplicadas podem resultar em mensagens sendo entregues ao SOURCE ou ao DEST aleatoriamente.
- **Telegram**: token de bot pode ser usado em apenas um webhook por vez. DEST vai conflitar com SOURCE.

### 2.3 Detalhamento de S-09 — Bug de dedup em TeamsMigrator e LabelsMigrator

A condição de dedup em ambos os migrators é:

```python
merged_account_ids: set[int] = {
    acct_id
    for acct_id in migrated_accounts
    if self.id_remapper.remap(acct_id, "accounts") == acct_id  # ← BUG
}
```

Esta condição retorna `True` apenas quando `src_id == dest_id` (i.e., o account tem o mesmo ID numérico em SOURCE e DEST). Para contas onde o merge é por nome mas os IDs diferem (e.g., SOURCE account_id=3, DEST account_id=7, ambos chamados "Cliente X"), `remap(3, "accounts") = 7 ≠ 3`, logo `merged_account_ids` fica vazio e **o dedup não é executado**. Teams e labels idênticos são duplicados em DEST para essas contas.

**Comparação com ContactsMigrator** (abordagem correta):

```python
merged_account_ids: set[int] = {
    acct_id
    for acct_id in src_account_ids
    if self.id_remapper.has_alias("accounts", acct_id)  # ← correto
}
```

> **Ação necessária**: Teams e LabelsMigrator devem usar `has_alias()` em vez de comparação de IDs.

Para o caso específico Vya Digital (src_id=1, dest_id=1), o bug não se manifesta porque `remap(1) == 1`. Mas para qualquer outra conta merged com IDs distintos, teams e labels serão duplicados.

---

## 3. Análise da Ordem de Migração

### 3.1 Verificação de dependências FK

```
accounts
  └─ inboxes (account_id)
  │    └─ channel_web_widgets / channel_api / ... (migrado antes, correto ✅)
  └─ users (sem FK direta para accounts; account_users sim)
  │    └─ account_users (account_id, user_id) ✅
  └─ teams (account_id) ✅
  └─ labels (account_id) ✅
  └─ contacts (account_id) ✅
       └─ contact_inboxes (contact_id, inbox_id) ✅
            └─ conversations (account_id, inbox_id, contact_id, contact_inbox_id,
                              assignee_id→users, team_id→teams) ✅
                 └─ messages (account_id, conversation_id, sender_id→users) ✅
                      └─ attachments (message_id, account_id) ✅
```

A ordem atual é **correta para todas as FKs declaradas**. Não há inversão de dependência.

### 3.2 Posicionamento de `inbox_members` (app/13)

`inbox_members` (inbox_id, user_id) tem FKs para `inboxes` e `users`. Dependência de dados: deve rodar APÓS inboxes e users estarem migrados.

**Pergunta operacional**: deve rodar antes ou depois de `conversations`?

- `conversations` não tem FK para `inbox_members`. Logo, **não há dependência de dados direta**.
- Porém, do ponto de vista operacional: se `inbox_members` não estiver populado quando o Chatwoot for ligado, **agentes não veem as conversas migradas** (a query de conversas visíveis por agente filtra por `inbox_members.user_id`). Portanto, `inbox_members` deve ser executado **antes de ligar o Chatwoot em DEST** (não necessariamente antes de `conversations` na pipeline de migração).

> **Recomendação**: documentar explicitamente que `app/13_migrar_inbox_members.py` deve ser executado **imediatamente após o passo `inboxes`**, antes de `conversations`, para garantir que a validação da visibilidade seja possível durante a migração.

### 3.3 Tabelas e junction tables ausentes da pipeline

| Tabela | FKs | Impacto da ausência |
|---|---|---|
| `team_members` | `team_id`, `user_id` | Membros de teams não migrados → agentes não recebem roteamento automático por team em DEST |
| `conversation_labels` | `conversation_id`, `label_id` | Labels atribuídas a conversas não são migradas → relatórios de labels quebrados |
| `conversation_participants` | `conversation_id`, `user_id` | Participantes de conversas perdidos → notificações quebradas |
| `taggings` / `tags` | polymorphic | Tags de contatos e conversas perdidas |
| `notifications` | `user_id`, `conversation_id` | Notificações não migradas — aceitável (temporárias) |
| `reports` / `v2_reports` | `account_id` | Histórico de relatórios não migrado — risco de dados analíticos incompletos |
| `csat_survey_responses` | `conversation_id`, `contact_id` | Respostas CSAT perdidas — pode ser intencional |

**Mais crítico**: `conversation_labels` — sem ela, todo o trabalho de categorização de conversas com labels no SOURCE é silenciosamente descartado.

---

## 4. Análise de Idempotência e Re-run

### 4.1 Interrupção no meio de `messages` (~310k registros, ~621 batches)

**Cenário**: migração executada, progride até o batch 300 de messages (150k registros), então crash.

**Comportamento no re-run**:
1. `compute_offsets()` é chamado novamente → `MAX(id)` de `messages` no DEST agora é `150000 + offset_original`. O offset na sessão 2 é MAIOR do que na sessão 1.
2. `migration_state` já tem `status='ok'` para os 150k message src_ids. Eles são skipped. ✅
3. As mensagens restantes (150k+1 a 310k) recebem novos IDs: `src_id + offset_sessao2`. ✅
4. **RISCO**: se o crash foi no meio de um batch (batch 300 de 500 rows) e algumas linhas do batch foram inseridas no Postgres antes do rollback (i.e., a transação foi ABORTADA, não commitada), o resultado é:
   - As linhas não foram commitadas → não existem em DEST ✅
   - Mas a sequence `messages_id_seq` pode ter avançado para além do que foi commitado → gaps de ID. Aceitável.
5. **RISCO REAL**: se o crash ocorreu FORA da transação (e.g., exception no `record_success_bulk` após o INSERT já commitado), os registros estão em DEST mas não em `migration_state`. Na sessão 2, esses src_ids não estão em `already_done`, então o `remap_fn` é aplicado novamente com o NOVO offset (diferente). O INSERT tentará inserir com ID `src_id + offset_sessao2`, que é diferente de `src_id + offset_sessao1`. Se o registro original (offset_sessao1) ainda existir em DEST, não haverá colisão de ID (IDs são diferentes). **Dois registros para o mesmo src_id existirão em DEST** — duplicata de mensagem.

> Este é o principal risco de re-run após crash parcial. O código tenta mitigar registrando falhas no `record_failure`, mas se o crash ocorreu entre o `bulk_insert` commit e o `record_success_bulk`, a janela existe.

### 4.2 Segunda execução completa sem limpar `migration_state`

**Cenário**: migração executou com sucesso e é executada uma segunda vez.

| Tabela | Comportamento | Safe? |
|---|---|---|
| `accounts` | Todos os src_ids em `migration_state` → dedup e merge re-executados, mas `already_done` faz skip do INSERT | ✅ Safe |
| `inboxes` | `already_done` via migration_state → skip | ✅ Safe |
| `inboxes` (channels) | `_migrate_channels` re-executa sem verificar se channel já existe em DEST → **re-insere** channels com novos IDs via nextval() | ⚠️ Unsafe para channels |
| `users` | Merge + migration_state → skip | ✅ Safe |
| `account_users` | `ON CONFLICT DO NOTHING` → idempotente | ✅ Safe |
| `teams` | Dedup + migration_state → skip | ✅ Safe |
| `labels` | Dedup + migration_state → skip | ✅ Safe |
| `contacts` | Dedup + migration_state → skip | ✅ Safe |
| `contact_inboxes` | Dedup por pair + migration_state → skip | ✅ Safe |
| `conversations` | migration_state → skip; `_display_id_counters` recalculado do novo MAX (que inclui a primeira run) | ✅ Safe |
| `messages` | migration_state → skip | ✅ Safe |
| `attachments` | migration_state → skip | ✅ Safe |
| `inbox_members` | `existing_pairs` + ON CONFLICT → idempotente | ✅ Safe |

**Único componente não-idempotente confirmado**: `_migrate_channels` dentro de `InboxesMigrator`. Se executado pela segunda vez, channel records são duplicados no DEST (novos IDs via sequence). Mas como os inbox records correspondentes já estão em `migration_state` e são skipped, os channels duplicados ficam como registros órfãos nas tabelas de channel.

### 4.3 Tabelas seguras vs não-seguras para re-run

| Tabela | Re-run safe? | Condição |
|---|---|---|
| `accounts` | ✅ | migration_state presente |
| `inboxes` | ✅ | migration_state presente — mas channels se re-inserem |
| `users` | ✅ | migration_state + `ON CONFLICT DO NOTHING` em account_users |
| `teams` | ✅ | migration_state presente |
| `labels` | ✅ | migration_state presente |
| `contacts` | ✅ | migration_state presente |
| `contact_inboxes` | ✅ | migration_state + dedup por pair |
| `conversations` | ✅ | migration_state presente; race condition de display_id apenas em run concorrente |
| `messages` | ✅ | migration_state presente |
| `attachments` | ✅ | migration_state presente |
| `inbox_members` (app/13) | ✅ | ON CONFLICT DO NOTHING + set local |
| `channel_*` (interno InboxesMigrator) | ❌ | Sem controle de idempotência — re-insere sempre |

---

## 5. Riscos Específicos para `account_id=1` (Vya Digital)

### 5.1 Perfil da conta no contexto de migração

- SOURCE: `chatwoot_dev1_db`, account_id=1, nome "Vya Digital"
- DEST: `chatwoot004_dev1_db`, account_id=1, nome "Vya Digital"
- Resultado do AccountsMigrator: merge por nome → alias registrado `src_id=1 → dest_id=1`
- DEST já tem dados pré-existentes: 378 conversas, 18 inboxes

### 5.2 Tratamento de colisões de `display_id`

O `_display_id_counters[1]` é inicializado com `MAX(display_id)` do DEST para account_id=1 (provavelmente ≥ 378). Cada nova conversa migrada recebe `display_id = MAX + incremento_in_memory`.

**Problema de race condition** (RISCO-D acima): durante a migração, se um agente ou processo cria uma nova conversa em DEST para account_id=1, o `MAX(display_id)` já calculado está desatualizado. A nova conversa recebe um `display_id` via Chatwoot Rails que pode colidir com o próximo valor do contador in-memory.

**Solução de mitigação necessária**: colocar DEST em modo de manutenção (sem novas conversas) durante a janela de migração.

### 5.3 Tratamento de contacts de Vya Digital em DEST

O `ContactsMigrator` identifica account_id=1 como `merged_account_ids` (via `has_alias`). A lógica de dedup consulta DEST por `(account_id=1, phone_number)`, `(account_id=1, email)` e `(account_id=1, identifier)`. Contacts com match → alias, skip INSERT.

**Riscos**:
1. Contato SOURCE com `phone="+5511999990000"` vs DEST com `phone="5511999990000"` → não matcham → duplicata.
2. Contato sem phone/email/identifier → sem chave de dedup → sempre inserido como novo, mesmo que seja duplicata nominal.
3. Os ~38.868 contacts SOURCE incluem contacts de todas as contas. Para account_id=1 especificamente, a quantidade de contatos com dedup falho por formato de telefone é desconhecida sem consulta ao dado real.

### 5.4 Inboxes de Vya Digital — impacto do BUG-B

Os 18 inboxes pré-existentes em DEST para account_id=1 foram criados via instalação normal do Chatwoot (synchat.vya.digital). Se esses inboxes são funcionalmente os mesmos que existem em SOURCE (chat.vya.digital), o BUG-B causa:

1. 18 inboxes SOURCE → inseridos como novos inboxes com IDs `src_id + offset_inboxes` em DEST.
2. DEST terá 36+ inboxes para account_id=1 (18 originais + 18+ novos duplicados).
3. Todos os inbox_members e conversations migrados apontam para os 18 novos, não para os 18 originais.
4. Canais Facebook/WhatsApp dos 18 novos inboxes têm as **mesmas credenciais** que os 18 originais (verbatim copy) — conflito imediato de webhook/session.

Se os 18 DEST inboxes são **diferentes** dos SOURCE (e.g., DEST tem configuração nova para vya-chat-dev), a duplicação ainda ocorre mas o impacto de conflito de credenciais não se aplica.

> **Ação necessária antes de executar em produção**: verificar se os inboxes de account_id=1 no SOURCE e no DEST são os mesmos (comparar por nome/tipo). Se sim, o BUG-B deve ser corrigido antes da migração.

---

## 6. Checklist de Validações SQL — Pré-condição da Migração

As queries abaixo devem ser executadas no SOURCE e no DEST **antes de iniciar a migração**, em ordem de criticidade. Cada query deve retornar zero rows ou satisfazer o critério especificado; caso contrário, ação corretiva é obrigatória.

### PRE-01 🔴 CRÍTICO — Inventário de channel_types no SOURCE

**Database**: SOURCE (`chatwoot_dev1_db`)

```sql
SELECT channel_type, COUNT(*) AS qtd
FROM inboxes
GROUP BY channel_type
ORDER BY qtd DESC;
```

**O que verifica**: lista todos os channel_types que existirão no DEST após migração.

**Ação se resultado problemático**: qualquer `channel_type` **não** presente em `['Channel::WebWidget', 'Channel::Api', 'Channel::FacebookPage', 'Channel::Telegram', 'Channel::Email', 'Channel::TwilioSms', 'Channel::Whatsapp', 'Channel::Line', 'Channel::Sms']` acionará o BUG-A (dangling channel_id FK). Adicionar o tipo ausente ao `_CHANNEL_CFG` antes de prosseguir.

---

### PRE-02 🔴 CRÍTICO — Inboxes de contas merged no SOURCE vs DEST

**Database**: SOURCE e DEST

```sql
-- SOURCE: inboxes de account_id=1
SELECT id, name, channel_type
FROM inboxes WHERE account_id = 1 ORDER BY name;

-- DEST: inboxes de account_id=1
SELECT id, name, channel_type
FROM inboxes WHERE account_id = 1 ORDER BY name;
```

**O que verifica**: se os inboxes das duas instâncias são os mesmos (por nome). Se forem idênticos (mesmos nomes e tipos), o BUG-B deve ser corrigido antes de migrar, ou os inboxes DEST devem ser deletados antes da migração (recriar do zero via migração).

**Ação se idênticos**: corrigir BUG-B no código (adicionar dedup de inboxes por `(name, account_id)` para contas merged), ou alternativamente, remover os inboxes pré-existentes em DEST e deixar a migração recriar tudo.

---

### PRE-03 🔴 CRÍTICO — Verificar se `migration_state` está limpo (para primeira run)

**Database**: DEST

```sql
SELECT tabela, COUNT(*) AS qtd, MAX(migrated_at) AS ultima_migracao
FROM migration_state
GROUP BY tabela
ORDER BY ultima_migracao DESC;
```

**O que verifica**: se existe estado de migração residual de runs anteriores. Se existir, a migração se comportará como re-run (idempotente), o que pode ser intencional ou não.

**Ação**: se for uma primeira migração limpa, `TRUNCATE migration_state;` antes de prosseguir. Se for re-run intencional, verificar quais tabelas estão completas e quais estão incompletas.

---

### PRE-04 🟠 ALTO — Contagem de source records por tabela

**Database**: SOURCE

```sql
SELECT
  (SELECT COUNT(*) FROM accounts)        AS accounts,
  (SELECT COUNT(*) FROM inboxes)         AS inboxes,
  (SELECT COUNT(*) FROM users)           AS users,
  (SELECT COUNT(*) FROM teams)           AS teams,
  (SELECT COUNT(*) FROM labels)          AS labels,
  (SELECT COUNT(*) FROM contacts)        AS contacts,
  (SELECT COUNT(*) FROM contact_inboxes) AS contact_inboxes,
  (SELECT COUNT(*) FROM conversations)   AS conversations,
  (SELECT COUNT(*) FROM messages)        AS messages,
  (SELECT COUNT(*) FROM attachments)     AS attachments,
  (SELECT COUNT(*) FROM inbox_members)   AS inbox_members;
```

**O que verifica**: baseline de contagem para comparação pós-migração. Salvar o resultado.

**Ação**: nenhuma; apenas documentar os valores.

---

### PRE-05 🟠 ALTO — Contatos sem nenhuma chave de dedup em contas merged

**Database**: SOURCE

```sql
SELECT COUNT(*) AS contacts_sem_chave_dedup
FROM contacts
WHERE account_id = 1  -- substituir por todas as contas merged
  AND (phone_number IS NULL OR TRIM(phone_number) = '')
  AND (email IS NULL OR TRIM(email) = '')
  AND (identifier IS NULL OR TRIM(identifier) = '');
```

**O que verifica**: quantidade de contatos da conta Vya Digital sem nenhuma chave de dedup. Esses contatos serão sempre inseridos como novos em DEST, mesmo que já existam.

**Ação se > 0**: avaliar se é necessário um dedup adicional por `name` antes da migração, ou aceitar a duplicação e tratar manualmente depois.

---

### PRE-06 🟠 ALTO — Variações de formato de phone_number em contas merged

**Database**: SOURCE e DEST

```sql
-- SOURCE: distribuição de formatos de phone_number para account_id=1
SELECT
  CASE
    WHEN phone_number LIKE '+%' THEN 'E.164 com +'
    WHEN phone_number ~ '^\d{10,15}$' THEN 'numérico sem +'
    WHEN phone_number IS NULL THEN 'NULL'
    ELSE 'outro formato'
  END AS formato,
  COUNT(*) AS qtd
FROM contacts
WHERE account_id = 1
GROUP BY 1;

-- DEST: mesma consulta
-- (substituir chatwoot_dev1_db por chatwoot004_dev1_db na conexão)
```

**O que verifica**: se há mismatch de formato entre SOURCE e DEST que causará falha de dedup (RISCO-B).

**Ação se formatos divergem**: normalizar ambas as bases para E.164 antes da migração, ou aceitar a duplicação e deduplicar manualmente pós-migração.

---

### PRE-07 🟡 MÉDIO — Verifica `MAX(display_id)` por account em DEST

**Database**: DEST

```sql
SELECT account_id, MAX(display_id) AS max_display_id, COUNT(*) AS total_conversas
FROM conversations
GROUP BY account_id
ORDER BY account_id;
```

**O que verifica**: baseline do `display_id` antes da migração. O `ConversationsMigrator` inicializará `_display_id_counters` com esses valores.

**Ação**: documentar. Usar para verificar pós-migração se os display_ids ficaram sequenciais e sem gaps.

---

### PRE-08 🟡 MÉDIO — Verifica sequences em DEST para todas as tabelas migradas

**Database**: DEST

```sql
SELECT
  schemaname,
  sequencename,
  last_value,
  is_called
FROM pg_sequences
WHERE sequencename IN (
  'accounts_id_seq',
  'inboxes_id_seq',
  'users_id_seq',
  'teams_id_seq',
  'labels_id_seq',
  'contacts_id_seq',
  'contact_inboxes_id_seq',
  'conversations_id_seq',
  'messages_id_seq',
  'attachments_id_seq',
  'channel_web_widgets_id_seq',
  'channel_api_id_seq',
  'channel_facebook_pages_id_seq',
  'channel_telegram_id_seq',
  'channel_email_id_seq',
  'channel_twilio_sms_id_seq',
  'channel_whatsapp_id_seq',
  'channel_line_id_seq',
  'channel_sms_id_seq'
)
ORDER BY sequencename;
```

**O que verifica**: garante que as sequences estão adiantadas o suficiente para não colidir com IDs inseridos pelo migrador (que usa `INSERT ... id = src_id + offset`).

**Ação se `last_value < MAX(id)` de alguma tabela**: executar `SELECT setval('tabela_id_seq', (SELECT MAX(id) FROM tabela));` antes de ligar o Chatwoot após a migração.

---

### PRE-09 🟡 MÉDIO — Convesações `open` no SOURCE para contas merged

**Database**: SOURCE

```sql
SELECT account_id, status, COUNT(*) AS qtd
FROM conversations
WHERE account_id = 1  -- contas merged
GROUP BY account_id, status
ORDER BY account_id, status;
```

**O que verifica**: quantas conversas abertas serão inseridas em DEST e contaminarão filas de agentes.

**Ação se qtd alta**: definir politicamente o `status` de destino para conversas históricas. Documentar a decisão antes de executar a migração.

---

## 7. Checklist de Validações Pós-migração

As queries abaixo devem ser executadas no DEST **imediatamente após a migração**, antes de ligar o Chatwoot em produção, em ordem de criticidade.

### POS-01 🔴 CRÍTICO — Contagem final vs contagem baseline (PRE-04)

**Database**: DEST

```sql
-- Comparar com os valores de PRE-04
SELECT
  (SELECT COUNT(*) FROM accounts)        AS accounts,
  (SELECT COUNT(*) FROM inboxes)         AS inboxes,
  (SELECT COUNT(*) FROM users)           AS users,
  (SELECT COUNT(*) FROM teams)           AS teams,
  (SELECT COUNT(*) FROM labels)          AS labels,
  (SELECT COUNT(*) FROM contacts)        AS contacts,
  (SELECT COUNT(*) FROM contact_inboxes) AS contact_inboxes,
  (SELECT COUNT(*) FROM conversations)   AS conversations,
  (SELECT COUNT(*) FROM messages)        AS messages,
  (SELECT COUNT(*) FROM attachments)     AS attachments,
  (SELECT COUNT(*) FROM inbox_members)   AS inbox_members;
```

**O que verifica**: os totais em DEST devem ser ≥ baseline pré-existente + registros migrados do SOURCE (menos os skipped por orphan FK). Qualquer shortfall deve ser investigado.

---

### POS-02 🔴 CRÍTICO — FKs dangling em `inboxes.channel_id`

**Database**: DEST

```sql
WITH channel_refs AS (
  SELECT
    i.id AS inbox_id,
    i.channel_type,
    i.channel_id,
    CASE i.channel_type
      WHEN 'Channel::WebWidget'    THEN (SELECT COUNT(*) FROM channel_web_widgets    w WHERE w.id = i.channel_id)
      WHEN 'Channel::Api'          THEN (SELECT COUNT(*) FROM channel_api             a WHERE a.id = i.channel_id)
      WHEN 'Channel::FacebookPage' THEN (SELECT COUNT(*) FROM channel_facebook_pages  f WHERE f.id = i.channel_id)
      WHEN 'Channel::Telegram'     THEN (SELECT COUNT(*) FROM channel_telegram        t WHERE t.id = i.channel_id)
      WHEN 'Channel::Email'        THEN (SELECT COUNT(*) FROM channel_email           e WHERE e.id = i.channel_id)
      WHEN 'Channel::Whatsapp'     THEN (SELECT COUNT(*) FROM channel_whatsapp        w WHERE w.id = i.channel_id)
      ELSE 0
    END AS channel_exists
  FROM inboxes i
  WHERE i.channel_id IS NOT NULL
)
SELECT inbox_id, channel_type, channel_id
FROM channel_refs
WHERE channel_exists = 0
ORDER BY inbox_id;
```

**O que verifica**: inboxes com `channel_id` que não encontram correspondência na tabela de channel. Zero rows é o resultado esperado.

**Ação se rows retornadas**: para cada inbox listado, a inbox está quebrada. É necessário inserir manualmente o channel record ou deletar o inbox.

---

### POS-03 🔴 CRÍTICO — `migration_state` sem erros

**Database**: DEST

```sql
SELECT tabela, status, COUNT(*) AS qtd
FROM migration_state
GROUP BY tabela, status
ORDER BY tabela, status;
```

**O que verifica**: quantos registros têm `status != 'ok'`. Qualquer registro com `status = 'failed'` indica perda de dado.

**Ação se status='failed' presente**: investigar o motivo do erro nos logs de migração e reprocessar manualmente ou via re-run seletivo.

---

### POS-04 🟠 ALTO — Conversas sem `contact_inbox_id` (NULL-out)

**Database**: DEST

```sql
SELECT
  account_id,
  COUNT(*) FILTER (WHERE contact_inbox_id IS NULL) AS conv_sem_contact_inbox,
  COUNT(*) AS total_conv,
  ROUND(100.0 * COUNT(*) FILTER (WHERE contact_inbox_id IS NULL) / COUNT(*), 2) AS pct_sem_vínculo
FROM conversations
WHERE id > (SELECT COALESCE(MAX(id), 0) FROM conversations WHERE created_at < NOW() - INTERVAL '1 year')
  -- ajustar filtro de data conforme janela de migração
GROUP BY account_id
ORDER BY pct_sem_vínculo DESC;
```

**O que verifica**: percentual de conversas migradas sem vínculo de `contact_inbox_id`. Um percentual alto indica problema no migrador de `contact_inboxes`.

**Threshold aceitável**: < 5%. Acima disso, investigar.

---

### POS-05 🟠 ALTO — Sequences desatualidas pós-migração

**Database**: DEST

```sql
SELECT
  t.tablename,
  t.max_id,
  s.last_value AS seq_last_value,
  (t.max_id > s.last_value) AS sequence_behind
FROM (
  VALUES
    ('accounts',        (SELECT MAX(id) FROM accounts)),
    ('inboxes',         (SELECT MAX(id) FROM inboxes)),
    ('users',           (SELECT MAX(id) FROM users)),
    ('contacts',        (SELECT MAX(id) FROM contacts)),
    ('contact_inboxes', (SELECT MAX(id) FROM contact_inboxes)),
    ('conversations',   (SELECT MAX(id) FROM conversations)),
    ('messages',        (SELECT MAX(id) FROM messages)),
    ('attachments',     (SELECT MAX(id) FROM attachments))
) AS t(tablename, max_id)
JOIN pg_sequences s ON s.sequencename = t.tablename || '_id_seq';
```

**O que verifica**: se alguma sequence está atrás do MAX(id) da tabela. Se `sequence_behind = true`, o próximo INSERT via Chatwoot Rails causará `duplicate key` error.

**Ação obrigatória se `sequence_behind = true`**:
```sql
SELECT setval('tabela_id_seq', (SELECT MAX(id) FROM tabela) + 1);
```
Executar para cada tabela com `sequence_behind = true`.

---

### POS-06 🟡 MÉDIO — `contact_inboxes` com `pubsub_token` NULL

**Database**: DEST

```sql
SELECT COUNT(*) AS total_null_pubsub_token
FROM contact_inboxes
WHERE pubsub_token IS NULL;
```

**O que verifica**: quantos `contact_inboxes` têm `pubsub_token` NULL (todos os migrados).

**Ação**: executar `UPDATE contact_inboxes SET pubsub_token = gen_random_uuid()::text WHERE pubsub_token IS NULL;` antes de ligar o Chatwoot.

---

### POS-07 🟡 MÉDIO — Conversas sem `contact_id` (NULL-outed)

**Database**: DEST

```sql
SELECT
  account_id,
  COUNT(*) FILTER (WHERE contact_id IS NULL) AS conv_sem_contato,
  COUNT(*) AS total
FROM conversations
GROUP BY account_id
HAVING COUNT(*) FILTER (WHERE contact_id IS NULL) > 0
ORDER BY conv_sem_contato DESC;
```

**O que verifica**: conversas sem vínculo de contato (FK orfã NULL-outed). Essas conversas precisam de reparo manual ou são aceitáveis.

---

### POS-08 🟡 MÉDIO — Mensagens sem `sender_id` (NULL-outed)

**Database**: DEST

```sql
SELECT
  message_type,
  COUNT(*) FILTER (WHERE sender_id IS NULL) AS msg_sem_sender,
  COUNT(*) AS total
FROM messages
GROUP BY message_type
ORDER BY msg_sem_sender DESC;
```

**O que verifica**: distribuição de mensagens sem sender por tipo. Para `message_type=1 (outgoing)`, mensagens sem sender_id são particularmente problemáticas (aparecerão sem autor na UI).

---

### POS-09 🟢 BAIXO — `display_id` sequencial por account (sem gaps)

**Database**: DEST

```sql
WITH ranked AS (
  SELECT
    account_id,
    display_id,
    ROW_NUMBER() OVER (PARTITION BY account_id ORDER BY display_id) AS rn
  FROM conversations
)
SELECT account_id, COUNT(*) AS gaps
FROM ranked
WHERE display_id != rn
GROUP BY account_id
HAVING COUNT(*) > 0;
```

**O que verifica**: conversas com `display_id` não sequencial (gaps). Chatwoot espera `display_id` sequencial por account para exibição na UI.

**Ação**: gaps são aceitáveis mas devem ser documentados. Não é necessário corrigi-los; Chatwoot continua funcionando com gaps.

---

### POS-10 🟢 BAIXO — Inboxes duplicados por nome para contas merged

**Database**: DEST

```sql
SELECT account_id, name, channel_type, COUNT(*) AS qtd
FROM inboxes
GROUP BY account_id, name, channel_type
HAVING COUNT(*) > 1
ORDER BY account_id, name;
```

**O que verifica**: inboxes com o mesmo nome e tipo na mesma conta (resultado do BUG-B, se presente).

**Ação**: se duplicatas encontradas, investigar se os inboxes novos (offset) contêm as conversas migradas. Decidir entre: (a) manter os originais e reassociar conversas, ou (b) aceitar os duplicados e desativar os originais.

---

## Referências

- Código analisado: `src/migrators/*.py`, `app/13_migrar_inbox_members.py`
- Data da análise: 2026-04-24
- Commits analisados: estado atual do branch principal
- Debates relacionados: D3 (estratégia merge), D7 (visibilidade Marcos), D8 (404 API)

---

*Este documento é de uso interno do projeto `enterprise-chathoot-migration`.  
Não contém código SQL executável — apenas documentação de análise e recomendações.*
