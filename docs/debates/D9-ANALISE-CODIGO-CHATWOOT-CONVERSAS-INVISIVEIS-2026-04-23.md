# D9 — Análise do Código-Fonte Chatwoot: Por que Conversas Migradas Ficam Invisíveis na API

**Data**: 2026-04-23
**Status**: INVESTIGAÇÃO CONCLUÍDA — diagnóstico e correções documentados
**Autores**: análise via GitHub Copilot (Claude Sonnet 4.6)
**Referências**: D7, D8; Chatwoot v3.9.0 `develop` branch
**Repositório analisado**: https://github.com/chatwoot/chatwoot (branch `develop`)
**Contexto**: 309 conversas existem no DB `chatwoot004_dev1_db` (account_id=1) com campos
            FK válidos, mas a API `/conversations/meta?status=all` retorna apenas 378.

---

## 1. Diagrama do Fluxo de Dados

```
GET /api/v1/accounts/1/conversations/meta?status=all
                │
                ▼
Api::V1::Accounts::ConversationsController#meta
  ├── before_action :set_current_account   (via AccountsController concern)
  ├── before_action :authenticate_user!    (Devise / api_access_token)
  └── meta()
        │
        ▼
  result = conversation_finder.perform_meta_only
        │
        ▼
  ConversationFinder.new(Current.user, params)
    │
    ├── set_up()
    │     ├── set_inboxes()              → @inbox_ids
    │     ├── set_team()                 → @team
    │     ├── set_assignee_type()        → @assignee_type
    │     ├── find_all_conversations()
    │     │     ├── find_conversation_by_inbox()
    │     │     │     └── @conversations = Current.account.conversations
    │     │     │          WHERE conversations.account_id = :account_id  ← FILTRO #1
    │     │     │          [+ WHERE inbox_id IN @inbox_ids  se params[:inbox_id] presente]
    │     │     └── Conversations::PermissionFilterService.perform()
    │     │           ├── admin?  → return conversations (sem filtro)    ← FILTRO #2
    │     │           └── agent?  → WHERE inbox_id IN user.inboxes       ← FILTRO #2b
    │     ├── filter_by_status()
    │     │     └── params[:status] == 'all' → SKIP                      ← FILTRO #3 (ignorado)
    │     ├── filter_by_team()           → sem param → SKIP
    │     ├── filter_by_labels()         → sem param → SKIP
    │     ├── filter_by_query()          → sem param → SKIP
    │     └── filter_by_source_id()      → sem param → SKIP
    │
    └── set_count_for_all_conversations()
          SELECT COUNT(*) FROM conversations WHERE ... (filtros acumulados)
          ┌───────────────────────────────────────────────────────────┐
          │  mine_count      = @conversations.assigned_to(user).count │
          │  unassigned_count = @conversations.unassigned.count       │
          │  all_count        = @conversations.count                  │ ← retornado em meta
          └───────────────────────────────────────────────────────────┘
                │
                ▼
  @conversations_count = { mine_count:, assigned_count:, unassigned_count:, all_count: }
                │
                ▼
  Response JSON: { "data": { "all_count": 378, ... } }  ← deveria ser 687
```

---

## 2. Scopes e Filtros — Lista Completa

### 2.1 Filtros em `ConversationFinder` (app/finders/conversation_finder.rb)

| Ordem | Filtro | Ativo quando | Impacto |
|-------|--------|-------------|---------|
| 1 | `account_id = N` | Sempre | Base via `current_account.conversations` |
| 2 | `PermissionFilterService` | Sempre | Admin → nenhum; Agent → WHERE inbox_id IN user.inboxes |
| 3 | `filter_by_status` | `params[:status] != 'all'` | WHERE status = N (default: 0=open) |
| 4 | `filter_by_team` | `params[:team_id]` presente | WHERE team_id = N |
| 5 | `filter_by_labels` | `params[:labels]` presente | JOIN taggings WHERE label IN (...) |
| 6 | `filter_by_query` | `params[:q]` presente | JOIN messages WHERE content ILIKE % |
| 7 | `filter_by_source_id` | `params[:source_id]` presente | JOIN contact_inboxes WHERE source_id = X |
| 8 | `filter_by_conversation_type` | `params[:conversation_type]` presente | mention / participating / unattended |

### 2.2 Scopes do modelo `Conversation` (app/models/conversation.rb)

