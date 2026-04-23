# Documentação: Scripts SQL Legados de Importação

**Data de análise**: 2026-04-23
**Arquivos analisados**:
- [`scriptImportacaoChatToSynchat.sql`](scriptImportacaoChatToSynchat.sql)
- [`scriptImportacaoTbChatChatWoot.sql`](scriptImportacaoTbChatChatWoot.sql)

---

## 1. Contexto e Propósito

Estes scripts foram a **primeira implementação** da migração de dados para o Chatwoot.
Foram escritos em PL/pgSQL (PostgreSQL) e executados diretamente via `psql` contra
o banco de destino.

O modelo de execução é **de staging para produção**: os dados legados do sistema
TBChat foram pré-carregados em três tabelas temporárias de staging, e estes scripts
lêem dessas tabelas e inserem nas tabelas nativas do Chatwoot.

### Tabelas de Staging (Fonte)

| Tabela de Staging | Conteúdo | Campo-chave |
|-------------------|----------|-------------|
| `public.contacts_tbchat` | Contatos do sistema TBChat | `id`, `phone`, `email`, `name_contact`, `cpf`, `id_empresa` |
| `public.conversations_tbchat` | Sessões/conversas do TBChat | `id`, `id_contact`, `id_empresa`, `data_reg`, `data_ini`, `last_data_update` |
| `public.messages_tbchat` | Mensagens individuais | `id`, `id_session`, `id_contact`, `id_empresa`, `message`, `message_type`, `type_in_message`, `file_url`, `moment` |

### Tabelas de Destino (Chatwoot)

| Tabela Chatwoot | Função |
|-----------------|--------|
| `public.contacts` | Contatos/clientes |
| `public.contact_inboxes` | Vínculo contato ↔ inbox |
| `public.conversations` | Conversas |
| `public.messages` | Mensagens |

---

## 2. Arquitetura dos Scripts

Ambos os scripts compartilham a mesma arquitetura em blocos PL/pgSQL anônimos (`DO $$`):

```
┌──────────────────────────────────────────────────────┐
│  Bloco 1: Importação de Contacts                     │
│    - Lê contacts_tbchat                              │
│    - Deduplica por phone_number                      │
│    - Insere em public.contacts                       │
│    - DELETE do staging após inserção                 │
└──────────────────────────────────────────────────────┘
        ↓
┌──────────────────────────────────────────────────────┐
│  Bloco 2: Conversations + Messages (bulk / loop)     │
│    - Lê conversations_tbchat                         │
│    - Para cada conversa:                             │
│      1. Calcula display_id = MAX(display_id)+1       │
│      2. Busca contact_id via external_id             │
│      3. Determina inbox_id por id_empresa            │
│      4. INSERT contact_inboxes (RETURNING id)        │
│      5. INSERT conversations                         │
│      6. INSERT messages (bulk ou loop)               │
│      7. DELETE do staging                            │
│      8. COMMIT                                       │
└──────────────────────────────────────────────────────┘
        ↓
┌──────────────────────────────────────────────────────┐
│  Bloco 3: Conversations específicas (id_contact=1001)│
│    - Versão fragmentada para casos especiais         │
│    - Sem messages (apenas conversas)                 │
└──────────────────────────────────────────────────────┘
        ↓
┌──────────────────────────────────────────────────────┐
│  Bloco 4: Messages específicas (id_contact=1001)     │
│    - Processa mensagens do contato 1001              │
│    - DELETE do staging após inserção                 │
└──────────────────────────────────────────────────────┘
```

---

## 3. Análise Detalhada por Script

### 3.1 `scriptImportacaoChatToSynchat.sql`

**Execução**: `psql chatwoot_tb_db < scriptImportacaoChatToSynchat.sql`

#### Bloco 1 — Contacts

```
Account alvo  : 'Sol Copernico'
Fonte         : contacts_tbchat (LIMIT 1 — teste/debug)
Dedup         : phone_number = TRIM(var_contact_row.phone)
```

