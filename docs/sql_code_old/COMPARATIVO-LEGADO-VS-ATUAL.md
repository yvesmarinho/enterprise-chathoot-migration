# Comparativo: Código Legado SQL vs Migrador Python Atual

**Data**: 2026-04-23
**Legado**: `docs/sql_code_old/script*.sql` (PL/pgSQL)
**Atual**: `src/migrators/*.py` (Python 3.12 + SQLAlchemy 2.0)

---

## 1. Visão Geral

| Dimensão | Código Legado (SQL) | Código Atual (Python) |
|----------|---------------------|-----------------------|
| **Linguagem** | PL/pgSQL (DO blocks) | Python 3.12 + SQLAlchemy Core |
| **Execução** | `psql db < script.sql` | `python src/migrar.py` |
| **Ambiente alvo** | `chatwoot_tb_db` (banco único) | `chatwoot004_dev1_db` (DEST) |
| **Ambiente fonte** | staging tables no mesmo banco | `chatwoot_dev1_db` (SOURCE separado) |
| **Volume** | ~42.329 conversas (TBChat) | ~42.000+ conversas Chatwoot nativas |
| **Modelo** | Staging → Produção | SOURCE DB → DEST DB (merge) |
| **Idempotência** | `custom_attributes->>'external_id'` | `migration_state` table + IDRemapper |
| **Transação** | `COMMIT` por conversa (loop) | Batch de 500 (configurable) |
| **Reversibilidade** | IRREVERSÍVEL (staging deletada) | Reversível (migration_state; staging intacto) |

---

## 2. Comparativo por Entidade

### 2.1 Contacts

| Aspecto | Legado | Atual |
|---------|--------|-------|
| **Fonte** | `contacts_tbchat` (staging no mesmo DB) | `chatwoot_dev1_db.contacts` (DB separado) |
| **Dedup** | `phone_number = TRIM(phone)` ou `CONCAT('+', phone)` | `phone_number` OU `email` (OR logic) |
| **Email** | `scriptTbChat`: sempre NULL; `scriptChat`: copiado | Copiado conforme está no SOURCE |
| **phone_number** | Inconsistente: um script TRIM, outro CONCAT '+' | Copiado verbatim (normalização não forçada) |
| **additional_attributes** | `scriptChat`: cópia verbatim; `scriptTbChat`: build manual | Copiado verbatim do SOURCE |
| **custom_attributes** | `{'cpf': ..., 'external_id': ...}` | Copiado verbatim (sem `external_id` extra) |
| **identifier** | NULL | Copiado do SOURCE |
| **account_id** | Lookup por nome ('Dr. Thiago Bianco') | Remapeado via IDRemapper |
| **Rastreabilidade** | `custom_attributes.external_id = TBChat.id` | `migration_state` table |
| **Limite** | LIMIT 1 ou LIMIT 10 (incompleto) | Sem limite (todos os registros) |

**Diferença crítica**: O legado usava tabelas de staging intermediárias com schema
diferente do Chatwoot. O migrador atual lê diretamente das tabelas nativas Chatwoot
do SOURCE — sem transformações de campo (cpf, id_empresa, etc.).

---

### 2.2 Inboxes

| Aspecto | Legado | Atual |
|---------|--------|-------|
| **Migração de inboxes** | ❌ NÃO migrava inboxes | ✅ Migra todos os inboxes |
| **channel records** | ❌ NÃO migrava channel_web_widgets, channel_api etc. | ✅ `_migrate_channels()` cria channel records no DEST |
| **inbox_id no DEST** | Hardcoded: 1 (Bellegarde) ou 2 (SmartHair) | Calculado via IDRemapper (offset) |
| **Tokens/credentials** | N/A | Regenerados: `website_token`, `identifier`, `hmac_token` |
| **channel_types suportados** | N/A | 9 tipos: WebWidget, Api, Telegram, Facebook, Email, etc. |
| **Dedup** | N/A | Por nome + channel_type (a ser confirmado) |

---

### 2.3 Contact Inboxes

