# D8 — Análise Completa: HTTP 404 na API Chatwoot + Inboxes Invisíveis

**Data**: 2026-04-23
**Status**: RESOLVIDO (código corrigido, DB restaurado — pronto para nova migração)
**Autores**: diagnose via GitHub Copilot (Claude Sonnet 4.6)
**Referências**: D5, D6, D7; app/10_validar_api.py; app/12–16_diagnostico_*.py

---

## 1. Contexto

Durante a validação pós-migração (`make validate-api-deep SAMPLE=5 MAX_MSGS=50`),
dois problemas críticos foram identificados:

| Sintoma | Impacto |
|---------|---------|
| HTTP 404 para **todas** as conversas migradas (309/309) | Validação de API falha totalmente |
| Apenas **18/32 inboxes** visíveis na API (14 invisíveis) | Inboxes migrados inacessíveis |

O banco `chatwoot004_dev1_db` foi **restaurado** ao estado original antes de
qualquer correção manual.

---

## 2. Ambiente

| Item | Valor |
|------|-------|
| Chatwoot versão | v3.9.0 |
| Rails | 7.0.8.1 |
| PostgreSQL | 16.10 @ `wfdb02.vya.digital:5432` |
| SOURCE | `chatwoot_dev1_db` = chat.vya.digital |
| DEST | `chatwoot004_dev1_db` = synchat.vya.digital (API: vya-chat-dev.vya.digital) |
| Account ID | 1 (Vya Digital) |
| API Base | `https://vya-chat-dev.vya.digital/api/v1` |
| API Token | user_id=1 (admin@vya.digital, role=administrator) |

---

## 3. Estado do DEST após restore

| Tabela | Contagem |
|--------|---------|
| `inboxes` (account_id=1) | **18** (pré-existentes) |
| `conversations` (account_id=1) | **378** (pré-existentes) |
| `channel_web_widgets` (account_id=1) | **3** |
| `channel_api` (account_id=1) | **13** |
| `migration_state` | ✗ não existe |

---

## 4. Root Cause 1 — BUG-05: InboxesMigrator não migra channel records

### 4.1 Descrição técnica

A tabela `inboxes` tem uma associação polimórfica Rails:
```ruby
# app/models/inbox.rb
belongs_to :channel, polymorphic: true, dependent: :destroy
```

Isso significa que cada inbox possui:
- `channel_type` → indica qual tabela de canal (ex: `"Channel::WebWidget"`)
- `channel_id`   → FK para o registro de canal nessa tabela

**Antes da correção**, o `InboxesMigrator.remap_fn` apenas remapeava `id` e
`account_id`, copiando `channel_id` verbatim do SOURCE:

```python
return {
    **row,
    "id": self.id_remapper.remap(int(row["id"]), "inboxes"),
    "account_id": self.id_remapper.remap(account_id_origin, "accounts"),
    # channel_id copiado sem remapear ← BUG
}
```

### 4.2 Consequência no DEST

Os 14 inboxes migrados do SOURCE tinham `channel_id` = {1, 2, 9, 10, 16, 17, 18,
20, 21, 43, 52, 68} (IDs do SOURCE). Em DEST:

- Esses channel_ids **não existiam** nas tabelas de canal (nenhum `channel_web_widgets.id=1`, etc.)
- OU **colidiram** com canais pré-existentes de outros inboxes (ex: `channel_id=20` pertencia ao inbox 216)

### 4.3 Impacto na API Chatwoot

Cadeia de chamadas Rails (v3.9.0):

```
GET /api/v1/accounts/1/inboxes
  → InboxesController#index
  → policy_scope(Current.account.inboxes.order_by_name.includes(:channel, ...))
  → InboxPolicy::Scope#resolve → user.assigned_inboxes
  → administrator? → Current.account.inboxes (todos os 32)
  → includes(:channel) carrega os channel records de forma eager
  → Jbuilder serializa: inbox.channel.website_token (Channel::WebWidget)
                          inbox.channel.identifier   (Channel::Api)
                          inbox.inbox_type → channel.name
  → Se channel = nil → NoMethodError → inbox OMITIDO da resposta
```

