# Plano de Execução da Migração — 2026-04-24

**Status**: � ATUALIZADO — D12 identificou ações obrigatórias pré-container
**Prazo**: Hoje
**Contexto operacional**:
- DEST (`chatwoot004_dev1_db`) com pipeline executado ✅
- Container `vya-chat-dev.vya.digital` parado — .env já correto (`chatwoot004_dev1_db`)
- SOURCE e DEST são cópias DEV — **sem risco de produção**

---

## ⚠️ NOVO — FASE PRÉ-CONTAINER (D12 — 2026-04-24)

> Análise completa: [D12-ANALISE-CRITICA-LOGICA-NEGOCIO-FLUXO-DADOS-2026-04-24.md](../../debates/D12-ANALISE-CRITICA-LOGICA-NEGOCIO-FLUXO-DADOS-2026-04-24.md)

### Ações P0 — obrigatórias antes de reiniciar o serviço

| ID | Risco | Ação |
|----|-------|------|
| D12-P0-1 | A-05: tokens duplicados entre instâncias | Regenerar `authentication_token` de todos os usuários migrados |
| D12-P0-2 | F-04: `snoozed` vencido dispara job automático | Quantificar + decidir com cliente: forçar `resolved` ou manter |
| D12-P0-3 | A-02: conversas `open` históricas contaminam filas | Quantificar + decidir com cliente: manter ou fechar |

### Ações P1 — antes de liberar para usuários

| ID | Risco | Ação |
|----|-------|------|
| D12-P1-1 | A-01: `contact_inbox_id` NULL/dangling | Executar query de verificação, documentar baseline |
| D12-P1-2 | A-03: colisão silenciosa de phone no SOURCE | Executar query no SOURCE, listar duplicatas |
| D12-P1-3 | L-01: `contact_id=NULL` herdado do legado | Contar no SOURCE, propagar awareness |
| D12-P1-4 | F-02: `conversation_participants` ausente | Avaliar relevância com cliente |
| D12-P1-5 | A-05: webhooks apontando para SOURCE | Verificar URLs dos webhooks migrados |

### Ações P2 — para robustez de re-runs futuros

| ID | Risco | Ação |
|----|-------|------|
| D12-P2-1 | F-01: migration_state vs. truncate | Documentar procedimento de reset completo |
| D12-P2-2 | A-03: normalização E.164 | Implementar normalização de phone antes de novo ContactsMigrator |
| D12-P2-3 | F-03: prioridade de dedup ambígua | Definir e documentar: `identifier > phone > email` |

---

## Decisões Registradas

| ID | Decisão | Escolha | Impacto no código |
|---|---|---|---|
| DEC-01 | `conversations.status` nas conversas migradas | **A — Preservar verbatim** | Nenhum — comportamento atual mantido |
| DEC-02 | Canais com SOURCE ainda ativo | **DEV — sem risco** | CRED-channels removido dos bloqueadores |
| DEC-03 | `authentication_token` dos usuários | **DEV — aceitável verbatim** | Nenhum — **revisar com D12-P0-1** |
| DEC-04 | Inboxes conta Vya Digital | **Dedup por nome/canal** | FIX-01 obrigatório |
| DEC-05 | display_id e URLs antigas | **Aceitar mudança** | Nenhum |
| DEC-06 | `canned_responses` | **Implementar migrador** | Novo `CannedResponsesMigrator` |
| DEC-07 | `webhooks` e `integration_hooks` | **Migrar automaticamente** | Novos `WebhooksMigrator`, `IntegrationHooksMigrator` |

---

## Pipeline Final (nova ordem com migrators adicionados)

```
accounts
  → custom_attribute_definitions   [NOVO — FIX-05]
  → canned_responses               [NOVO — DEC-06]
  → inboxes                        [FIX-01: dedup BUG-B]
  → webhooks                       [NOVO — DEC-07]
  → users
  → teams                          [FIX-02: dedup BUG-C]
  → team_members                   [NOVO — FIX-03]
  → labels                         [FIX-02: dedup BUG-C]
  → contacts
  → contact_inboxes
  → integration_hooks              [NOVO — DEC-07]
  → conversations
  → messages
  → attachments
  → conversation_labels            [NOVO — FIX-04]

+ app/13_migrar_inbox_members.py   [separado, após pipeline principal]
```