| Aspecto | Legado | Atual |
|---------|--------|-------|
| **Criação** | Inline dentro do loop de conversations | Migrador separado: `contact_inboxes_migrator.py` |
| **Dedup** | ❌ Nenhuma — criava duplicata por conversa | ✅ Dedup por par `(contact_id, inbox_id)` |
| **source_id** | `gen_random_uuid()` | `uuid.uuid4()` (novo por registro) |
| **pubsub_token** | NULL | NULL (idem — não regenerado aqui) |
| **hmac_verified** | `false` | Copiado do SOURCE |
| **Alias** | N/A | Registra alias para pares já existentes no DEST |

**Diferença crítica**: O legado criava um novo `contact_inboxes` por **conversa**,
sem verificar se o par (contact, inbox) já existia. Isso geraria milhares de
registros duplicados para contatos com múltiplas conversas. O migrador atual
deduplica corretamente.

---

### 2.4 Conversations

| Aspecto | Legado | Atual |
|---------|--------|-------|
| **display_id** | `MAX(display_id)+1` por iteração | Sequência por account iniciando após MAX do DEST |
| **uuid** | `gen_random_uuid()` | `uuid.uuid4()` |
| **status** | `1` (resolved) fixo | Copiado do SOURCE |
| **assignee_id** | `admin@vya.digital` fixo | Remapeado via IDRemapper (ou NULL se orphan) |
| **contact_id** | lookup via `custom_attributes.external_id` | Remapeado via IDRemapper (NULL-out se orphan) |
| **inbox_id** | Hardcoded 1 ou 2 | Remapeado via IDRemapper |
| **contact_inbox_id** | RETURNING id do INSERT inline | BUG-06 fix: triplo fallback (remapper → pair → NULL) |
| **team_id** | NULL fixo | Remapeado (NULL-out se orphan) |
| **additional_attributes** | `'{}'::jsonb` | Copiado do SOURCE |
| **custom_attributes** | `{'external_id': TBChat.id}` | Copiado do SOURCE |
| **Idempotência** | `custom_attributes->>'external_id'` | `migration_state` table |
| **Race condition display_id** | ❌ Sim (MAX+1 dentro do loop) | ✅ Não (offset calculado antes do loop) |

---

### 2.5 Messages

| Aspecto | Legado | Atual |
|---------|--------|-------|
| **message_type** | Calculado de `type_in_message` (RECEIVED/SENT) | Copiado do SOURCE (`message_type` Chatwoot nativo) |
| **sender_type** | 'Contact' ou 'User' por lógica TBChat | Copiado do SOURCE |
| **sender_id** | contact_id ou user_id | Remapeado via IDRemapper |
| **content** | Texto ou URL construída (S3) | Copiado do SOURCE (URL S3 já está no Chatwoot) |
| **content_attributes** | NULL | Copiado do SOURCE |
| **content_type** | `0` fixo | Copiado do SOURCE |
| **source_id** | NULL | Copiado do SOURCE |
| **account_id** | Subquery por mensagem | Remapeado via IDRemapper |
| **inbox_id** | Subquery por mensagem | Remapeado via IDRemapper |
| **conversation_id** | Subquery por mensagem | Remapeado via IDRemapper |
| **private** | `'0'` (string!) | Copiado do SOURCE (boolean) |
| **status** | `0` fixo | Copiado do SOURCE |
| **Rastreabilidade** | `additional_attributes.external_id = TBChat.id` | `migration_state` table |
| **Dedup** | `additional_attributes->>'external_id'` | `migration_state` table |

---

### 2.6 Attachments

| Aspecto | Legado | Atual |
|---------|--------|-------|
| **Migrado?** | ❌ Não — arquivos S3 embutidos no `content` como texto | ✅ Sim — tabela `attachments` migrada com `external_url` |
| **S3** | URL construída concatenada no `content` | `external_url` copiada verbatim |
| **file_type** | N/A | Copiado do SOURCE |
| **message_id** | N/A | Remapeado via IDRemapper |

---

## 3. Comparativo de Abordagem de Migração

### 3.1 Modelo de Dados Fonte

