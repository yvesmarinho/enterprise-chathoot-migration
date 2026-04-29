# Data Model: Enterprise Chatwoot Migration

**Branch**: `001-enterprise-chatwoot-migration`
**Phase**: 1 — Design
**Date**: 2026-04-09
**Schema SHA1**: `da6b4a366d550dc7794f55f5e1536342ce50845f` (idêntico em ambas as instâncias)

---

## Entidades Migradas (schema Chatwoot — somente leitura na origem)

### 1. accounts

| Campo | Tipo | Constraints | Sensível |
|-------|------|-------------|----------|
| id | BIGINT | PK | — |
| name | VARCHAR | NOT NULL | ⚠️ mascarar |
| created_at | TIMESTAMP | NOT NULL | — |
| updated_at | TIMESTAMP | NOT NULL | — |
| _(demais campos)_ | — | — | — |

**Volumes**: origem=5 / destino=20
**FK inbound**: todas as outras entidades referenciam `account_id`
**Remapeamento**: `novo_id = id + offset_accounts`

---

### 2. inboxes

| Campo | Tipo | Constraints | Sensível |
|-------|------|-------------|----------|
| id | BIGINT | PK | — |
| account_id | BIGINT | FK → accounts.id | — |
| name | VARCHAR | NOT NULL | — |
| channel_type | VARCHAR | NOT NULL | — |
| created_at | TIMESTAMP | NOT NULL | — |
| updated_at | TIMESTAMP | NOT NULL | — |

**Volumes**: origem=21 / destino=151
**FK remapeadas no insert**: `account_id`
**Remapeamento**: `novo_id = id + offset_inboxes`

---

### 3. users

| Campo | Tipo | Constraints | Sensível |
|-------|------|-------------|----------|
| id | BIGINT | PK | — |
| account_id | BIGINT | FK → accounts.id (via account_users) | — |
| name | VARCHAR | NOT NULL | ⚠️ mascarar |
| email | VARCHAR | UNIQUE | ⚠️ mascarar |
| phone_number | VARCHAR | — | ⚠️ mascarar |
| created_at | TIMESTAMP | NOT NULL | — |
| updated_at | TIMESTAMP | NOT NULL | — |

**Volumes**: origem=112 / destino=294
**FK remapeadas no insert**: `account_id` (via tabela `account_users`)
**Remapeamento**: `novo_id = id + offset_users`
**Nota**: `email` é UNIQUE global — após remapeamento de IDs, emails da origem podem colidir
com emails do destino. Estratégia: sufixo `_migrated` ou prefixo de domínio. Ver contrato CLI.

---

### 4. teams

| Campo | Tipo | Constraints | Sensível |
|-------|------|-------------|----------|
| id | BIGINT | PK | — |
| account_id | BIGINT | FK → accounts.id | — |
| name | VARCHAR | NOT NULL | — |
| created_at | TIMESTAMP | NOT NULL | — |
| updated_at | TIMESTAMP | NOT NULL | — |

**Volumes**: origem=3 / destino=22
**FK remapeadas no insert**: `account_id`
**Remapeamento**: `novo_id = id + offset_teams`

---

### 5. labels

| Campo | Tipo | Constraints | Sensível |
|-------|------|-------------|----------|
| id | BIGINT | PK | — |
| account_id | BIGINT | FK → accounts.id | — |
| title | VARCHAR | NOT NULL | — |
| color | VARCHAR | — | — |
| created_at | TIMESTAMP | NOT NULL | — |
| updated_at | TIMESTAMP | NOT NULL | — |

**Volumes**: origem=32 / destino=184
**FK remapeadas**: `account_id`
**Remapeamento**: `novo_id = id + offset_labels`

---

### 6. contacts

| Campo | Tipo | Constraints | Sensível |
|-------|------|-------------|----------|
| id | BIGINT | PK | — |
| account_id | BIGINT | FK → accounts.id | — |
| name | VARCHAR | — | ⚠️ mascarar |
| email | VARCHAR | — | ⚠️ mascarar |
| phone_number | VARCHAR | — | ⚠️ mascarar |
| identifier | VARCHAR | — | ⚠️ mascarar |
| additional_attributes | JSONB | — | ⚠️ mascarar |
| created_at | TIMESTAMP | NOT NULL | — |
| updated_at | TIMESTAMP | NOT NULL | — |

**Volumes**: origem=38.868 / destino=225.536
**FK remapeadas**: `account_id`
**Remapeamento**: `novo_id = id + offset_contacts`

---

### 7. conversations

| Campo | Tipo | Constraints | Sensível |
|-------|------|-------------|----------|
| id | BIGINT | PK | — |
| account_id | BIGINT | FK → accounts.id | — |
| inbox_id | BIGINT | FK → inboxes.id | — |
| contact_id | BIGINT | FK → contacts.id | NULLABLE |
| assignee_id | BIGINT | FK → users.id | NULLABLE |
| team_id | BIGINT | FK → teams.id | NULLABLE |
| meta | JSONB | — | ⚠️ mascarar |
| additional_attributes | JSONB | — | ⚠️ mascarar |
| created_at | TIMESTAMP | NOT NULL | — |
| updated_at | TIMESTAMP | NOT NULL | — |

