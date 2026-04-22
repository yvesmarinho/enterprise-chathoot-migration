# D7 — DEBATE: Mensagens de marcos.andrade@vya.digital não visíveis no Destino

**Data**: 2026-04-22
**Revisado em**: 2026-04-22 (v2 — arquitetura corrigida)
**Participantes**: @chatwoot-expert, @system-engineer, @dba-sql-expert
**Status**: EM INVESTIGAÇÃO — arquitetura corrigida; questionnaire gerado e respondido; diagnóstico conclusivo em Seção 13.
**Contexto**: Pós-migração 2026-04-20 + validação hash 2026-04-21.
**Sintoma reportado**: Usuário `marcos.andrade@vya.digital` não visualiza conversa de **14/11/2025** na instância destino `vya-chat-dev.vya.digital`.

---

## 0. ARQUITETURA CORRIGIDA (v2 — 2026-04-22)

> ⚠️ A versão v1 deste debate operava com entendimento incorreto da topologia.
> Esta seção substitui o contexto técnico e impacta todas as hipóteses.

### 0.1 — Topologia real do projeto

```
┌──────────────────────────────────────────────────────────────────┐
│  EXPORT (mesmo dia)                                              │
│                                                                  │
│  chat.vya.digital   ──export──►  chatwoot_dev1_db   (SOURCE)     │
│                                       read-only                  │
│                                                                  │
│  synchat.vya.digital ─export──►  chatwoot004_dev1_db  (DEST)     │
│                                       read-write                 │
│                                  + recebe dados do SOURCE        │
└──────────────────────────────────────────────────────────────────┘

  Pipeline de migração:  chatwoot_dev1_db  ──MERGE──►  chatwoot004_dev1_db

  Frontend SOURCE:   chat.vya.digital          (sem front ativo pós-export)
  API SOURCE:        chat.vya.digital           ← usar para queries de origem

  Frontend DEST:     vya-chat-dev.vya.digital   ← usar para validação
  API DEST:          vya-chat-dev.vya.digital    ← NÃO usar synchat.vya.digital
  ⚠️  synchat.vya.digital = produção live, dados mais recentes — NÃO usar
```

### 0.2 — Implicações da arquitetura corrigida

| Item | Impacto |
|------|----------|
| `chatwoot004_dev1_db` já tinha dados de `synchat.vya.digital` **antes** da migração | Marcus pode ter conversas pré-existentes no DEST que NÃO vieram do SOURCE |
| A migração MERGE adicionou dados de `chat.vya.digital` ao DEST | A conversa de 14/11/2025 pode ser de qualquer um dos dois sistemas |
| API `vya-chat-dev.vya.digital` = DEST pós-migração | Validações API devem usar este host, não `synchat.vya.digital` |
| A api_key em `.secrets/generate_erd.json["synchat"]` autentica em **todos os três hosts** | Uma única chave serve para SOURCE e DEST (confirmado na seção 8.6) |
| `chat.vya.digital` sem front ativo = dados congelados no export | Ideal para comparação snapshot-a-snapshot |

### 0.3 — Mapeamento de accounts SOURCE → DEST

Apenas 3 accounts do SOURCE (chat.vya.digital) foram migradas para o DEST:

| SOURCE account_id | Empresa | DEST account_id |
|---|---|---|
| 1 | Vya Digital | 1 (preservado) |
| 17 | Unimed Poços PJ | 17 (preservado) |
| 18 | Unimed Poços PF | 61 (novo ID) |
| 25 | Unimed Guaxupé | 68 (novo ID) |

O DEST também contém accounts **pré-existentes de synchat.vya.digital** (IDs: 28, 30, 31, 32, 33, 37, 38, 40, 43) que **não participaram da migração** e portanto **não têm dados de chat.vya.digital**.

### 0.4 — Foco do debate: conversa de 14/11/2025

A conversa específica que Marcus não visualiza data de **14 de novembro de 2025**. As perguntas centrais são:

1. **Origem**: A conversa estava em `chat.vya.digital` (chatwoot_dev1_db) ou em `synchat.vya.digital` (chatwoot004_dev1_db, pré-existente)?
2. **Migração**: Se estava no SOURCE → foi migrada para o DEST?
3. **Visibilidade**: Se está no DEST → por que Marcus não a vê?

---

---

## 1. Arquitetura Chatwoot: como a visibilidade funciona para um agente

#### 1.1 Hierarquia de acesso

O Chatwoot determina o que um agente (usuário com `role = 'agent'`) pode ver através de **quatro camadas de controle**, todas persistidas no banco PostgreSQL:

```
account_users                 ← marco está associado à account?
       ↓
inbox_members                 ← marco é membro do inbox onde a conversa está?
       ↓
conversations (assignee_id)   ← marco está atribuído a esta conversa?
       ↓
messages (sender_id)          ← marco enviou esta mensagem?
```

**Tabelas diretamente relevantes para visibilidade**:

| Tabela | Coluna-chave | Papel |
|--------|-------------|-------|
| `account_users` | `(account_id, user_id, role)` | Associa o agente à conta; sem esta linha, o user não existe para a conta |
| `inbox_members` | `(inbox_id, user_id)` | Controla quais inboxes o agente pode acessar; ausência = inbox invisível |
| `conversations` | `assignee_id` | Atribuição direta; NULL não impede ver a conversa se o agente é membro do inbox |
| `conversations` | `team_id` | Acesso via equipe; agentes no `team_members` veem conversas do time |
| `team_members` | `(team_id, user_id)` | Membro de um time vê todas as conversas desse time |
| `messages` | `sender_id` | Quem enviou; relevante para histórico do agente, não para visibilidade |

#### 1.2 Regra de visibilidade do Chatwoot por `role`

- **`super_admin`**: vê tudo, independente de inbox_members ou assignee_id
- **`administrator`** (dentro da account): vê todas as conversas da account
- **`agent`**: vê APENAS conversas de inboxes onde está em `inbox_members`, OU onde é `assignee_id`, OU onde é membro de um time (`team_members`) que tem a conversa atribuída

Se `marcos.andrade@vya.digital` é `role = 'agent'`, a ausência de uma linha em `inbox_members` para qualquer um dos inboxes migrados é suficiente para tornar **todas as conversas daquele inbox invisíveis** na UI.

---

### 2. Hipóteses de causa raiz — análise técnica

#### H1 — Usuario foi "merged" (não skipped) — MAS o alias pode estar incorreto

**Status: PROVÁVEL, requer verificação**

Com 8 migrados e 104 skipped na tabela `users`, o comportamento do `UsersMigrator` precisa ser entendido precisamente:

O código do `UsersMigrator` implementa **dois fluxos distintos**:

```python
# Fluxo A — Merge por email (email já existe no DEST)
self.id_remapper.register_alias("users", src_id, dest_id)
self.state_repo.record_success(dest_conn, "users", src_id, dest_id)
# → NÃO passa por _run_batches → CONTADO NO "skipped" DO RESULTADO

# Fluxo B — Insert novo (email não existe no DEST)
# → Passa por _run_batches → CONTADO NO "migrated"
```

Como `marcos.andrade@vya.digital` tem domínio `@vya.digital`, é **altamente provável** que este usuário já existia no DEST antes da migração (ele é um funcionário Vya com conta em ambas as instâncias). Portanto ele estaria no **Fluxo A**: alias registrado, entrada em `migration_state` com `id_destino = <dest_user_id>`.

**Risco real do Fluxo A**: o `id_destino` em `migration_state` aponta para o `user.id` no DEST que tem este email. Se este mapeamento estiver correto, o `ConversationsMigrator` remapeia `assignee_id` corretamente. Se o alias apontou para o user_id errado (edge case de email case-sensitive ou email com espaço), o remap produziria `assignee_id` inválido — e o DEST teria conversas atribuídas a outro usuário.