```ruby
# Scopes definidos — NENHUM é default_scope
scope :unassigned,         -> { where(assignee_id: nil) }
scope :assigned,           -> { where.not(assignee_id: nil) }
scope :assigned_to, ->(a)  -> { where(assignee_id: a.id) }
scope :unattended,         -> { where(first_reply_created_at: nil).or(where.not(waiting_since: nil)) }
scope :resolvable_not_waiting, lambda { |minutes| open.where('last_activity_at < ?', ...) }
scope :resolvable_all,         lambda { |minutes| open.where('last_activity_at < ?', ...) }
scope :last_user_message_at,   lambda { joins(...) }
```

> ⚠️ **Não existe `default_scope`** no modelo Conversation. Toda filtragem vem
> dos métodos `set_up` do `ConversationFinder` ou de scopes explicitamente chamados.

### 2.3 `PermissionFilterService` — detalhe crítico

Arquivo: `app/services/conversations/permission_filter_service.rb`

```ruby
class Conversations::PermissionFilterService
  def perform
    return conversations if user_role == 'administrator'   # ← admin: sem filtro
    accessible_conversations                               # ← agent: filtro inbox
  end

  private

  def accessible_conversations
    # Filtra para apenas inboxes onde o agente é membro (inbox_members)
    conversations.where(inbox: user.inboxes.where(account_id: account.id))
  end

  def user_role
    AccountUser.find_by(account_id: account.id, user_id: user.id)&.role
  end
end
```

E no modelo `User` (app/models/user.rb):

```ruby
def assigned_inboxes
  administrator? ? Current.account.inboxes : inboxes.where(account_id: Current.account.id)
end

# has_many :inboxes, through: :inbox_members, source: :inbox
```

> **Conclusão de permissão**: Se o token da API pertence a um **administrator**,
> TODAS as conversas da conta são retornadas. Se pertence a um **agent**, apenas
> conversas em inboxes onde o agente está em `inbox_members` são retornadas.
>
> Diagnóstico do projeto (D8, seção 3): user_id=1 tem role=administrator → PermissionFilterService
> retorna TODAS as conversas. **Portanto, permissão NÃO é a causa da invisibilidade neste projeto.**

---

## 3. DB Triggers Críticos (invisíveis para quem só lê o código Ruby)

### 3.1 Trigger: `display_id` em conversas

Definido em `app/models/conversation.rb`:

```ruby
trigger.before(:insert).for_each(:row) do
  "NEW.display_id := nextval('conv_dpid_seq_' || NEW.account_id);"
end
```

E a sequência é criada quando a account é inserida (`app/models/account.rb`):

```ruby
trigger.after(:insert).for_each(:row) do
  "execute format('create sequence IF NOT EXISTS conv_dpid_seq_%s', NEW.id);"
end
```

**Comportamento crítico para migração direta via SQL**:

```
INSERT INTO conversations (account_id, display_id, ...) VALUES (1, 1093, ...)
                                                                     ↑
                                                              SERÁ IGNORADO

→ Trigger fires: NEW.display_id := nextval('conv_dpid_seq_1')
                                   ↓
              DEST tinha 378 conversas → nextval = 379
              A conversa que o SOURCE tinha com display_id=1093
              chega ao DEST com display_id=379
```

**Consequência direta**:
- A conversa existe no DB com display_id=379 (não 1093)
- A validação pós-migração tenta `GET /api/v1/accounts/1/conversations/1093`
- Rails faz: `Conversation.find_by!(display_id: 1093)` → **RecordNotFound → HTTP 404**

> ⚠️ Este é o mecanismo que causou **309/309 HTTP 404** no diagnóstico D8.
> O `after_create_commit :load_attributes_created_by_db_triggers` no modelo
> Rails carrega o `display_id` real do DB **apenas quando criado via ActiveRecord**.
> Para INSERT direto via SQL, esse callback não roda — mas o trigger DO roda,
> então o `display_id` no DB é correto; o problema é que o migrator usava o
> display_id do SOURCE para validação posterior.

### 3.2 Trigger: `uuid` — coluna com default PostgreSQL

Do schema (`db/schema.rb`):

```ruby
t.uuid "uuid", default: -> { "gen_random_uuid()" }, null: false
```

Se INSERT for feito sem `uuid`, PostgreSQL gera automaticamente via `gen_random_uuid()`.
Se o INSERT incluir um uuid explícito do SOURCE, ele é aceito (sem trigger, só default).