**Confirmação via diagnóstico**: Todos os 5 tokens de administrator testados
retornaram exatamente os mesmos 18 inboxes — confirmando que é um filtro de dados,
não de permissão:

```json
"user_1_admin@vya.digital":   { "count": 18, "ids": [...] }
"user_3_michele.nunes":       { "count": 18, "ids": [...] }  ← mesmo admin, mesmo resultado
"user_4_anselmo.nunes":       { "count": 18, "ids": [...] }
```

### 4.4 Detalhe dos 14 inboxes invisíveis

| Inbox ID | Nome (SOURCE) | channel_type | channel_id (SOURCE) | Problema DEST |
|----------|---------------|-------------|---------------------|---------------|
| 399→* | Atendimento Web | Channel::WebWidget | 1 | channel record não existe |
| 403→* | La Pizza | Channel::WebWidget | 2 | channel record não existe |
| 409→* | vya.digital | Channel::FacebookPage | 1 | channel record não existe |
| 428→* | AtendimentoVYADIgital | Channel::Api | 18 | channel record não existe |
| 430→* | vya.digital - apresentação | Channel::WebWidget | 9 | channel record não existe |
| 435→* | Chatbot SDR | Channel::WebWidget | 10 | channel record não existe |
| 449→* | VyaDigitalBot Telegram | Channel::Telegram | 2 | channel record não existe |
| 480→* | Vya Lab | Channel::WebWidget | 16 | channel record não existe |
| 481→* | 551131357298 | Channel::Api | 43 | channel record não existe |
| 485→* | Grupo Caelitus | Channel::WebWidget | 17 | channel record não existe |
| 499→* | 5535988628436 | Channel::Api | 52 | channel record não existe |
| 518→* | Agente IA - SDR | Channel::WebWidget | 20 | **CONFLITO**: channel_id=20 já usado pelo inbox 216 |
| 519→* | Agente de Negociação | Channel::WebWidget | 21 | **CONFLITO**: channel_id=21 já usado pelo inbox 365 |
| 521→* | wea004 | Channel::Api | 68 | channel record não existe |

*IDs no DEST variavam conforme execução (offset shift)

### 4.5 Correção implementada (BUG-05 FIX)

Arquivo: `src/migrators/inboxes_migrator.py`

**Abordagem**: Método `_migrate_channels()` executado **antes** de `_run_batches`.

```python
# Fluxo da correção:
# 1. Coleta todos os (channel_type, channel_id) únicos do SOURCE
# 2. Para cada par, busca o registro de canal no SOURCE
# 3. Obtém novo ID via nextval(sequence) no DEST
# 4. Remapeia account_id usando o IDRemapper
# 5. Regenera campos únicos/sensíveis:
#    - channel_web_widgets.website_token  → secrets.token_urlsafe(18)
#    - channel_api.identifier             → secrets.token_urlsafe(24)
#    - channel_api.hmac_token             → secrets.token_urlsafe(24)
# 6. Insere o registro de canal no DEST
# 7. Retorna mapa {(channel_type, src_id): dest_id}
#
# No remap_fn dos inboxes:
#    new_row["channel_id"] = channel_id_map[(channel_type, src_channel_id)]
```

Tipos de canal suportados:

| channel_type | Tabela DEST | Seq | Campos regenerados |
|-------------|-------------|-----|--------------------|
| Channel::WebWidget | channel_web_widgets | channel_web_widgets_id_seq | website_token |
| Channel::Api | channel_api | channel_api_id_seq | identifier, hmac_token |
| Channel::FacebookPage | channel_facebook_pages | channel_facebook_pages_id_seq | — |
| Channel::Telegram | channel_telegram | channel_telegram_id_seq | — |
| Channel::Email | channel_email | channel_email_id_seq | — |
| Channel::TwilioSms | channel_twilio_sms | channel_twilio_sms_id_seq | — |
| Channel::Whatsapp | channel_whatsapp | channel_whatsapp_id_seq | — |
| Channel::Line | channel_line | channel_line_id_seq | — |
| Channel::Sms | channel_sms | channel_sms_id_seq | — |

