# D17 — Análise de Cobertura de Tabelas na Migração

**Data**: 2026-05-24
**Sessão**: S23
**Tipo**: Análise Técnica — Validação de Completude do Workflow de Migração

---

## 📋 Contexto

O **Account Offboarding Tool** (`tools/account_offboarding/cleanup.py`) foi criado para **remover TODOS os dados** de um account Chatwoot, cobrindo **45+ tabelas** do schema.

Esta análise compara a **lista completa de tabelas** do `cleanup.py` com as **tabelas atualmente migradas** em `src/migrar.py` para identificar:

1. ✅ **Tabelas cobertas** pela pipeline de migração
2. ⚠️ **Tabelas NÃO migradas** (gaps)
3. 🔍 **Impacto** de cada gap (crítico vs aceitável)
4. 📝 **Recomendações** de ação

---

## 📊 Inventário Completo de Tabelas

### Tabelas no `cleanup.py` (52 tabelas)

**Ordem FK-aware de remoção:**

```python
# --- Dependentes de messages ---
1.  attachments
2.  mentions
3.  reporting_events
4.  messages

# --- Dependentes de conversations ---
5.  conversation_participants
6.  csat_survey_responses
7.  applied_slas
8.  sla_events
9.  contact_inboxes
10. conversations

# --- Dependentes de contacts ---
11. contacts

# --- Dependentes de inboxes ---
12. agent_bot_inboxes
13. inbox_members
14. working_hours
15. channel_api
16. channel_whatsapp
17. channel_web_widgets
18. channel_email
19. channel_facebook_pages
20. channel_telegram
21. channel_sms
22. channel_twilio_sms
23. channel_line
24. channel_twitter_profiles
25. inboxes

# --- Agent bots ---
26. agent_bots

# --- Notificações ---
27. notification_settings
28. notifications

# --- Teams ---
29. team_memberships
30. teams

# --- Portals (Knowledge Base / Help Center) ---
31. portal_members
32. categories
33. articles
34. folders
35. portals

# --- Features de nível account ---
36. labels
37. canned_responses
38. automation_rules
39. macros
40. campaigns
41. dashboard_apps
42. custom_attribute_definitions
43. custom_filters
44. custom_roles
45. data_imports
46. email_templates
47. sla_policies
48. webhooks
49. integrations_hooks
50. telegram_bots

# --- Vínculo users↔account ---
51. account_users

# --- Raiz ---
52. accounts
```

**Total: 52 tabelas** identificadas no schema Chatwoot.

---

### Tabelas em `src/migrar.py` (_MIGRATION_ORDER)

**Ordem canônica de migração:**

```python
_MIGRATION_ORDER = [
    "accounts",                         # 1
    "custom_attribute_definitions",     # 2
    "canned_responses",                 # 3
    "inboxes",                          # 4
    "webhooks",                         # 5
    "users",                            # 6
    "teams",                            # 7
    "team_members",                     # 8
    "labels",                           # 9
    "contacts",                         # 10
    "contact_inboxes",                  # 11
    "conversations",                    # 12
    "messages",                         # 13
    "attachments",                      # 14
    "conversation_labels",              # 15
]
```

**Total: 15 tabelas** migradas.

---

## 🔍 Análise Comparativa

### ✅ Tabelas Cobertas pela Migração (15)

| Tabela | Status | Migrator | Notas |
|--------|--------|----------|-------|
| `accounts` | ✅ Migrado | `AccountsMigrator` | Raiz |
| `custom_attribute_definitions` | ✅ Migrado | `CustomAttributeDefinitionsMigrator` | Definições de campos customizados |
| `canned_responses` | ✅ Migrado | `CannedResponsesMigrator` | Respostas prontas |
| `inboxes` | ✅ Migrado | `InboxesMigrator` | Inboxes + channels (WhatsApp, API, etc.) |
| `webhooks` | ✅ Migrado | `WebhooksMigrator` | Integrações webhook |
| `users` | ✅ Migrado | `UsersMigrator` | Usuários + `account_users` |
| `teams` | ✅ Migrado | `TeamsMigrator` | Equipes |
| `team_members` | ✅ Migrado | `TeamMembersMigrator` | Membros de equipes |
| `labels` | ✅ Migrado | `LabelsMigrator` | Etiquetas |
| `contacts` | ✅ Migrado | `ContactsMigrator` | Contatos |
| `contact_inboxes` | ✅ Migrado | `ContactInboxesMigrator` | Pivot contacts↔inboxes |
| `conversations` | ✅ Migrado | `ConversationsMigrator` | Conversas |
| `messages` | ✅ Migrado | `MessagesMigrator` | Mensagens |
| `attachments` | ✅ Migrado | `AttachmentsMigrator` | Anexos (S3) |
| `conversation_labels` | ✅ Migrado | `ConversationLabelsMigrator` | Pivot conversations↔labels (tabela `taggings`) |

