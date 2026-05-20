# D16 — DEBATE: HTTP 500 nas Conversações Pós-Migração DEV

**Data**: 2026-05-20
**Sessão**: 21
**Ambiente**: DEV — `vya-chat-dev.vya.digital` → banco `chatwoot004_dev1_db`
**Account afetada**: Unimed Guaxupé — `account_id=69` (src=25), `inbox_id=526` (src=100)
**Última migração bem-sucedida**: 2026-05-19 — Sessão 20 Parte 1

---

## 📋 Manifestação do Problema

### Evidência 1 — HTTP 500 autenticado
```
GET https://vya-chat-dev.vya.digital/api/v1/accounts/69/conversations
    ?inbox_id=526&status=all&assignee_type=all&page=1&sort_by=last_activity_at_desc
→ 500 Internal Server Error
```

**Contexto**: Usuário logado no dashboard Chatwoot, selecionando mensagens "não atribuídas".
**Implicação**: A sessão está ativa, a autenticação passou. O 500 ocorre **durante o processamento da query de conversações**.

### Evidência 2 — Erro de auth ao acessar URL diretamente
```json
{"errors":["Você precisa entrar ou se cadastrar antes de continuar."]}
```
**Contexto**: URL copiada e aberta sem cookie de sessão.
**Implicação**: Comportamento esperado — não relacionado ao bug principal. O endpoint é protegido por autenticação Devise.

### Premissas Declaradas pelo Usuário
- Banco de dados mantido intacto para análise
- Aplicação não foi alterada desde a última migração bem-sucedida
- Migração DEV Unimed Guaxupé executada em S20 com sucesso declarado (35.976 registros, FK integrity 100%)

## ✅ Resultado da Fase 1 (executada em 2026-05-20)

### Stack trace confirmado no container web
Arquivo de evidência: `.tmp/d16_stacktrace_20260520_1204.txt`

Erro capturado:
- `ActionView::Template::Error (undefined method [] for nil)`
- Origem: `app/models/attachment.rb:80 in file_metadata`
- Cadeia: `attachment.rb:50` → `message.rb:159` → `_conversation.json.jbuilder:29` → `accounts/conversations/index.json.jbuilder`

### Diagnóstico DB read-only confirmado
Arquivo de evidência: `.tmp/d16_diagnostico_http500_20260520_120230.json`

Achados principais (account=69, inbox=526):
- `conversations=4092`, `messages=22992`, `attachments=1932`
- `missing_active_storage_attachment=1932`
- `missing_active_storage_blob=1932`
- Ou seja: **100% dos anexos migrados não possuem vínculo em `active_storage_attachments`/`active_storage_blobs`**
- `conversation_contact_inbox_mismatch=[]` (sem inconsistência detectada)
- `sequence_health` OK (`seq == max(id)` para conversations/messages/attachments)

### Conclusão da Fase 1
A causa raiz do HTTP 500 está **confirmada** no pipeline de attachments: registros em `attachments` existem, mas os vínculos do ActiveStorage não foram criados para os anexos migrados. Na serialização da conversa, `Attachment#file_metadata` tenta acessar metadado de blob inexistente e lança `undefined method [] for nil`.

---

## 🔍 Análise Técnica — O que o endpoint faz

O endpoint Rails `GET /api/v1/accounts/:account_id/conversations` em Chatwoot:

1. Resolve `Account.find(account_id=69)`
2. Aplica filtros: `inbox_id=526`, `status=all`, `assignee_type=all`
3. Executa includes de associações: `:contact`, `:assignee` (User), `:inbox`, `:labels`, `:contact_inbox`, `:meta`
4. Serializa via `ConversationSerializer` (inclui `last_activity_at`, `contact.thumbnail`, `meta.sender`, etc.)
5. Pagina resultado (page=1)

O 500 pode ocorrer em **qualquer uma** dessas etapas. Com o stack trace e o diagnóstico DB da Fase 1, a falha foi localizada no path de serialização de `attachments`/`active_storage`.

---

## 🧩 Hipóteses de Causa Raiz

### H1 — `authentication_token` inconsistente (PREP-2 não executado) ★★★★☆

**Descrição**: Os tokens de autenticação dos usuários migrados foram copiados do SOURCE (chatwoot_dev1_db) para o DEST (chatwoot004_dev1_db). O Chatwoot usa `authentication_token` como identificador de sessão persistente (via Devise Token Auth ou campo próprio). Colisão ou duplicação deste campo pode causar:
- O Rails serializer retornar dados de usuário errado na serialização de conversações
- O `PermissionFilterService` do Chatwoot falhar ao verificar permissões no account_id=69
- Uma query de JOIN via `authentication_token` retornar múltiplos registros → ActiveRecord raise

