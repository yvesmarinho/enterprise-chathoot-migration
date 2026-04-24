# D12 — Análise Crítica: Lógica de Negócio e Fluxo de Dados (2026-04-24)

**Data**: 2026-04-24
**Escopo**: Análise de lógica entre o código legado SQL e o pipeline Python atual
**Objetivo**: Identificar problemas de fluxo de dados, corrupção silenciosa e riscos residuais
**Nível**: Pré-código — semântica de domínio, não só sintaxe

---

## 1. Tabela Mestre de Problemas

| ID | Descrição | Sistema | Severidade | Natureza | Impacto real |
|----|-----------|---------|-----------|---------|-------------|
| **L-01** | LIMIT 1/10 em contacts — contatos jamais migrados | Legado | **CRÍTICO** | Perda de dados | ~99.9% dos contatos TBChat não foram migrados |
| **L-02** | MAX(display_id)+1 dentro do loop | Legado | **ALTO** | Race condition | display_id duplicado; scope global em vez de por account |
| **L-03** | contact_inboxes criado sem dedup por conversa | Legado | **ALTO** | Corrupção silenciosa | ~38k registros redundantes de "sessões fantasma" por contact×inbox |
| **L-04** | DELETE destrutivo da staging table pós-COMMIT | Legado | **ALTO** | Irreversibilidade | Nenhuma recuperação possível de dados corrompidos pós-commit |
| **L-05** | COMMIT por iteração (N transações) | Legado | **MÉDIO** | Performance + consistência parcial | 42k transações; estado intermediário persistente após crash |
| **L-06** | N+1 subqueries com JSONB sem índice em messages | Legado | **ALTO** | Performance | ~620k sequential scans; estimativa de 3–5h de CPU só nessas queries |
| **L-07** | `private = '0'` string em campo boolean | Legado | **BAIXO** | Corrupção silenciosa | Funciona por acidente: PostgreSQL aceita `'0'::boolean = false` |
| **L-08** | `status = 1` fixo para todas as conversas | Legado | **MÉDIO** | Perda de informação | Estado original das conversas apagado |
| **L-09** | `assignee_id` fixo como admin | Legado | **MÉDIO** | Corrupção de métricas | Responsável original perdido; métricas de agentes inúteis |
| **A-01** | contact_inbox_id → NULL fallback | Atual | **ALTO** | Perda de rastreabilidade | Sessão contact×inbox desvinculada; conversa visível mas sem contexto de canal |
| **A-02** | Status verbatim — conversas `open` históricas + `snoozed` vencidas | Atual | **CRÍTICO** | Impacto operacional | Filas contaminadas; `ConversationScheduledJob` reativa `snoozed` automaticamente |
| **A-03** | Dedup por phone — colisão silenciosa de identidade | Atual | **CRÍTICO** | Corrupção silenciosa | Conversas do Contato B aparecem como do Contato A; sem alerta no log |
| **A-04** | `remap_fn=None` conta como skipped, não failed | Atual | **MÉDIO** | Observabilidade | Exit 0 com milhares de registros orphan sem distinção visível |
| **A-05** | `authentication_token` verbatim entre instâncias ativas | Atual | **ALTO** | Segurança | Cross-access SOURCE/DEST com mesma credencial; auditoria impossível |
| **F-01** | migration_state desincronizada com re-run parcial | Fluxo | **ALTO** | Inconsistência oculta | Re-run sem truncar migration_state → 0 inserts, exit 0, nenhum erro visível |
| **F-02** | `conversation_participants` ausente do pipeline | Fluxo | **MÉDIO** | Perda de dados | Assinaturas de conversas perdidas permanentemente |
| **F-03** | Prioridade de dedup: phone vence identifier | Fluxo | **MÉDIO** | Ambiguidade de identidade | Identidade determinada pelo dado com menor qualidade possível |
| **F-04** | `status=snoozed` com `snoozed_until` no passado | Fluxo | **ALTO** | Comportamento inesperado | Job automático Chatwoot reativa conversas minutos após o container subir |

---

## 2. Análise Detalhada dos Críticos/Altos

### L-01 — LIMIT 1/10: artefato de teste nunca removido

Era definitivamente esquecimento. Evidência: o loop de conversas usa `LIMIT 42329` — número exato obtido de um `SELECT COUNT(*)` manual. O mesmo autor fez testes incrementais (1 contato, depois 10) e nunca voltou a corrigir.