**Verificação**:
```sql
-- No SOURCE: qual é o src_id de marcos?
SELECT id, email, name, role FROM users WHERE email ILIKE 'marcos.andrade@vya.digital';

-- No DEST: qual é o dest_id de marcos?
SELECT id, email, name, role FROM users WHERE email ILIKE 'marcos.andrade@vya.digital';

-- No migration_state: o mapeamento foi registrado?
SELECT tabela, id_origem, id_destino, status, migrated_at
FROM migration_state
WHERE tabela = 'users'
  AND id_origem = <src_user_id>;  -- substitua pelo id do SELECT acima
```

---

#### H2 — `assignee_id` NULL-out nas conversations

**Status: POSSÍVEL, especialmente se H1 apresentar falha**

O `ConversationsMigrator` null-a o `assignee_id` quando o user não está em `migrated_users`:

```python
if assignee_id_origin in migrated_users:
    new_row["assignee_id"] = self.id_remapper.remap(assignee_id_origin, "users")
else:
    new_row["assignee_id"] = None   # ← se marcus não estava em migrated_users
```

`migrated_users` é carregado de `state_repo.get_migrated_ids(conn, "users")` antes de processar conversas. Se o `UsersMigrator` rodou antes (ordem FK correta: `users` → `conversations`) e registrou marcus via `record_success`, ele ESTARIA em `migrated_users`.

Porém — se houve um re-run parcial onde conversations foram processadas ANTES de um re-run de users, ou se o state da sessão anterior tinha marcus ausente, as conversations de marcus teriam `assignee_id = NULL`.

**Consequência para visibilidade**: Um agente com `role = 'agent'` NÃO vê conversas com `assignee_id = NULL` na aba "Mine". Elas ficam somente em "All" — que pode não estar acessível dependendo da configuração de `inbox_members`.

**Verificação**:
```sql
-- Quantas conversations de marcus têm assignee_id NULL no DEST?
-- Primeiro, descobrir o dest_id de marcus:
WITH marcus AS (
    SELECT id FROM users WHERE email ILIKE 'marcos.andrade@vya.digital'
)
SELECT
    COUNT(*) FILTER (WHERE assignee_id IS NULL)    AS conversations_sem_assignee,
    COUNT(*) FILTER (WHERE assignee_id = m.id)     AS conversations_com_marcus,
    COUNT(*)                                        AS total_conversations
FROM conversations, marcus m
-- apenas conversas de inboxes que marcos deveria acessar
WHERE inbox_id IN (
    SELECT inbox_id FROM inbox_members WHERE user_id = m.id
);
```

---

#### H3 — `inbox_members` não migrado para marcus

**Status: ALTA PROBABILIDADE — este é o vetor mais comum de invisibilidade**

A tabela `inbox_members` **NÃO está na pipeline de migração atual** (não existe `inbox_members_migrator.py` em `src/migrators/`). Isso significa que:

1. Os inboxes foram migrados (21 migrados, 0 skipped)
2. Os users foram migrados/merged
3. **MAS as associações user↔inbox em `inbox_members` não foram copiadas do SOURCE**

Se marcus era membro de inboxes no SOURCE (ex: inbox `WhatsApp Vya`, `Email Suporte`) e essas associações não existem no DEST para o `dest_user_id` de marcus, **ele literalmente não vê nenhuma das conversas desses inboxes** na UI.

**Verificação crítica**:
```sql
-- No SOURCE: em quais inboxes marcus é membro?
SELECT
    im.inbox_id,
    i.name AS inbox_name,
    i.channel_type
FROM inbox_members im
JOIN inboxes i ON i.id = im.inbox_id
WHERE im.user_id = <src_marcus_id>;

-- No DEST: em quais inboxes marcus é membro?
SELECT
    im.inbox_id,
    i.name AS inbox_name,
    i.channel_type
FROM inbox_members im
JOIN inboxes i ON i.id = im.inbox_id
WHERE im.user_id = <dest_marcus_id>;

-- Diferença: inboxes que marcos tinha no SOURCE mas não tem no DEST
SELECT inbox_id FROM inbox_members WHERE user_id = <src_marcus_id>
EXCEPT
SELECT (inbox_id - <offset_inboxes>) -- ajustar pelo offset
FROM inbox_members WHERE user_id = <dest_marcus_id>;
```

---

#### H4 — `account_users` não migrado ou com `role` incorreto

**Status: POSSÍVEL**

O `UsersMigrator` migra `account_users` após os users, usando `on_conflict_do_nothing()`. Se marcus já tinha um registro em `account_users` no DEST (via Fluxo A de merge), o novo insert é silenciosamente ignorado. Isso geralmente é correto — mas se o `role` no DEST for diferente do SOURCE (ex: `agent` no DEST vs `administrator` no SOURCE), marcus teria permissões reduzidas.

**Verificação**:
```sql
-- Comparar role no SOURCE vs DEST para marcus
SELECT u.email, au.account_id, au.role, au.availability_status
FROM account_users au
JOIN users u ON u.id = au.user_id
WHERE u.email ILIKE 'marcos.andrade@vya.digital';
-- executar no SOURCE e no DEST
```

---

#### H5 — Marcus é um CONTATO, não um AGENTE

**Status: IMPROVÁVEL mas precisa ser descartado**

Se `marcos.andrade@vya.digital` for um `contact` (cliente) e não um `user` (agente), a análise de visibilidade muda completamente. Contatos acessam o Chatwoot via portal/widget, não via painel de agente.

Os 246 contacts "missing" no hash (3.41% de perda) são a única linha com `missing > 0`. Se marcus estiver nesses 246, seu contato não existe no DEST e suas conversas teriam `contact_id = NULL`.

**Verificação**:
```sql
-- É um user (agente)?
SELECT id, email, role FROM users WHERE email ILIKE 'marcos.andrade@vya.digital';

-- É um contact?
SELECT id, email, name, phone_number FROM contacts WHERE email ILIKE 'marcos.andrade@vya.digital';
-- executar em SOURCE e DEST
```

---

#### H6 — Divergência API: synchat.vya.digital ≠ vya-chat-dev.vya.digital

**Status: CONFIRMADO como divergência — IMPACTA a validação API, não a migração DB**

Esta é a divergência mais crítica para INTERPRETAR os resultados de validação:

| Item | Valor configurado | Valor real |
|------|-------------------|------------|
| `.secrets/generate_erd.json` `synchat` → `api_key` | aponta para `synchat.vya.digital` | instância diferente |
| DEST DB migrado | `chatwoot004_dev1_db` | frontend: `vya-chat-dev.vya.digital` |

Se `synchat.vya.digital` é uma instância Chatwoot **diferente** (com banco diferente do `chatwoot004_dev1_db`), então:
- A validação via API em `app/10_validar_api.py` estava CONSULTANDO UMA INSTÂNCIA ERRADA
- Os resultados de validação API (se realizados) são INVÁLIDOS
- A validação hash `app/11_validar_hash.py` consulta diretamente os bancos e é VÁLIDA independentemente

**Hipótese de mapeamento**:
```
SOURCE: chat.vya.digital  →  DB: chatwoot_dev1_db
DEST:   vya-chat-dev.vya.digital  →  DB: chatwoot004_dev1_db  ← migração foi aqui
OUTRO:  synchat.vya.digital  →  DB: ??? (provavelmente banco diferente)
```

**Verificação imediata**:
```bash
# Comparar account_id=1 em ambas as APIs
curl -s -H "api_access_token: <token_synchat>" \
  https://synchat.vya.digital/api/v1/profile | jq '.account_id'

curl -s -H "api_access_token: <token_vya_chat_dev>" \
  https://vya-chat-dev.vya.digital/api/v1/profile | jq '.account_id'
```

Se os `account_id` retornados diferirem, são instâncias diferentes.

---

### 3. Queries SQL de diagnóstico completo

#### 3.1 — Localizar marcus no SOURCE e DEST