```
LEGADO                              ATUAL
─────────────────────────────       ──────────────────────────────────
Sistema TBChat (externo)            Chatwoot SOURCE (chatwoot_dev1_db)
    ↓                                   ↓
Tabelas staging intermediárias      Leitura direta das tabelas nativas
  contacts_tbchat                     contacts, inboxes, conversations,
  conversations_tbchat                messages, attachments, users, etc.
  messages_tbchat
    ↓
Schema diferente do Chatwoot        Schema idêntico ao DEST
(campos: phone, name_contact,       (sem transformação de schema)
 data_reg, data_ini, moment, etc.)
```

### 3.2 Modelo de ID

```
LEGADO                              ATUAL
─────────────────────────────       ──────────────────────────────────
IDs hardcoded (inbox_id=1 ou 2)     IDRemapper com offset automático
Nenhum remapeamento de FK           Remapeamento completo de todos os FKs
Race condition em display_id        Sequência pre-calculada por account
contact_inbox_id inline (sem dedup) contact_inbox_id com lookup DEST
```

### 3.3 Estratégia de Deduplicação

```
LEGADO                              ATUAL
─────────────────────────────       ──────────────────────────────────
Contacts: por phone_number          Contacts: por phone OR email
Conversations: por external_id      Conversations: por migration_state
Messages: por external_id           Messages: por migration_state
contact_inboxes: NENHUMA            contact_inboxes: por (contact, inbox) pair
Accounts: N/A                       Accounts: por id+name (merge)
```

### 3.4 Tratamento de Erros e Idempotência

| Cenário | Legado | Atual |
|---------|--------|-------|
| Registro já existe | Pula (sem UPDATE) | Pula via migration_state |
| Falha no meio | Staging parcialmente deletada; dados inconsistentes | migration_state preservado; re-run de onde parou |
| FK orphan (contact não migrado) | NULL silencioso (contact_id não resolvido) | NULL-out com log warning |
| Re-execução completa | IMPOSSÍVEL (staging foi deletada) | Idempotente (migration_state como checkpoint) |
| Rollback | IMPOSSÍVEL | Possível (truncar tabelas DEST + limpar migration_state) |

---

## 4. Questões Levantadas pelo Legado Relevantes ao Atual

### 4.1 Campos que o legado populava e o atual NÃO verifica

| Campo | Legado | Atual | Risco |
|-------|--------|-------|-------|
| `contacts.custom_attributes.cpf` | ✅ Populado de TBChat | ❌ Não existe no SOURCE Chatwoot | Nenhum — fonte diferente |
| `contacts.custom_attributes.external_id` | ✅ ID do TBChat | N/A | Nenhum — fonte diferente |
| `conversations.custom_attributes.external_id` | ✅ ID da sessão TBChat | Copiado do SOURCE | OK |
| `messages.additional_attributes.external_id` | ✅ ID da mensagem TBChat | Copiado do SOURCE | OK |

### 4.2 Bucket S3 `tbchatuploads`

O legado construía URLs para `tbchatuploads.s3.sa-east-1.amazonaws.com` manualmente
no campo `content`. No SOURCE Chatwoot atual, os attachments já estão armazenados
com `external_url` correto na tabela `attachments`. O migrador atual copia essa URL
verbatim — sem reconstrução.

**Questão aberta**: O SOURCE (chat.vya.digital) usa o mesmo bucket `tbchatuploads`
ou um bucket diferente? Ver [Q-C1](../debates/Q1-QUESTIONARIO-INFORMACOES-FALTANTES-2026-04-23.md).

### 4.3 Accounts Alvo

| Aspecto | Legado | Atual |
|---------|--------|-------|
| Account name | 'Dr. Thiago Bianco' / 'Sol Copernico' | 'Vya Digital' (account_id=1) |
| Lookup | Por `name` (frágil) | Por `id` via IDRemapper (merge src=1 → dest=1) |

O legado migraria para dois accounts distintos (Dr. Thiago Bianco e Sol Copernico).
O migrador atual consolida tudo no account_id=1 ('Vya Digital') — consistente com
a arquitetura enterprise do projeto.