> **Ordem de webhooks**: antes de users (depende apenas de accounts).
> **Ordem de integration_hooks**: após contact_inboxes (pode referenciar inboxes).
> **Ordem de conversation_labels**: última (depende de conversations + labels).

---

## FASE 1 — Correções de Código

### ✅ Critério de conclusão da Fase 1
Todos os itens FIX e DEC implementados, `uv run pytest` passando, sem erros de lint.

---

### TAREFA 1 — FIX-02: Corrigir BUG-C em TeamsMigrator e LabelsMigrator

**Arquivo**: `src/migrators/teams_migrator.py`, `src/migrators/labels_migrator.py`

**Bug**: A condição de dedup usa:
```python
if self.id_remapper.remap(acct_id, "accounts") == acct_id
```
Isso só identifica contas onde `src_id == dest_id`. Para contas `src=4→dest=47`, `src=18→dest=61`, `src=25→dest=68`, o dedup é silenciosamente ignorado.

**Correção**:
1. Condição: substituir por `self.id_remapper.has_alias("accounts", acct_id)`
2. Query DEST: usar `self.id_remapper.remap(acct_id, "accounts")` como `account_id` na cláusula WHERE (não `acct_id` direto)

**Justificativa do ponto 2**: Para `src=4→dest=47`, a query deve buscar `WHERE account_id = 47` no DEST, não `WHERE account_id = 4`.

---

### TAREFA 2 — FIX-01: Implementar dedup de inboxes em InboxesMigrator (BUG-B)

**Arquivo**: `src/migrators/inboxes_migrator.py`

**Bug**: Não há etapa de dedup para inboxes de contas merged. Inboxes do SOURCE para `account_id=1` (Vya Digital) serão reinseridos no DEST duplicando os inboxes pré-existentes.

**Correção**: Adicionar bloco de dedup ANTES de `_migrate_channels`, seguindo o padrão de TeamsMigrator:

1. Identificar contas merged via `has_alias("accounts", acct_id)`
2. Para cada conta merged, buscar inboxes do DEST por `account_id = remap(acct_id, "accounts")`
3. Chave de dedup: `(str(name).lower(), str(channel_type))` — case-insensitive por nome + tipo
4. Para cada inbox SOURCE que bate na chave: `register_alias("inboxes", src_id, dest_id)` + `record_success`
5. `_migrate_channels` deve pular channels de inboxes que foram aliasados (não criar canal duplicado)

**Atenção**: O `remap_fn` já filtra via `_run_batches` os IDs que estão em `migration_state` — o alias garante que esses registros não são reinseridos.

---

### TAREFA 3 — FIX-03: Implementar TeamMembersMigrator

**Arquivo novo**: `src/migrators/team_members_migrator.py`

**Tabela**: `team_members` — schema esperado: `(team_id, user_id)` — sem PK surrogate, composite PK

**Comportamento**:
- Não tem `id` próprio — não usa IDRemapper para PK
- Remapear `team_id` via `id_remapper.remap(team_id, "teams")`
- Remapear `user_id` via `id_remapper.remap(user_id, "users")`
- Skip se `team_id` orphan (não em migration_state de teams)
- Skip se `user_id` orphan (não em migration_state de users)
- `ON CONFLICT DO NOTHING` para idempotência
- **Nota**: `BaseMigrator._run_batches` usa `id` para migration_state — para tabelas sem PK surrogate, implementar lógica de batch diretamente no `migrate()` sem herdar `_run_batches`

---

### TAREFA 4 — FIX-04: Implementar ConversationLabelsMigrator

**Arquivo novo**: `src/migrators/conversation_labels_migrator.py`

**Tabela**: `conversation_labels` — tabela de junção (ou `taggings` com polimorfismo — verificar schema)

> ⚠️ **Verificar schema antes de implementar**: o Chatwoot pode usar a gem `acts-as-taggable-on`, que armazena labels em `taggings` (polimórfica) em vez de `conversation_labels` direta. O script `.tmp/diag_label_schema.py` foi criado para verificar isso. Executar antes de implementar.

