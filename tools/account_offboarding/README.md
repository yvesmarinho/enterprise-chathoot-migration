# Account Offboarding Tool

## 📋 Visão Geral

Ferramenta para **offboarding completo de accounts Chatwoot** — cenários de término de contrato, remoção de dados de clientes, ou limpeza de migrações incorretas.

**Recursos:**
- ✅ **Auditoria read-only** (`inspect.py`) — identifica todos os dados vinculados a um account_id
- ✅ **Remoção completa** (`cleanup.py`) — deleta TODOS os dados do account respeitando ordem de FKs
- ✅ **Segurança**: confirmação interativa, dry-run obrigatório, transação única com rollback automático em erro
- ✅ **Cobertura**: 40+ tabelas Chatwoot (messages, contacts, conversations, inboxes, portals, teams, etc.)

---

## 📁 Estrutura

```
tools/account_offboarding/
├── README.md                    # Este arquivo
├── config.json.example          # Template de configuração
├── inspect.py                   # Auditoria (read-only)
└── cleanup.py                   # Remoção completa (destrutivo)
```

**Outputs:** Ambos scripts salvam JSON em `tools/account_offboarding/<db_key>_account_<id>_<operation>_YYYYMMDD_HHMMSS.json`

---

## ⚙️ Configuração

### 1. Criar arquivo de configuração

```bash
cd tools/account_offboarding
cp config.json.example config.json
```

### 2. Editar `config.json`

```json
{
  "db_key": "vya-chat-dev",
  "account_id": 44,
  "secrets_file": "../../.secrets/generate_erd.json"
}
```

| Campo | Descrição | Exemplo |
|-------|-----------|---------|
| `db_key` | Chave do banco no secrets file | `vya-chat-dev`, `synchat-vya-digital` |
| `account_id` | ID do account Chatwoot | `44` |
| `secrets_file` | Caminho relativo ao secrets JSON | `../../.secrets/generate_erd.json` |

**⚠️ NUNCA versione `config.json`** — use apenas `config.json.example` como template.

---

## 🔍 Uso: `inspect.py` (Auditoria)

### Propósito
Identificar **quantos registros** existem em cada tabela Chatwoot para um `account_id` específico.

### Estratégias de Busca
1. **Direct**: Tabelas com coluna `account_id` (48+ tabelas)
2. **FK-based**: Busca via foreign keys (ex: `contact_inboxes`, `inbox_members`, `team_memberships`, `portal_members`)

### Exemplos

#### Via config.json
```bash
uv run python inspect.py --config config.json
```

#### Via CLI direto
```bash
uv run python inspect.py --db-key vya-chat-dev --account-id 44
```

#### Produção
```bash
uv run python inspect.py --db-key synchat-vya-digital --account-id 45
```

### Output

```
[inspect] Conectando a 'vya-chat-dev'…
[inspect] Banco: chatwoot004_dev1_db  |  account_id: 44
[inspect] 48 tabelas com coluna account_id…

[inspect] 12 tabelas com dados do account 44:
  messages                    : 670
  attachments                 : 6
  reporting_events            : 166
  contact_inboxes             : 92
  conversations               : 77
  contacts                    : 54
  working_hours               : 14
  notification_settings       : 4
  inboxes                     : 2
  agent_bot_inboxes           : 2
  inbox_members               : 2
  account_users               : 1

[inspect] Total de linhas: 853
[inspect] Relatório salvo em: vya-chat-dev_account_44_audit_20260524_115823.json
```

**JSON gerado:**
```json
{
  "db_key": "vya-chat-dev",
  "database": "chatwoot004_dev1_db",
  "account_id": 44,
  "timestamp": "2026-05-24T11:58:23",
  "tables_with_data": {
    "messages": {"count": 670, "strategy": "direct"},
    "attachments": {"count": 6, "strategy": "direct"},
    "contact_inboxes": {"count": 92, "strategy": "fk"},
    ...
  },
  "total_rows": 853
}
```

---

## 🗑️ Uso: `cleanup.py` (Remoção)

### Propósito
**Deletar TODOS os dados** vinculados a um `account_id` de forma segura e completa.

### ⚠️ ATENÇÃO — Operação Destrutiva

- ✅ **SEMPRE execute dry-run primeiro**
- ✅ Confirmação interativa obrigatória (digite o `account_id` para prosseguir)
- ✅ Transação única: COMMIT apenas se tudo executar com sucesso, ROLLBACK em qualquer erro
- ✅ Pré-conta → executa → pós-verifica (garante 0 linhas ao final)

### Workflow Obrigatório

#### 1. Dry-run
```bash
uv run python cleanup.py --db-key vya-chat-dev --account-id 44 --dry-run
```