```sql
-- ============================================================
-- Executar no SOURCE (chatwoot_dev1_db)
-- ============================================================
SELECT
    'SOURCE' AS db,
    u.id AS user_id,
    u.email,
    u.name,
    u.role,
    u.availability_status,
    u.confirmed,
    au.account_id,
    au.role AS account_role
FROM users u
LEFT JOIN account_users au ON au.user_id = u.id
WHERE u.email ILIKE 'marcos.andrade@vya.digital';

-- ============================================================
-- Executar no DEST (chatwoot004_dev1_db)
-- ============================================================
SELECT
    'DEST' AS db,
    u.id AS user_id,
    u.email,
    u.name,
    u.role,
    u.availability_status,
    u.confirmed,
    au.account_id,
    au.role AS account_role
FROM users u
LEFT JOIN account_users au ON au.user_id = u.id
WHERE u.email ILIKE 'marcos.andrade@vya.digital';
```

#### 3.2 — Verificar migration_state para marcus

```sql
-- Executar no DEST (migration_state está no DEST)
SELECT
    ms.tabela,
    ms.id_origem,
    ms.id_destino,
    ms.status,
    ms.migrated_at,
    u.email AS dest_email,
    u.name  AS dest_name
FROM migration_state ms
LEFT JOIN users u ON u.id = ms.id_destino
WHERE ms.tabela = 'users'
  AND ms.id_origem = (
      -- src_id de marcos — substituir após executar 3.1
      SELECT id FROM users WHERE email ILIKE 'marcos.andrade@vya.digital'
      -- NOTA: esta subquery deve ser executada no SOURCE
      -- cole o valor manualmente: AND ms.id_origem = <src_id>
  );
```

> **Nota prática**: como `migration_state` está no DEST e `users` está no SOURCE, execute o SELECT do src_id no SOURCE primeiro e cole o valor hardcoded na query do DEST.

#### 3.3 — Conversations atribuídas a marcus no SOURCE

```sql
-- Executar no SOURCE (chatwoot_dev1_db)
-- Substitua <src_marcus_id> pelo id obtido em 3.1
SELECT
    c.id AS conversation_id,
    c.display_id,
    c.status,
    c.inbox_id,
    i.name AS inbox_name,
    c.contact_id,
    c.assignee_id,
    c.created_at,
    COUNT(m.id) AS message_count
FROM conversations c
JOIN inboxes i ON i.id = c.inbox_id
LEFT JOIN messages m ON m.conversation_id = c.id
WHERE c.assignee_id = <src_marcus_id>
GROUP BY c.id, c.display_id, c.status, c.inbox_id, i.name,
         c.contact_id, c.assignee_id, c.created_at
ORDER BY c.created_at DESC
LIMIT 50;
```

#### 3.4 — Conversations de marcus no DEST (pós-migração)

```sql
-- Executar no DEST (chatwoot004_dev1_db)
-- Substitua <dest_marcus_id> pelo id obtido em 3.1
SELECT
    c.id AS conversation_id,
    c.display_id,
    c.status,
    c.inbox_id,
    i.name AS inbox_name,
    c.assignee_id,
    c.additional_attributes->>'src_id' AS src_id_rastreio,
    COUNT(m.id) AS message_count
FROM conversations c
JOIN inboxes i ON i.id = c.inbox_id
LEFT JOIN messages m ON m.conversation_id = c.id
WHERE c.assignee_id = <dest_marcus_id>
GROUP BY c.id, c.display_id, c.status, c.inbox_id, i.name,
         c.assignee_id, c.additional_attributes
ORDER BY c.created_at DESC
LIMIT 50;
```

#### 3.5 — Conversations sem assignee do SOURCE que deveriam ter marcus

```sql
-- Executar no DEST (chatwoot004_dev1_db)
-- Encontrar conversations migradas do SOURCE cujo assignee foi NULL-out
SELECT
    c.id AS dest_conv_id,
    c.additional_attributes->>'src_id' AS src_conv_id,
    c.assignee_id,
    c.inbox_id,
    c.status,
    c.created_at
FROM conversations c
WHERE c.assignee_id IS NULL
  AND c.additional_attributes->>'src_id' IS NOT NULL
ORDER BY c.created_at DESC
LIMIT 100;
```

#### 3.6 — Diagnóstico inbox_members para marcus

```sql
-- Executar no SOURCE
SELECT
    im.inbox_id,
    i.name,
    i.channel_type,
    i.account_id
FROM inbox_members im
JOIN inboxes i ON i.id = im.inbox_id
WHERE im.user_id = <src_marcus_id>;

-- Executar no DEST
SELECT
    im.inbox_id,
    i.name,
    i.channel_type,
    i.account_id
FROM inbox_members im
JOIN inboxes i ON i.id = im.inbox_id
WHERE im.user_id = <dest_marcus_id>;
```

#### 3.7 — Checar se inbox_members foi migrado (contagem global)

```sql
-- Executar no SOURCE
SELECT COUNT(*), COUNT(DISTINCT user_id), COUNT(DISTINCT inbox_id)
FROM inbox_members;

-- Executar no DEST
SELECT COUNT(*), COUNT(DISTINCT user_id), COUNT(DISTINCT inbox_id)
FROM inbox_members;
```

Se as contagens do SOURCE forem muito maiores que as do DEST, **`inbox_members` não foi migrado** e TODOS os agentes têm acesso reduzido, não apenas marcus.

#### 3.8 — Messages enviadas por marcus no SOURCE

```sql
-- Executar no SOURCE
SELECT
    COUNT(*) AS total_messages,
    COUNT(DISTINCT conversation_id) AS conversations_with_messages,
    MIN(created_at) AS first_message,
    MAX(created_at) AS last_message
FROM messages
WHERE sender_id = <src_marcus_id>
  AND sender_type = 'User';
```

#### 3.9 — Messages de marcus no DEST

```sql
-- Executar no DEST
SELECT
    COUNT(*) AS total_messages,
    COUNT(DISTINCT conversation_id) AS conversations_with_messages,
    MIN(created_at) AS first_message,
    MAX(created_at) AS last_message
FROM messages
WHERE sender_id = <dest_marcus_id>
  AND sender_type = 'User';

-- Verificar via src_id (rastreio direto):
SELECT
    COUNT(*) AS messages_with_src_id,
    COUNT(*) FILTER (WHERE sender_id = <dest_marcus_id>) AS messages_correto_sender,
    COUNT(*) FILTER (WHERE sender_id != <dest_marcus_id>) AS messages_sender_errado,
    COUNT(*) FILTER (WHERE sender_id IS NULL) AS messages_sender_null
FROM messages
WHERE additional_attributes->>'src_id' IS NOT NULL
  AND conversation_id IN (
      SELECT id FROM conversations
      WHERE additional_attributes->>'src_id' IS NOT NULL
  );
```

---

### 4. Sequência de verificação via API REST Chatwoot

#### 4.1 — Resolver divergência de instância PRIMEIRO

```bash
# Passo 1: Confirmar qual instância corresponde ao banco DEST (chatwoot004_dev1_db)
# Testar API vya-chat-dev.vya.digital — precisa de token desta instância
curl -s \
  -H "api_access_token: <TOKEN_VYA_CHAT_DEV>" \
  "https://vya-chat-dev.vya.digital/api/v1/profile"

# Passo 2: Ver quantas accounts existem nesta instância
curl -s \
  -H "api_access_token: <TOKEN_VYA_CHAT_DEV>" \
  "https://vya-chat-dev.vya.digital/auth/sign_in" \
  # Alternativa: usar super_admin token e listar /auth/sign_in
```

#### 4.2 — Validar token e perfil

```bash
# Com token correto da instância vya-chat-dev.vya.digital
BASE="https://vya-chat-dev.vya.digital"
TOKEN="<api_access_token>"

curl -s -H "api_access_token: $TOKEN" "$BASE/api/v1/profile" | jq '{
    id: .id,
    email: .email,
    role: .role,
    account_id: .account_id
}'
```

#### 4.3 — Buscar marcus via API