---

## 5. Root Cause 2 — BUG-06: ConversationsMigrator não remapeia `contact_inbox_id`

### 5.1 Descrição técnica

A tabela `conversations` possui a coluna `contact_inbox_id` (FK para
`contact_inboxes.id`). O Chatwoot usa esse vínculo para encontrar conversas via
API:

```
GET /api/v1/accounts/1/conversations/:id
  → ConversationsController#show
  → @conversation = Current.account.conversations.find_by(display_id: params[:id])
  → Ou via contact_inbox_id para validação de acesso
```

**Antes da correção**, `remap_fn` não remapeava `contact_inbox_id`:

```python
new_row = dict(row)  # copia contact_inbox_id verbatim do SOURCE ← BUG
new_row["id"] = self.id_remapper.remap(id_origin, "conversations")
new_row["account_id"] = ...
new_row["inbox_id"] = ...
# contact_inbox_id = SOURCE ID (ex: 47) → não existe em DEST ← CAUSA DO 404
```

### 5.2 Diagnóstico

Scripts executados: `app/14_verificar_conv_marcos.py`, `.tmp/diagnose_inbox_plan_limits.py`

Resultado: **309/309** conversas migradas tinham `contact_inbox_id` inválido:
- 43 tinham uma correspondência findável por `(contact_id, inbox_id)` no DEST
- 266 precisavam de INSERT em `contact_inboxes` antes do UPDATE

### 5.3 Correção implementada (BUG-06 FIX)

Arquivo: `src/migrators/conversations_migrator.py`

**Abordagem**: Remapeamento com triplo fallback em `remap_fn`.

```python
# Pré-carregado no início de migrate():
migrated_contact_inboxes = state_repo.get_migrated_ids(conn, "contact_inboxes")
_dest_ci_pairs = {
    (contact_id, inbox_id): ci_id
    for (contact_id, inbox_id, ci_id) in conn.execute(
        text("SELECT contact_id, inbox_id, id FROM contact_inboxes")
    ).fetchall()
}

# Em remap_fn:
# 1. ci_origin in migrated_contact_inboxes → id_remapper.remap(ci_origin, "contact_inboxes")
# 2. else → busca (dest_contact_id, dest_inbox_id) em _dest_ci_pairs
# 3. else → NULL + WARNING
```

**Nota**: O `_dest_ci_pairs` captura todos os `contact_inboxes` já em DEST no
momento em que `ConversationsMigrator.migrate()` é chamado — incluindo os
recém-inseridos pelo `ContactInboxesMigrator` na mesma execução (pois
`ContactInboxesMigrator` roda antes de `ConversationsMigrator` na ordem
`_MIGRATION_ORDER`).

---

## 6. Fluxo completo de chamada Chatwoot (para referência)

```
InboxesController#index
  ↓
policy_scope(
  Current.account.inboxes
    .order_by_name              ← scope: ORDER BY lower(name) ASC
    .includes(:channel, :agent_bot_inbox, :webhooks, :agent_bot)
)
  ↓
InboxPolicy::Scope#resolve
  → scope.none  (agents sem inbox_members)
  → user.assigned_inboxes
      → administrator? → Current.account.inboxes  (todos)
      → agent        → inboxes WHERE inbox_members.user_id = current_user.id
  ↓
Current.account.inboxes
  → Account.find(params[:account_id]).inboxes
  → has_many :inboxes, dependent: :destroy_async  (sem scope extra)
  ↓
includes(:channel) — polimórfico Rails:
  SELECT * FROM inboxes WHERE account_id=1
  SELECT * FROM channel_web_widgets WHERE id IN (...)
  SELECT * FROM channel_api WHERE id IN (...)
  SELECT * FROM channel_facebook_pages WHERE id IN (...)
  ...
  → inbox.channel = nil se registro não encontrado
  ↓
Jbuilder serializa:
  inbox_type = channel.name          → nil.name → NoMethodError
  website_token = channel.website_token  → omitido silenciosamente
  ↓
Inbox com channel=nil → OMITIDO da resposta JSON
```