**Output:**
```
[dry-run] Conectando a 'vya-chat-dev' (READ-ONLY)…
[dry-run] Banco: chatwoot004_dev1_db  |  account_id: 44

[dry-run] Pré-contagem (15 tabelas):
  messages                    : 670
  attachments                 : 6
  reporting_events            : 166
  contact_inboxes             : 92
  ...
[dry-run] Total a deletar: 864 linhas

[dry-run] ✅ Nenhuma modificação feita (dry-run).
```

#### 2. Execute (após confirmar dry-run)
```bash
uv run python cleanup.py --db-key vya-chat-dev --account-id 44 --execute
```

**Confirmação interativa:**
```
═══════════════════════════════════════════════════════════════
⚠️  CONFIRMAÇÃO OBRIGATÓRIA ⚠️
═══════════════════════════════════════════════════════════════

Você está prestes a DELETAR PERMANENTEMENTE todos os dados de:

  DATABASE    : chatwoot004_dev1_db
  ACCOUNT_ID  : 44
  TOTAL LINHAS: 864

Esta operação NÃO pode ser desfeita.

Digite o account_id (44) para confirmar, ou CTRL+C para cancelar:
```

**Após digitar `44`:**
```
[execute] SET SESSION default_transaction_read_only = off
[execute] Executando 15 operações DELETE…
  ✓ messages                    : 670 linhas deletadas
  ✓ attachments                 : 6 linhas deletadas
  ✓ reporting_events            : 166 linhas deletadas
  ...
[execute] Total deletado: 864 linhas
[execute] Pós-verificação (tudo deve ser 0):
  messages                    : 0
  attachments                 : 0
  ...
[execute] ✅ COMMIT executado com sucesso.
```

### Tabelas Cobertas (45+ operações)

A ferramenta processa as tabelas na ordem correta de dependências FK:

```python
# --- Dependentes de messages ---
attachments, mentions, reporting_events, messages

# --- Dependentes de conversations ---
conversation_participants, csat_survey_responses, applied_slas, sla_events,
contact_inboxes, conversations

# --- Dependentes de contacts ---
contacts

# --- Dependentes de inboxes ---
agent_bot_inboxes, inbox_members, working_hours,
channel_api, channel_whatsapp, channel_web_widgets, channel_email,
channel_facebook_pages, channel_telegram, channel_sms, channel_twilio_sms,
channel_line, channel_twitter_profiles, inboxes

# --- Agent bots ---
agent_bots

# --- Notificações ---
notification_settings, notifications

# --- Teams ---
team_memberships, teams

# --- Portals (help center) ---
portal_members, categories, articles, folders, portals

# --- Demais features ---
labels, canned_responses, automation_rules, macros, campaigns,
dashboard_apps, custom_attribute_definitions, custom_filters, custom_roles,
data_imports, email_templates, sla_policies, webhooks, integrations_hooks,
telegram_bots

# --- Vínculo users↔account ---
account_users

# --- Raiz ---
accounts
```

### Outputs

**JSON gerado** (`<db_key>_account_<id>_cleanup_YYYYMMDD_HHMMSS.json`):
```json
{
  "db_key": "vya-chat-dev",
  "database": "chatwoot004_dev1_db",
  "account_id": 44,
  "dry_run": false,
  "timestamp": "2026-05-24T11:59:42",
  "pre_count": {
    "messages": 670,
    "attachments": 6,
    ...
    "total": 864
  },
  "deletions": {
    "messages": 670,
    "attachments": 6,
    ...
    "total": 864
  },
  "post_count": {
    "messages": 0,
    "attachments": 0,
    ...
    "total": 0
  },
  "success": true,
  "committed": true
}
```

---

## 🛡️ Segurança e Limitações

### Proteções Implementadas

- ✅ **Read-only default**: `inspect.py` usa `set_session(readonly=True)`
- ✅ **Transaction safety**: `cleanup.py` usa transação única — ROLLBACK automático em erro
- ✅ **Interactive confirmation**: Usuário deve digitar `account_id` para prosseguir
- ✅ **Dry-run obrigatório**: Fluxo recomendado sempre exige `--dry-run` antes de `--execute`
- ✅ **Post-verification**: Após DELETE, recontagem confirma 0 linhas (detecta FKs esquecidas)

### Restrições do `migration_user`

O role PostgreSQL `migration_user` tem `default_transaction_read_only = on` por padrão.

**Sintoma:**
```
psycopg2.errors.ReadOnlySqlTransaction: cannot execute DELETE in a read-only transaction
```

**Solução (já implementada):**
```python
cur.execute("SET SESSION default_transaction_read_only = off")
conn.commit()
```

O `cleanup.py` já faz isso automaticamente antes de qualquer DELETE.

---

## 📊 Casos de Uso