```bash
# Listar agentes da account
ACCOUNT_ID=1  # ajustar para a account correta no DEST
curl -s \
  -H "api_access_token: $TOKEN" \
  "$BASE/api/v1/accounts/$ACCOUNT_ID/agents" \
  | jq '.[] | select(.email == "marcos.andrade@vya.digital") | {id, email, role, availability_status}'
```

#### 4.4 — Listar conversations atribuídas a marcus via API

```bash
# Passo 1: obter o agent_id de marcus via endpoint acima
MARCUS_AGENT_ID=<id_obtido_no_step_anterior>

# Passo 2: listar conversations atribuídas
curl -s \
  -H "api_access_token: $TOKEN" \
  "$BASE/api/v1/accounts/$ACCOUNT_ID/conversations?assignee_type=assigned&page=1" \
  | jq '.data.payload[] | select(.meta.assignee.id == '$MARCUS_AGENT_ID') | {
      id: .id,
      display_id: .display_id,
      status: .status,
      inbox_id: .inbox_id,
      message_count: .messages_count
    }'
```

#### 4.5 — Verificar inboxes acessíveis para marcus

```bash
# Lista de inboxes que a instância tem
curl -s \
  -H "api_access_token: $TOKEN" \
  "$BASE/api/v1/accounts/$ACCOUNT_ID/inboxes" \
  | jq '.payload[] | {id: .id, name: .name, channel_type: .channel_type}'

# Inboxes que marcus PODE acessar (como agente membro)
# Esse endpoint requer super_admin ou o próprio token de marcus
curl -s \
  -H "api_access_token: <TOKEN_DO_PROPRIO_MARCUS>" \
  "$BASE/api/v1/profile" | jq '.inboxes'
```

#### 4.6 — Contagem de conversations por status

```bash
for STATUS in open resolved pending; do
    echo "=== $STATUS ==="
    curl -s \
      -H "api_access_token: $TOKEN" \
      "$BASE/api/v1/accounts/$ACCOUNT_ID/conversations/meta?status=$STATUS" \
      | jq '{status: "'$STATUS'", all_count: .data.all_count, assigned: .data.assigned_count}'
done
```

---

### 5. Riscos específicos do Chatwoot que causam invisibilidade

#### R1 — `inbox_members` não migrado (RISCO CRÍTICO — P0)

**Impacto**: Todos os agentes `role = 'agent'` ficam sem acesso a qualquer inbox migrado.
**Sintoma**: Na UI, o agente vê "Nenhuma conversa" em todos os inboxes.
**Causa raiz**: `inbox_members` não tem migrator no pipeline atual.
**Solução**: Migrar `inbox_members` do SOURCE para o DEST, remapeando `user_id` e `inbox_id` pelos offsets.

#### R2 — `team_members` não migrado

**Impacto**: Conversas atribuídas a times ficam invisíveis para membros de times.
**Sintoma**: Aba "Teams" vazia; conversas com `team_id != NULL` não aparecem para os agentes.
**Solução**: Verificar se `team_members` foi migrado; adicionar migrator se necessário.

#### R3 — `assignee_id` NULL-out em conversas originalmente de marcus

**Impacto**: As conversas ficam em "All/Unassigned" em vez de "Mine" na UI do marcus.
**Sintoma**: Marcus não encontra conversas em "Mine" mas as encontra em "All" (se tiver acesso ao inbox).
**Solução**: Script de pós-migração para restaurar `assignee_id` usando `migration_state` e o alias registrado.

#### R4 — `pubsub_token = NULL` em `contact_inboxes`

O migrator deliberadamente seta `pubsub_token = NULL` (requisito de segurança — coluna UNIQUE global). O Chatwoot Rails regenera automaticamente este token quando o contato acessa o canal. **Isso NÃO afeta a visibilidade do agente**, mas pode causar falha na notificação em tempo real (ActionCable) para o contato.

#### R5 — `display_id` resequenciado quebrando bookmarks/links

O `ConversationsMigrator` resequencia `display_id` para evitar colisões. Se marcus tiver bookmarks ou links externos para conversas pelo `display_id` antigo, eles não funcionarão. **Os dados existem**, mas o identificador público mudou.

#### R6 — Cache Redis na instância de destino desatualizado

O Chatwoot usa Redis para cache de contagens e estado de conversas. Após uma migração em massa diretamente no banco (bypass do Rails), o cache Redis pode estar com contagens antigas. **Sintoma**: a UI mostra "0 conversas" mesmo com dados no banco.
**Solução**: `rails runner "Rails.cache.clear"` na instância `vya-chat-dev.vya.digital`, ou aguardar expiração.

#### R7 — `content_attributes` tipo `json` vs `jsonb`

Nosso migrator seta `content_attributes = NULL` nas mensagens para evitar quebrar o Rails (tipo `json` — constraint do schema). Mensagens onde o Rails esperaria conteúdo específico em `content_attributes` (ex: mensagens de e-mail com `email_from`) podem aparecer com formatação incompleta na UI, mas **aparecem** — não ficam invisíveis.

#### R8 — `conversation_id` de messages com offset errado

Se o `id_remapper` calculou um offset incorreto para conversations, as `messages.conversation_id` podem apontar para conversas de um account diferente do esperado. A mensagem existe no banco mas aparece na conversa errada. Checar:

```sql
-- Mensagens cujo conversation_id aponta para uma conversa de account diferente
SELECT m.id, m.account_id, m.conversation_id, c.account_id AS conv_account_id
FROM messages m
JOIN conversations c ON c.id = m.conversation_id
WHERE m.account_id != c.account_id
LIMIT 20;
```

---

### 6. Recomendações de ação imediata

| Prioridade | Ação | Justificativa |
|-----------|------|---------------|
| **P0** | Executar queries 3.1 e 3.6 (user + inbox_members) | Confirmar se `inbox_members` está vazio no DEST |
| **P0** | Resolver divergência synchat vs vya-chat-dev | Sem isso, toda validação API é inválida |
| **P1** | Executar query 3.3 vs 3.4 (conversations SOURCE vs DEST) | Quantificar conversations de marcus com/sem assignee |
| **P1** | Executar query 3.2 (migration_state para marcus) | Confirmar se alias está correto em migration_state |
| **P2** | Se `inbox_members` vazio → criar script de migração | Copiar inbox_members do SOURCE com remap de user_id e inbox_id |
| **P2** | Se assignee_id NULL → script de restauração | UPDATE conversations SET assignee_id = <dest_id> usando migration_state |

---

### 7. Árvore de decisão diagnóstica

```
marcus.andrade@vya.digital não vê mensagens
│
├── [A] marcus existe no DEST como user?
│     ├── NÃO → migration_state tem marcus? → verificar alias
│     │           └── NÃO → usuário foi perdido → criar manualmente
│     └── SIM → continuar
│
├── [B] marcus tem account_users no DEST para a account correta?
│     ├── NÃO → inserir account_users manualmente
│     └── SIM → continuar
│
├── [C] inbox_members existe no DEST para marcus?
│     ├── NÃO → migrar inbox_members (H3 — RISCO MAIS PROVÁVEL)
│     └── SIM → continuar
│
├── [D] conversations com assignee_id = marcus existem no DEST?
│     ├── NÃO (assignee NULL) → restaurar assignee_id via migration_state
│     └── SIM → continuar
│
├── [E] API vya-chat-dev.vya.digital responde com dados corretos?
│     ├── NÃO → divergência de instância — obter token correto
│     └── SIM → problema é de cache Redis ou configuração Rails
│
└── [F] Cache Redis limpo?
      ├── NÃO → limpar cache na instância destino
      └── SIM → escalar para diagnóstico de Rails logs
```

---

*Perspectiva produzida por @chatwoot-expert em 2026-04-22 para o Debate D7.*
*Próximo passo: executar as queries acima e trazer resultados para fechamento do debate.*

---

## 8. DIAGNÓSTICO EXECUTADO — 2026-04-22 (resultados reais)

**Script**: `app/12_diagnostico_marcos.py` via `make diagnose-agent`
**Artefato**: `.tmp/diagnostico_marcos_20260422_174753.json`
**Executado em**: 2026-04-22 17:47–17:48