---

## 7. Arquivos de diagnóstico gerados

| Arquivo | Propósito |
|---------|-----------|
| `.tmp/diagnose_api_user_inboxes_20260423_125048.json` | Confirma user_id=1 é admin, sim_admin=32 |
| `.tmp/diagnose_inbox_visibility_20260423_140655.json` | channel_exists por inbox |
| `.tmp/diagnose_inbox_count_api_20260423_141319.json` | 18 inboxes para todos os admins; canais com NULL tokens |
| `.tmp/check_user_role.py` | Confirma role=1 para user_id=1 em account_id=1 |
| `.tmp/check_channel_conflicts.py` | Conflito channel_id=20/21 entre inboxes 518/519 |
| `.tmp/diagnose_inbox_plan_limits.py` | 309/309 contact_inbox_id inválidos |

---

## 8. Arquivos corrigidos

### `src/migrators/inboxes_migrator.py`

| Mudança | Detalhe |
|---------|---------|
| Adicionado `_CHANNEL_CFG` | Mapeamento channel_type → (tabela, sequência, campos a regenerar) |
| Adicionado `_migrate_channels()` | Migra todos os channel records antes dos inboxes |
| `remap_fn` atualizado | Usa `channel_id_map[(type, src_id)]` para remapear `channel_id` |
| Segurança | `website_token`, `identifier`, `hmac_token` regenerados com `secrets.token_urlsafe()` |

### `src/migrators/conversations_migrator.py`

| Mudança | Detalhe |
|---------|---------|
| Pré-carregamento | `migrated_contact_inboxes` e `_dest_ci_pairs` carregados no início de `migrate()` |
| `remap_fn` atualizado | Remapeia `contact_inbox_id` com triplo fallback |

---

## 9. Questões abertas (ver Seção 10)

1. Credenciais de Facebook/Telegram migradas do SOURCE: válidas ou inválidas?
2. Estratégia para inboxes já existentes em DEST com mesmo nome do SOURCE?
3. S3 attachments: bucket acessível do DEST?

---

## 10. Próximos passos

```bash
# 1. Executar migração completa com as correções
python src/migrar.py --verbose

# 2. Verificar inboxes visíveis na API
curl -H "api_access_token: 5to6j4U3rhpsEVJcEQWHKFXJ" \
     https://vya-chat-dev.vya.digital/api/v1/accounts/1/inboxes | jq '.payload | length'
# Esperado: 32 (18 pré-existentes + 14 migrados)

# 3. Verificar conversas via API
make validate-api-deep SAMPLE=5 MAX_MSGS=50
# Esperado: conversations_found_api > 0
```

---

## 11. Histórico de investigação

| Data | Descoberta |
|------|-----------|
| 2026-04-22 | D7: visibilidade de conversas do Marcus (contact_inbox_id) |
| 2026-04-23 09h | Confirmado: user_id=1 é administrator em account_id=1 |
| 2026-04-23 12h | 309/309 contact_inbox_id inválidos; 43 fixáveis, 266 precisam INSERT |
| 2026-04-23 13h | Rastreamento da call chain Chatwoot: InboxPolicy→assigned_inboxes |
| 2026-04-23 14h | 18 inboxes para TODOS os admins → filtro de dados, não permissão |
| 2026-04-23 14h30 | channel_web_widgets.website_token=NULL → omitido no Jbuilder |
| 2026-04-23 15h | DB restaurado; código corrigido (BUG-05 + BUG-06) |