| Campo Chatwoot | Origem TBChat | Transformação |
|----------------|---------------|---------------|
| `name` | `name_contact` | `TRIM()` |
| `email` | `email` | `TRIM()` |
| `phone_number` | `phone` | `TRIM()` |
| `account_id` | — | lookup por name='Sol Copernico' |
| `created_at` | `created_at` | `TO_TIMESTAMP(...)` |
| `updated_at` | `updated_at` | `TO_TIMESTAMP(...)` |
| `additional_attributes` | `additional_attributes` | Cópia verbatim da coluna |
| `custom_attributes` | `cpf`, `id` | `{'cpf': ..., 'external_id': ...}` |
| `last_activity_at` | `last_activity_at` | `TO_TIMESTAMP(...)` |
| `identifier` | — | NULL |

**Observação**: `additional_attributes` é copiado diretamente da coluna fonte
(ao contrário do script TbChat que reconstrói o objeto manualmente).

#### Bloco 2 — Conversations + Messages (LIMIT 42329)

```
Account alvo  : 'Dr. Thiago Bianco'
User assignee : admin@vya.digital
Fonte         : conversations_tbchat (LIMIT 42329)
Idempotência  : custom_attributes->>'external_id' = id_source
```

**Mapeamento de inbox por empresa:**

| `id_empresa` | `inbox_id` |
|-------------|-----------|
| `'2'` | `1` (Bellegarde) |
| outros | `2` (SmartHair) |

**Tratamento de timestamps:**

```sql
-- Se data_ini IS NULL → usa data_reg como fallback
CASE
    WHEN data_ini IS null THEN TO_TIMESTAMP(data_reg, 'YYYY-MM-DD HH24:MI:SS')
    ELSE data_ini
END
```

Afeta: `created_at`, `updated_at`, `contact_last_seen_at`, `agent_last_seen_at`,
`assignee_last_seen_at`, `waiting_since`.

**Inserção de messages**: Neste bloco, as mensagens são inseridas via **SELECT em batch**
a partir de `messages_tbchat` (sem loop interno). Isso é uma diferença importante
versus o bloco de debugging com loop.

**Pós-processamento**: Após cada conversa, o script apaga os registros do staging
(`DELETE`) e executa `COMMIT`.

#### Bloco 3 — Conversations específicas (`id_contact = '1001'`)

Versão sem mensagens — apenas `contact_inboxes` + `conversations` para o contato
com `external_id = 1001`. Provavelmente foi usado para reprocessar casos de erro.

#### Bloco 4 — Messages específicas (`id_contact = '1001'`)

Processa apenas as mensagens do contato 1001. Pode existir porque a conversa
desse contato já havia sido migrada mas as mensagens falharam.

---

### 3.2 `scriptImportacaoTbChatChatWoot.sql`

**Execução**: `psql chatwoot_tb_db < scriptImportacaoTbChatChatWoot.sql`

#### Bloco 1 — Contacts

```
Account alvo  : 'Dr. Thiago Bianco'
Fonte         : contacts_tbchat (LIMIT 10 — teste/debug)
Dedup         : phone_number = CONCAT('+', phone)
```

| Campo Chatwoot | Origem TBChat | Transformação |
|----------------|---------------|---------------|
| `name` | `name_contact` | `TRIM()` |
| `email` | — | NULL (hardcoded) |
| `phone_number` | `phone` | `CONCAT('+', phone)` |
| `account_id` | — | lookup por name='Dr. Thiago Bianco' |
| `created_at` | `data_reg` | `TO_TIMESTAMP(...)` |
| `updated_at` | `data_reg` | `TO_TIMESTAMP(data_reg, ...)` (mesmo que created_at) |
| `additional_attributes` | `id_empresa` | Construído: `{city, country, company_name, description, country_code}` |
| `custom_attributes` | `cpf`, `id` | `{'cpf': ..., 'external_id': ...}` |
| `last_activity_at` | — | NULL |
| `identifier` | — | NULL |

**Lógica de company_name por empresa:**

```sql
IF id_empresa = '2' THEN
    company_name := 'Bellegarde';
ELSE
    company_name := 'SmartHair';
END IF;
```

#### Bloco 2 — Conversations + Messages (LIMIT 42329 / LIMIT 10)

Idêntico ao `scriptImportacaoChatToSynchat.sql` na lógica de negócio.
Diferenças:
- Bloco de 42329 usa **bulk INSERT** de mensagens (sem loop)
- Bloco de LIMIT 10 usa **loop interno** por mensagem (com tratamento detalhado)

#### Blocos 3 e 4 — Idênticos ao outro script