> **Para migração**: sempre incluir o uuid original do SOURCE no INSERT para preservar
> rastreabilidade. O UNIQUE index garantirá deduplicação.

### 3.3 Coluna `last_activity_at` — default CURRENT_TIMESTAMP

```ruby
t.datetime "last_activity_at", default: -> { "CURRENT_TIMESTAMP" }, null: false
```

Se NULL no INSERT, PostgreSQL usa CURRENT_TIMESTAMP. Nunca será NULL no DB.

---

## 4. Callbacks Rails que Populam Colunas (bypassados por SQL direto)

| Callback | Momento | O que faz | Valor se bypassed via SQL |
|----------|---------|-----------|--------------------------|
| `before_validation :validate_additional_attributes` | antes de salvar | Garante `additional_attributes = {}` se não for Hash | Qualquer valor do INSERT (pode ser NULL ou `{}`) |
| `before_create :determine_conversation_status` | antes de criar | Seta `status = pending` se inbox tem bot ativo | Status do INSERT (geralmente `open=0`) |
| `before_create :ensure_waiting_since` | antes de criar | Seta `waiting_since = created_at` | NULL (se não incluído no INSERT) |
| `before_save :ensure_snooze_until_reset` | antes de salvar | Zera `snoozed_until` se status ≠ snoozed | Valor do INSERT |
| `after_create_commit :load_attributes_created_by_db_triggers` | após criar via AR | Relê `display_id` e `uuid` do DB | Não roda — mas display_id já está correto via trigger |
| `after_create_commit :notify_conversation_creation` | após criar via AR | Dispara evento WebSocket | Não roda — sem notificação em tempo real |

### 4.1 O caso crítico: `waiting_since`

```ruby
before_create :ensure_waiting_since

private
def ensure_waiting_since
  self.waiting_since = created_at
end
```

Para conversas criadas via Rails: `waiting_since = created_at`.
Para conversas inseridas via SQL sem `waiting_since`: `waiting_since = NULL`.

O scope `:unattended` é:
```ruby
scope :unattended, -> { where(first_reply_created_at: nil).or(where.not(waiting_since: nil)) }
```

Se `waiting_since` for NULL e `first_reply_created_at` também for NULL, a conversa
NÃO aparece em unattended — mas isso não afeta o count geral com `status=all`.

### 4.2 O caso crítico: `status = pending` para inboxes com bot

```ruby
def determine_conversation_status
  self.status = :resolved and return if contact.blocked?
  return handle_campaign_status if campaign.present?
  self.status = :pending if inbox.active_bot?
end
```

Se o inbox de destino tiver um bot ativo (`active_bot?`), conversas criadas via Rails
receberiam `status = pending (2)`. Conversas inseridas via SQL com `status = 0 (open)`
do SOURCE **não** terão o status ajustado.

> **Impacto no count com `status=all`**: nenhum — o filtro de status é completamente
> ignorado com `status=all`. Mas ao exibir no dashboard (onde o padrão é `status=open`),
> conversas que "deveriam" ser pending ficariam listadas como open (comportamento incorreto
> mas ainda visíveis com `status=open`).

---

## 5. Causas Prováveis da Invisibilidade — Ordenadas por Probabilidade

### CAUSA #1 — ⭐⭐⭐⭐⭐ `contact_inbox_id` inválido (SOURCE ID não remapeado)

**Probabilidade**: ALTÍSSIMA (confirmada em D8: 309/309 conversas afetadas)

**Mecanismo**:

```
Conversation no DEST:
  contact_inbox_id = 47  ← ID do SOURCE
  
No DEST, contact_inboxes.id=47 pertence a outro contato/inbox ou não existe.

Rails ao renderizar a conversa:
  @conversation.contact_inbox  → Executa: SELECT * FROM contact_inboxes WHERE id = 47
  → nil (não existe no DEST) ou registro errado

GET /api/v1/accounts/1/conversations/:display_id → HTTP 404
(o display_id do SOURCE ≠ display_id no DEST por causa do trigger)
```

**Por que afeta o META count?**

O META count usa `@conversations.count` que é apenas `SELECT COUNT(*) FROM conversations WHERE account_id=1`. Este count NÃO faz JOIN com `contact_inboxes`.

