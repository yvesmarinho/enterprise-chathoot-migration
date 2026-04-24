# D10 — Debate: SQL Legado vs. Python Atual — Análise Profunda das Transformações

**Data**: 2026-04-24
**Status**: CONCLUÍDO — Veredito emitido
**Contexto**: Revisão da análise COMPARATIVO-LEGADO-VS-ATUAL.md com foco nas transformações reais de campo
**Participantes**:
- 🗄️ **DBA Expert** — perspectiva de banco de dados e integridade de dados
- 🐍 **Python Expert** — perspectiva de engenharia de software
- 🟢 **Chatwoot Expert** — perspectiva de domínio Chatwoot
- 📐 **Moderador** — compilação e síntese

---

## 0. Contexto do Debate

A análise anterior (`COMPARATIVO-LEGADO-VS-ATUAL.md`) descrevia o comparativo em termos de "o que é migrado" e "qual a arquitetura", mas não analisou **as transformações de campo concretas** que o código SQL legado executava.

Este debate parte da leitura literal do código PL/pgSQL e compara, campo a campo, o que o SQL fazia com o que o Python atual faz — e por quê cada diferença existe ou deve existir.

### Fontes Primárias

| Arquivo | Conteúdo |
|---------|----------|
| `docs/sql_code_old/scriptImportacaoTbChatChatWoot.sql` | Script original TBChat→Chatwoot (Dr. Thiago Bianco) |
| `docs/sql_code_old/scriptImportacaoChatToSynchat.sql` | Script revisado TBChat→Chatwoot (Sol Copernico) |
| `src/migrators/contacts_migrator.py` | Migrador Python — Contacts |
| `src/migrators/conversations_migrator.py` | Migrador Python — Conversations |
| `src/migrators/messages_migrator.py` | Migrador Python — Messages |
| `src/migrators/inboxes_migrator.py` | Migrador Python — Inboxes + BUG-05 fix |

### Contextos de Migração (DIFERENTES)

```
LEGADO SQL:
  Sistema TBChat (schema proprietário)
    → tabelas staging (contacts_tbchat, conversations_tbchat, messages_tbchat)
    → Chatwoot nativo (chatwoot_tb_db)

PYTHON ATUAL:
  Chatwoot SOURCE (chatwoot_dev1_db / chat.vya.digital)
    → Chatwoot DEST (chatwoot004_dev1_db / vya-chat-dev.vya.digital)
```

**Conclusão antecipada**: Os contextos são fundamentalmente diferentes. As transformações SQL eram necessárias para o schema TBChat heterogêneo. O Python atual opera em schema Chatwoot→Chatwoot (homogêneo), tornando a maioria das transformações SQL obsoletas — mas com exceções importantes identificadas neste debate.

---

## 1. Análise das Transformações SQL — Campo a Campo

### 1.1 Tabela: `contacts`

#### Schema TBChat de origem (staging `contacts_tbchat`)

O sistema TBChat usava nomes de campos completamente diferentes do Chatwoot:

| Campo TBChat | Tipo TBChat | Campo Chatwoot DEST | Transformação SQL |
|---|---|---|---|
| `name_contact` | VARCHAR | `name` | `TRIM(name_contact)` |
| `phone` | VARCHAR (número puro) | `phone_number` | Script1: `CONCAT('+', phone)` / Script2: `TRIM(phone)` |
| `email` | VARCHAR | `email` | Script1: `NULL` hardcoded / Script2: `TRIM(email)` |
| `data_reg` | VARCHAR `'YYYY-MM-DD HH24:MI:SS'` | `created_at`, `updated_at` | `TO_TIMESTAMP(data_reg, 'YYYY-MM-DD HH24:MI:SS')` |
| `cpf` | VARCHAR | `custom_attributes.cpf` | `jsonb_build_object('cpf', cpf, 'external_id', id)` |
| `id` (TBChat ID) | INT | `custom_attributes.external_id` | id como string no JSON |
| `empresa` | VARCHAR | `additional_attributes.company_name` | Script1: `jsonb_build_object('company_name', empresa)` / Script2: verbatim |
| `last_activity_at` | VARCHAR | `last_activity_at` | Script1: `NULL` / Script2: `TO_TIMESTAMP(last_activity_at,...)` |
| N/A | — | `account_id` | Lookup por `name = 'Dr. Thiago Bianco'` ou `'Sol Copernico'` |

**Inconsistência crítica entre scripts**:

```sql
-- Script 1 (TbChatChatWoot): CONCAT — adiciona prefixo E.164
phone_number = CONCAT('+', var_contact_row.phone)

-- Script 2 (ChatToSynchat): TRIM — preserva sem prefixo
phone_number = TRIM(var_contact_row.phone)
```

Isso significa que parte dos contatos no SOURCE atual pode ter `phone_number` sem prefixo `+`, dependendo de qual script foi executado primeiro.

#### O que o Python atual faz para contacts

O SOURCE é Chatwoot nativo — campo `phone_number` já é E.164 (ou não, dependendo da migração anterior). O Python:

1. Copia verbatim todos os campos do SOURCE (sem transformação)
2. Dedup por `(account_id, phone_number)` OR `(account_id, email)` OR `(account_id, identifier)` com `.strip().lower()`
3. IDRemapper para `account_id`

---

### 1.2 Tabela: `conversations`

#### Schema TBChat de origem (staging `conversations_tbchat`)