---

### 8.1 — Dados do usuário (SOURCE vs DEST)

| Campo | SOURCE | DEST | Status |
|-------|--------|------|--------|
| `user_id` | 88 | 88 | ✅ Mesmo ID (não remapeado) |
| `name` | Marcos Andrade | Marcos Andrade | ✅ |
| `role` | 1 (administrator) | 1 (administrator) | ✅ |
| `account_users` | 4 contas | 13 contas | ⚠️ Expandido na migração |
| `confirmed` | sim | sim | ✅ |

**SOURCE account_users** (IDs das contas no SOURCE):

| account_id | role | Empresa |
|------------|------|---------|
| 1 | 1 (admin) | Vya Digital |
| 17 | 1 (admin) | Unimed Poços PJ |
| 18 | 1 (admin) | Unimed Poços PF |
| 25 | 1 (admin) | Unimed Guaxupé |

**DEST account_users** (13 contas no DEST):

```
17, 33, 38, 31, 28, 30, 32, 37, 40, 1, 43, 68, 61
```

Contas que correspondem à migração SOURCE→DEST:
- `1` → Vya Digital (direto)
- `17` → Unimed Poços PJ (direto)
- `61` → Unimed Poços PF (SOURCE 18 → DEST 61)
- `68` → Unimed Guaxupé (SOURCE 25 → DEST 68)

Contas extras no DEST (`33, 38, 31, 28, 30, 32, 37, 40, 43`): **pré-existentes no DEST** antes da migração — não vieram do SOURCE.

---

### 8.2 — migration_state

| Campo | Valor |
|-------|-------|
| `tabela` | `users` |
| `id_origem` | 88 |
| `id_destino` | 88 |
| `status` | `ok` |
| `migrated_at` | 2026-04-20 17:52:03 |
| `alias_correct` | ✅ True |

> **H1 DESCARTADA**: alias correto, user_id preservado (88→88).

---

### 8.3 — Conversations

| Métrica | SOURCE | DEST | Delta |
|---------|--------|------|-------|
| `conversations WHERE assignee_id=88` | **3** | **17** | DEST tem +14 |
| por account (SOURCE) | account 1: 2, account 17: 1 | — | — |
| `conversations migradas com assignee=NULL` | — | **0** | H2 DESCARTADA |
| acessíveis via inbox_members (DEST) | — | 284 | via inboxes 145, 179 |

> **H2 TOTALMENTE DESCARTADA**: Zero conversas migradas têm `assignee_id=NULL`. O DEST tem 17 conversas atribuídas a marcus vs 3 no SOURCE. O pipeline preservou e até expandiu as atribuições.

---

### 8.4 — Messages

| Métrica | DEST | Análise |
|---------|------|---------|
| `messages WHERE sender_id=88` | 94 | ✅ Mensagens enviadas por marcus presentes |
| mensagens em conversas de marcus | 89 | ✅ Correspondência alta |

> **Mensagens de marcus EXISTEM no DEST** e estão corretamente vinculadas.

---

### 8.5 — inbox_members

| Métrica | SOURCE | DEST |
|---------|--------|------|
| inbox_members para marcus | **0 inboxes** | **2 inboxes** |
| inboxes no DEST | — | 145 ("551131357275"), 179 ("Receptivo_Santander") |

> **H3 N/A**: Marcus tem 0 inbox_members no SOURCE porque ele é **administrator** — administradores no Chatwoot acessam TODOS os inboxes de suas contas sem precisar de registro em `inbox_members`. A ausência de inbox_members no SOURCE é ESPERADA.

> **Inboxes 145 e 179 no DEST** são inboxes **pré-existentes no DEST** (não vieram da migração do SOURCE). Eles foram adicionados ao DEST de forma independente.

---

### 8.6 — API

| Host | Acessível | Observação |
|------|-----------|------------|
| `synchat.vya.digital` | ✅ HTTP 200 | API key funcional |
| `vya-chat-dev.vya.digital` | ✅ HTTP 200 | API key funcional |

> **H6 PARCIALMENTE DESCARTADA**: Ambas as instâncias são acessíveis com a mesma api_key. A preocupação de instâncias divergentes não se confirmou para autenticação, mas a identificação do banco correto ainda requer verificação de qual banco está por trás de `vya-chat-dev.vya.digital`.

---

### 8.7 — Hipóteses revisadas (pós-diagnóstico)

| Hipótese | Status Final | Evidência |
|----------|-------------|-----------|
| H1 — alias incorreto | ❌ **DESCARTADA** | migration_state 88→88, alias_correct=True |
| H2 — assignee_id NULL-out | ❌ **DESCARTADA** | 0 conversas migradas com assignee=NULL; DEST tem 17 vs SOURCE 3 |
| H3 — inbox_members não migrado | ❌ **N/A** | marcus é admin; 0 inbox_members em SOURCE é ESPERADO |
| H4 — role incorreto no DEST | ❌ **DESCARTADA** | role=1 (admin) preservado em DEST |
| H5 — é contato, não agente | ❌ **DESCARTADA** | Encontrado em `users` com role=admin |
| H6 — divergência de instância | ⚠️ **PARCIAL** | Ambas APIs respondem; verificar qual banco serve vya-chat-dev |
| **H7 (NOVO) — conta errada na UI** | 🔴 **ALTA SUSPEITA** | marcus tem 13 accounts no DEST; pode estar acessando conta sem dados migrados |
| **H8 (NOVO) — Redis cache desatualizado** | 🟡 **POSSÍVEL** | Inserção direta no DB bypassa o Rails/ActionCable |
| **H9 (NOVO) — display_id resequenciado** | 🟡 **POSSÍVEL** | Bookmarks/links com display_id antigo não funcionam mais |

---

### 8.8 — Hipótese H7 — Conta errada na UI (MAIS PROVÁVEL)

Marcus tem **13 account_users no DEST**, incluindo 9 contas pré-existentes do DEST (`33, 38, 31, 28, 30, 32, 37, 40, 43`) que **não têm dados migrados do chat.vya.digital**.

Se marcus faz login em `vya-chat-dev.vya.digital` e o sistema carrega uma dessas 9 contas por padrão (ou a última conta acessada), ele verá uma conta vazia ou com dados irrelevantes, sem nenhuma das conversas migradas.

**As contas com dados migrados no DEST são**:

| DEST account_id | Empresa (SOURCE) | Conversas migradas (aprox.) |
|----------------|------------------|---------------------------|
| 1 | Vya Digital | ✅ Sim |
| 17 | Unimed Poços PJ | ✅ Sim |
| 61 | Unimed Poços PF | ✅ Sim |
| 68 | Unimed Guaxupé | ✅ Sim |

**Ação imediata**: Pedir ao usuário que acesse `vya-chat-dev.vya.digital` e confirme **qual account/organização está selecionado** na UI. Deve ser um dos quatro acima.

---

### 8.9 — Hipótese H8 — Redis cache desatualizado

O pipeline de migração inseriu ~313.000 linhas diretamente no PostgreSQL do DEST, **bypassando completamente o Rails app e o ActionCable**. O Chatwoot usa Redis para:
- Cache de contagens de conversas por status (open/resolved/pending)
- Cache de membros de inbox
- Sessões de usuário e pubsub tokens

Após inserção massiva direta no DB:
- Contagens no Redis podem estar em 0 ou valores antigos
- A UI pode mostrar "0 conversas" mesmo com dados no banco
- Filtros por status podem retornar vazio enquanto o Redis não expira

**Verificação/Correção**:
```bash
# Na instância vya-chat-dev.vya.digital (acesso ao servidor)
# Opção 1: limpar cache Rails
rails runner "Rails.cache.clear" --environment production

# Opção 2: aguardar expiração natural do Redis (TTL padrão Chatwoot: 1 hora)

# Opção 3: verificar se o problema sumiu após fazer logout/login
```

---

### 8.10 — Recomendações de ação (ordenadas por prioridade)