**CONCLUSÃO**: `contact_inbox_id` inválido **NÃO causa invisibilidade no META count**.
Causa apenas HTTP 404 em lookups individuais. O META provavelmente retorna 687,
não 378. O que retorna 404 é a validação por display_id.

---

### CAUSA #2 — ⭐⭐⭐⭐⭐ `display_id` do SOURCE usado para validação (trigger override)

**Probabilidade**: ALTÍSSIMA (confirmada: é o mecanismo do HTTP 404)

**Mecanismo**:

```
Cenário:
  SOURCE conversation: id=82000, display_id=1093, account_id=1
  
  INSERT INTO conversations (id, display_id, account_id, ...) VALUES (82000, 1093, 1, ...)
  
  TRIGGER fires: NEW.display_id = nextval('conv_dpid_seq_1')
  Sequência estava em 378 → display_id SOBRESCRITO para 379
  
  A conversa agora existe no DEST com display_id=379, não 1093.
  
  Validador tenta: GET /conversations/1093 → 404 NOT FOUND
  Validador tenta: GET /conversations/82000 → 404 (params[:id] é display_id, não id primário)
```

**SQL do Rails para lookup individual** (conversations_controller.rb):
```ruby
@conversation = Current.account.conversations.find_by!(display_id: params[:id])
```

> Se o validador usa os display_ids do SOURCE (como fez o `app/10_validar_api.py`),
> todos os 309 retornam 404, dando a falsa impressão de invisibilidade total.

---

### CAUSA #3 — ⭐⭐⭐⭐ `account_id` errado nas conversas migradas

**Probabilidade**: ALTA (principal explicação para META count = 378)

**Mecanismo**:

```python
# Bug hipotético em ConversationsMigrator.remap_fn:
new_row["account_id"] = row["account_id"]  # copia SEM remapear

# SOURCE account_id=1 → OK (mapeamento trivial 1→1)
# SOURCE account_id=18 → DEST deveria ser 61, mas ficou 18
# SOURCE account_id=25 → DEST deveria ser 68, mas ficou 25
```

Se o remapeamento de account_id falhar para os accounts não triviais (18→61, 25→68),
as conversas ficam no DEST com account_id errado. A query
`current_account.conversations` filtra por `account_id = 1` e não retorna essas.

**Para o projeto atual**: O mapeamento 1→1 é trivial. Mas se o migrator tiver bug
e copiar verbatim account_id de outros accounts, conversas de outros accounts
seriam invisíveis na account 1.

**Diagnóstico SQL**:
```sql
-- Verificar distribuição de account_id nas conversas inseridas após a migração
SELECT account_id, COUNT(*) as total
FROM conversations
WHERE id > (SELECT MAX(id) FROM conversations WHERE created_at < '2026-04-20')
   OR created_at > '2026-04-20'
GROUP BY account_id
ORDER BY account_id;
```

---

### CAUSA #4 — ⭐⭐⭐⭐ Token da API pertence a um agente, não administrador

**Probabilidade**: ALTA (se o token usado for de um agente)

**Mecanismo** (já detalhado na seção 2.3):

```ruby
# PermissionFilterService para agentes:
conversations.where(inbox: user.inboxes.where(account_id: account.id))
# → user.inboxes usa inbox_members
# → Se as 309 conversas estão em inboxes onde o agente NÃO é membro → invisíveis
```

**Para o projeto atual**: Descartada — user_id=1 tem role=administrator (confirmado em D8).

**Diagnóstico SQL**:
```sql
-- Verificar role do usuário dono do token
SELECT u.email, au.role,
  CASE au.role WHEN 0 THEN 'agent' WHEN 1 THEN 'administrator' END as role_name
FROM users u
JOIN account_users au ON u.id = au.user_id
WHERE au.account_id = 1
  AND u.id = (
    SELECT owner_id FROM access_tokens WHERE token = 'SEU_API_TOKEN_AQUI' AND owner_type = 'User'
  );
```

---

### CAUSA #5 — ⭐⭐⭐ `inbox_id` não remapeado (SOURCE IDs no DEST)

**Probabilidade**: ALTA (confirmada parcialmente em D8/BUG-05 — inboxes com channel_id errado)

**Mecanismo**:

```
SOURCE conversation: inbox_id=125 (inbox "Atendimento X" do SOURCE)
DEST inbox_id=125: pode ser um inbox DIFERENTE, ou
DEST pode não ter inbox_id=125 (se IDs foram remapeados com offset)

Se a FK conversation.inbox_id → inboxes.id é válida (registro existe),
mas o inbox é de um account diferente:

  PermissionFilterService para admin → SEM filtro → conversa ainda aparece
  PermissionFilterService para agent → WHERE inbox IN user.inboxes → pode filtrar
```

**Situação especial**: Mesmo que o inbox exista no DEST com mesmo ID, se ele pertence
a uma account diferente da conta que está sendo consultada, o comportamento depende
de qual account o inbox pertence.

**Diagnóstico SQL**:
```sql
-- Verificar se conversas migradas têm inbox_id de inboxes que pertencem à account_id=1
SELECT c.id, c.inbox_id, i.account_id as inbox_account_id, i.name
FROM conversations c
JOIN inboxes i ON c.inbox_id = i.id
WHERE c.account_id = 1
  AND i.account_id != 1;  -- inboxes de outra account → anomalia
```

---

### CAUSA #6 — ⭐⭐⭐ `channel_id` errado em inboxes migrados → inbox invisível na API

**Probabilidade**: ALTA (confirmada em D8/BUG-05 como causa dos 14 inboxes invisíveis)

**Mecanismo**:

```ruby
# InboxesController#index — Jbuilder serializa todos os inboxes
# includes(:channel) → eager-load polimórfico
# Se channel record não existe → inbox.channel = nil
# → channel.name → NoMethodError → inbox OMITIDO do JSON
```

**Impacto no META count das conversas**: NENHUM direto. O META de conversas
não inclui inboxes. Mas tem impacto indireto:
- Inboxes com channel=nil ficam invisíveis na API de inboxes
- Agentes não conseguem visualizar as conversas nessas inboxes via UI
- A UI do dashboard filtra conversas pelo inbox selecionado → conversas em inboxes
  "fantasmas" não aparecem no frontend

---

### CAUSA #7 — ⭐⭐ `additional_attributes` com formato inválido

**Probabilidade**: MÉDIA

**Mecanismo**:

```ruby
# before_validation :validate_additional_attributes
def validate_additional_attributes
  self.additional_attributes = {} unless additional_attributes.is_a?(Hash)
end
```

Se o INSERT colocar `NULL` ou um JSON inválido em `additional_attributes`, o Rails
normalizaria para `{}`. Via SQL, pode ser inserido com qualquer valor.

O projeto atualmente usa `additional_attributes->>'src_id'` para rastreio de origem.
Se o campo contiver `NULL` (não o JSON `null`, mas NULL SQL), queries JSONB podem
falhar silenciosamente.

**Diagnóstico SQL**:
```sql
-- Verificar conversas com additional_attributes problemáticos
SELECT id, account_id, display_id, additional_attributes
FROM conversations
WHERE account_id = 1
  AND additional_attributes IS NULL  -- deveria ser {} no mínimo
  OR NOT (additional_attributes @> '{}'::jsonb);  -- não é JSON válido
```

---

### CAUSA #8 — ⭐⭐ `waiting_since = NULL` em conversas sem first_reply

**Probabilidade**: MÉDIA-BAIXA (afeta exibição mas não o count total)

**Mecanismo**:

```ruby
# before_create :ensure_waiting_since
def ensure_waiting_since
  self.waiting_since = created_at  # Rails define automaticamente
end
```

Via SQL direto: `waiting_since` permanece NULL se não incluído no INSERT.

**Impacto**: Conversas com `waiting_since = NULL` e `first_reply_created_at = NULL`
não aparecem no filtro "Unattended". Mas com `status=all`, ainda aparecem no
count geral.

**Fix SQL**:
```sql
-- Corrigir waiting_since NULL nas conversas migradas
UPDATE conversations
SET waiting_since = created_at
WHERE account_id = 1
  AND waiting_since IS NULL
  AND first_reply_created_at IS NULL
  AND additional_attributes->>'src_id' IS NOT NULL;  -- tag de origem da migração
```

---

## 6. Colunas Críticas em `conversations` — Checklist de Migração