**Comportamento esperado**:
- Remapear `conversation_id` via migration_state
- Remapear `label_id` (ou usar `label_title` como string — verificar schema)
- Skip se `conversation_id` orphan
- `ON CONFLICT DO NOTHING` para idempotência

---

### TAREFA 5 — FIX-05: Implementar CustomAttributeDefinitionsMigrator

**Arquivo novo**: `src/migrators/custom_attribute_definitions_migrator.py`

**Tabela**: `custom_attribute_definitions` — schema: `(id, account_id, attribute_display_name, attribute_key, attribute_model, attribute_display_type, ...)`

**Comportamento**:
- Dedup por `(account_id_dest, attribute_key)` para contas merged
- Remapear `id` via offset_custom_attribute_definitions
- Remapear `account_id` via id_remapper
- Skip se `account_id` orphan
- Sem campos sensíveis para regenerar

---

### TAREFA 6 — DEC-06: Implementar CannedResponsesMigrator

**Arquivo novo**: `src/migrators/canned_responses_migrator.py`

**Tabela**: `canned_responses` — schema: `(id, account_id, short_code, content)`

**Comportamento**:
- Dedup por `(account_id_dest, short_code)` para contas merged (short_code é o atalho `/código`)
- Remapear `id` via offset
- Remapear `account_id` via id_remapper
- Skip se `account_id` orphan

---

### TAREFA 7 — DEC-07: Implementar WebhooksMigrator

**Arquivo novo**: `src/migrators/webhooks_migrator.py`

**Tabela**: `webhooks` — schema: `(id, account_id, url, subscriptions, webhook_type, ...)`

**Comportamento**:
- Sem dedup (webhooks são configurações únicas por URL — mas em DEV pode duplicar, usar `(account_id_dest, url)`)
- Remapear `id` via offset
- Remapear `account_id` via id_remapper
- Skip se `account_id` orphan
- `url` copiado verbatim (aponta para sistemas externos — aceitável em DEV)

---

### TAREFA 8 — DEC-07: Implementar IntegrationHooksMigrator

**Arquivo novo**: `src/migrators/integration_hooks_migrator.py`

**Tabela**: `integration_hooks` — schema: `(id, account_id, app_id, reference_id, settings, ...)`

**Comportamento**:
- `reference_id` pode ser `inbox_id` (para bots) — remapear se `reference_id` referencia inbox
- Sem dedup simples — usar `(account_id_dest, app_id, reference_id_dest)` como chave
- Remapear `id` via offset
- Remapear `account_id` via id_remapper
- `settings` (JSONB) copiado verbatim — pode conter credenciais de API de bots (aceitável em DEV)
- Skip se `account_id` orphan

> **Verificar**: Se `reference_id` é sempre inbox_id, adicionar remapeamento. Se NULL ou outro tipo, preservar.

---

### TAREFA 9 — Registrar migrators em src/migrar.py

**Arquivo**: `src/migrar.py`

**Alterações necessárias**:
1. Adicionar imports dos 6 novos migrators
2. Atualizar `_MIGRATION_ORDER` para a nova ordem com todas as entidades
3. Atualizar `_MIGRATOR_MAP` com os novos migrators
4. Adicionar as novas tabelas na chamada de `compute_offsets` no IDRemapper (se aplicável)

**Nova `_MIGRATION_ORDER`**:
```python
_MIGRATION_ORDER = [
    "accounts",
    "custom_attribute_definitions",
    "canned_responses",
    "inboxes",
    "webhooks",
    "users",
    "teams",
    "team_members",
    "labels",
    "contacts",
    "contact_inboxes",
    "integration_hooks",
    "conversations",
    "messages",
    "attachments",
    "conversation_labels",
]
```

---

## FASE 2 — Validações SQL Pré-migração

> Executar com `psql` direto no SOURCE. Nenhum resultado problemático deve existir antes de prosseguir.

