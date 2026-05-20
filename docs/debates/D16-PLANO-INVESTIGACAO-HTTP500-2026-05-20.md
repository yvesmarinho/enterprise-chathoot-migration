# 📋 Plano de Investigação — HTTP 500 Conversações Pós-Migração DEV

**Ref Debate**: D16 — `docs/debates/D16-DEBATE-HTTP500-CONVERSACOES-POS-MIGRACAO-2026-05-20.md`
**Data**: 2026-05-20 | **Sessão**: 21
**Ambiente**: DEV — `vya-chat-dev.vya.digital` | `chatwoot004_dev1_db`
**Account**: Unimed Guaxupé — account_id=69, inbox_id=526

---

## Objetivo

Identificar a causa raiz do `HTTP 500 Internal Server Error` ao carregar conversações no Chatwoot após migração DEV bem-sucedida, **sem modificar o banco de dados**, e propor correção.

---

## Fase 1 — Diagnóstico Imediato (read-only)

### TAREFA-D16-01 — Coletar stack trace do Rails

**Prioridade**: P0 — executar primeiro
**Método**: Acessar logs do container Docker no servidor vya-chat-dev

```bash
# SSH no servidor
ssh <servidor-vya-chat-dev>

# Inspecionar log do container Chatwoot
docker ps | grep chatwoot
docker logs <container_name> 2>&1 | grep -B 5 -A 50 "500\|Error\|Exception" | tail -200

# OU verificar logs Rails diretamente no container
docker exec -it <container_name> tail -n 500 /app/log/production.log
```

**Resultado esperado**: Stack trace com o método + linha exata onde o 500 é lançado.
**Output**: Copiar stack trace para `.tmp/D16_rails_stacktrace_YYYYMMDD_HHMMSS.txt`

---

### TAREFA-D16-02 — Script diagnóstico banco DEST

**Prioridade**: P0 — executar em paralelo com D16-01
**Método**: Criar script Python de diagnóstico read-only

Script a criar: `.tmp/D16_diagnostico_500_YYYYMMDD.py`

**Queries a executar**:

**D16-02a** — JSONB `meta` com IDs do SOURCE:
```sql
SELECT c.id, c.display_id,
       c.meta->'sender'->>'id' AS meta_sender_id,
       c.contact_id AS contact_dest_id,
       c.meta->'sender'->>'type' AS meta_sender_type
FROM conversations c
WHERE c.account_id = 69 AND c.inbox_id = 526
  AND c.meta IS NOT NULL AND c.meta->'sender' IS NOT NULL
ORDER BY c.id LIMIT 50;
```

**D16-02b** — `contact_inbox_id` inconsistente (cross-account):
```sql
SELECT c.id, c.contact_inbox_id, ci.inbox_id, ci.account_id
FROM conversations c
JOIN contact_inboxes ci ON ci.id = c.contact_inbox_id
WHERE c.account_id = 69 AND c.inbox_id = 526
  AND ci.inbox_id != 526;
```

**D16-02c** — Sequences vs MAX(id):
```sql
SELECT
    (SELECT last_value FROM conversations_id_seq) AS seq_conversations,
    (SELECT MAX(id) FROM conversations WHERE account_id=69) AS max_conv_id,
    (SELECT last_value FROM messages_id_seq) AS seq_messages,
    (SELECT MAX(id) FROM messages m JOIN conversations c ON c.id=m.conversation_id WHERE c.account_id=69) AS max_msg_id;
```

**D16-02d** — `authentication_token` duplicado:
```sql
SELECT authentication_token, COUNT(*) AS cnt
FROM users
GROUP BY authentication_token
HAVING COUNT(*) > 1;
```

**D16-02e** — Mensagens com `content_type` inválido:
```sql
SELECT content_type, COUNT(*) FROM messages m
JOIN conversations c ON c.id=m.conversation_id
WHERE c.account_id=69 AND c.inbox_id=526
GROUP BY content_type ORDER BY COUNT(*) DESC;
```

**D16-02f** — Query completa simulando o endpoint Rails:
```sql
EXPLAIN ANALYZE
SELECT c.id, c.display_id, c.status, c.last_activity_at,
       co.id AS contact_id, co.name, ci.id AS ci_id, u.id AS assignee_id
FROM conversations c
LEFT JOIN contacts co ON co.id = c.contact_id
LEFT JOIN contact_inboxes ci ON ci.id = c.contact_inbox_id
LEFT JOIN inboxes i ON i.id = c.inbox_id
LEFT JOIN users u ON u.id = c.assignee_id
WHERE c.account_id = 69 AND c.inbox_id = 526
ORDER BY c.last_activity_at DESC LIMIT 25;
```

---

### TAREFA-D16-03 — Verificar migration_state da última execução

**Prioridade**: P1
**Objetivo**: Confirmar que a migração finalizou sem erros silenciosos

```sql
SELECT entity_type, COUNT(*) AS total,
       SUM(CASE WHEN status='migrated' THEN 1 ELSE 0 END) AS migrated,
       SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed,
       SUM(CASE WHEN status='skipped' THEN 1 ELSE 0 END) AS skipped
FROM migration_state
GROUP BY entity_type
ORDER BY entity_type;
```

---

## Fase 2 — Análise dos Resultados (baseada em D16-01 + D16-02)

### Se H2 confirmada (JSONB meta com IDs do SOURCE)