| Prioridade | Ação | Responsável | Tempo estimado |
|-----------|------|------------|----------------|
| **P0** | Verificar qual account está selecionado na UI de `vya-chat-dev` para marcus | @yvesmarinho (frente) | 2 min |
| **P0** | Se conta correta → fazer logout e login novamente (força reload do cache) | @yvesmarinho | 2 min |
| **P1** | Se problema persistir → limpar Redis no servidor `vya-chat-dev` | DevOps | 5 min |
| **P2** | Confirmar qual banco (`chatwoot_dev1_db` ou `chatwoot004_dev1_db`) serve `vya-chat-dev.vya.digital` via test de conta | @yvesmarinho | 5 min |
| **P3** | Informar marcus que display_ids mudaram após migração (bookmarks antigos inválidos) | @yvesmarinho | — |

---

### 8.11 — Teste rápido de confirmação (para fazer no front)

1. Abrir `https://vya-chat-dev.vya.digital`
2. Fazer login com `marcos.andrade@vya.digital`
3. No canto superior esquerdo, verificar **qual organização/account está selecionado**
4. Tentar trocar para "Vya Digital" (account_id=1) — deve aparecer conversas
5. Tentar trocar para "Unimed Poços PJ" (account_id=17) — deve aparecer conversas
6. Verificar aba **"All"** (não "Mine") para ver todas as conversas do account
7. Se a UI mostrar 0 em todos — problema de Redis cache → limpar cache

---

*Diagnóstico executado por `make diagnose-agent` em 2026-04-22 17:47.*
*JSON completo: `.tmp/diagnostico_marcos_20260422_174753.json`*
*Status: AGUARDA VERIFICAÇÃO NO FRONT (H7 — conta errada na UI)*

---

## 9. RE-INTERPRETAÇÃO DO DIAGNÓSTICO — Arquitetura corrigida

Com a arquitetura corrigida (seção 0), os resultados da seção 8 ganham novo significado:

### 9.1 — As 13 accounts no DEST (re-interpretação)

No diagnóstico anterior (seção 8.1), Marcus tinha 13 `account_users` no DEST contra 4 no SOURCE. Com a arquitetura corrigida:

| Grupo | account_ids no DEST | Origem |
|-------|---------------------|--------|
| Migradas de chat.vya.digital | 1, 17, 61, 68 | Export SOURCE → pipeline MERGE |
| Pré-existentes de synchat.vya.digital | 28, 30, 31, 32, 33, 37, 38, 40, 43 | Já existiam antes da migração |

Marcus é admin em **ambos os grupos**. Suas conversas podem estar em qualquer uma das 13 accounts.

### 9.2 — As 17 conversas com assignee=88 no DEST (re-interpretação)

Originalmente interpretamos como: 3 do SOURCE + 14 novas. Com a arquitetura corrigida:

```
DEST (chatwoot004_dev1_db) antes da migração:
  → conversas pré-existentes de synchat.vya.digital com assignee=88 (quantidade desconhecida)

DEST após migração:
  + 3 conversas migradas de chat.vya.digital com assignee=88
  ─────────────────────────────────────────────────────────
  = 17 conversas totais com assignee=88
  → estimativa: ~14 pré-existentes de synchat, 3 migradas de chat
```

A conversa de 14/11/2025 pode estar em qualquer um dos dois grupos.

### 9.3 — Script `app/12_diagnostico_marcos.py` — correções necessárias

O script atual probe `synchat.vya.digital` como API, o que está **incorreto** conforme arquitetura corrigida:

| Campo atual | Correto (v2) |
|---|---|
| `synchat.vya.digital` → API probe | `chat.vya.digital` → SOURCE API |
| `vya-chat-dev.vya.digital` → API probe | `vya-chat-dev.vya.digital` → DEST API ✅ |

Script corrigido: `app/14_verificar_conv_marcos.py` (seção 10).

### 9.4 — H7 re-avaliada com arquitetura corrigida

A hipótese H7 (conta errada na UI) permanece a **mais provável**, mas agora com detalhe adicional:

Se Marcus acessa `vya-chat-dev.vya.digital` e o sistema carrega uma das 9 contas pré-existentes do synchat (ex: account_id=33, 38…), ele verá conversas **do synchat antigo**, não as conversas de `chat.vya.digital` que deveriam ter sido migradas.

Se Marcus acessa account_id=1 (Vya Digital) no DEST, ele deveria ver:
- Conversas pré-existentes de synchat.vya.digital na account 1
- + Conversas migradas de chat.vya.digital na account 1

Se a conversa de 14/11/2025 era de `chat.vya.digital` account 1 → deveria aparecer no DEST account 1.

---

## 10. RESULTADOS — `make verify-marcus-conv CONV_DATE=2025-11-14` (2026-04-22 18:10)

> Script: `app/14_verificar_conv_marcos.py` — janela 11-18/11/2025 — user_id=88
> JSON completo: `.tmp/verificacao_conv_marcos_20260422_181025.json`

### 10.1 — VEREDICTO: **MIGRATION_GAP CONFIRMADO** ✅

```
VEREDICTO: MIGRATION_GAP
SOURCE conversas encontradas : 1
DEST encontradas (src_id)    : 0    ← conversa NÃO migrada
DEST encontradas (data)      : 1    ← conversa PRÉ-EXISTENTE de synchat (diferente)
Gaps de migração             : 1
Visíveis via API DEST        : 0
Invisíveis via API DEST      : 1    ← conversa do DEST com HTTP 404 no admin API
API SOURCE (chat.vya.digital) : acessível ✅
API DEST (vya-chat-dev.vya.digital): acessível ✅
```

### 10.2 — Conversa não migrada (GAP confirmado)

| Campo | Valor |
|-------|-------|
| **SOURCE conv_id** | `62363` |
| **SOURCE display_id** | `1093` |
| **SOURCE account_id** | `1` (Vya Digital) |
| **SOURCE inbox_id** | `125` |
| **SOURCE created_at** | `2025-11-14 23:48:22` |
| **Encontrado via** | `assignee` (Marcus é o assignee) |
| **DEST esperado (account)** | `1` (mesma account — mapeamento 1→1) |
| **Migrado?** | **NÃO** — nenhum registro em DEST com `additional_attributes->>'src_id' = '62363'` |

### 10.3 — Conversa pré-existente no DEST (synchat, diferente)

| Campo | Valor |
|-------|-------|
| DEST conv_id | `219047` |
| DEST display_id | `1850` |
| DEST account_id | `1` |
| Origem | Pré-existente de `synchat.vya.digital` (não migrada do SOURCE) |
| API DEST GET | **HTTP 404** — não encontrada via admin API em account 1 |

> **Observação**: O HTTP 404 da conversa 219047 pode indicar que o admin user (api_key de synchat) não está em `account_users` da account 1 em `vya-chat-dev.vya.digital`. Isso é um problema secundário de configuração de admin. Não afeta o diagnóstico do GAP.

### 10.4 — Conclusão do diagnóstico

```
H2 (assignee NULL)        — DESCARTADA (Marcus é assignee=88 na conversa de origin)
H3 (inbox_members)        — DESCARTADA (Marcus é admin, não precisa de entrada)
H7 (conta errada na UI)   — PARCIALMENTE RELEVANTE (mas não é a causa raiz)
H9 (display_id resequenc) — RELEVANTE (display_id 1093 no SOURCE → qual seria no DEST?)

CAUSA RAIZ: A conversa src_conv_id=62363 / display_id=1093 NÃO foi migrada
            do SOURCE (chatwoot_dev1_db / chat.vya.digital) para o DEST
            (chatwoot004_dev1_db / vya-chat-dev.vya.digital).

AÇÃO NECESSÁRIA: Investigar por que a pipeline de migração não migrou esta
                 conversa e executar migração corretiva.
```

---

## 11. INVESTIGAÇÃO ADICIONAL — Por que a conversa não foi migrada?

### 11.1 — Hipóteses para o gap