### PRE-01 — Contar registros por entidade no SOURCE (baseline)
```sql
SELECT 'accounts' AS t, COUNT(*) FROM accounts
UNION ALL SELECT 'inboxes', COUNT(*) FROM inboxes
UNION ALL SELECT 'users', COUNT(*) FROM users
UNION ALL SELECT 'teams', COUNT(*) FROM teams
UNION ALL SELECT 'team_members', COUNT(*) FROM team_members
UNION ALL SELECT 'labels', COUNT(*) FROM labels
UNION ALL SELECT 'contacts', COUNT(*) FROM contacts
UNION ALL SELECT 'contact_inboxes', COUNT(*) FROM contact_inboxes
UNION ALL SELECT 'conversations', COUNT(*) FROM conversations
UNION ALL SELECT 'messages', COUNT(*) FROM messages
UNION ALL SELECT 'attachments', COUNT(*) FROM attachments
UNION ALL SELECT 'conversation_labels', COUNT(*) FROM conversation_labels
UNION ALL SELECT 'canned_responses', COUNT(*) FROM canned_responses
UNION ALL SELECT 'webhooks', COUNT(*) FROM webhooks
UNION ALL SELECT 'integration_hooks', COUNT(*) FROM integration_hooks
UNION ALL SELECT 'custom_attribute_definitions', COUNT(*) FROM custom_attribute_definitions;
```
**Ação**: Documentar resultado. Usar como referência para POS-01.

---

### ⛔ PRE-02 — BLOQUEADOR: Verificar channel_types no SOURCE
```sql
SELECT DISTINCT channel_type, COUNT(*) AS qty
FROM inboxes
GROUP BY channel_type
ORDER BY qty DESC;
```
**Critério de aprovação**: Todos os valores devem estar na lista:
`Channel::WebWidget`, `Channel::Api`, `Channel::FacebookPage`, `Channel::Telegram`, `Channel::Email`, `Channel::TwilioSms`, `Channel::Whatsapp`, `Channel::Line`, `Channel::Sms`

**Se aparecer tipo desconhecido**: BUG-A se materializa — inbox ficará invisível. Avaliar antes de prosseguir.

---

### PRE-03 — Verificar contas com nomes colisionando SOURCE vs DEST
```sql
-- Executar no SOURCE
SELECT name FROM accounts;
-- Cruzar manualmente com DEST: SELECT name FROM accounts;
```
**Esperado**: Apenas "Vya Digital" (e possivelmente outros que devem ser merged) colidem. Documentar lista completa.

---

### PRE-04 — Distribuição de phone_number (RISCO-B)
```sql
SELECT
  COUNT(*) FILTER (WHERE phone_number IS NOT NULL AND phone_number LIKE '+%') AS com_prefixo,
  COUNT(*) FILTER (WHERE phone_number IS NOT NULL AND phone_number NOT LIKE '+%') AS sem_prefixo,
  COUNT(*) FILTER (WHERE phone_number IS NULL) AS nulo
FROM contacts;
```
**Ação**: Documentar. Alta proporção "sem_prefixo" implica dedup falho para contatos que existem no DEST com formato diferente.

---

### PRE-05 — Verificar schema de conversation_labels (antes de FIX-04)
```sql
-- Verificar se existe tabela conversation_labels
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN ('conversation_labels', 'taggings', 'conversations_labels')
ORDER BY table_name, ordinal_position;
```
**Ação**: Resultado determina o schema correto para implementar FIX-04.

---

### PRE-06 — Verificar schema de team_members
```sql
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'team_members'
ORDER BY ordinal_position;
```

---

### PRE-07 — Verificar schema de integration_hooks
```sql
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'integration_hooks'
ORDER BY ordinal_position;

-- Verificar se reference_id referencia inboxes
SELECT DISTINCT app_id, reference_id IS NOT NULL AS has_reference
FROM integration_hooks;
```

---

## FASE 3 — Execução da Migração

### 3.1 — Dry-run completo
```bash
uv run python -m src.migrar --dry-run --verbose 2>&1 | tee .tmp/dryrun_$(date +%Y%m%d_%H%M%S).log
```
**Verificar no log**:
- Nenhum `sys.exit(3)` em accounts
- Contagens de `skipped` razoáveis (dedup de contas merged)
- Zero `WARNING: channel_id kept as SOURCE value` (PRE-02 deve ter passado)
- Novos migrators aparecem na sequência

---