**Nota:** `InboxesMigrator` cobre **inboxes** + **todos os channels** (channel_whatsapp, channel_api, channel_web_widgets, etc.) — confirmado por análise do código.

---

### ⚠️ Tabelas NÃO Migradas (37 gaps)

#### 🔴 Crítico — Perda de Funcionalidade Core

| # | Tabela | Impacto | Prioridade |
|---|--------|---------|------------|
| 1 | `mentions` | Menções (@user) em mensagens não migradas | 🔴 ALTA |
| 2 | `reporting_events` | Dados de analytics/relatórios perdidos | 🔴 ALTA |
| 3 | `conversation_participants` | Participantes de conversas (multi-user) perdidos | 🔴 ALTA |
| 4 | `csat_survey_responses` | Respostas de pesquisa de satisfação perdidas | 🟡 MÉDIA |
| 5 | `applied_slas` | SLAs aplicados a conversas (dados de compliance) | 🟡 MÉDIA |
| 6 | `sla_events` | Eventos de SLA (violações, alertas) | 🟡 MÉDIA |
| 7 | `working_hours` | Horários de atendimento por inbox | 🟡 MÉDIA |
| 8 | `notification_settings` | Preferências de notificação por usuário/account | 🟡 MÉDIA |
| 9 | `notifications` | Histórico de notificações (não crítico) | 🟢 BAIXA |

#### 🟡 Médio — Features Avançadas

| # | Tabela | Impacto | Prioridade |
|---|--------|---------|------------|
| 10 | `automation_rules` | Regras de automação (workflows) não migradas | 🟡 MÉDIA |
| 11 | `macros` | Macros (ações em lote) não migradas | 🟡 MÉDIA |
| 12 | `campaigns` | Campanhas de mensagens ativas não migradas | 🟡 MÉDIA |
| 13 | `sla_policies` | Políticas de SLA não migradas | 🟡 MÉDIA |
| 14 | `custom_filters` | Filtros customizados de usuários perdidos | 🟡 MÉDIA |
| 15 | `custom_roles` | Papéis customizados (permissões) não migrados | 🟡 MÉDIA |

#### 🔵 Opcional — Features Especializadas

| # | Tabela | Impacto | Prioridade |
|---|--------|---------|------------|
| 16 | `portals` | Help center / knowledge base (se usado) | 🔵 BAIXA-MÉDIA |
| 17 | `folders` | Pastas do portal | 🔵 BAIXA |
| 18 | `categories` | Categorias do portal | 🔵 BAIXA |
| 19 | `articles` | Artigos do portal | 🔵 BAIXA |
| 20 | `portal_members` | Membros do portal | 🔵 BAIXA |
| 21 | `agent_bots` | Agent bots (se usado) | 🔵 BAIXA |
| 22 | `agent_bot_inboxes` | Vínculo bots↔inboxes | 🔵 BAIXA |
| 23 | `inbox_members` | Membros de inbox (agents assignados) | 🔵 BAIXA-MÉDIA |
| 24 | `dashboard_apps` | Aplicações de dashboard customizadas | 🔵 BAIXA |
| 25 | `email_templates` | Templates de email customizados | 🔵 BAIXA |
| 26 | `integrations_hooks` | Hooks de integração (não confundir com webhooks) | 🔵 BAIXA |
| 27 | `telegram_bots` | Bots Telegram específicos | 🔵 BAIXA |
| 28 | `data_imports` | Histórico de imports de dados | 🔵 BAIXA |

---

## 🎯 Impacto Detalhado por Tabela Crítica

### 1. `mentions` 🔴 CRÍTICO

**O que é:** Menções de usuários em mensagens (`@user`).

**Tabela:**
```sql
CREATE TABLE mentions (
  id bigint PRIMARY KEY,
  user_id bigint,
  conversation_id bigint,
  mentioned_at timestamp,
  account_id bigint
);
```