**TAREFA-D16-04** — Quantificar impacto:
```sql
-- Contar conversações com meta.sender.id que NÃO existe em contacts DEST
SELECT COUNT(*) AS impacted
FROM conversations c
WHERE c.account_id = 69
  AND c.inbox_id = 526
  AND c.meta IS NOT NULL
  AND (c.meta->'sender'->>'id')::int NOT IN (
      SELECT id FROM contacts WHERE account_id = 69
  );
```

**Decisão**: Se confirmado → gerar script de correção para reprocessar `meta.sender.id` com mapeamento source→dest dos contacts.

---

### Se H3 confirmada (contact_inbox_id cross-account)

**TAREFA-D16-05** — Mapear registros afetados e calcular correção correta:
```sql
SELECT c.id, c.contact_id, c.inbox_id, c.contact_inbox_id,
       correct_ci.id AS correct_contact_inbox_id
FROM conversations c
JOIN contact_inboxes ci_wrong ON ci_wrong.id = c.contact_inbox_id
LEFT JOIN contact_inboxes correct_ci ON correct_ci.contact_id = c.contact_id
    AND correct_ci.inbox_id = c.inbox_id
WHERE c.account_id = 69
  AND ci_wrong.inbox_id != c.inbox_id;
```

---

### Se H4 confirmada (sequence collision)

**TAREFA-D16-06** — Verificar duplicidade de IDs:
```sql
SELECT id, COUNT(*) FROM conversations GROUP BY id HAVING COUNT(*) > 1;
SELECT id, COUNT(*) FROM messages GROUP BY id HAVING COUNT(*) > 1;
```

---

## Fase 3 — Correção

> ⚠️ **Esta fase modifica o banco.** Executar apenas após autorização explícita do usuário.
> ⚠️ O banco atual está **preservado para análise** — NÃO executar Fase 3 sem confirmar.

### TAREFA-D16-07 — Script de correção (a criar após Fase 2)

Baseado nos resultados da Fase 2, criar script Python em `.tmp/D16_correcao_*.py` que:
- Aplica as correções necessárias (update de meta JSONB, contact_inbox_id, sequences)
- É idempotente (pode ser reexecutado com segurança)
- Registra todas as mudanças no log
- Faz backup das linhas antes de alterar (INSERT em tabela temporária)

---

### TAREFA-D16-08 — Executar PREP-2 e PREP-3 (pendentes desde Sessão 15)

**PREP-2** — Regenerar `authentication_token`:
```sql
UPDATE users
SET authentication_token = encode(gen_random_bytes(20), 'hex'),
    updated_at = NOW()
WHERE id IN (
    SELECT DISTINCT owner_id FROM access_tokens WHERE owner_type = 'User'
);
```

**PREP-3** — Limpar sessões:
```sql
TRUNCATE TABLE sessions;
```

---

## Fase 4 — Validação Pós-Correção

### TAREFA-D16-09 — Verificar endpoint após correção

```bash
# Via script de validação API (já parametrizado em scripts/)
uv run python scripts/validate_api.py \
    --instance vya-chat-dev \
    --account-id 69 \
    --inbox-id 526

# OU verificação manual via curl
curl -H "api_access_token: <token>" \
  "https://vya-chat-dev.vya.digital/api/v1/accounts/69/conversations?inbox_id=526&status=all&page=1"
```

**Resultado esperado**: HTTP 200 com lista de conversações.

---

### TAREFA-D16-10 — Documentar causa raiz e prevenção

- Registrar causa confirmada no debate D16
- Verificar se o migrador precisa ser corrigido para não ocorrer em produção
- Se `meta` JSONB precisa de reprocessamento → adicionar passo no pipeline de migração
- Atualizar RUNBOOK com note sobre PREP-2/PREP-3 como obrigatórios antes de iniciar container

---

## Cronograma de Execução

| Tarefa | Quando | Duração Est. | Dependência |
|--------|--------|-------------|-------------|
| D16-01 (stack trace) | Agora | 10 min | — |
| D16-02 (script diag) | Agora (paralelo) | 20 min | — |
| D16-03 (migration_state) | Agora (paralelo) | 5 min | — |
| D16-04/05/06 (análise) | Após D16-01 + D16-02 | 20 min | D16-01, D16-02 |
| D16-07 (script correção) | Após análise confirmada | 30 min | D16-04/05/06 |
| D16-08 (PREP-2/3) | Com autorização usuário | 5 min | Autorização |
| D16-09 (validação) | Após correção | 15 min | D16-07, D16-08 |
| D16-10 (documentação) | Final | 20 min | D16-09 |

---

## Critério de Sucesso

- [x] Stack trace do Rails identificado → causa raiz confirmada
- [x] Script de diagnóstico executado → dados coletados
- [x] Hipótese principal confirmada ou refutada
- [ ] Script de correção criado e revisado
- [ ] Correção aplicada (com autorização)
- [ ] `GET /api/v1/accounts/69/conversations?inbox_id=526&...` retorna HTTP 200
- [ ] Nenhuma regressão nos dados existentes (FK integrity mantida)

## Evidências da Fase 1

- `.tmp/d16_stacktrace_20260520_1204.txt`
- `.tmp/d16_diagnostico_http500_20260520_120230.json`

Resumo: falha confirmada em `Attachment#file_metadata` por ausência de vínculos ActiveStorage para os attachments migrados.

---

*Plano de Investigação D16 | 2026-05-20 | Sessão 21*
