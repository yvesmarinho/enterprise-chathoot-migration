# D11 — Debate: Inboxes Migrados Invisíveis na API (2026-04-24)

**Data**: 2026-04-24
**Status**: ✅ RESOLVIDO — Causa raiz identificada
**Autor**: enterprise-chatwoot-migration / session-10

---

## 1. Contexto

Após a execução completa do pipeline de migração (FASE 3 + 4), os 13 inboxes migrados
para `chatwoot004_dev1_db` (IDs 399–519, `account_id=1`) **não apareciam** na UI nem na API
de `vya-chat-dev.vya.digital`.

**Universo de trabalho confirmado:**

| Papel | DB | Site |
|-------|----|------|
| SOURCE | `chatwoot_dev1_db` | `chat.vya.digital` |
| DEST | `chatwoot004_dev1_db` | `vya-chat-dev.vya.digital` |
| Produção separada | — | `synchat.vya.digital` (NÃO usar como referência de DEST) |

---

## 2. Sintoma

```
GET /api/v1/accounts/1/inboxes  →  retorna 18 inboxes (apenas pré-existentes)
GET /api/v1/accounts/1/inboxes/399  →  HTTP 404
GET /api/v1/accounts/1/inboxes/145  →  HTTP 200  (inbox pré-existente)
```

Todos os 13 inboxes migrados (id > 396) retornam 404. Os 18 pré-existentes retornam 200.

---

## 3. Hipóteses Investigadas

### H1 — Registros de canal inválidos/ausentes ❌ ELIMINADA
Verificação: todos os 13 inboxes possuem registro de canal correto com `account_id=1`:
- `channel_web_widgets` ids 25, 26, 28, 29, 30, 31, 32, 33 — presentes, `account_id=1`
- `channel_api` ids 356, 357, 358 — presentes, `account_id=1`
- `channel_telegram` id 6 — presente, `account_id=1`
- `channel_facebook_pages` id 2 — presente, `account_id=1`

### H2 — Admin não é membro dos inboxes ❌ ELIMINADA
`admin@vya.digital` (`user_id=1`) é **administrador global em TODAS as instâncias Chatwoot** (confirmado pelo operador do sistema). Tem `role=1` em todos os accounts de `chatwoot004_dev1_db`. Administradores Chatwoot visualizam todos os inboxes da instância independentemente de vínculos em `inbox_members` — esta regra é aplicada pelo `PermissionFilterService` do Chatwoot.

### H3 — account_users ausente ❌ ELIMINADA
`user_id=1` está em `account_users` com `role=1` para `account_id=1` em `chatwoot004_dev1_db`.
Admin presente em 21 accounts neste banco. Como `admin@vya.digital` é administrador global de todas as instâncias, a ausência de `account_users` seria improvável — mas foi verificada e confirmada presente.

### H4 — Row Level Security bloqueando ❌ ELIMINADA
`rowsecurity=False` em todas as tabelas. Zero políticas RLS no schema public.
`chatwoot_user` possui GRANT completo em todas as tabelas e sequences.

### H5 — Diferenças em flags de coluna ❌ ELIMINADA
Comparação entre inboxes pré-existentes (visíveis) e migrados: nenhuma diferença
discriminante em `enable_auto_assignment`, `working_hours_enabled`, `out_of_office_message`,
`channel_type` ou outros campos booleanos/status.

---

## 4. Causa Raiz — H-NEW ✅ CONFIRMADA

### Evidência A — `account_id=44` retornado pelo perfil
```
GET https://vya-chat-dev.vya.digital/api/v1/profile
→ { "account_id": 44, ... }
```

### Evidência B — `account_id=44` não existe no DEST correto
```sql
-- chatwoot004_dev1_db
SELECT id, name FROM accounts WHERE id = 44;
-- (0 rows)
```

### Evidência C — `account_id=44` existe em outro banco
```sql
-- chatwoot004_dev_db  (banco ERRADO)
SELECT id, name FROM accounts WHERE id = 44;
-- id=44, name='Sol Copernico'
```

### Evidência D — Contagem de inboxes bate com API
```sql
-- chatwoot004_dev_db
SELECT COUNT(*) FROM inboxes WHERE account_id = 1;
-- → 18  (igual ao retornado pela API)

-- chatwoot004_dev_db
SELECT COUNT(*) FROM inboxes WHERE id > 396 AND account_id = 1;
-- → 0  (inboxes migrados NÃO estão aqui)

-- chatwoot004_dev1_db
SELECT COUNT(*) FROM inboxes WHERE account_id = 1;
-- → 31  (18 pré-existentes + 13 migrados = o estado correto pós-migração)
```

### Conclusão

> **O container `vya-chat-dev.vya.digital` está conectado ao banco `chatwoot004_dev_db`
> (incorreto), não ao `chatwoot004_dev1_db` (correto).**

A migração está correta e completa no banco certo (`chatwoot004_dev1_db`).
O problema é exclusivamente de configuração do container/ambiente.

---

## 5. Correção Necessária

### Passo 1 — Atualizar variável de ambiente do container
No servidor onde roda o container/processo `vya-chat-dev.vya.digital`:

```bash
# Localizar o arquivo .env ou docker-compose.yml
# Alterar:
POSTGRES_DATABASE=chatwoot004_dev_db
# Para:
POSTGRES_DATABASE=chatwoot004_dev1_db
```

O arquivo de referência correto já existe no projeto:
```
docs/vya-chat-dev-env.txt  →  POSTGRES_DATABASE=chatwoot004_dev1_db  ✅
```

### Passo 2 — Reiniciar o serviço
```bash
# Docker Compose
docker compose down && docker compose up -d

# Ou systemd
systemctl restart chatwoot
```

### Passo 3 — Verificar após reinício
```bash
curl -s -H "api_access_token: 5to6j4U3rhpsEVJcEQWHKFXJ" \
  https://vya-chat-dev.vya.digital/api/v1/accounts/1/inboxes \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d['payload']), 'inboxes')"
# Esperado: 31 inboxes
```

---

## 6. Estado Pós-Correção Esperado

| Métrica | Antes (bug) | Depois (fix) |
|---------|-------------|--------------|
| Inboxes visíveis na API | 18 | 31 |
| Inboxes migrados visíveis | 0 | 13 |
| `account_id` em `/profile` | 44 | 1 |
| DB efetivo do container | `chatwoot004_dev_db` | `chatwoot004_dev1_db` |

---

## 7. Dados Coletados

- `.tmp/d11_coleta_20260424_121538.json` — diagnóstico inicial dos 13 inboxes
- `.tmp/d11_diag_canais.py` / resultado — 0 problemas em channel records
- `.tmp/d11_diag_apikey.py` / resultado — admin confirmado, role=1 em account_id=1
- `.tmp/d11_diag_flags.py` / resultado — sem diferenças discriminantes em flags
- `.tmp/d11_diag_api_direta.py` / resultado — todos os 13 migrados retornam 404, perfil retorna account_id=44