| Coluna | Default DB | Callback Rails | Comportamento SQL direto | Risco |
|--------|-----------|---------------|--------------------------|-------|
| `display_id` | `nextval(trigger)` | `after_create_commit` recarrega | ✅ Trigger SEMPRE sobrescreve | ALTO: display_id ≠ SOURCE |
| `uuid` | `gen_random_uuid()` | `after_create_commit` recarrega | ✅ Gerado se NULL; inserção explícita aceita | BAIXO |
| `last_activity_at` | `CURRENT_TIMESTAMP` | — | ✅ Default PostgreSQL aplica | BAIXO |
| `status` | `0` (open) | `before_create` (pending se bot) | ⚠️ Status do SOURCE preservado | MÉDIO |
| `waiting_since` | NULL | `before_create` (= created_at) | ❌ NULL se não incluído no INSERT | MÉDIO |
| `additional_attributes` | `{}` | `before_validation` (= {} se não-Hash) | ⚠️ Inserido tal como está | MÉDIO |
| `custom_attributes` | `{}` | — | ✅ Default vazio aplicável | BAIXO |
| `cached_label_list` | NULL | Atualizado em mudança de labels | ❌ NULL; labels não carregadas | BAIXO |
| `contact_inbox_id` | NULL | — | ❌ SOURCE ID não é válido no DEST | CRÍTICO |
| `assignee_id` | NULL | — | ⚠️ SOURCE user_id pode não existir no DEST | ALTO |
| `team_id` | NULL | — | ⚠️ SOURCE team_id pode não existir no DEST | ALTO |

---

## 7. O Mecanismo Exato do HTTP 404 (display_id trigger)

Este é o ROOT CAUSE confirmado dos 309/309 HTTP 404 em D8:

```
┌─────────────────────────────────────────────────────────────────────┐
│ SOURCE: conv display_id=1093, account_id=1, id=82000                │
│                                                                     │
│ INSERT INTO conversations                                           │
│   (id, account_id, display_id, ...)                                 │
│   VALUES (remapped_id, 1, 1093, ...)                                │
│           ─────────────────────┘                                    │
│                    ▼ TRIGGER FIRES                                  │
│   NEW.display_id = nextval('conv_dpid_seq_1')                       │
│                  = 379  ← sequência estava em 378                   │
│                                                                     │
│ DEST: conv display_id=379, account_id=1                             │
└─────────────────────────────────────────────────────────────────────┘
                           │
                           ▼
Validação pós-migração:
  GET /api/v1/accounts/1/conversations/1093
  ConversationsController#show:
    @conversation = Current.account.conversations.find_by!(display_id: 1093)
    → SELECT * FROM conversations WHERE account_id=1 AND display_id=1093
    → 0 rows → RecordNotFound → HTTP 404
```

**A conversa EXISTE no DB** (com display_id=379), mas a validação usa o
display_id errado (SOURCE 1093).

---

## 8. Por que o META count retorna 378 (hipóteses)

Dado que o usuário da API é administrator (bypass total de PermissionFilterService)
e usa `status=all` (bypass de filtro de status), o META **deveria** retornar 687.
Se retorna 378, as hipóteses são:

### Hipótese A: As conversas têm `account_id` errado (**mais provável**)

```sql
-- Verificar
SELECT account_id, COUNT(*) FROM conversations GROUP BY account_id;
-- Se existir account_id != 1 com ~309 linhas → esta é a causa
```

### Hipótese B: A query de validação usa display_id do SOURCE como parâmetro de conta

```
GET /api/v1/accounts/1/conversations/meta?status=all
            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Não há como este endpoint retornar 378 se 687 conversas têm account_id=1
e o usuário é admin, EXCETO se o banco tem apenas 378 com account_id=1.
```

### Hipótese C: O DB foi restaurado antes do teste do META

D8 confirma: "O banco foi restaurado ao estado original" em 2026-04-23 15h.
Se o teste do META foi feito após o restore, o DB tinha apenas 378 conversas.

### Hipótese D: Cache no servidor Rails (menos provável)

Rails Action Caching ou HTTP cache poderia servir resposta stale. Improvável
para endpoints de leitura de banco sem cache explícito no Chatwoot.

---

## 9. Análise do `conversations/meta` endpoint — SQL gerado pelo Rails

Para um admin com `status=all`:

```sql
-- mine_count:
SELECT COUNT(*)
FROM conversations
WHERE conversations.account_id = 1
  AND conversations.assignee_id = :current_user_id;

-- unassigned_count:
SELECT COUNT(*)
FROM conversations
WHERE conversations.account_id = 1
  AND conversations.assignee_id IS NULL;

-- all_count:
SELECT COUNT(*)
FROM conversations
WHERE conversations.account_id = 1;
-- ↑ Sem filtro adicional para admin com status=all
```