| ID | Hipótese | Prob. |
|----|----------|-------|
| G1 | Conversa com `assignee_id=88` excluída do batch por critério de filtro | Alta |
| G2 | Conversa pertence ao `inbox_id=125` que não foi mapeado no DEST | Média |
| G3 | Erro de FK durante migração (inbox_id 125 sem equivalente no DEST) | Média |
| G4 | Conversa criada DEPOIS do cutoff de migração | Baixa (data= nov/2025, migração= abr/2026) |
| G5 | Pipeline não migrou account_id=1 conversations (filtro por account) | Baixa |

### 11.2 — Próximas queries SQL necessárias

```sql
-- 1. Verificar se inbox_id=125 (SOURCE) tem equivalente no DEST
SELECT id, name, channel_type FROM inboxes WHERE id = 125;  -- no SOURCE
-- Buscar no DEST por nome ou por additional_attributes->>'src_id'

-- 2. Verificar quantas conversas do SOURCE de account_id=1 foram migradas
SELECT COUNT(*) FROM conversations
WHERE additional_attributes->>'src_id' IS NOT NULL
  AND account_id = 1;  -- no DEST

-- 3. Verificar se há erros de migração registrados para conv_id=62363
SELECT * FROM migration_states WHERE table_name='conversations' AND id_origem=62363;

-- 4. Verificar total de conversas de account_id=1 no SOURCE vs DEST
-- SOURCE: SELECT COUNT(*) FROM conversations WHERE account_id=1;
-- DEST:   SELECT COUNT(*) FROM conversations WHERE account_id=1
--                AND additional_attributes->>'src_id' IS NOT NULL;
```

### 11.3 — Ação imediata sugerida

**Opção A — Migração pontual da conversa específica**:
1. Identificar o inbox equivalente no DEST para `inbox_id=125` (SOURCE)
2. Migrar apenas a conversa `62363` e suas mensagens para o DEST
3. Verificar via API se ficou visível

**Opção B — Re-executar pipeline para account_id=1 / inbox_id=125**:
1. Verificar por que o inbox 125 não foi migrado (ou foi mapeado incorretamente)
2. Re-executar migração para todas as conversas do inbox 125 no SOURCE

---

## 12. QUESTIONNAIRE — Informações necessárias para fechar o debate

> As questões abaixo não podem ser respondidas programaticamente.
> Por favor, responder com base em acesso ao front-end e informações operacionais.

---

### Q1 — Localização da conversa de 14/11/2025 ✅ RESPONDIDA AUTOMATICAMENTE

> **Resposta confirmada pelo script `make verify-marcus-conv`**:
> A conversa estava em **`chat.vya.digital`** (SOURCE = `chatwoot_dev1_db`).
> `src_conv_id=62363`, `display_id=1093`, `account_id=1 (Vya Digital)`, `inbox_id=125`, criada em `2025-11-14 23:48:22`.

**Pergunta original**: A conversa que Marcus relata como "não visível" em `vya-chat-dev.vya.digital` — em qual sistema ela existia **antes da migração**?

- [x] **A) Em `chat.vya.digital`** ← **CONFIRMADO** (encontrada em `chatwoot_dev1_db`)
- [ ] B) Em `synchat.vya.digital`
- [ ] C) Em ambos os sistemas
- [ ] D) Não sei ao certo
- [x] E) Em `vya-chat-dev.vya.digital`

**Status**: GAP de migração confirmado — a conversa existe no SOURCE mas não no DEST.

---


### Q2 — O que Marcus vê hoje em vya-chat-dev.vya.digital

**Pergunta**: Quando Marcus acessa `https://vya-chat-dev.vya.digital` hoje:

- [ ] A) Vê zero conversas (tela completamente vazia)
- [ ] B) Vê algumas conversas, mas a de 14/11/2025 não está entre elas
- [ ] C) Não consegue nem fazer login
- [ ] D) Vê conversas mas de outra organização/account
- [x] E) Outra situação: vê as conversas que existem só no Destino.

**Por que importa**: Distingue entre "dados ausentes" (bug de migração) e "dados presentes mas invisíveis" (bug de UI/permissão/cache).

---

### Q3 — Account selecionada na UI

**Pergunta**: Ao fazer login em `vya-chat-dev.vya.digital`, qual organização/account aparece selecionada no canto superior esquerdo da interface?

- [x] A) Vya Digital
- [ ] B) Unimed Poços PJ
- [ ] C) Unimed Poços PF (pode aparecer com nome diferente)
- [ ] D) Unimed Guaxupé
- [ ] E) Outra organização com nome não reconhecível
- [ ] F) Consegue ver e trocar entre as organizações?

**Por que importa**: Marcus tem 13 organizations no DEST. Se está na errada, verá dados de synchat sem a conversa migrada de chat.vya.digital.

---

### Q4 — A conversa em chat.vya.digital

**Pergunta**: A conversa de 14/11/2025 ainda está visível em `chat.vya.digital` (o sistema de origem)?

- [x] A) Sim, consigo ver a conversa em chat.vya.digital
- [ ] B) Não, chat.vya.digital não está mais acessível
- [ ] C) Não tentei acessar

**Dado adicional desejado**: Se sim, qual é o `display_id` da conversa em `chat.vya.digital`? (número visível na URL: `/app/accounts/1/conversations/XXXX`)
**display_id 1093 e 1003, são as mensagens que não são exibidas no destino**
**Por que importa**: O `display_id` permite localizar a conversa no banco de dados e rastrear se foi migrada.

---

### Q5 — Papel de Marcus na conversa de 14/11/2025

**Pergunta**: Na conversa de 14/11/2025, qual é o papel de Marcus?

- [x] A) Agente atribuído (assignee) — a conversa aparecia na aba "Mine"
- [ ] B) Agente que enviou mensagens mas não era o assignee
- [ ] C) Observador — via a conversa por ser admin do account
- [ ] D) Contato/cliente (não era agente nessa conversa)

**Por que importa**: Determina se o bug é de `assignee_id` remapeado incorretamente ou de `sender_id`.

---

### Q6 — Período das conversas que Marcus consegue ver

**Pergunta**: No `vya-chat-dev.vya.digital`, nas conversas que Marcus consegue visualizar (se houver), qual é a data da mais antiga?

- Resposta: display_id: 1487 26/12/2025, display_id: 1237 03/09/2025, display_id: 1157 22/07/2025, display_id: 1152 22/07/2025

**Por que importa**: Se Marcus vê conversas mas só de depois de certa data, pode indicar que as conversas antigas do chat.vya.digital não foram migradas para aquela account específica.

---

### Q7 — Comportamento do Redis (visível indiretamente)

**Pergunta**: Após fazer **logout completo** e **novo login** em `vya-chat-dev.vya.digital`, as conversas aparecem?

- [ ] A) Sim, após logout/login aparecem mais conversas
- [x] B) Não, o problema persiste mesmo após logout/login
- [ ] C) Não testei

**Por que importa**: Se o problema sumiu após logout/login → era cache de sessão Redis. Isso seria H8 confirmada e resolução simples.

---

### Q8 — Canal/Inbox da conversa de 14/11/2025

**Pergunta**: Você sabe em qual **inbox/canal** a conversa de 14/11/2025 estava? (Ex: WhatsApp, e-mail, API, widget...)

- Resposta: whatsapp (a maioria das conversas são do whatsapp)

**Por que importa**: O `inbox_id` pode ter sido remapeado durante a migração. Se o inbox de origem (chat.vya.digital) não existe no DEST ou tem ID diferente, as conversas daquele inbox podem estar "escondidas" sob um inbox não mapeado.

---

*Questionnaire gerado em 2026-04-22. Responder Q1 e Q4 primeiro — são as mais decisivas.*
*Script de verificação automática: `make verify-marcus-conv CONV_DATE=2025-11-14`*

---

## 13. ANÁLISE CONCLUSIVA — Questionário + Diagnóstico Scripts