| Campo TBChat | Tipo TBChat | Campo Chatwoot DEST | Transformação SQL |
|---|---|---|---|
| `data_ini` (nullable) | timestamptz | `created_at` | `CASE WHEN NULL THEN TO_TIMESTAMP(data_reg,...) ELSE data_ini END` |
| `data_ini` (nullable) | timestamptz | `updated_at` | mesma lógica |
| `data_ini` (nullable) | timestamptz | `contact_last_seen_at` | mesma lógica |
| `data_ini` (nullable) | timestamptz | `agent_last_seen_at` | mesma lógica |
| `last_data_update` (nullable) | VARCHAR | `last_activity_at` | `CASE WHEN NULL THEN TO_TIMESTAMP(data_reg,...) ELSE TO_TIMESTAMP(last_data_update,...)` |
| `id_empresa` | VARCHAR `'2'`\|`'3'` | `inbox_id` | `IF '2' THEN 1 ELSE 2` (hardcoded) |
| `id_contact` | INT (TBChat ID) | `contact_id` | Lookup: `contacts WHERE custom_attributes->>'external_id' = id_contact` |
| `id` (TBChat ID) | INT | `custom_attributes.external_id` | rastreabilidade |
| N/A | — | `status` | **`1` (resolved) — hardcoded** |
| N/A | — | `assignee_id` | `SELECT id FROM users WHERE uid = 'admin@vya.digital'` (hardcoded) |
| N/A | — | `display_id` | `SELECT MAX(display_id)+1` — **race condition** |
| N/A | — | `account_id` | `1` (hardcoded) |
| N/A | — | `additional_attributes` | `'{}'::jsonb` (vazio) |
| N/A | — | `contact_inbox_id` | INSERT contact_inboxes RETURNING id (sem dedup) |

**Padrão de fallback de datas** (usado em 5 campos):

```sql
CASE
  WHEN var_conversations_row.data_ini IS NULL
  THEN TO_TIMESTAMP(var_conversations_row.data_reg, 'YYYY-MM-DD HH24:MI:SS')
  ELSE var_conversations_row.data_ini
END
```

Este padrão existia porque `data_ini` (data de início formal da conversa) podia ser NULL no TBChat — conversas iniciadas sem registro formal usavam `data_reg` (data de registro) como fallback.

#### O que o Python atual faz para conversations

```python
# ConversationsMigrator — sem fallback de datas (SOURCE já tem timestamps corretos)
new_row = dict(row)  # copia verbatim
new_row["id"] = self.id_remapper.remap(id_origin, "conversations")
new_row["account_id"] = self.id_remapper.remap(account_id_origin, "accounts")
new_row["inbox_id"] = self.id_remapper.remap(inbox_id_origin, "inboxes")
new_row["uuid"] = str(uuid.uuid4())  # sempre regenerado

# display_id pré-calculado ANTES do loop — sem race condition
_display_id_counters[dest_acct_id] += 1
new_row["display_id"] = _display_id_counters[dest_acct_id]
```

---

### 1.3 Tabela: `messages`

#### Transformações SQL mais críticas

Esta é a tabela onde o SQL legado realizou as transformações mais complexas — e também onde existe o maior risco de dados degradados no SOURCE atual:

**Transformação de `content` para attachments**:

```sql
content = CASE
  WHEN message_type = 'text' THEN "message"
  ELSE CONCAT(
    INITCAP(message_type),  -- 'Image', 'Document', 'Video', etc.
    ': https://tbchatuploads.s3.sa-east-1.amazonaws.com/',
    REPLACE(file_url, 'https://tbchatuploads.s3.sa-east-1.amazonaws.com/', '')
  )
END
```

Resultado: mensagens com `content_type = 'image'` no TBChat foram gravadas no Chatwoot SOURCE com content `"Image: https://tbchatuploads.s3.sa-east-1.amazonaws.com/arquivo.jpg"` — **sem registro na tabela `attachments`**.

**Transformação de `message_type`** (string → integer):

```sql
-- TBChat: type_in_message VARCHAR = 'RECEIVED' | 'SENT'
-- Chatwoot: message_type INT = 0 (incoming) | 1 (outgoing)
message_type = CASE WHEN type_in_message = 'RECEIVED' THEN 0 ELSE 1 END
```

**Transformação de `sender_type` e `sender_id`**:

```sql
-- Sender: RECEIVED → Contact lookup, SENT → hardcoded admin
sender_type = CASE WHEN type_in_message = 'RECEIVED' THEN 'Contact' ELSE 'User' END
sender_id = CASE
  WHEN type_in_message = 'RECEIVED'
  THEN (SELECT id FROM contacts WHERE custom_attributes->>'external_id' = CAST(id_contact AS text))
  ELSE (SELECT id FROM users WHERE uid = 'admin@vya.digital')
END
```

**Bug de tipo (`private`):**

```sql
'0' as "private"  -- STRING, não boolean
                  -- PostgreSQL faz cast implícito '0'::boolean = false
                  -- mas é tecnicamente incorreto
```

**Campos de rastreabilidade:**

```sql
additional_attributes = jsonb_build_object('external_id', id)
processed_message_content = [mesmo que content]
```

#### O que o Python atual faz para messages

```python
# MessagesMigrator — sem transformação de conteúdo
new_row = dict(row)  # copia verbatim: content, message_type, sender_type, private
new_row["id"] = self.id_remapper.remap(id_origin, "messages")
new_row["account_id"] = self.id_remapper.remap(account_id_origin, "accounts")
new_row["conversation_id"] = self.id_remapper.remap(conv_id_origin, "conversations")
# sender_id: NULL-out se user não migrado
```