**Volumes**: origem=41.743 / destino=153.582
**FK remapeadas**: `account_id`, `inbox_id`, `contact_id`, `assignee_id`, `team_id`
**Remapeamento**: `novo_id = id + offset_conversations`
**Inconsistência conhecida**: `contact_id` pode ser NULL ou inválido na origem — skip+log

---

### 8. messages

| Campo | Tipo | Constraints | Sensível |
|-------|------|-------------|----------|
| id | BIGINT | PK | — |
| account_id | BIGINT | FK → accounts.id | — |
| conversation_id | BIGINT | FK → conversations.id | NULLABLE |
| sender_id | BIGINT | FK → users.id | NULLABLE |
| content | TEXT | — | ⚠️ mascarar |
| content_attributes | JSONB | — | ⚠️ mascarar |
| created_at | TIMESTAMP | NOT NULL | — |
| updated_at | TIMESTAMP | NOT NULL | — |

**Volumes**: origem=310.155 / destino=1.302.949
**FK remapeadas**: `account_id`, `conversation_id`, `sender_id`
**Remapeamento**: `novo_id = id + offset_messages`
**Inconsistência conhecida**: `conversation_id` pode ser NULL ou inválido — skip+log

---

### 9. attachments

| Campo | Tipo | Constraints | Sensível |
|-------|------|-------------|----------|
| id | BIGINT | PK | — |
| message_id | BIGINT | FK → messages.id | — |
| account_id | BIGINT | FK → accounts.id | — |
| file_type | VARCHAR | — | — |
| external_url | TEXT | — | — |
| created_at | TIMESTAMP | NOT NULL | — |
| updated_at | TIMESTAMP | NOT NULL | — |

**Volumes**: origem=26.889 / destino=73.435
**FK remapeadas**: `message_id`, `account_id`
**Remapeamento**: `novo_id = id + offset_attachments`
**Nota**: Apenas `external_url` (referência S3) é migrada — arquivos físicos não movidos

---

## Entidade de Controle (criada pelo sistema de migração)

### migration_state

| Campo | Tipo | Constraints | Descrição |
|-------|------|-------------|-----------|
| id | BIGSERIAL | PK | Auto-increment interno |
| tabela | VARCHAR(100) | NOT NULL | Nome da tabela chatwoot migrada |
| id_origem | BIGINT | NOT NULL | ID original em chatwoot_dev1_db |
| id_destino | BIGINT | — | ID remapeado em chatwoot004_dev1_db |
| status | VARCHAR(20) | NOT NULL DEFAULT 'ok' | 'ok' \| 'failed' |
| migrated_at | TIMESTAMP | NOT NULL DEFAULT NOW() | Timestamp da migração |
| UNIQUE | — | (tabela, id_origem) | Garante idempotência |

**DDL**: criado via `metadata.create_all(engine_destino)` na primeira execução
**Index**: `ix_migration_state_tabela ON migration_state(tabela)` para queries de idempotência

---

## Diagrama de Dependências (FK Graph)

```
accounts
├── inboxes (account_id)
├── users (account_id via account_users)
├── teams (account_id)
├── labels (account_id)
└── contacts (account_id)
      └── conversations (account_id, inbox_id, contact_id[nullable], assignee_id[nullable], team_id[nullable])
            ├── messages (account_id, conversation_id[nullable], sender_id[nullable])
            └── attachments (message_id, account_id)
```

**Ordem de migração obrigatória** (respeita grafo):
1. accounts
2. inboxes
3. users
4. teams
5. labels
6. contacts
7. conversations
8. messages
9. attachments

---

## Mapeamento de Offsets

```python
# Calculado UMA VEZ no início da sessão
offsets: dict[str, int] = {
    "accounts":      session.execute(select(func.max(accounts.c.id))).scalar() or 0,
    "inboxes":       session.execute(select(func.max(inboxes.c.id))).scalar() or 0,
    "users":         session.execute(select(func.max(users.c.id))).scalar() or 0,
    "teams":         session.execute(select(func.max(teams.c.id))).scalar() or 0,
    "labels":        session.execute(select(func.max(labels.c.id))).scalar() or 0,
    "contacts":      session.execute(select(func.max(contacts.c.id))).scalar() or 0,
    "conversations": session.execute(select(func.max(conversations.c.id))).scalar() or 0,
    "messages":      session.execute(select(func.max(messages.c.id))).scalar() or 0,
    "attachments":   session.execute(select(func.max(attachments.c.id))).scalar() or 0,
}
# novo_id = id_origem + offsets[tabela]  (se offset=0, usa id original)
```

---

## Regras de Validação

| Regra | Tabela | Tipo | Ação em Falha |
|-------|--------|------|---------------|
| contact_id NULL ou orphan | conversations | FK nullable | Skip + log ID |
| conversation_id NULL ou orphan | messages | FK nullable | Skip + log ID |
| account_id orphan | qualquer | FK obrigatória | Skip + log ID + alertar |
| email duplicado após remapeamento | users | UNIQUE | Sufixo `+migrated@` no email |
| id_destino collision | qualquer | offset errado | ERROR — abort session |
