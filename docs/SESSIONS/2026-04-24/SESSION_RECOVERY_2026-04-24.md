# 🔄 Session Recovery — 2026-04-24

**Branch**: `001-enterprise-chatwoot-migration`
**Sessão**: SESSION-2026-04-24 (Sessão 10)
**Início**: 09:xx
**Status anterior**: 🟡 BLOQUEADO — aguardando token API de administrator + BUG-05 pendente

---

## Resumo de Contexto Recuperado

### Estado do Projeto

- **DB DEST** (`chatwoot004_dev1_db`): **restaurado** ao estado pré-migração para `account_id=1` após diagnóstico D8
  - `account_id=1` (Vya Digital): 378 conversas pré-existentes, 18 inboxes pré-existentes
  - `account_id=17, 47, 61, 68`: mantidos com migrações executadas anteriormente
- **Migrações executadas**: Pipeline completo (RUN-20260416, 311.539 registros) mas `account_id=1` foi restaurado
- **Root cause confirmado (D9)**: `PermissionFilterService` filtra agents por `inbox_id IN inbox_members`
  - Token atual é `role=agent` → 13 inboxes migrados com `inbox_members=0` → 309 conversas invisíveis
- **BUG-05 identificado (D8)**: `InboxesMigrator` não migra channel records (tabelas `channel_web_widgets`, `channel_api`, etc.)
  - 14 inboxes migrados com `channel_id` verbatim do SOURCE (não existe no DEST) → inboxes invisíveis na API
  - D8 diz "código corrigido" mas validar no código-fonte se fix foi commitado

---

## Bugs Conhecidos — Estado Atual

| Bug | Descrição | Status |
|-----|-----------|--------|
| BUG-05 | InboxesMigrator não migra channel records | ⚠️ VERIFICAR se corrigido |
| BUG-A | `pubsub_token` warning silenciado | ✅ Corrigido (91f2fba) |
| BUG-B | `api_conv=-1` → `meta.all_count` | ✅ Corrigido (91f2fba) |
| Endpoint | `synchat` → `vya-chat-dev` em `_load_api_config()` | ✅ Corrigido (91f2fba) |

---

## Bloqueadores Ativos

1. **TOKEN-ADMIN**: Token API de `administrator` para `account_id=1`
   - Usuário sugerido: `admin@vya.digital` (user_id=1)
   - Adicionar em `.secrets/generate_erd.json` chave `"vya-chat-dev-admin"`
   - Reexecutar `make validate-api` → esperado `api_conv=687`

2. **BUG-05**: InboxesMigrator precisa migrar channel records antes de re-executar migração para `account_id=1`

---

## O que fazer PRIMEIRO nesta sessão

```
1. VERIFICAR BUG-05 no código:
   - Ler src/migrators/inboxes_migrator.py
   - Verificar se channel records (channel_web_widgets, channel_api, etc.) estão sendo migrados
   - Se NÃO → implementar fix

2. SE BUG-05 CORRIGIDO → RE-EXECUTAR MIGRAÇÃO account_id=1:
   - make migrate ou PYTHONPATH=. python3 src/migrar.py --account 1
   - Verificar que 309 conversas + 14 inboxes migrados com channel records

3. VALIDAR via API:
   - Com token admin: make validate-api → api_conv=687 esperado
   - Com token agent após adicionar inbox_members → api_conv=687 esperado

4. RESPONDER Q1 (se cliente disponível):
   - Q-A1: Facebook token válido?
   - Q-A2: Telegram bot reutilizado ou novo?
   - Q-A3: Webhooks atualizar para DEST?
```

---

## Contexto Técnico

| Item | Valor |
|------|-------|
| DB SOURCE | `chatwoot_dev1_db` @ `wfdb02.vya.digital:5432` (export `chat.vya.digital`) |
| DB DEST | `chatwoot004_dev1_db` @ `wfdb02.vya.digital:5432` (export `synchat.vya.digital`) |
| API DEST | `https://vya-chat-dev.vya.digital` (chave `vya-chat-dev` em `.secrets/generate_erd.json`) |
| Branch | `001-enterprise-chatwoot-migration` |
| Último commit | `91f2fba` — encerramento sessão 9 — 2026-04-23 |
| Python env | uv (`pyproject.toml`) |