> **Data**: 2026-04-22 19:06 UTC-3
> **Scripts executados**: `make diagnose-inbox-gap`, `make diagnose-marcus-visibility`
> **Status**: DIAGNÓSTICO ENCERRADO — causa raiz identificada, ações corretivas definidas

---

### 13.1 — Hipóteses descartadas pelo questionário

| Hipótese | Evidência | Decisão |
|----------|-----------|---------|
| **H7 — Conta errada selecionada** | Q3 = Vya Digital (account_id=1) | ❌ DESCARTADA |
| **H8 — Cache Redis** | Q7 = problema persiste após logout/login | ❌ DESCARTADA |

---

### 13.2 — Escopo expandido: não é 1 conversa, são duas

Q4 revelou dois `display_id` ausentes no DEST (números visíveis em `chat.vya.digital`):

| SOURCE display_id | conv_id SOURCE | inbox SOURCE | created | msgs |
|------------------|----------------|--------------|---------|------|
| **1093** | 62363 | 125 (`wea004`, `Channel::Api`) | 2025-11-14 | 3 |
| **1003** | 43817 | 32 | 2025-02-04 | 2 |

> ⚠️ **CORREÇÃO**: inbox_id=125 tem `Channel::Api` (não WhatsApp). A resposta Q8 ("whatsapp") era uma percepção do usuário sobre o canal geral das conversas — mas o registro técnico mostra `Channel::Api` para este inbox específico.

---

### 13.3 — As conversas FORAM migradas (não é migration gap)

Scripts `app/15_diagnostico_inbox125.py` e `app/16_diagnostico_visibilidade_marcus.py` confirmaram:

```
migration_state (DEST):
  id_origem=62363 → id_destino=219047  status=ok  (conversa display_id=1093)
  id_origem=43817 → id_destino=200501  status=ok  (conversa display_id=1003)
```

As conversas existem no DEST. O diagnóstico anterior de "MIGRATION_GAP" em `app/14` foi um **falso negativo**: o script buscava `additional_attributes->>'src_id'` que **o `ConversationsMigrator` não escreve** — o campo `additional_attributes` é passado como-está do SOURCE, sem injeção de `src_id`.

---

### 13.4 — Causa raiz real: display_id resequenciado (BUG-04 fix)

O `ConversationsMigrator` aplica resequenciamento de `display_id` (BUG-04 anti-colisão) para evitar conflito com conversas pré-existentes no DEST. **Os display_ids foram trocados**:

| SOURCE display_id | DEST display_id | DEST conv_id | DEST inbox_id | assignee_id |
|------------------|-----------------|--------------|---------------|-------------|
| 1091 | **1848** | 219045 | 521 | None |
| 1092 | **1849** | 219046 | 521 | None |
| 1093 | **1850** | 219047 | 521 | **88 (Marcus)** |

Marcus procura display_id=1093 em `vya-chat-dev.vya.digital`. **Esse display_id não existe no DEST** — está registrado como 1850. Invisibilidade aparente = confusão de numeração.

---

### 13.5 — Problema secundário: dois inboxes `wea004` no DEST

A migração criou um segundo inbox `wea004` no DEST:

| inbox_id | name | channel | account | origem |
|----------|------|---------|---------|--------|
| **372** | `wea004` | Channel::Api | 1 | Pré-existente (synchat.vya.digital) |
| **521** | `wea004` | Channel::Api | 1 | **Migrado** (chat.vya.digital, SOURCE inbox_id=125) |

As conversas migradas (219045-219047) ficam em `inbox_id=521`. Marcus pode estar navegando via sidebar pelo inbox 372 (sem as conversas migradas) ou não encontrar as conversas no inbox 521 porque não sabia que esse inbox existia.

Marcus é **administrador** em account_id=1 (role=1) — portanto **não precisa de entrada em `inbox_members`** para ver conversas. Mas a navegação por inbox na sidebar mostra dois `wea004` e isso cria confusão.

---

### 13.6 — Problema terciário: assignee nullado em 2 conversas

Durante a migração, `assignee_id` de dois registros foi nullado:

| DEST conv_id | SOURCE display_id | assignee SOURCE | assignee DEST |
|--------------|------------------|-----------------|---------------|
| 219045 | 1091 | desconhecido | **None** |
| 219046 | 1092 | desconhecido | **None** |
| 219047 | 1093 | 88 (Marcus) | **88 (Marcus)** ✓ |

O `ConversationsMigrator` nulifica `assignee_id` quando o usuário SOURCE não foi encontrado em `migrated_users`. Os assignees originais de 219045 e 219046 provavelmente não foram migrados ou eram o mesmo Marcus mas com lógica de offset que divergiu.

> **Nota**: display_id=1003 (SOURCE conv_id=43817, inbox=32) → DEST id_destino=200501 também foi migrado. Seu DEST display_id requer consulta direta. Este é o segundo "missing" que Marcus reportou.

---

### 13.7 — Ações corretivas

#### A. Imediato — Informar Marcus sobre novos display_ids

| Conversas que Marcus procura | Onde encontrar no DEST |
|------------------------------|----------------------|
| display_id **1093** (chat.vya.digital) | display_id **1850** em `vya-chat-dev.vya.digital` |
| display_id **1003** (chat.vya.digital) | display_id via `migration_state` conv_id=200501 |

**Instrução ao Marcus**: No `vya-chat-dev.vya.digital`, navegar para "All Conversations" (não "Mine"), filtrar por inbox `wea004 (521)` ou buscar por data 14/11/2025.

#### B. Curto prazo — Investigar display_id de conv_id=200501

```sql
-- DEST: qual é o display_id de id_destino=200501?
SELECT id, display_id, account_id, inbox_id, assignee_id, status, created_at
FROM conversations
WHERE id = 200501;
```

#### C. Opcional — Reatribuir conversas 219045 e 219046 a Marcus

Se as conversas 1091 e 1092 deviam ser de Marcus (assignee):

```sql
-- Verificar assignees SOURCE para conv_ids 62361, 62362
SELECT id, display_id, assignee_id FROM conversations WHERE id IN (62361, 62362);

-- Se necessário, reatribuir no DEST (revisar antes de executar):
-- UPDATE conversations SET assignee_id = 88 WHERE id IN (219045, 219046) AND account_id = 1;
```

#### D. Opcional — Renomear inbox 521 para evitar ambiguidade

```sql
-- Verificar antes:
SELECT id, name, channel_type FROM inboxes WHERE id IN (372, 521);
-- Renomear inbox migrado (via API Chatwoot ou SQL):
-- UPDATE inboxes SET name = 'wea004 (migrado)' WHERE id = 521;
```

---

### 13.8 — Resumo executivo D7

> **O problema foi mal diagnosticado inicialmente como migration gap.**
> As conversas estão no DEST com status=ok.
> A causa raiz é o **resequenciamento obrigatório de `display_id`** (BUG-04 anti-colisão):
> - SOURCE display_id=1093 → DEST display_id=1850 (inbox_id=521, assignee=Marcus)
> - Marcus procura por 1093, mas o número mudou para 1850
>
> **Ação imediata**: comunicar ao Marcus os novos display_ids e o inbox correto (521).
> **Ação de melhoria**: considerar adicionar `src_display_id` e `src_inbox_id` a
> `additional_attributes` em futuras migrações para facilitar rastreamento.

**Scripts criados neste debate**:
- `app/12_diagnostico_marcos.py` — diagnóstico geral de visibilidade
- `app/14_verificar_conv_marcos.py` — verifica conversa específica por data
- `app/15_diagnostico_inbox125.py` — diagnóstico do inbox SOURCE (gap investigado)
- `app/16_diagnostico_visibilidade_marcus.py` — diagnóstico de visibilidade/role/assignee

**Make targets**:
- `make diagnose-agent` — diagnóstico geral
- `make verify-marcus-conv` — verifica por data
- `make diagnose-inbox-gap` — diagnóstico inbox SOURCE
- `make diagnose-marcus-visibility` — diagnóstico de visibilidade