**FK:** `user_id → users.id`, `conversation_id → conversations.id`

**Impacto da não migração:**
- ❌ Menções em mensagens antigas não aparecem no destino
- ❌ Funcionalidade de busca por menções quebrada
- ❌ Notificações de menções históricas perdidas

**Exemplo de caso de uso afetado:**
- Cliente busca "quando fulano me mencionou?" → retorna vazio mesmo tendo menções no SOURCE

**Mitigação:**
- ✅ Criar `MentionsMigrator` (prioridade ALTA)

---

### 2. `reporting_events` 🔴 CRÍTICO

**O que é:** Eventos de analytics/relatórios (mensagens enviadas, conversas criadas, etc.).

**Tabela:**
```sql
CREATE TABLE reporting_events (
  id bigint PRIMARY KEY,
  name varchar,
  value float,
  account_id bigint,
  conversation_id bigint,
  inbox_id bigint,
  user_id bigint,
  created_at timestamp
);
```

**FK:** `conversation_id → conversations.id`, `inbox_id → inboxes.id`

**Impacto da não migração:**
- ❌ Dashboards de analytics/relatórios mostram dados ZERADOS pós-migração
- ❌ Métricas históricas (volume de mensagens, tempo de resposta) perdidas
- ❌ Relatórios executivos comprometidos

**Exemplo de caso de uso afetado:**
- Gerente quer ver "quantas mensagens foram enviadas em março/2025" → retorna 0

**Mitigação:**
- ✅ Criar `ReportingEventsMigrator` (prioridade ALTA)
- ⚠️ **Risco de volume:** Tabela pode ter milhões de linhas (histórico completo de eventos)
- Considerar migração seletiva (ex: últimos 12 meses) ou skip completo com comunicação aos stakeholders

---

### 3. `conversation_participants` 🔴 CRÍTICO

**O que é:** Participantes de uma conversa (multi-user, não apenas assignee).

**Tabela:**
```sql
CREATE TABLE conversation_participants (
  id bigint PRIMARY KEY,
  account_id bigint,
  user_id bigint,
  conversation_id bigint
);
```

**FK:** `user_id → users.id`, `conversation_id → conversations.id`

**Impacto da não migração:**
- ❌ Conversas com múltiplos participantes perdem vínculo com users além do assignee
- ❌ Funcionalidade de "quem participou desta conversa" quebrada

**Exemplo de caso de uso afetado:**
- Conversa teve 3 agents participando (assignee + 2 que comentaram) → após migração só o assignee aparece

**Mitigação:**
- ✅ Criar `ConversationParticipantsMigrator` (prioridade ALTA)

---

## 📝 Recomendações de Ação

### 🔴 P0 — CRÍTICO (fazer ANTES de migração PROD)

1. ✅ **Criar `MentionsMigrator`**
2. ✅ **Criar `ConversationParticipantsMigrator`**
3. ✅ **Comunicar perda de `reporting_events`** OU criar migrator

### 🟡 P1 — ALTA (avaliar antes de PROD)

4. ✅ **Criar `WorkingHoursMigrator`**
5. ✅ **Criar `AutomationRulesMigrator`** (complexo: JSONB remapping)
6. ✅ **Criar `MacrosMigrator`**
7. ✅ **Validar uso de Portals** (se usado, criar migrators)

### 🔵 P2 — MÉDIA (backlog)

8. ✅ `InboxMembersMigrator`, `CSATSurveyResponsesMigrator`, `SLAMigrator`

---

## 🎯 Conclusão

**Cobertura atual:** 15 de 52 tabelas (~29%)

**Gaps críticos:**
- ❌ `mentions`, `conversation_participants` (UX quebrada)
- ❌ `reporting_events` (analytics zerados)
- ❌ `working_hours`, `automation_rules` (retrabalho manual)

**Risco de ir para PROD sem mitigação:**
- 🔴 **ALTO** — Funcionalidade visível perdida
- 🟡 **MÉDIO** — Retrabalho manual significativo

**Ação recomendada:**
1. ✅ Criar 2-3 migrators P0 ANTES de PROD
2. ✅ Validar uso de features opcionais (portals, SLAs) por account
3. ✅ Documentar recursos não migrados no runbook

---

**Debate:** Aguardando decisão sobre quais gaps mitigar.