### 3.2 — Execução real
```bash
uv run python -m src.migrar --verbose 2>&1 | tee .tmp/migration_$(date +%Y%m%d_%H%M%S).log
```
**Monitorar durante execução**:
- Exit code: `echo $?` — esperado `0` (success) ou `1` (falhas parciais aceitáveis); `3` = abort
- Warnings de `orphan` acumulados → documentar
- Tamanho estimado: accounts(5) → inboxes(~Nx) → users → ... → messages(310k) → attachments(27k)

---

### 3.3 — Script separado: inbox_members
```bash
uv run python app/13_migrar_inbox_members.py
```
**Executar obrigatoriamente APÓS o pipeline principal** e ANTES de subir o container.

---

### 3.4 — Corrigir pubsub_token em contact_inboxes (RISCO-C)
Executar no DEST via psql **após** a migração e **antes** de subir o container:
```sql
UPDATE contact_inboxes
SET pubsub_token = encode(gen_random_bytes(32), 'hex')
WHERE pubsub_token IS NULL;
```
**Justificativa**: `pubsub_token` NULL em `contact_inboxes` causa ausência de push WebSocket em tempo real para todas as conversas migradas.

---

## FASE 4 — Validações Pós-migração

> Executar no DEST **antes de subir o container**. Todos os critérios devem ser atendidos.

### ⛔ POS-01 — Inboxes com channel_id inválido (BUG-A)
```sql
SELECT i.id, i.channel_type, i.channel_id, i.name
FROM inboxes i
WHERE NOT EXISTS (
  SELECT 1 FROM channel_web_widgets WHERE id = i.channel_id AND i.channel_type = 'Channel::WebWidget'
  UNION ALL SELECT 1 FROM channel_api WHERE id = i.channel_id AND i.channel_type = 'Channel::Api'
  UNION ALL SELECT 1 FROM channel_facebook_pages WHERE id = i.channel_id AND i.channel_type = 'Channel::FacebookPage'
  UNION ALL SELECT 1 FROM channel_telegram WHERE id = i.channel_id AND i.channel_type = 'Channel::Telegram'
  UNION ALL SELECT 1 FROM channel_email WHERE id = i.channel_id AND i.channel_type = 'Channel::Email'
  UNION ALL SELECT 1 FROM channel_twilio_sms WHERE id = i.channel_id AND i.channel_type = 'Channel::TwilioSms'
  UNION ALL SELECT 1 FROM channel_whatsapp WHERE id = i.channel_id AND i.channel_type = 'Channel::Whatsapp'
  UNION ALL SELECT 1 FROM channel_sms WHERE id = i.channel_id AND i.channel_type = 'Channel::Sms'
);
```
**Critério**: Zero registros.

---

### ⛔ POS-02 — Inboxes duplicados por nome/canal para mesma conta (BUG-B check)
```sql
SELECT account_id, name, channel_type, COUNT(*) AS qty
FROM inboxes
GROUP BY account_id, name, channel_type
HAVING COUNT(*) > 1;
```
**Critério**: Zero registros. Se houver duplicatas, FIX-01 não funcionou.

---

### POS-03 — Conversas com inbox_id FK inválido
```sql
SELECT COUNT(*) AS orphan_conversations
FROM conversations c
WHERE NOT EXISTS (SELECT 1 FROM inboxes i WHERE i.id = c.inbox_id);
```
**Critério**: Zero.

---

### POS-04 — Contagem de conversas com contact_inbox_id NULL
```sql
SELECT
  COUNT(*) AS total_conversations,
  COUNT(*) FILTER (WHERE contact_inbox_id IS NULL) AS sem_contact_inbox,
  ROUND(100.0 * COUNT(*) FILTER (WHERE contact_inbox_id IS NULL) / COUNT(*), 2) AS pct_null
FROM conversations;
```
**Critério**: Documentar. Alta % indica problema no fallback de contact_inbox_id.

---

### POS-05 — Teams com zero membros (FIX-03 check)
```sql
SELECT t.id, t.name, t.account_id, COUNT(tm.user_id) AS member_count
FROM teams t
LEFT JOIN team_members tm ON tm.team_id = t.id
GROUP BY t.id, t.name, t.account_id
HAVING COUNT(tm.user_id) = 0;
```
**Critério**: Documentar. Times sem membros existentes no SOURCE não devem existir no DEST.