Nenhum JOIN com `contact_inboxes`, `inboxes`, `channels` ou qualquer outra tabela.

---

## 10. Solução: SQL de Diagnóstico e Correção para as 309 Conversas Invisíveis

### 10.1 Diagnóstico completo pós-migração

```sql
-- 1. VERIFICAR: Quantas conversas existem por account_id
SELECT account_id, COUNT(*) as total,
       MIN(created_at) as primeira,
       MAX(created_at) as ultima
FROM conversations
GROUP BY account_id
ORDER BY account_id;

-- 2. VERIFICAR: display_id range das conversas migradas (tag src_id)
SELECT
  MIN(display_id) as min_display,
  MAX(display_id) as max_display,
  COUNT(*) as total_migradas,
  COUNT(additional_attributes->>'src_id') as com_src_id
FROM conversations
WHERE account_id = 1
  AND additional_attributes->>'src_id' IS NOT NULL;

-- 3. VERIFICAR: Conversas com contact_inbox_id inválido
SELECT COUNT(*) as total_invalidos
FROM conversations c
LEFT JOIN contact_inboxes ci ON c.contact_inbox_id = ci.id
WHERE c.account_id = 1
  AND c.additional_attributes->>'src_id' IS NOT NULL  -- migradas
  AND ci.id IS NULL;  -- FK quebrada

-- 4. VERIFICAR: inboxes das conversas migradas
SELECT c.inbox_id, i.name, i.channel_type, i.account_id,
       COUNT(c.id) as total_conversas
FROM conversations c
JOIN inboxes i ON c.inbox_id = i.id
WHERE c.account_id = 1
  AND c.additional_attributes->>'src_id' IS NOT NULL
GROUP BY c.inbox_id, i.name, i.channel_type, i.account_id
ORDER BY total_conversas DESC;

-- 5. VERIFICAR: status distribution das conversas migradas
SELECT status,
  CASE status
    WHEN 0 THEN 'open'
    WHEN 1 THEN 'resolved'
    WHEN 2 THEN 'pending'
    WHEN 3 THEN 'snoozed'
  END as status_name,
  COUNT(*) as total
FROM conversations
WHERE account_id = 1
  AND additional_attributes->>'src_id' IS NOT NULL
GROUP BY status;

-- 6. VERIFICAR: sequência atual do display_id
SELECT last_value, is_called FROM conv_dpid_seq_1;
-- Deve ser >= número total de conversas em account_id=1
```

### 10.2 Correção: `waiting_since` para conversas migradas

```sql
-- Corrigir waiting_since NULL nas conversas migradas (open sem first_reply)
UPDATE conversations
SET waiting_since = created_at
WHERE account_id = 1
  AND additional_attributes->>'src_id' IS NOT NULL  -- identifica migradas
  AND waiting_since IS NULL
  AND status = 0;  -- open
-- Registrar quantas foram afetadas
-- SELECT changes() não existe no PostgreSQL, use RETURNING:
-- UPDATE ... RETURNING id;
```

### 10.3 Correção: `contact_inbox_id` para conversas migradas

```sql
-- Para cada conversa migrada, tenta localizar o contact_inbox correto via (contact_id, inbox_id)
UPDATE conversations c
SET contact_inbox_id = ci.id
FROM contact_inboxes ci
WHERE c.account_id = 1
  AND c.additional_attributes->>'src_id' IS NOT NULL
  AND ci.contact_id = c.contact_id
  AND ci.inbox_id = c.inbox_id
  AND (c.contact_inbox_id IS NULL
    OR NOT EXISTS (
      SELECT 1 FROM contact_inboxes WHERE id = c.contact_inbox_id
    )
  );

-- Verificar conversas que ainda não têm contact_inbox_id válido
SELECT c.id, c.display_id, c.contact_id, c.inbox_id, c.contact_inbox_id
FROM conversations c
LEFT JOIN contact_inboxes ci ON c.contact_inbox_id = ci.id
WHERE c.account_id = 1
  AND c.additional_attributes->>'src_id' IS NOT NULL
  AND ci.id IS NULL;
```

### 10.4 Correção: Ajustar sequência `conv_dpid_seq_1` após migração