---

## 4. Variáveis Principais (Comuns a Ambos os Scripts)

| Variável | Tipo | Uso |
|----------|------|-----|
| `var_account_id` | INT | ID do account Chatwoot |
| `var_user_id` | INT | ID do usuário assignee padrão (admin@vya.digital) |
| `var_contact_id` | INT | ID do contato resolvido no DEST |
| `var_conversation_id` | INT | ID da conversa recém-inserida |
| `var_display_id` | INT | Próximo display_id calculado como MAX+1 |
| `var_contact_inbox_id` | INT | ID do contact_inbox criado |
| `var_inbox_id` | INT | Inbox alvo (1 ou 2, por empresa) |
| `var_id_empresa` | INT | Código da empresa (2=Bellegarde, 3=SmartHair) |
| `var_message_type` | INT | 0=RECEIVED, 1=SENT |
| `var_sender_type` | VARCHAR | 'Contact' ou 'User' |
| `var_sender_id` | INT | ID do remetente (contact_id ou user_id) |
| `var_content` | TEXT | Conteúdo processado da mensagem |

---

## 5. Regras de Negócio Identificadas

### 5.1 Deduplicação de Contatos

- **Chave de dedup**: `phone_number` (sem normalização robusta — apenas TRIM ou CONCAT '+')
- Se o phone já existe no DEST → pula (sem atualizar dados)
- Se não existe → insere e deleta do staging

### 5.2 Idempotência de Conversas

- Chave: `custom_attributes->>'external_id' = TBChat.id`
- Se conversa com esse external_id já existe → pula (não processa mensagens)
- **BUG**: Quando a conversa já existe (ELSE), o script ainda tenta processar
  mensagens fora do IF no bloco com LIMIT 42329, podendo inserir mensagens
  duplicadas.

### 5.3 Idempotência de Mensagens

- Chave: `additional_attributes->>'external_id' = TBChat.id`
- Se a mensagem com esse external_id já existe → pula

### 5.4 Mapeamento de Tipo de Mensagem

```
TBChat.type_in_message  →  Chatwoot.message_type  →  Chatwoot.sender_type
─────────────────────────────────────────────────────────────────────────
'RECEIVED'              →       0                 →  'Contact'
qualquer outro          →       1                 →  'User'
```

### 5.5 Tratamento de Arquivos

Mensagens não-texto têm o conteúdo transformado em link:
```sql
CONCAT(INITCAP(message_type), ': https://tbchatuploads.s3.sa-east-1.amazonaws.com/', arquivo)
```
Exemplo: `Audio: https://tbchatuploads.s3.sa-east-1.amazonaws.com/audio/xyz.ogg`

O bucket S3 usado é `tbchatuploads.s3.sa-east-1.amazonaws.com`.

### 5.6 display_id — Race Condition

```sql
SELECT MAX(display_id)+1 INTO var_display_id FROM public.conversations;
```

Isso é calculado **por linha** dentro de um loop sequencial. Em execução single-thread
com `COMMIT` por iteração, é funcionalmente correto mas extremamente lento para volumes
grandes (42329 conversas = 42329 full-table aggregates).

---

## 6. Problemas e Limitações Identificados

| ID | Categoria | Descrição | Impacto |
|----|-----------|-----------|---------|
| L-01 | Performance | `MAX(display_id)+1` recalculado a cada iteração | Muito lento para grandes volumes |
| L-02 | Performance | `SELECT` de mensagens com subqueries correlacionadas (x3) por linha | N+1 query problem grave |
| L-03 | Concorrência | `COMMIT` dentro do loop expõe janela de race condition no display_id | Em produção com usuários simultâneos: IDs duplicados |
| L-04 | Integridade | `contact_inbox_id` inserido sem verificar se já existe o par (contact, inbox) | Duplicatas em `contact_inboxes` |
| L-05 | Cobertura | Inboxes mapeados como IDs hardcoded (1 e 2) | Não migrável para outros ambientes |
| L-06 | Cobertura | Inboxes da categoria `channel_type` não são migrados | Sem migração de `channel_web_widgets`, `channel_api` etc. |
| L-07 | Portabilidade | Account resolvido por `name` (hardcoded string) | Quebra se o nome mudar |
| L-08 | Rollback | Staging deletada após inserção bem-sucedida | Sem retry após falha parcial |
| L-09 | Cobertura | Limites hardcoded (LIMIT 1, LIMIT 10, LIMIT 42329) | Não processa todos os registros automaticamente |
| L-10 | Dados | Email NULL hardcoded em `scriptImportacaoTbChatChatWoot.sql` | Perda de email mesmo quando disponível |
| L-11 | Dados | `pubsub_token = null` em contact_inboxes | Pode causar falha em websocket |
| L-12 | Rastreabilidade | Sem tabela de log/auditoria | Impossível saber o que foi migrado vs. o que falhou |
| L-13 | Dados | Status fixo `status = 1` (resolved) para todas as conversas | Pode não refletir o estado real |
| L-14 | Dados | `assignee_id` fixo para admin@vya.digital em todas as conversas | Sem preservação do agente original |