**Evidência a favor**: PREP-2 (`UPDATE users SET authentication_token = encode(gen_random_bytes(20), 'hex')`) está marcado como `[ ]` não executado no TODO.md — é `✅ CRÍTICO`.

**Evidência contra**: O usuário consegue logar e a sessão está ativa. O 500 é em operação pós-autenticação.

**Veredicto**: Improvável como causa direta do 500, mas pode causar comportamento errático em serialização de `assignee` nas conversações. Requer investigação do campo para usuários do account 69.

---

### H2 — Dados JSONB inválidos em `additional_attributes`, `meta` ou `custom_attributes` ★★★★★

**Descrição**: As colunas JSONB das tabelas `conversations` e `messages` contêm dados que foram copiados literalmente do SOURCE. O Chatwoot pode ter classes Ruby serializadas nestes campos (via `serialize :meta, HashWithIndifferentAccess` ou `coder: JSON`). Se o formato esperado pelo Chatwoot DEST for diferente, o serializer Rails pode lançar `ActiveRecord::SerializationTypeMismatch` ou `JSON::ParserError`.

**Especificamente**: O campo `meta` em `conversations` no Chatwoot contém informações do remetente (`sender.id`, `sender.name`, etc.) que são calculadas na aplicação. Se esses valores referenciarem IDs do SOURCE (não remapeados), o Chatwoot pode tentar resolver `User.find(id_origem)` e falhar com `ActiveRecord::RecordNotFound`.

**Evidência a favor**:
- O migrador copia `additional_attributes` e `meta` literalmente sem reprocessar IDs internos nesses JSONBs
- O `ConversationsMigrator` inclui masking de `meta` no log — indicando que o campo tem conteúdo sensível que NÃO é transformado
- A query usa `inbox_id=526` (DEST) e `account_id=69` (DEST) corretamente, mas os dados serializados em JSONB podem ter IDs do SOURCE

**Campos suspeitos em `conversations`**:
```
meta → {sender: {id: <SOURCE_contact_id>, ...}}
additional_attributes → {mail_subject: ..., conversation_language: ..., ...}
```

**Campos suspeitos em `messages`**:
```
content_attributes → {item: {title: ..., id: <SOURCE_id>}, ...}
```

**Veredicto**: **HIPÓTESE DE MAIOR RISCO** — requer inspeção direta dos valores JSONB no DEST.

---

### H3 — `contact_inbox_id` NULL ou inconsistente em `conversations` ★★★☆☆

**Descrição**: O campo `contact_inbox_id` em `conversations` foi tratado pelo `ConversationsMigrator` com lógica de fallback (BUG-06 FIX). A validação pós-migração confirmou "0 NULL `contact_inbox_id`". No entanto, mesmo não-NULL, um `contact_inbox_id` pode apontar para um `contact_inboxes` record com `inbox_id` diferente de 526, causando inconsistência na query de filtro Rails.

**Evidência a favor**: O BUG-06 fix usa lookup `(contact_id, inbox_id) → contact_inboxes.id` sobre TODOS os contact_inboxes no DEST, não apenas os do account 69. Isso pode ter atribuído um `contact_inbox_id` de outro account.

**Evidência contra**: A validação confirmou FK integrity 100% clean para contact_inbox_id. Mas FK integrity verifica apenas que o ID existe em `contact_inboxes` — não verifica que pertence ao account correto.

---

### H4 — Conflito de sequência de IDs (INSERT collisions após migração) ★★★☆☆

**Descrição**: Após a migração, as sequences PostgreSQL de `conversations` e `messages` foram resetadas via `setval(COALESCE(MAX(id),1))`. Se a aplicação Chatwoot criou novas conversações (mesmo uma) após a migração, o ID gerado pela sequence pode colidir com IDs já migrados que usam offset.

**Fórmula do offset**: `novo_id = id_origem + MAX(id_dest_pre_migration)`

Se a sequence foi setada para `MAX(id) atual` (correto), não deve haver colisão. Mas se o reset foi feito ANTES dos INSERTs de migração (ou usando valor desatualizado), pode haver colisão.

**Evidência a favor**: O pipeline faz `setval` como etapa de cleanup. A ordem exata precisa ser verificada em `migrar.py`.

**Veredicto**: Requer verificação da ordem de `setval` vs. último INSERT no pipeline.

---

### H5 — `assignee_id` em `conversations` apontando para usuário não-existente ★★★☆☆