---

### POS-06 — Contagem total por entidade (comparar com PRE-01)
```sql
-- Mesma query do PRE-01 — executar no DEST e comparar
SELECT 'accounts' AS t, COUNT(*) FROM accounts
UNION ALL SELECT 'inboxes', COUNT(*) FROM inboxes
-- ... (mesma lista do PRE-01)
```
**Critério**: Totais DEST ≥ totais DEST pré-migração + totais SOURCE migrados. Documentar delta.

---

### POS-07 — display_id único por account
```sql
SELECT account_id, display_id, COUNT(*) AS qty
FROM conversations
GROUP BY account_id, display_id
HAVING COUNT(*) > 1;
```
**Critério**: Zero registros.

---

### POS-08 — pubsub_token NULL após UPDATE
```sql
SELECT COUNT(*) AS null_pubsub FROM contact_inboxes WHERE pubsub_token IS NULL;
```
**Critério**: Zero (confirmação do UPDATE da fase 3.4).

---

### POS-09 — Contagem de migration_state por tabela
```sql
SELECT tabela, status, COUNT(*) AS qty
FROM migration_state
GROUP BY tabela, status
ORDER BY tabela, status;
```
**Critério**: Documentar. `status='migrated'` deve cobrir todos os registros. `status='failed'` deve ser zero ou explicado.

---

## FASE 5 — Ativação do DEST

### 5.1 — Iniciar container
```bash
# No servidor (ou docker-compose)
docker start vya-chat-dev
# ou
docker-compose up -d chatwoot
```

### 5.2 — Verificar saúde da aplicação
```bash
# Aguardar ~30s para Rails inicializar
curl -s https://vya-chat-dev.vya.digital/auth/sign_in | head -c 200
```

### 5.3 — Executar validação via API
```bash
make validate-api-counts
```
**Critério**: `api_conv` ≥ contagem DB para account_id=1. Exit 0.

### 5.4 — Teste manual de visibilidade
- Logar como administrator em `vya-chat-dev.vya.digital`
- Verificar que inboxes aparecem no seletor lateral
- Verificar que conversas migradas aparecem por inbox
- Logar como agent (verificar inbox_members configurados por app/13)
- Verificar que agent vê conversas de seus inboxes

---

## Resumo de Arquivos a Criar/Editar

| Arquivo | Tipo | Tarefa |
|---|---|---|
| `src/migrators/teams_migrator.py` | Editar | FIX-02: condição dedup |
| `src/migrators/labels_migrator.py` | Editar | FIX-02: condição dedup |
| `src/migrators/inboxes_migrator.py` | Editar | FIX-01: bloco dedup BUG-B |
| `src/migrators/team_members_migrator.py` | Criar | FIX-03 |
| `src/migrators/conversation_labels_migrator.py` | Criar | FIX-04 |
| `src/migrators/custom_attribute_definitions_migrator.py` | Criar | FIX-05 |
| `src/migrators/canned_responses_migrator.py` | Criar | DEC-06 |
| `src/migrators/webhooks_migrator.py` | Criar | DEC-07 |
| `src/migrators/integration_hooks_migrator.py` | Criar | DEC-07 |
| `src/migrar.py` | Editar | Registrar todos os novos migrators |

---

## Ordem de Execução das Tarefas de Código

```
1. Executar PRE-05, PRE-06, PRE-07 (verificar schemas) → informa FIX-04 e FIX-08
2. FIX-02 (mais simples, sem dependência)
3. FIX-01 (mais complexo, base para teste de integração)
4. FIX-03, FIX-04, FIX-05 (novos migrators simples)
5. DEC-06, DEC-07 (novos migrators)
6. TAREFA 9 (registrar em migrar.py — último, após todos os migrators criados)
7. uv run pytest (verificar sem regressões)
8. Iniciar FASE 2 (validações SQL)
9. FASE 3 (execução)
```

---

*Plano gerado em 2026-04-24 com base em D13, D11, D12, D10 e decisões DEC-01 a DEC-07.*