---

## 2. Debate — Rodada 1: Posições Iniciais

---

### 🗄️ DBA Expert — Posição

**O Python é superior para Chatwoot→Chatwoot. O SQL legado era correto para TBChat→Chatwoot.**

---

#### ARGUMENTO D-1 — Schema heterogêneo: cada transformação SQL tinha razão de ser

Cada transformação SQL existia porque o campo de origem era semanticamente diferente:

```sql
-- TBChat.phone = "5511999..." (número puro)
-- Chatwoot exige E.164 "+5511999..."
phone_number = CONCAT('+', var_contact_row.phone)   -- correto para TBChat

-- TBChat.data_reg = VARCHAR "2024-03-01 14:30:00"
-- PostgreSQL timestamptz requer cast explícito
created_at = TO_TIMESTAMP(var_contact_row.data_reg, 'YYYY-MM-DD HH24:MI:SS')

-- TBChat.type_in_message = 'RECEIVED'|'SENT' (string)
-- Chatwoot.message_type = 0|1 (integer)
message_type = CASE WHEN type_in_message = 'RECEIVED' THEN 0 ELSE 1 END
```

No contexto atual, o SOURCE Chatwoot já tem `phone_number` em E.164, `created_at` como `timestamptz`, `message_type` como `int`. Aplicar `CONCAT('+', phone)` no SOURCE quebraria os dados (duplo prefixo: `++5511...`). **O Python está correto em copiar verbatim.**

---

#### ARGUMENTO D-2 — Race condition em `display_id`: bug funcional no SQL

```sql
-- SQL legado: executa dentro do loop, sem lock de concorrência
SELECT MAX(display_id)+1 INTO var_display_id FROM public.conversations;
-- Duas execuções lendo o mesmo MAX → colisão de UNIQUE CONSTRAINT
```

```python
# Python: pré-calcula ANTES do loop, incrementa in-memory
_display_id_counters[dest_acct_id] = COALESCE(MAX(display_id), 0)
# Depois, por row:
new_row["display_id"] = _display_id_counters[dest_acct_id] + 1
```

O SQL funcionou em produção apenas por ser single-session serial. Em qualquer cenário com paralelismo ou re-run parcial, colidiria.

---

#### ARGUMENTO D-3 — Assertions SQL recomendadas pré-migração

O SQL legado nos ensina o que verificar antes de rodar o Python:

```sql
-- 1. Verificar created_at NULL (sem fallback no Python)
SELECT 'conversations' AS entity, COUNT(*) AS nulls
FROM conversations WHERE created_at IS NULL
UNION ALL
SELECT 'messages', COUNT(*) FROM messages WHERE created_at IS NULL
UNION ALL
SELECT 'contacts', COUNT(*) FROM contacts WHERE created_at IS NULL;

-- 2. Duplicatas de contact_inboxes (falha de dedup silenciosa)
SELECT contact_id, inbox_id, COUNT(*) AS dup_count
FROM contact_inboxes
GROUP BY contact_id, inbox_id
HAVING COUNT(*) > 1;

-- 3. Conversas "cegas" pós-migração
SELECT COUNT(*) AS blind_conversations
FROM conversations
WHERE contact_inbox_id IS NULL;

-- 4. Phone sem E.164 (risco de dedup falho)
SELECT COUNT(*) FROM contacts
WHERE phone_number IS NOT NULL
  AND phone_number NOT LIKE '+%';
```

---

#### ARGUMENTO D-4 — O que o SQL legado preservava que Python deve validar

```sql
-- custom_attributes.cpf — populado de TBChat
var_custom_attributes := jsonb_build_object('cpf', cpf, 'external_id', id);
```

Se esse dado chegou ao SOURCE Chatwoot, o Python copia verbatim — correto. Mas requer verificação:

```sql
SELECT COUNT(*) FROM contacts
WHERE custom_attributes IS NULL
   OR NOT (custom_attributes ? 'cpf');
-- Se > 0 para contatos que deveriam ter CPF: problema de dados herdado
```

---

#### VEREDICTO DBA

**Python atual: SUPERIOR** para contexto Chatwoot→Chatwoot.

| Critério | SQL Legado | Python Atual |
|---|---|---|
| Race condition display_id | ❌ Ativo | ✅ Corrigido |
| inbox_id hardcoded | ❌ Acoplamento rígido | ✅ IDRemapper |
| status hardcoded | ❌ Perde estado real | ⚠️ Verbatim (decisão pendente) |
| private string | ❌ '0' em vez de false | ✅ Boolean nativo |
| contact_inboxes dedup | ❌ Duplicatas | ✅ Triplo fallback |
| Dedup contacts | Phone only | Phone OR email OR identifier |
| Auditabilidade | RAISE NOTICE (volátil) | migration_state table |

---

### 🐍 Python Expert — Posição

**Python vence por diferença técnica substancial. O SQL legado era a solução correta para o problema errado.**

---

#### ARGUMENTO P-1 — Testabilidade: pytest vs RAISE NOTICE

O SQL depende de `RAISE NOTICE` para observabilidade — não testável, não assertável, não automatizável. Cada "teste" exige execução real contra o banco.