**Descrição**: O `ConversationsMigrator` remapeia `assignee_id` via `migrated_users`, mas NULLa se não encontrado. Se alguma conversa tem `assignee_id` que foi NULLado mas o Chatwoot tenta serializar como `assignee.id` obrigatório, pode falhar.

**No entanto**: O Chatwoot trata `assignee` como opcional (nullable em conversações). Improvável que seja 500, mais provável NULL silencioso.

---

### H6 — Tabela `migration_state` interferindo em queries ★★☆☆☆

**Descrição**: A tabela `migration_state` foi criada no DEST durante a migração. Se o Chatwoot Rails tenta resolver alguma model com schema autodiscovery e encontra tabelas inesperadas, pode apresentar erros.

**Veredicto**: Muito improvável. Rails não faz autodiscovery de novas tabelas em runtime.

---

### H7 — Sessões Devise stale (PREP-3 não executado) ★★☆☆☆

**Descrição**: A tabela `sessions` não foi truncada (PREP-3 pendente). Sessões antigas do SOURCE importadas junto com users migrados podem causar conflito com a sessão atual no browser. O Rails pode estar carregando dados de uma sessão do SOURCE (que referencia account_id/inbox_id do SOURCE).

**Evidência a favor**: PREP-3 (`TRUNCATE TABLE sessions`) está como `[ ]` não executado.

**Veredicto**: Possível contributor. A sessão do browser usa cookie, mas se houver colisão de session token no banco, pode causar comportamento errático.

---

## 🎯 Ranking de Hipóteses por Probabilidade

| Rank | Hipótese | Probabilidade | Impacto | Diagnóstico |
|------|----------|--------------|---------|-------------|
| 1 | **H2 — JSONB `meta`/`additional_attributes` com IDs do SOURCE** | Alta | HTTP 500 direto | Inspecionar JSONB no DEST |
| 2 | **H3 — `contact_inbox_id` inconsistente cross-account** | Média-Alta | 500 em includes | Query de verificação |
| 3 | **H4 — Sequence collision pós-migração** | Média | 500 em INSERT, não GET | `SELECT MAX(id), nextval()` |
| 4 | **H1 — `authentication_token` duplicado** | Média | Comportamento errático | `SELECT authentication_token, COUNT(*) FROM users GROUP BY authentication_token HAVING COUNT(*) > 1` |
| 5 | **H5 — `assignee_id` NULL em conversações** | Baixa | Silent NULL | `SELECT COUNT(*) FROM conversations WHERE assignee_id IS NOT NULL AND account_id=69` |
| 6 | **H7 — Sessions Devise stale** | Baixa | Auth erratic | `SELECT COUNT(*) FROM sessions` |
| 7 | **H6 — `migration_state` interferindo** | Muito Baixa | — | — |

---

## 🔎 Diagnóstico Necessário — Sem Modificar o Banco

> **Regra**: banco preservado. Todos os diagnósticos são read-only (SELECT, EXPLAIN).

### Diagnóstico 1 — Stack Trace do Rails (PRIORITÁRIO)

**Objetivo**: Identificar a linha exata do erro Rails.
**Ação**: Inspecionar logs do container Chatwoot em `vya-chat-dev.vya.digital`.

```bash
docker logs <container_chatwoot> 2>&1 | grep -A 30 "500 Internal Server Error"
# OU via SSH no servidor:
tail -n 200 /app/log/production.log | grep -A 30 "ActionController::RoutingError\|NoMethodError\|ActiveRecord"
```

**Resultado esperado**: Stack trace com classe + linha onde ocorreu o erro.

---

### Diagnóstico 2 — Inspecionar JSONB em `conversations` (H2)

**Query 1 — Verificar campo `meta`**:
```sql
SELECT id, display_id,
       meta,
       additional_attributes,
       (meta->>'sender')::jsonb AS sender_meta
FROM public.conversations
WHERE account_id = 69
  AND inbox_id = 526
LIMIT 20;
```

**Query 2 — Detectar IDs do SOURCE em `meta.sender.id`**:
```sql
SELECT c.id AS conv_dest_id,
       c.meta->'sender'->>'id' AS meta_sender_id,
       c.contact_id AS contact_dest_id,
       c.meta->'sender'->>'type' AS meta_sender_type
FROM public.conversations c
WHERE c.account_id = 69
  AND c.inbox_id = 526
  AND c.meta IS NOT NULL
  AND c.meta->'sender' IS NOT NULL
LIMIT 50;
```

**O que verificar**: O `meta.sender.id` deve referenciar o contact_id do DEST (≥ offset), não o do SOURCE (id original).

---

### Diagnóstico 3 — Verificar `contact_inbox_id` cross-account (H3)