**Consequência herdada no SOURCE atual**: as conversas que referenciavam contatos além do LIMIT foram inseridas com `contact_id = NULL` (lookup por `custom_attributes->>'external_id'` retornou NULL). O `chatwoot_dev1_db` hoje contém conversas com `contact_id = NULL` como herança direta desse bug. Quando o pipeline Python migra essas conversas, elas chegam ao DEST com `contact_id = NULL` — o Python copia verbatim.

**Verificação**:
```sql
-- chatwoot_dev1_db (SOURCE)
SELECT COUNT(*) FROM conversations WHERE contact_id IS NULL AND account_id = 1;
```

---

### L-02 — MAX(display_id): três vetores de falha, não um

O problema vai além da race condition textbook. **Vetor menos óbvio**: `SELECT MAX(display_id) FROM conversations` é **global**, não por account. Em um sistema com múltiplas contas, a conta A com 100 conversas e a conta B com 50.000 faz com que todas as novas conversas da conta A recebam display_ids começando em 50.001 — numeração descontinuada impossível de corrigir retroativamente.

O pipeline Python corrige isso com `_display_id_counters` pré-calculado por `account_id`.

---

### L-03 — 50 conversas = 50 sessões: violação semântica do modelo Chatwoot

O `contact_inboxes` não viola a constraint `(contact_id, inbox_id, source_id)` porque `source_id = gen_random_uuid()` diverge sempre. Mas o modelo de domínio Chatwoot define que cada `contact_inboxes` representa uma *sessão de canal* identificada pelo `source_id` externo (ex: JID WhatsApp). Criar 50 sessões para o mesmo par cria 50 "identidades de canal" para o mesmo contato.

No Ruby do Chatwoot: `contact.contact_inboxes.where(inbox: inbox)` retorna 50 objetos onde deveria retornar 1.

---

### L-06 — O custo real das N+1 subqueries

As subqueries 2 e 3 são **idênticas** — `(SELECT inbox_id FROM conversations WHERE custom_attributes->>'external_id' = id_session)` e `(SELECT id FROM conversations WHERE...)` — o mesmo scan feito duas vezes por mensagem. Sem índice funcional em `custom_attributes->>'external_id'`, cada uma é sequential scan em ~38k rows.

Para 310k mensagens × 2 subqueries = **620k sequential scans** em tabela de 38k rows. Estimativa conservadora: **3–5 horas de CPU** só nessas queries.

---

### A-02 — O problema do `snoozed` é pior que o do `open`

Conversas `open` históricas aparecem nas filas, mas o agente pode resolvê-las manualmente. Conversas `snoozed` com `snoozed_until` no passado são **reativadas automaticamente** pelo `ConversationScheduledJob` do Chatwoot (job Rails background).

**Minutos após o container subir corretamente**, essas conversas mudam de status para `open`, disparam notificações push para os agentes e criam uma avalanche de atividade não iniciada por nenhum usuário.

---

### A-03 — Por que a colisão silenciosa de identidade é pior do que parece

O log de ContactsMigrator para dedup bem-sucedido e dedup-colisão são **idênticos** — ambos chamam `register_alias` sem distinção. A única forma de detectar é cruzar o número de dedup registros com a contagem de contatos únicos.

Se 5.000 src_contacts → 4.800 dest_contacts (200 colisões), o log diz apenas `"5000 contacts matched"`. As 200 identidades colisionadas são silenciosamente perdidas, e as conversas do Contato B ficam associadas ao Contato A.

---

### A-05 — authentication_token: o risco não é teórico

Enquanto o container aponta para o banco errado (D11), o SOURCE (`chat.vya.digital`) está ativo. Com tokens idênticos em ambos os sistemas, qualquer script de automação com `Authorization: Bearer <token>` pode acessar o DEST acidentalmente — e nenhum log mostrará a diferença.

---

### F-04 — Avalanche de reativação por `snoozed_until` vencido

O `ConversationScheduledJob` do Chatwoot roda a cada poucos minutos e processa:
```ruby
Conversation.snoozed.where("snoozed_until <= ?", Time.zone.now).find_each
```
Conversas migradas com `status=3 (snoozed)` e `snoozed_until` no passado serão processadas automaticamente. Com 309 conversas migradas, mesmo que 10% estejam nesse estado, são ~30 conversas reativadas sem ação humana nos primeiros minutos.

---

## 3. Riscos Residuais com SQL de Verificação

### Risco 1 — Conversas `open`/`snoozed` históricas contaminando filas