O Python tem:
```python
# test/unit/test_contacts_migrator.py
def test_dedup_by_phone_normalised(mock_engines, mock_state_repo):
    rows = [{"id": 1, "account_id": 1, "phone_number": "+55 11 9 1234-5678", ...}]
    # Injeta rows via mock — zero IO real
```

`BaseMigrator._run_batches` é puro: recebe `remap_fn: Callable[[dict], dict | None]` — testável sem nenhuma conexão PostgreSQL real.

---

#### ARGUMENTO P-2 — Idempotência robusta

SQL usa rastreabilidade por conteúdo (frágil):
```sql
IF NOT EXISTS (SELECT 1 FROM conversations
  WHERE custom_attributes->>'external_id' = CAST(id AS text))
```

Se `custom_attributes` for sobrescrito por outro processo, o dedup quebra silenciosamente → duplicatas.

Python usa controle externo em tabela dedicada:
```python
already_migrated = self.state_repo.get_migrated_ids(conn, "conversations")
```

`migration_state` é append-only, escrita em `BEGIN/COMMIT` por batch. Re-run seguro por design.

---

#### ARGUMENTO P-3 — Performance: 500x throughput

SQL: `INSERT` + `COMMIT` por conversa → 42.329 commits para 42.329 conversas.
Python: batch de 500 → ~85 commits para as mesmas conversas. Em PostgreSQL, `COMMIT` é o custo dominante de disco.

Para 310.155 mensagens: SQL ≈ 310.155 commits / Python ≈ 621 commits.

---

#### ARGUMENTO P-4 — Type safety: `private = '0'` é bug confirmado

```sql
-- SQL legado (scriptImportacaoChatToSynchat.sql linha ~224):
'0' as "private"
-- Schema Chatwoot: private boolean NOT NULL DEFAULT false
-- PostgreSQL aceita '0'::text como cast implícito para false
-- mas é comportamento não-documentado (driver-dependent)
```

Python copia o campo `private` (bool nativo do SOURCE via psycopg2) → sem ambiguidade.

---

#### MAPEAMENTO DE TRANSFORMAÇÕES SQL — Status no contexto atual

| Transformação SQL | Status no Python atual | Justificativa |
|---|---|---|
| `CONCAT('+', phone)` → E.164 | **OBSOLETA** | SOURCE Chatwoot já tem phone_number E.164 |
| `email = NULL` hardcoded | **OBSOLETA** | TbChatChatWoot não tinha email; SOURCE tem |
| `TO_TIMESTAMP(data_reg,...)` | **OBSOLETA** | Campos data_reg/data_ini não existem em SOURCE Chatwoot |
| fallback `data_ini IS NULL → data_reg` | **OBSOLETA** | SOURCE tem timestamps já corretos |
| `id_empresa → inbox_id` mapping | **OBSOLETA** | SOURCE tem inbox_id real |
| `type_in_message='RECEIVED' → 0` | **OBSOLETA** | SOURCE message_type já é int nativo |
| `sender_type` de `type_in_message` | **OBSOLETA** | SOURCE tem sender_type nativo |
| S3 URL embedding em content | **OBSOLETA** | SOURCE tem tabela attachments nativa |
| `custom_attributes->>'external_id'` como FK | **OBSOLETA** | migration_state substitui |
| Dedup por `phone_number` (TRIM) | **JÁ IMPLEMENTADA** | ContactsMigrator linha ~97: `str(phone).strip().lower()` |
| Dedup por `email` | **JÁ IMPLEMENTADA** | ContactsMigrator: `str(email).strip().lower()` |
| `gen_random_uuid()` para `source_id` | **JÁ IMPLEMENTADA** | ContactInboxesMigrator: `uuid.uuid4()` |
| `uuid` gerado novo para conversations | **JÁ IMPLEMENTADA** | ConversationsMigrator: `str(uuid.uuid4())` |
| Skip se já existe | **JÁ IMPLEMENTADA (melhorada)** | migration_state idempotência |
| contact_inboxes sem dedup | **CORRIGIDA (era BUG)** | ContactInboxesMigrator separado com dedup |

---

#### GAP-REAL identificado

**GAP-4 — `status` hardcoded no SQL vs. verbatim no Python:**

```sql
-- SQL legado: todas resolvidas
1 as "status"   -- resolved (decisão deliberada de negócio)
```

```python
# Python atual: preserva estado real
new_row["status"] = row["status"]  -- pode ser open/pending/snoozed
```

O SQL hardcodava `resolved` como decisão deliberada de não contaminar filas de agentes com conversas históricas. O Python preserva o estado real — correto tecnicamente, mas requer confirmação de negócio.

**Ação necessária**: confirmar com o cliente se conversas abertas no SOURCE devem:
- (a) Aparecer na fila dos agentes no DEST (preservar `open`)
- (b) Ser arquivadas como resolvidas (forçar `resolved`)

---

#### VEREDICTO PYTHON

Python: SUPERIOR. O único item pendente é GAP-4 (`status`) — decisão de negócio, não técnica.

---

### 🟢 Chatwoot Expert — Posição

**Domínio Chatwoot confirma Python superior. Identifica 3 ações críticas para execução hoje.**

---

#### ARGUMENTO C-1 — `contact_inbox_id = NULL` vs. ID inválido: diferença crítica

Existe distinção fundamental que o debate anterior não capturou:

- **`contact_inbox_id = NULL`**: Conversa aparece no dashboard de administrators (conta rows por `account_id` sem JOIN). Perde visibilidade na **aba Conversations do contato** (`GET /contacts/:id/conversations`). Operacionalmente aceitável.

- **`contact_inbox_id` com ID inválido (bug pré-BUG-06)**: Causa HTTP 404 em `GET /conversations/:display_id` porque Rails tenta `@conversation.contact_inbox → nil → NoMethodError` em alguns paths do serializer. Confirmado em D8: 309/309 conversas afetadas.

O triple-fallback do BUG-06 (remap → pair lookup → NULL) está **tecnicamente correto**. NULL é aceitável; ID errado é catastrófico.

---

#### ARGUMENTO C-2 — `conversations.status = open` — risco operacional real

Valores válidos em Chatwoot v3.x: `0=open | 1=resolved | 2=pending | 3=snoozed`.

Migrar conversas como `open` (verbatim) tem consequência operacional direta: todas as conversas abertas do SOURCE aparecerão nas filas dos agentes no DEST imediatamente após a migração. Se o SOURCE tinha centenas de conversas `open` historicamente abandonadas, agentes verão uma inundação.

O SQL hardcodava `status=1 (resolved)` — **era uma decisão deliberada de negócio**, não um bug. O Python Expert (GAP-4) identificou isso corretamente. A solução deve ser definida antes da execução.

---

#### ARGUMENTO C-3 — Por que inboxes sem channel record ficam invisíveis (BUG-05)

A causa raiz está no polymorphic association do Rails:

```ruby
# app/models/inbox.rb
belongs_to :channel, polymorphic: true, dependent: :destroy
```

Quando `includes(:channel)` carrega um inbox onde `channel_id` não referencia nenhum registro:
- `inbox.channel` retorna `nil`
- Jbuilder serializa silenciosamente `nil.website_token` → omite o inbox do JSON
- **Não é exceção — é silêncio**, o que tornava o diagnóstico difícil

O BUG-05 fix (`_migrate_channels()` com regeneração de tokens) é **suficiente para visibilidade**. Ressalva: canais Facebook/Telegram copiados com credenciais do SOURCE podem conflitar com webhooks se SOURCE e DEST rodarem simultaneamente.

---

#### ARGUMENTO C-4 — Messages com S3 URLs embutidas no `content`

O pipeline de criação do SOURCE foi:
```
TBChat → SQL Legado → chatwoot_dev1_db (SOURCE) → Python → chatwoot004_dev1_db (DEST)
```

Se o SQL legado foi usado para criar o SOURCE, podem existir mensagens onde:
- `content_type = 0` (text)
- `content = "Image: https://tbchatuploads.s3.sa-east-1.amazonaws.com/..."`
- **Nenhum registro na tabela `attachments`**

O Python copia verbatim — correto. O Chatwoot renderiza como texto puro com URL raw, não como imagem incorporada. É degradação de UX, não invisibilidade.

**Verificação recomendada**:
```sql
SELECT COUNT(*) FROM messages
WHERE content ILIKE '%tbchatuploads.s3%' OR content ILIKE '%Image:%';
```

---

#### ARGUMENTO C-5 — Visibilidade para agentes: cadeia completa

Para um agente ver uma conversa, o Chatwoot verifica esta cadeia:

```
1. account_users (account_id, user_id) → usuário existe na conta?
2. inbox_members (inbox_id, user_id)   → usuário é membro do inbox?
   OU conversations.assignee_id = user_id
   OU team_members (team_id, user_id) + conversations.team_id
3. inboxes.channel_id                 → registro de canal existe? (BUG-05)
4. conversations.contact_inbox_id     → remapeado corretamente? (BUG-06)
```

O `PermissionFilterService` filtra por:
```ruby
conversations.where(inbox: user.inboxes.where(account_id: account.id))
# user.inboxes = has_many :inboxes, through: :inbox_members
```

Para agents (não administrators): ausência de qualquer `inbox_members` record para os inboxes migrados torna **todas** as conversas desses inboxes invisíveis — independentemente de BUG-05 e BUG-06 estarem corrigidos.

---

#### AÇÕES URGENTES (Chatwoot Expert)

**Ação C-U1 — CRÍTICA: Verificar `inbox_members` com remapeamento de IDs**

```python
# app/13_migrar_inbox_members.py DEVE fazer:
src_inbox_id = row["inbox_id"]
dest_inbox_id = id_remapper.remap(src_inbox_id, "inboxes")  # ← obrigatório
src_user_id = row["user_id"]
dest_user_id = id_remapper.remap(src_user_id, "users")      # ← obrigatório
```

Se o script usa IDs verbatim do SOURCE, todos os agentes ficam cegos para conversas migradas — independentemente de qualquer outro fix.

**Ação C-U2 — CRÍTICA: Decidir `conversations.status` ANTES de migrar**

Consultar o cliente agora:
> "Conversas abertas em chat.vya.digital devem aparecer na fila dos agentes no novo sistema, ou ser arquivadas como resolvidas?"

Se não houver resposta: **migrar como `resolved` é mais seguro** e consistente com o legado. Conversas abertas específicas podem ser reabertas manualmente. O inverso é trabalhoso.

**Ação C-U3 — CRÍTICA: Assertion `phone_number` E.164 antes do pipeline**

```sql
-- SOURCE: quantos contacts têm phone sem + (risco de dedup falho)?
SELECT COUNT(*) FROM contacts
WHERE phone_number IS NOT NULL
  AND phone_number NOT LIKE '+%'
  AND account_id = 1;
```