```sql
-- Após a migração, a sequência deve estar em sync com o MAX(display_id)
-- Isso evita conflitos em novas conversas criadas via Rails
SELECT setval('conv_dpid_seq_1', (SELECT MAX(display_id) FROM conversations WHERE account_id = 1));

-- Verificar
SELECT last_value FROM conv_dpid_seq_1;
-- Deve ser igual a MAX(display_id) da account 1
```

### 10.5 Verificação final pós-correção

```sql
-- Contar conversas visíveis na API (simulando admin query)
SELECT COUNT(*) as deve_retornar_na_api
FROM conversations
WHERE account_id = 1;

-- Verificar integridade das conversas migradas
SELECT
  COUNT(*) as total_migradas,
  COUNT(CASE WHEN ci.id IS NOT NULL THEN 1 END) as com_contact_inbox_valido,
  COUNT(CASE WHEN i.id IS NOT NULL THEN 1 END) as com_inbox_valido,
  COUNT(CASE WHEN cont.id IS NOT NULL THEN 1 END) as com_contact_valido,
  COUNT(CASE WHEN waiting_since IS NOT NULL THEN 1 END) as com_waiting_since
FROM conversations c
LEFT JOIN contact_inboxes ci ON c.contact_inbox_id = ci.id
LEFT JOIN inboxes i ON c.inbox_id = i.id
LEFT JOIN contacts cont ON c.contact_id = cont.id
WHERE c.account_id = 1
  AND c.additional_attributes->>'src_id' IS NOT NULL;
```

---

## 11. Resumo Executivo — O que Causa Invisibilidade e Como Corrigir

| # | Causa | Sintoma | Componente afetado | Fix |
|---|-------|---------|-------------------|-----|
| 1 | `display_id` sobrescrito por trigger | HTTP 404 em lookup individual | DB trigger `conversations_before_insert_row_tr` | Usar display_id do DEST para validação; OU avançar sequência antes do INSERT |
| 2 | `contact_inbox_id` SOURCE ID | HTTP 404 em lookup individual (Rails eager load) | `conversations.contact_inbox_id` | Remap em `ConversationsMigrator.remap_fn` — **BUG-06, corrigido em D8** |
| 3 | `channel_id` errado em inboxes | 14 inboxes invisíveis na API | `inboxes.channel_id` | Migrar channel records antes de inboxes — **BUG-05, corrigido em D8** |
| 4 | `account_id` errado | META count menor que esperado | `conversations.account_id` | Verificar `id_remapper.remap(account_id)` no migrator |
| 5 | `waiting_since = NULL` | Ausente em filtro "Unattended" | `conversations.waiting_since` | UPDATE `SET waiting_since = created_at` |
| 6 | `assignee_id` SOURCE user_id | Conversa com assignee fantasma | `conversations.assignee_id` | Remap user_ids ou setar NULL |
| 7 | `status` não ajustado para pending | Comportamento incorreto em inboxes com bot | `conversations.status` | Aceitar como open (mantém visibilidade) |

---

## 12. Referências no Código Chatwoot (v3.9.0)

| Arquivo | Linha/Método | Relevância |
|---------|-------------|-----------|
| `app/finders/conversation_finder.rb` | `set_up`, `find_all_conversations`, `filter_by_status` | Pipeline completo de filtragem |
| `app/services/conversations/permission_filter_service.rb` | `perform`, `accessible_conversations` | Filtro por inbox_members para agentes |
| `app/models/conversation.rb` | `trigger.before(:insert)` | Display_id override por trigger |
| `app/models/conversation.rb` | `before_create :determine_conversation_status` | Status auto-ajustado |
| `app/models/conversation.rb` | `before_create :ensure_waiting_since` | waiting_since = created_at |
| `app/models/conversation.rb` | `after_create_commit :load_attributes_created_by_db_triggers` | Recarrega display_id e uuid |
| `app/models/user.rb` | `assigned_inboxes`, `has_many :inboxes, through: :inbox_members` | Filtro inbox para agentes |
| `app/controllers/api/v1/accounts/conversations_controller.rb` | `meta`, `conversation_finder` | Endpoint meta |
| `db/schema.rb` | `create_table "conversations"` | Defaults das colunas (uuid, last_activity_at) |
| `enterprise/app/finders/enterprise/conversation_finder.rb` | `conversations_base_query` | Enterprise: apenas adiciona includes SLA (sem filtros extras) |