```sql
-- chatwoot004_dev1_db
SELECT
    status,
    CASE status WHEN 0 THEN 'open' WHEN 1 THEN 'resolved'
                WHEN 2 THEN 'pending' WHEN 3 THEN 'snoozed' END AS label,
    COUNT(*) AS total,
    COUNT(*) FILTER (WHERE created_at < NOW() - INTERVAL '30 days') AS older_30d,
    COUNT(*) FILTER (WHERE status = 3 AND snoozed_until < NOW()) AS snoozed_vencido
FROM conversations
WHERE id > 156684  -- offset: apenas conversas migradas
  AND account_id = 1
GROUP BY status ORDER BY status;
```

### Risco 2 — Conversas sem `contact_inbox_id` (FK dangling)

```sql
-- chatwoot004_dev1_db
SELECT
    COUNT(*) AS total_migrated,
    COUNT(*) FILTER (WHERE contact_inbox_id IS NULL) AS ci_null,
    COUNT(*) FILTER (WHERE contact_id IS NULL) AS contact_null,
    COUNT(*) FILTER (
        WHERE contact_inbox_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM contact_inboxes ci
              WHERE ci.id = conversations.contact_inbox_id
          )
    ) AS ci_dangling
FROM conversations
WHERE id > 156684 AND account_id = 1;
```

### Risco 3 — `authentication_token` duplicado entre instâncias (fix obrigatório)

```sql
-- chatwoot004_dev1_db — EXECUTAR ANTES DE LIGAR O CONTAINER
UPDATE users
SET authentication_token = encode(gen_random_bytes(20), 'hex'),
    updated_at = NOW()
WHERE id IN (
    -- usuários que vieram da migração (remapeados pelo pipeline)
    SELECT DISTINCT owner_id FROM access_tokens WHERE owner_type = 'User'
);
-- Verificar duplicatas antes:
SELECT authentication_token, COUNT(*)
FROM users GROUP BY authentication_token HAVING COUNT(*) > 1;
```

### Risco 4 — Contacts com phone duplicado no SOURCE (colisão A-03)

```sql
-- chatwoot_dev1_db (SOURCE) — verificar antes de qualquer re-run
SELECT phone_number, COUNT(*) AS n, array_agg(id) AS ids
FROM contacts
WHERE account_id = 1 AND phone_number IS NOT NULL
GROUP BY phone_number HAVING COUNT(*) > 1
ORDER BY n DESC LIMIT 20;
```

---

## 4. Recomendações Priorizadas

### P0 — ANTES de reconfigurar/reiniciar o container

1. **[A-05]** Regenerar `authentication_token` para todos os usuários migrados (Risco 3 SQL acima)
2. **[A-02 / F-04]** Identificar conversas `snoozed` com prazo vencido e decidir com o cliente: forçar `resolved` ou manter `snoozed`?
3. **[A-02]** Decidir com o cliente sobre conversas `open` com mais de 30 dias — manter abertas ou fechar automaticamente?

### P1 — ANTES de liberar para usuários

4. Executar as 4 queries de verificação acima e documentar baseline
5. **[F-02]** Verificar se `conversation_participants` é relevante para o cliente — se sim, criar migrador
6. **[A-05]** Confirmar que webhooks e integrações do DEST usam URLs distintas do SOURCE

### P2 — Para robustez de re-runs futuros

7. **[F-01]** Documentar procedimento de reset: truncar `migration_state` + tabelas de dados JUNTOS, nunca separados
8. **[A-03]** Normalizar telefones E.164 no ContactsMigrator antes de nova execução para qualquer account
9. **[F-03]** Definir explicitamente a prioridade de dedup: `identifier > phone > email` (maior qualidade primeiro)

---

## 5. Problema Herdado do Legado no SOURCE Atual

O bug **L-01** (LIMIT 1/10) significa que o `chatwoot_dev1_db` foi construído parcialmente com dados do TBChat. Isso implica que:

- Parte dos contatos em SOURCE foram criados pelo Chatwoot nativo (sem `custom_attributes.external_id`)
- Parte foi criada pelo legado TBChat (com `custom_attributes.external_id = TBChat.id`)
- Uma parte **nunca foi migrada** do TBChat (os registros além do LIMIT)

O pipeline Python atual trata todos como nativos Chatwoot e copia verbatim — o que é correto. Mas a rastreabilidade para o TBChat original está irremediavelmente perdida para os registros não migrados.