```sql
SELECT c.id AS conv_id,
       c.contact_inbox_id,
       ci.contact_id AS ci_contact_id,
       ci.inbox_id AS ci_inbox_id,
       ci.account_id AS ci_account_id
FROM public.conversations c
JOIN public.contact_inboxes ci ON ci.id = c.contact_inbox_id
WHERE c.account_id = 69
  AND c.inbox_id = 526
  AND ci.inbox_id != 526  -- inconsistência!
LIMIT 20;
```

**O que verificar**: Qualquer resultado indica `contact_inbox_id` atribuído a um contact_inbox de outro inbox/account.

---

### Diagnóstico 4 — Verificar sequence vs. MAX(id) (H4)

```sql
-- Sequences atuais
SELECT schemaname, sequencename,
       last_value,
       increment_by
FROM pg_sequences
WHERE sequencename IN ('conversations_id_seq', 'messages_id_seq', 'contacts_id_seq');

-- MAX ids atuais
SELECT
    (SELECT MAX(id) FROM conversations WHERE account_id = 69) AS max_conv_id,
    (SELECT MAX(id) FROM messages WHERE account_id = 69)      AS max_msg_id,
    (SELECT MAX(id) FROM contacts WHERE account_id = 69)      AS max_contact_id;
```

**O que verificar**: `last_value` da sequence deve ser ≥ `MAX(id)` da tabela. Se `last_value` < `MAX(id)`, há risco de colisão.

---

### Diagnóstico 5 — Verificar `authentication_token` duplicado (H1)

```sql
SELECT authentication_token, COUNT(*) AS cnt
FROM public.users
WHERE id IN (
    SELECT DISTINCT assignee_id
    FROM conversations
    WHERE account_id = 69 AND assignee_id IS NOT NULL
)
GROUP BY authentication_token
HAVING COUNT(*) > 1;
```

---

### Diagnóstico 6 — Verificar integridade completa de `messages` para inbox 526

```sql
SELECT
    COUNT(*) AS total_messages,
    SUM(CASE WHEN sender_id IS NULL AND sender_type = 'Contact' THEN 1 ELSE 0 END) AS null_contact_senders,
    SUM(CASE WHEN sender_id IS NULL AND sender_type = 'User' THEN 1 ELSE 0 END) AS null_user_senders,
    SUM(CASE WHEN content_attributes IS NOT NULL THEN 1 ELSE 0 END) AS with_content_attributes,
    SUM(CASE WHEN content_type NOT IN ('text', 'input_select', 'cards', 'form', 'article', 'incoming_email', 'email', 'image', 'audio', 'video', 'file', 'location', 'sticker', 'activity', 'template_button_reply', 'input_csat') THEN 1 ELSE 0 END) AS unknown_content_type
FROM public.messages m
JOIN public.conversations c ON c.id = m.conversation_id
WHERE c.account_id = 69 AND c.inbox_id = 526;
```

---

### Diagnóstico 7 — Reproduzir a query Rails manualmente

```sql
-- Simular a query base do ConversationsController
EXPLAIN ANALYZE
SELECT c.*, co.id AS contact_id_check, ci.id AS ci_check
FROM conversations c
LEFT JOIN contacts co ON co.id = c.contact_id
LEFT JOIN contact_inboxes ci ON ci.id = c.contact_inbox_id
LEFT JOIN inboxes i ON i.id = c.inbox_id
LEFT JOIN users u ON u.id = c.assignee_id
WHERE c.account_id = 69
  AND c.inbox_id = 526
ORDER BY c.last_activity_at DESC
LIMIT 25;
```

**O que verificar**: Se o `EXPLAIN ANALYZE` retornar erro ou resultado inconsistente.

---

## 📝 Conclusão Preliminar

Com base na análise dos migrators e dos dados disponíveis, a **H2 (dados JSONB com IDs do SOURCE)** é a hipótese de maior risco porque:

1. O `ConversationsMigrator` copia `meta` e `additional_attributes` literalmente, sem reprocessar IDs internos em campos JSONB
2. O campo `meta` do Chatwoot contém `sender.id` — um contact_id — que referencia IDs do SOURCE
3. O Chatwoot Rails pode tentar resolver `Contact.find(meta['sender']['id'])` durante serialização
4. Se `id_source` < offset (e portanto não existe no DEST), Rails lança `ActiveRecord::RecordNotFound` → 500

**Próximo passo obrigatório**: Obter stack trace do Rails container para confirmar qual hipótese está correta.

---

*Gerado em 2026-05-20 | Sessão 21 | Debate D16*