### 4.4 Inboxes — Diferença Fundamental

O legado **NÃO migrava inboxes** nem channel records. Usava `inbox_id = 1 ou 2`
hardcoded no DEST, assumindo que esses inboxes já existiam manualmente.

O migrador atual **cria os inboxes e seus channel records** no DEST automaticamente
(BUG-05 fix em `inboxes_migrator.py`). Isso é um avanço significativo em
completude da migração.

---

## 5. Legado Como Evidência de Decisões de Negócio

O código legado captura informações de negócio que ajudam a entender o contexto:

### 5.1 Empresas no Sistema TBChat

```
id_empresa = '2' → Bellegarde (inbox_id=1)
id_empresa = '3' → SmartHair (inbox_id=2)
```

Isso indica que o sistema TBChat era multi-tenant com pelo menos 2 empresas.
No Chatwoot atual (SOURCE), cada empresa pode corresponder a inboxes separados.

### 5.2 Volume Histórico

O `LIMIT 42329` é um indicativo do volume total de conversas no sistema TBChat.
Isso ajuda a calibrar as expectativas de volume para o migrador atual:
- SOURCE Chatwoot: ~42.000 conversas (coerente com o LIMIT do legado)

### 5.3 Contato Especial: `id_contact = '1001'`

Os scripts têm blocos específicos para processar conversas e mensagens do contato
1001. Indica que esse contato teve problemas na migração original (dados faltantes,
falha no loop principal, etc.). Pode ser relevante rastrear se esse contato existe
no SOURCE atual.

### 5.4 Status Fixo `= 1` (Resolved)

O legado migraria todas as conversas como "resolvidas" (`status = 1`).
O migrador atual preserva o status original do SOURCE. Se o SOURCE tiver conversas
em `status = 0` (open) ou `status = 2` (pending), elas serão importadas com o
status correto no DEST.

---

## 6. Sumário de Melhorias do Migrador Atual vs Legado

| # | Área | Melhoria |
|---|------|----------|
| M-01 | Inboxes | Migra inboxes e channel records completos (legado não fazia) |
| M-02 | IDs | Remapeamento automático de todos os FKs (legado hardcodava) |
| M-03 | Idempotência | Checkpoint por `migration_state` + re-run seguro (legado destruía staging) |
| M-04 | contact_inboxes | Dedup por par (contact, inbox) (legado criava N duplicatas) |
| M-05 | display_id | Sequência por account sem race condition (legado: MAX+1 por iteração) |
| M-06 | contact_inbox_id | Triplo fallback + log warning (legado: NULL silencioso) |
| M-07 | Performance | Batch de 500 em vez de row-by-row com COMMIT (legado: 1 commit/conversa) |
| M-08 | Attachments | Tabela `attachments` migrada (legado: URL embutida no content como texto) |
| M-09 | Cobertura | Todos os registros sem LIMIT (legado: LIMIT hardcoded) |
| M-10 | Status | Preservado do SOURCE (legado: status=1 fixo) |
| M-11 | Assignee | Preservado do SOURCE com NULL-out gracioso (legado: admin fixo) |
| M-12 | email | Preservado (um dos scripts legado: NULL hardcoded) |
| M-13 | Rollback | Possível (legado: irreversível) |
| M-14 | Multi-account | Suportado via IDRemapper (legado: account_id=1 fixo) |

---

## 7. Regressões Potenciais (O que o legado fazia que o atual deve verificar)

| # | Item | Legado | Verificar no Atual |
|---|------|--------|--------------------|
| R-01 | `cpf` nos contatos | Preservado em `custom_attributes` | SOURCE Chatwoot tem `cpf`? |
| R-02 | `company_name` nos contatos | Em `additional_attributes.company_name` | SOURCE tem esse campo? |
| R-03 | S3 bucket tbchatuploads | URLs construídas no `content` | Attachments do SOURCE apontam para qual bucket? |
| R-04 | Contatos com `external_id` TBChat | Preservados para rastreabilidade | SOURCE já tem esse rastreio ou é nativo Chatwoot? |