---

## 7. Tabela de Mapeamento de Campos — Conversations

| Campo Chatwoot | Valor/Origem | Observação |
|----------------|--------------|------------|
| `account_id` | `1` (hardcoded) | account 'Dr. Thiago Bianco' |
| `inbox_id` | `1` ou `2` (por empresa) | Hardcoded por id_empresa |
| `status` | `1` | Sempre "resolved" |
| `assignee_id` | `admin@vya.digital` | Fixo, sem preservar agente original |
| `created_at` | `data_ini` ou `data_reg` | Fallback para data_reg se data_ini NULL |
| `contact_id` | lookup via `external_id` | Pode ser NULL se contato não migrado |
| `display_id` | `MAX(display_id)+1` | Race condition (ver L-03) |
| `contact_inbox_id` | `RETURNING id` do INSERT | Criado inline, sem dedup |
| `uuid` | `gen_random_uuid()` | Novo UUID por conversa |
| `last_activity_at` | `last_data_update` ou `data_reg` | Fallback |
| `team_id` | NULL | Não preservado |
| `campaign_id` | NULL | Não aplicável |
| `snoozed_until` | NULL | Não aplicável |
| `custom_attributes` | `{'external_id': TBChat.id}` | Chave de rastreabilidade |
| `assignee_last_seen_at` | `data_ini` | Mesmo que created_at |
| `first_reply_created_at` | NULL | Não calculado |
| `priority` | NULL | Não definido |
| `sla_policy_id` | NULL | Não aplicável |
| `waiting_since` | `data_ini` | Mesmo que created_at |

---

## 8. Tabela de Mapeamento de Campos — Messages

| Campo Chatwoot | Valor/Origem | Observação |
|----------------|--------------|------------|
| `content` | `message` (text) ou URL construída | Conteúdo ou link S3 |
| `account_id` | lookup name='Dr. Thiago Bianco' | Subquery por mensagem (ineficiente) |
| `inbox_id` | lookup via conversation.external_id | Subquery por mensagem |
| `conversation_id` | lookup via external_id | Subquery por mensagem |
| `message_type` | `0` (RECEIVED) ou `1` | |
| `created_at` | `moment` | Timestamp da mensagem |
| `updated_at` | `moment` | Mesmo que created_at |
| `private` | `'0'` | Sempre público |
| `status` | `0` | Sempre 'sent' |
| `source_id` | NULL | Não rastreado |
| `content_type` | `0` | Sempre texto |
| `sender_type` | `'Contact'` ou `'User'` | Por type_in_message |
| `sender_id` | contact_id ou user_id | Por type_in_message |
| `additional_attributes` | `{'external_id': TBChat.id}` | Chave de rastreabilidade |
| `processed_message_content` | Mesmo que `content` | Duplicado |
| `sentiment` | `'{}'::jsonb` | Vazio |

---

## 9. Dados de Contexto do Ambiente Legado

- **Sistema fonte**: TBChat
- **Bucket S3**: `tbchatuploads.s3.sa-east-1.amazonaws.com`
- **Accounts Chatwoot**: 'Dr. Thiago Bianco', 'Sol Copernico'
- **Usuário assignee padrão**: `admin@vya.digital`
- **Empresas**:
  - `id_empresa = '2'` → Bellegarde → inbox_id = 1
  - `id_empresa != '2'` → SmartHair → inbox_id = 2
- **Volume de conversas**: ~42.329 (conforme LIMIT hardcoded)