Se > 0: adicionar normalização no `ContactsMigrator`:
```python
phone = row.get("phone_number")
if phone and not str(phone).startswith("+"):
    self.logger.warning(
        "ContactsMigrator: id=%d — phone_number='%s' não é E.164 — não será corrigido automaticamente",
        row["id"], phone
    )
```

---

## 3. Debate — Rodada 2: Contraposições

---

### 🗄️ DBA Expert responde Python Expert

**Sobre GAP-4 (`status`)**: Concordo que é decisão de negócio, não técnica. Mas adiciono: o SQL legado tinha essa decisão **explícita no código** (comentada como "all resolved"). O Python atual não documenta essa decisão em lugar algum. Recomendo adicionar uma constante configurável:

```python
# src/migrators/conversations_migrator.py
# Configuração de comportamento de status na migração
FORCE_RESOLVED_ON_MIGRATION = True  # set via env var or config
# ...
if FORCE_RESOLVED_ON_MIGRATION:
    new_row["status"] = 1  # resolved
```

**Sobre Dedup de phone_number**: O DBA confirma que dois contatos com `"+5511..."` no DEST e `"5511..."` no SOURCE não serão deduplicados pelo Python atual. O lookup usa `.strip().lower()` mas não normaliza o formato E.164. Isso é uma lacuna real.

---

### 🐍 Python Expert responde DBA Expert

**Sobre FORCE_RESOLVED_ON_MIGRATION**: Concordo com a abordagem de configuração explícita. Adiciono que deve ser `False` por default para preservar dados reais — o cliente decide, não o código.

**Sobre phone_number sem E.164**: Confirmo o gap. Mas não deve ser corrigido automaticamente (pode haver `"+0"` ou casos edge). O correto é: logar warning, não corrigir, e entregar relatório ao cliente antes da migração.

---

### 🟢 Chatwoot Expert responde ambos

**Sobre phone_number E.164**: No Chatwoot, o dedup de contatos em `conv.contact_inbox_id` usa `source_id` (UUID), não phone. Então contatos duplicados criam contact_inboxes separados — cada um pode ter conversas associadas — e ambos aparecem como contatos separados na UI. O risco de dedup falho é real e silencioso: sem erro, sem warning na UI, apenas dados duplicados.

**Sobre `status`**: Adiciono dados concretos: verificar no SOURCE:
```sql
SELECT status, COUNT(*) FROM conversations WHERE account_id = 1 GROUP BY status;
-- status=0 (open): N1 conversas → aparecem nas filas se migradas verbatim
-- status=1 (resolved): N2 conversas → neutras
-- status=3 (snoozed): N3 conversas → podem causar notificações indesejadas
```

O número real de conversas `open` e `snoozed` deve guiar a decisão de negócio.

---

## 4. Síntese Final — Moderador

### 4.1 O que o SQL legado fez CORRETAMENTE (para seu contexto)

| # | Transformação | Por que estava certa no contexto TBChat→Chatwoot |
|---|---|---|
| T-01 | `CONCAT('+', phone)` → E.164 | TBChat não usava E.164; Chatwoot exige |
| T-02 | `TO_TIMESTAMP(data_reg,...)` | TBChat usava VARCHAR para datas |
| T-03 | `CASE data_ini IS NULL → data_reg` | Fallback para dados ausentes no TBChat |
| T-04 | `type_in_message → message_type int` | Schema TBChat usava string; Chatwoot usa int |
| T-05 | S3 URL embedding em content | TBChat não tinha tabela attachments |
| T-06 | `cpf + external_id` em custom_attributes | Enriquecimento de dados do TBChat |
| T-07 | Lookup account_id por name | TBChat não conhecia account IDs do Chatwoot |
| T-08 | status=1 (resolved) | Decisão deliberada de não contaminar filas |
| T-09 | dedup por phone_number | Correto para qualquer contexto |

### 4.2 O que o SQL legado fez ERRONEAMENTE (bugs confirmados)

| # | Bug | Impacto | Corrigido no Python? |
|---|---|---|---|
| B-01 | `display_id` race condition (MAX+1 dentro do loop) | Colisão de UNIQUE em execução paralela | ✅ Sim (pré-calculado) |
| B-02 | `contact_inboxes` sem dedup (cria N duplicatas) | Violação de semântica contact↔inbox | ✅ Sim (triplo fallback) |
| B-03 | `private = '0'` (string, não boolean) | Cast implícito frágil | ✅ Sim (bool nativo) |
| B-04 | `inbox_id` hardcoded (1 ou 2) | Acoplamento ao ambiente específico | ✅ Sim (IDRemapper) |
| B-05 | `status = 1` hardcoded | Perde estado real das conversas | ⚠️ Verbatim (decisão pendente) |
| B-06 | `assignee_id` hardcoded (admin) | Perde assignee real | ✅ Sim (remapeia ou nulla) |
| B-07 | `additional_attributes = '{}'::jsonb` | Perde dados de negócio | ✅ Sim (verbatim) |
| B-08 | `account_id = 1` hardcoded | Não suporta multi-account | ✅ Sim (IDRemapper) |

### 4.3 O que Python deve verificar herdado do contexto SQL legado

Mesmo com a fonte sendo Chatwoot nativo, o SOURCE pode carregar **artefatos da migração SQL original** (TBChat → SOURCE). Esses artefatos devem ser verificados antes da migração Python:

| # | Artefato | Query de verificação | Ação se encontrado |
|---|---|---|---|
| A-01 | Mensagens com S3 URL embutida em `content` | `SELECT COUNT(*) FROM messages WHERE content ILIKE '%tbchatuploads.s3%'` | Logar, não corrigir automaticamente |
| A-02 | Phone sem E.164 | `SELECT COUNT(*) FROM contacts WHERE phone_number NOT LIKE '+%' AND phone_number IS NOT NULL` | Logar, decidir com cliente |
| A-03 | `created_at` NULL | `SELECT COUNT(*) FROM conversations WHERE created_at IS NULL` | Adicionar fallback `COALESCE(created_at, NOW())` |
| A-04 | Contatos sem `custom_attributes.cpf` (se esperado) | `SELECT COUNT(*) FROM contacts WHERE NOT (custom_attributes ? 'cpf')` | Informativo — não bloqueia |
| A-05 | `contact_inboxes` duplicados pre-migração | `SELECT contact_id, inbox_id, COUNT(*) FROM contact_inboxes GROUP BY 1,2 HAVING COUNT(*)>1` | Deduplicar antes de migrar |

### 4.4 GAPs reais no Python atual

| # | GAP | Urgência | Ação |
|---|---|---|---|
| G-01 | `status` verbatim vs. forçar `resolved` | 🔴 CRÍTICO — Decisão antes de executar | Consultar cliente; default: `resolved` |
| G-02 | Phone sem E.164 não deduplicado | 🟡 MÉDIO — Silencioso | Executar A-02, logar, não auto-corrigir |
| G-03 | `inbox_members` IDs não remapeados | 🔴 CRÍTICO — Agentes ficam cegos | Verificar `app/13_migrar_inbox_members.py` |
| G-04 | S3 URLs em content (artefato legado) | 🟢 BAIXO — UX degradada, não invisível | Informativo para cliente |

---

## 5. Plano de Ação — HOJE

### 5.1 Ações bloqueadoras (executar ANTES da migração)

```
[ ] A-1: Executar assertions SQL no SOURCE (queries de §4.3)
[ ] A-2: Verificar app/13_migrar_inbox_members.py — usa IDRemapper?
[ ] A-3: Confirmar com cliente: status=open preservar ou forçar resolved?
[ ] A-4: Se G-03 confirmado (inbox_members sem remap): corrigir script
[ ] A-5: Se G-01 decisão = resolved: adicionar config FORCE_RESOLVED
```

### 5.2 Assertions SQL prontas para execução

```sql
-- Executar no SOURCE (chatwoot_dev1_db):

-- 1. created_at NULL
SELECT 'conversations' AS entity, COUNT(*) AS nulls
FROM conversations WHERE created_at IS NULL AND account_id = 1
UNION ALL
SELECT 'messages', COUNT(*) FROM messages
JOIN conversations ON messages.conversation_id = conversations.id
WHERE messages.created_at IS NULL AND conversations.account_id = 1
UNION ALL
SELECT 'contacts', COUNT(*) FROM contacts
WHERE created_at IS NULL AND account_id = 1;

-- 2. Phone sem E.164
SELECT COUNT(*) AS sem_e164,
       COUNT(*) FILTER (WHERE phone_number IS NULL) AS sem_phone
FROM contacts
WHERE account_id = 1;
-- detalhe:
SELECT phone_number FROM contacts
WHERE account_id = 1
  AND phone_number IS NOT NULL
  AND phone_number NOT LIKE '+%'
LIMIT 20;

-- 3. S3 URLs embutidas em messages
SELECT COUNT(*) AS legado_s3_urls
FROM messages m
JOIN conversations c ON m.conversation_id = c.id
WHERE c.account_id = 1
  AND (m.content ILIKE '%tbchatuploads.s3%'
    OR m.content ILIKE 'Image:%'
    OR m.content ILIKE 'Document:%'
    OR m.content ILIKE 'Video:%'
    OR m.content ILIKE 'Audio:%');

-- 4. contact_inboxes duplicados
SELECT contact_id, inbox_id, COUNT(*) AS dups
FROM contact_inboxes ci
JOIN inboxes i ON ci.inbox_id = i.id
WHERE i.account_id = 1
GROUP BY contact_id, inbox_id
HAVING COUNT(*) > 1
ORDER BY dups DESC
LIMIT 20;

-- 5. Status das conversas a migrar
SELECT status, COUNT(*) AS total,
  CASE status
    WHEN 0 THEN 'open — aparece na fila dos agentes'
    WHEN 1 THEN 'resolved — neutro'
    WHEN 2 THEN 'pending — aparece na fila pendente'
    WHEN 3 THEN 'snoozed — pode disparar notificações'
  END AS descricao
FROM conversations
WHERE account_id = 1
GROUP BY status
ORDER BY status;
```

---

## 6. Comparativo Revisado — CORRIGIDO

Esta seção substitui o `COMPARATIVO-LEGADO-VS-ATUAL.md` com análise baseada nas transformações reais de campo:

### 6.1 Transformações que EXISTIAM no SQL e NÃO existem no Python (por design)