### 1. Offboarding de Cliente (contrato encerrado)
```bash
# 1. Auditoria
uv run python inspect.py --db-key synchat-vya-digital --account-id 99

# 2. Dry-run
uv run python cleanup.py --db-key synchat-vya-digital --account-id 99 --dry-run

# 3. Confirmação manual (revisar outputs)

# 4. Execução
uv run python cleanup.py --db-key synchat-vya-digital --account-id 99 --execute
```

### 2. Limpeza de Migração Incorreta
```bash
# Cenário: account_id=45 foi migrado para produção por engano

# 1. Identificar
uv run python inspect.py --db-key synchat-vya-digital --account-id 45

# 2. Remover
uv run python cleanup.py --db-key synchat-vya-digital --account-id 45 --execute
```

### 3. Teste em Ambiente DEV
```bash
# Após testes, limpar account de teste
uv run python cleanup.py --db-key vya-chat-dev --account-id 999 --execute
```

---

## 🔧 Manutenção

### Adicionar Nova Tabela

Se o schema Chatwoot for atualizado com novas tabelas vinculadas a `account_id`:

1. **Editar `cleanup.py`**:
```python
_STEPS = [
    # ... steps existentes ...
    _sql("nova_tabela", "account_id = %(aid)s"),  # ← Adicionar aqui
]
```

2. **Posicionar corretamente** na lista (respeitar ordem de FKs):
   - Se depende de `conversations` → antes de `conversations`
   - Se depende de `inboxes` → antes de `inboxes`
   - Se é raiz (só depende de `accounts`) → antes de `accounts`

3. **Testar**:
```bash
# Dry-run em ambiente dev
uv run python cleanup.py --db-key vya-chat-dev --account-id 999 --dry-run
```

### `inspect.py` Não Precisa Atualizar

O `inspect.py` descobre tabelas **dinamicamente** via:
1. `information_schema.columns` (tabelas com `account_id`)
2. `pg_constraint` (tabelas com FKs para outras tabelas do account)

**Exceção:** Tabelas que usam `id` em vez de `account_id` (ex: `accounts` usa `id`, não `account_id`). Essas não aparecem no inspect automaticamente.

---

## 📝 Exemplos de Outputs Reais

### Exemplo 1: Ambiente DEV (account_id=44, usado ativamente)

**Inspect:**
```
[inspect] 12 tabelas com dados do account 44:
[inspect] Total de linhas: 853
```

**Cleanup dry-run:**
```
[dry-run] Total a deletar: 864 linhas
```

**Cleanup execute:**
```
[execute] Total deletado: 864 linhas
[execute] ✅ COMMIT executado com sucesso.
```

**Diferença 853 vs 864:** `inspect.py` não conta a linha na tabela `accounts` (bug conhecido, usa `account_id=44` mas tabela usa `id=44`). Cleanup está correto.

### Exemplo 2: Produção (account_id=45, migração incorreta)

**Inspect pós-cleanup:**
```
[inspect] 0 tabelas com dados do account 45
[inspect] Total de linhas: 0
```

**Cleanup anterior:**
```
[execute] Total deletado: 2339 linhas
```

---

## 🐛 Problemas Conhecidos

### 1. `inspect.py` não conta tabela `accounts`

**Causa:** Busca por `account_id = X`, mas `accounts` usa `id = X`.

**Impacto:** Conta total aparece 1 linha menor que o real (se account existe).

**Workaround:** `cleanup.py` está correto (usa `id = %(aid)s` para accounts).

### 2. Tabelas sem `account_id` e sem FK direto

**Exemplo hipotético:** `logs_internos` que vincula via `user_id` sem FK explícito.

**Mitigação:** Verificar schema manualmente antes de usar em produção. Adicionar entrada customizada no `_STEPS` se necessário.

---

## 📚 Referências

- **Secrets file**: `.secrets/generate_erd.json` (nunca versionado)
- **Documentação do projeto**: `docs/INDEX.md`
- **Guia de migração**: `docs/RUNBOOK_MIGRACAO_PRODUCAO_2026-05-16.md`
- **Copilot rules**: `.github/copilot-instructions.md`

---

## ✅ Checklist de Uso

**Antes de executar em produção:**

- [ ] Executei `inspect.py` para ver quantas linhas serão afetadas
- [ ] Executei `cleanup.py --dry-run` e revisei o output
- [ ] Confirmei que o `account_id` está correto
- [ ] Confirmei que estou conectando ao banco correto (`db_key`)
- [ ] Tenho backup ou snapshot do banco (caso necessário rollback)
- [ ] Obtive aprovação do responsável (se política exigir)
- [ ] Executei `cleanup.py --execute` e confirmei interativamente
- [ ] Verifiquei o JSON de output (`success: true`, `committed: true`)
- [ ] Executei `inspect.py` novamente para confirmar 0 linhas

---

**Criado em:** 2026-05-24  
**Versão da ferramenta:** 1.0.0  
**Testado com:** Chatwoot schema v3.x, PostgreSQL 16.10
