# Scripts de Operação — Enterprise Chatwoot Migration

Coleção de scripts utilitários parametrizados para operação, validação e diagnóstico do processo de migração.

---

## 📋 Índice

- [Validação Pós-Migração](#validação-pós-migração)
- [Verificação e Diagnóstico](#verificação-e-diagnóstico)
- [Testes de API](#testes-de-api)
- [Operações de Rollback](#operações-de-rollback)
- [Configuração](#configuração)

---

## Validação Pós-Migração

### `validate_migration.py`

**Descrição**: Valida integridade referencial (FK) e contagens por tabela após migração.

**Uso**:
```bash
# Validar migração para account_id=69
python scripts/validate_migration.py --account-id 69

# Especificar arquivo de saída
python scripts/validate_migration.py --account-id 69 --output validation_report.json
```

**Saída**:
- FK integrity check (0 orphans esperado)
- Contagens por tabela (account-scoped)
- JSON report em `.tmp/validation_<timestamp>.json`

**Exemplo**:
```bash
$ python scripts/validate_migration.py --account-id 69
INFO Validating migration for account_id=69
INFO Running FK integrity check (account_id=69)…
INFO   FK inboxes.account_id → accounts.id                      ✓ OK
INFO   FK contacts.account_id → accounts.id                     ✓ OK
...
INFO FK integrity: 0 total violations
INFO Querying per-table row counts…
INFO   accounts                                          1  ✓
INFO   conversations                                  4092  ✓
...
INFO Validation report saved: .tmp/validation_20260519_141101.json
```

---

## Verificação e Diagnóstico

### `check_conversations.py`

**Descrição**: Analisa distribuição de conversas por status e inbox.

**Uso**:
```bash
# Distribuição geral para account_id=69
python scripts/check_conversations.py --account-id 69

# Detalhamento específico de um inbox
python scripts/check_conversations.py --account-id 69 --inbox-id 526

# Especificar arquivo de saída
python scripts/check_conversations.py --account-id 69 --output conv_report.json
```

**Saída**:
- Breakdown por status (open, resolved, pending)
- Distribuição por inbox
- Sample de conversas recentes (se --inbox-id especificado)
- JSON report em `.tmp/conversations_<timestamp>.json`

---

### `check_inbox_mapping.py`

**Descrição**: Verifica mapeamento de IDs de inboxes (source → destination).

**Uso**:
```bash
# Verificar inboxes e mapeamentos para account_id=69
python scripts/check_inbox_mapping.py --account-id 69

# Salvar em arquivo específico
python scripts/check_inbox_mapping.py --account-id 69 --output inbox_map.json
```

**Saída**:
- Lista de inboxes no banco de destino
- Mapeamento source_id → dest_id da tabela `migration_state`
- JSON report em `.tmp/inbox_mapping_<timestamp>.json`

---

### `check_db_schema.py`

**Descrição**: Verifica schema do banco de destino (tabelas, schemas PostgreSQL).

**Uso**:
```bash
# Verificar schema do banco
python scripts/check_db_schema.py

# Especificar arquivo de saída
python scripts/check_db_schema.py --output schema_report.json
```

**Saída**:
- Lista de schemas PostgreSQL
- Contagem de tabelas por schema
- Localização da tabela `accounts`
- search_path atual
- JSON report em `.tmp/schema_<timestamp>.json`

**Credenciais**: Lê de `.secrets/generate_erd.json` usando `MIGRATION_DEST_KEY` (padrão: `chatwoot004_dev`)

---

## Testes de API

### `test_api_endpoints.py`

**Descrição**: Testa endpoints críticos da API Chatwoot após migração.

**Uso**:
```bash
# Testar endpoints básicos
python scripts/test_api_endpoints.py --instance vya-chat-dev --account-id 69

# Testar inbox específico (endpoint que falhava com HTTP 500)
python scripts/test_api_endpoints.py --instance vya-chat-dev --account-id 69 --inbox-id 526
```

**Testes executados**:
1. `GET /api/v1/profile` — Profile do usuário autenticado
2. `GET /api/v1/accounts/{account_id}/conversations` — Todas conversas
3. `GET /api/v1/accounts/{account_id}/conversations?inbox_id={inbox_id}` — Conversas do inbox (se --inbox-id)

**Credenciais**: Requer `.secrets/chatwoot_api_tokens.json`:
```json
{
  "vya-chat-dev": {
    "base_url": "https://vya-chat-dev.vya.digital",
    "token": "SeuTokenAqui"
  }
}
```

---

### `validate_api.py`

**Descrição**: Validação abrangente da API com relatório detalhado.

**Uso**:
```bash
# Validação completa
python scripts/validate_api.py --instance vya-chat-dev --account-id 69

# Com inbox específico e arquivo de saída
python scripts/validate_api.py --instance vya-chat-dev --account-id 69 --inbox-id 526 --output api_report.json
```

**Saída**:
- Status de cada endpoint (200, 500, timeout)
- Contagem de items retornados
- Summary (X/Y checks passed)
- JSON report em `.tmp/api_validation_<timestamp>.json`

**Credenciais**: Requer `.secrets/chatwoot_api_tokens.json` (mesmo formato de `test_api_endpoints.py`)

---

## Operações de Rollback

### `rollback_account.py`

**Descrição**: Remove todos os dados migrados de uma conta (reverter migração).

⚠️ **ATENÇÃO**: Operação DESTRUTIVA. Use `--dry-run` primeiro.

**Uso**:
```bash
# Dry run (mostra o que seria deletado, SEM deletar)
python scripts/rollback_account.py --account-id 69 --dry-run

# Executar rollback de verdade (requer confirmação)
python scripts/rollback_account.py --account-id 69
```

**Confirmação interativa**:
```
⚠️ WARNING: This will DELETE all data for account_id=69.
Type 'DELETE' to confirm: DELETE
```

**Ordem de deleção** (dependency-ordered):
1. `taggings` (conversation labels)
2. `attachments`
3. `messages`
4. `conversations`
5. `contact_inboxes`
6. `contacts`
7. `team_members`
8. `teams`
9. `labels`
10. `webhooks`
11. `canned_responses`
12. `custom_attribute_definitions`
13. `inboxes`
14. `account_users`
15. `accounts`

**Saída**: JSON report em `.tmp/rollback_<timestamp>.json`

---

## Configuração

### Credenciais de Banco de Dados

Todos os scripts que acessam o banco usam:
- **Arquivo**: `.secrets/generate_erd.json`
- **Variáveis de ambiente**:
  - `MIGRATION_SOURCE_KEY` (padrão: `chatwoot_dev`)
  - `MIGRATION_DEST_KEY` (padrão: `chatwoot004_dev`)

**Formato esperado**:
```json
{
  "chatwoot_dev": {
    "host": "wfdb02.vya.digital",
    "port": 5432,
    "database": "chatwoot_dev1_db",
    "username": "...",
    "password": "..."
  },
  "chatwoot004_dev": {
    "host": "wfdb02.vya.digital",
    "port": 5432,
    "database": "chatwoot004_dev1_db",
    "username": "...",
    "password": "..."
  }
}
```

### Credenciais de API

Scripts de teste de API requerem:
- **Arquivo**: `.secrets/chatwoot_api_tokens.json`

**Formato esperado**:
```json
{
  "vya-chat-dev": {
    "base_url": "https://vya-chat-dev.vya.digital",
    "token": "access_token_aqui"
  },
  "synchat": {
    "base_url": "https://synchat.vya.digital",
    "token": "outro_token"
  }
}
```

**Como obter tokens**:
```sql
-- Obter token de um usuário com acesso à conta
SELECT at.token, u.email
FROM access_tokens at
JOIN users u ON u.id = at.owner_id AND at.owner_type = 'User'
JOIN account_users au ON au.user_id = u.id
WHERE au.account_id = 69
LIMIT 1;
```

---

## Arquivos de Saída

Todos os scripts salvam outputs em `.tmp/` (nunca versionado):

| Script | Padrão de nome | Conteúdo |
|--------|----------------|----------|
| `validate_migration.py` | `validation_<timestamp>.json` | FK integrity + row counts |
| `check_conversations.py` | `conversations_<timestamp>.json` | Status/inbox distribution |
| `check_inbox_mapping.py` | `inbox_mapping_<timestamp>.json` | Source → dest mappings |
| `check_db_schema.py` | `schema_<timestamp>.json` | DB schema info |
| `test_api_endpoints.py` | _(stdout apenas)_ | Test results |
| `validate_api.py` | `api_validation_<timestamp>.json` | API check results |
| `rollback_account.py` | `rollback_<timestamp>.json` | Deletion summary |

---

## Dependências

Scripts de API requerem `requests`:
```bash
pip install requests
# ou via uv:
uv pip install requests
```

Todos os outros scripts usam apenas bibliotecas do projeto:
- SQLAlchemy 2.0.49
- psycopg2-binary 2.9.11
- Módulos `src/*` (ConnectionFactory, FKValidator, etc.)

---

## Exemplos de Workflow

### Validação pós-migração completa
```bash
# 1. Validar FK integrity e contagens
python scripts/validate_migration.py --account-id 69

# 2. Verificar distribuição de conversas
python scripts/check_conversations.py --account-id 69 --inbox-id 526

# 3. Validar mapeamento de inboxes
python scripts/check_inbox_mapping.py --account-id 69

# 4. Testar API
python scripts/test_api_endpoints.py --instance vya-chat-dev --account-id 69 --inbox-id 526
```

### Rollback de migração problemática
```bash
# 1. Dry run (ver o que seria deletado)
python scripts/rollback_account.py --account-id 69 --dry-run

# 2. Executar rollback (requer confirmação)
python scripts/rollback_account.py --account-id 69
# Digite "DELETE" quando solicitado
```

---

## Troubleshooting

### Erro: "Secrets file not found"
- Verifique se `.secrets/generate_erd.json` ou `.secrets/chatwoot_api_tokens.json` existem
- Scripts de banco: usam `generate_erd.json`
- Scripts de API: usam `chatwoot_api_tokens.json`

### Erro: "Instance 'X' not found"
- Verifique a key exata no arquivo de secrets (case-sensitive)
- Liste keys disponíveis: o erro mostra as keys válidas

### FK violations encontradas
- Indica problema de integridade referencial na migração
- Revisar lógica de remapeamento de IDs em `src/migrators/`
- Verificar se todos os migrators foram executados na ordem correta

### API retorna HTTP 500
- Verificar se sequences foram resetadas (parte de `src/migrar.py`)
- Conferir logs do container: `docker logs vya-chat-dev`
- Verificar se Redis foi limpo antes da migração

---

**Última atualização**: 2026-05-19
**Projeto**: enterprise-chatwoot-migration