| Transformação SQL | Razão de existir | Por que Python não replica | Status |
|---|---|---|---|
| `CONCAT('+', phone)` E.164 | TBChat.phone era número puro | SOURCE já tem E.164 | CORRETO não replicar |
| `TO_TIMESTAMP(data_reg,...)` | TBChat.data_reg era VARCHAR | SOURCE tem timestamptz nativo | CORRETO não replicar |
| `CASE WHEN data_ini IS NULL THEN data_reg` | data_ini nullable no TBChat | SOURCE não tem data_ini | CORRETO não replicar |
| `CASE WHEN last_data_update IS NULL THEN data_reg` | last_data_update nullable | SOURCE não tem esses campos | CORRETO não replicar |
| `id_empresa → inbox_id` mapping | TBChat não conhecia inbox IDs | SOURCE tem inbox_id correto | CORRETO não replicar |
| `type_in_message → int` | TBChat usava RECEIVED/SENT | SOURCE tem int nativo | CORRETO não replicar |
| `sender_type` de `type_in_message` | TBChat não tinha sender_type | SOURCE tem campo nativo | CORRETO não replicar |
| S3 URL em `content` | TBChat não tinha tabela attachments | SOURCE pode ter legado — verificar A-01 | VERIFICAR |
| `cpf + external_id` em custom_attributes | TBChat tinha CPF como coluna | SOURCE tem custom_attributes JSONB | CORRETO não replicar (copia verbatim) |
| `email = NULL` hardcoded | TbChatChatWoot não tinha email | SOURCE tem email real | CORRETO não replicar |
| `company_name` em additional_attributes | TBChat tinha empresa como campo | SOURCE tem additional_attributes JSONB | CORRETO não replicar |

### 6.2 Transformações que EXISTIAM no SQL e FORAM MELHORADAS no Python

| Transformação SQL | Bug no SQL | Solução Python |
|---|---|---|
| `MAX(display_id)+1` no loop | Race condition | Pre-calculado in-memory por account |
| contact_inboxes inline sem dedup | Cria N duplicatas | ContactInboxesMigrator + triplo fallback |
| `private = '0'` string | Cast implícito | Boolean nativo psycopg2 |
| `assignee_id = admin hardcoded` | Perde assignee real | Remapeia ou NULL-out |
| `status = 1 hardcoded` | Perde estado real | Verbatim ⚠️ GAP-4 |
| `account_id = 1 hardcoded` | Single-account | IDRemapper multi-account |
| `inbox_id = 1 ou 2 hardcoded` | Acoplamento rígido | IDRemapper offset |
| Dedup por phone exact | `TRIM` apenas | `strip().lower()` + OR email OR identifier |
| Sem inboxes migration | Inboxes não existiam sem script manual | InboxesMigrator + channel records |

---

## 7. Veredito Final

### Veredito Técnico

> **O Python atual é tecnicamente superior ao SQL legado para o contexto Chatwoot→Chatwoot.**

O SQL legado era a engenharia correta para o problema que existia em 2024: migrar dados de um sistema proprietário (TBChat) com schema heterogêneo para o Chatwoot. Aplicar esse código hoje seria um erro de categoria — inverteria transformações que a migração anterior já aplicou.

O Python atual herda os acertos do SQL legado (dedup, rastreabilidade, uuid regenerado) e corrige todos os bugs identificados (race condition, contact_inboxes sem dedup, type mismatch de private, hardcoding de IDs).

### Veredito Operacional

> **Há 2 ações críticas bloqueadoras antes da execução hoje:**

**1. Verificar `app/13_migrar_inbox_members.py`** — deve usar IDRemapper para `inbox_id` e `user_id`. Se não usar, agentes ficam cegos para todas as conversas migradas.

**2. Decidir `conversations.status`** — consultar cliente. Se não houver resposta: forçar `resolved` (consistente com SQL legado, seguro operacionalmente).

### Scorecard Final

| Dimensão | SQL Legado | Python Atual | Vencedor |
|---|---|---|---|
| Correção para contexto atual | ❌ Errado (schema diferente) | ✅ Correto | Python |
| Testabilidade | ❌ Nenhuma | ✅ pytest completo | Python |
| Idempotência | ⚠️ Frágil (custom_attributes) | ✅ migration_state | Python |
| Performance | ❌ 1 commit/row | ✅ 500 rows/commit | Python |
| Race condition display_id | ❌ Ativo | ✅ Corrigido | Python |
| contact_inboxes dedup | ❌ Cria duplicatas | ✅ Triplo fallback | Python |
| Type safety (private) | ❌ String '0' | ✅ Boolean nativo | Python |
| Multi-account | ❌ account_id=1 fixo | ✅ IDRemapper | Python |
| Inboxes + channel records | ❌ Não migrava | ✅ Migra + BUG-05 fix | Python |
| Auditabilidade | ❌ RAISE NOTICE volátil | ✅ migration_state table | Python |
| Decisão de status explícita | ✅ Hardcoded resolved | ⚠️ Verbatim (pendente) | SQL* |
| Documentação de decisões | ⚠️ No código | ✅ Debates D1-D10 | Python |

*O SQL vence em "decisão de status explícita" apenas porque havia uma decisão de negócio embutida. O Python pode replicar isso com 3 linhas de código assim que o cliente confirme.

**Placar: Python 11 × 1 SQL** (com 1 ação pendente)

---

*Debate D10 — Compilado em 2026-04-24*
*Participantes: DBA Expert, Python Expert, Chatwoot Expert, Moderador*
*Baseado em leitura literal de: scriptImportacaoTbChatChatWoot.sql, scriptImportacaoChatToSynchat.sql, src/migrators/*.py*
