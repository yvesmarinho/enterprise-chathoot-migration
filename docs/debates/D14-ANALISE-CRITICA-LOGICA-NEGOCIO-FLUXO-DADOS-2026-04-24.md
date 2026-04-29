# D14 — Análise Crítica: Lógica de Negócio e Fluxo de Dados — Legado vs. Atual

**Data**: 2026-04-24
**Status**: 🔴 ANÁLISE COMPLETA — contém riscos residuais confirmados no DEST atual
**Autor**: Engenheiro Sênior de Dados e Migração
**Contexto**: Análise de lógica pura (não arquitetural) dos dois sistemas de migração
**Referências cruzadas**: D3, D10, D11, D12, D13
**Foco**: Comportamento observável, consequências de dados, e SQL de verificação

---

## 1. TABELA MESTRE DE PROBLEMAS

| ID | Descrição curta | Sistema | Severidade | Natureza | Impacto real |
|----|----------------|---------|-----------|---------|-------------|
| L-01 | LIMIT 1/10 em contacts — dados jamais migrados | Legado | CRÍTICO | Perda de dados | ~99.9% dos contatos não migrados |
| L-02 | MAX(display_id)+1 dentro do loop — race condition | Legado | ALTO | Race condition | display_id duplicado sob concorrência ou crash |
| L-03 | contact_inboxes criado sem dedup por conversa | Legado | ALTO | Corrupção silenciosa | N sessões fantasma para mesma relação contact×inbox |
| L-04 | DELETE destrutivo de staging antes de confirmar sucesso macro | Legado | ALTO | Irreversibilidade | Impossibilidade de auditoria/reprocessamento pós-migração |
| L-05 | COMMIT por iteração — N transações independentes | Legado | MÉDIO | Performance + consistência parcial | Estado intermediário persistente após crash |
| L-06 | N+1 subqueries em messages — JSONB sem índice | Legado | ALTO | Performance | Estimativa: ~1.2M queries extras, dezenas de horas |
| L-07 | `private = '0'` string em campo boolean | Legado | BAIXO | Corrupção silenciosa | Funciona por acidente (cast implícito PostgreSQL) |
| L-08 | `status = 1` fixo para todas as conversas | Legado | MÉDIO | Perda de informação | Estado original de conversas perdido |
| L-09 | `assignee_id` fixo como admin global | Legado | MÉDIO | Corrupção de métricas | Métricas de agentes distorcidas; atribuição original perdida |
| A-01 | contact_inbox_id → NULL para conversas sem CI | Atual | ALTO | Perda de rastreabilidade | Sessão contact×inbox desvinculada; visível mas sem contexto |
| A-02 | Status verbatim — conversas open históricas | Atual | CRÍTICO | Impacto operacional | Filas de agentes contaminadas com backlog histórico |
| A-03 | Dedup por phone — colisão silenciosa de identidade | Atual | CRÍTICO | Corrupção silenciosa | Conversas do contato B aparecem como do contato A |
| A-04 | remap_fn=None conta como skipped, não failed | Atual | MÉDIO | Observabilidade | Exit code 0 com milhares de registros perdidos sem alerta |
| A-05 | authentication_token verbatim entre instâncias ativas | Atual | ALTO | Segurança | Cross-access SOURCE/DEST com mesma credencial de API |
| F-01 | migration_state desincronizada com re-run parcial | Fluxo | ALTO | Inconsistência oculta | Re-run sem truncar migration_state → 0 inserts sem erro |
| F-02 | conversation_participants ausente do pipeline | Fluxo | MÉDIO | Perda de dados | Assinaturas de conversas perdidas permanentemente |
| F-03 | Dedup de contacts: phone vence email vs. identifier | Fluxo | MÉDIO | Ambiguidade de identidade | Identidade determinada por dado de menor qualidade |
| F-04 | status=snoozed com snoozed_until no passado | Fluxo | ALTO | Comportamento inesperado | Chatwoot reativa conversas minutos após migração |

---

## 2. ANÁLISE DETALHADA — PROBLEMAS CRÍTICOS E ALTOS

---

### L-01 — LIMIT 1/10 em contacts: CRÍTICO

**O que o código faz:**

```sql
FOR var_contact_row IN SELECT * FROM public.contacts_tbchat LIMIT 1   -- ChatToSynchat
FOR var_contact_row IN SELECT * FROM public.contacts_tbchat LIMIT 10  -- TbChatChatWoot
```

**Este LIMIT era intencional ou esquecimento?**

A evidência sugere **artefato de teste não removido**. Os indícios:

1. O LIMIT do script de conversas é `LIMIT 42329` — um número suspeitamente exato que corresponde
   ao count real de conversas no momento da execução. Alguém inspecionou `SELECT COUNT(*)` e
   hardcodou esse número como limite "de segurança". O mesmo raciocínio de "testar com poucos"
   explica LIMIT 1 e 10 nos contatos.
2. Os dois scripts têm limites diferentes (1 vs 10) indicando desenvolvimento iterativo com
   incremento de teste — e nenhum dos dois chegou a "remover o limite para produção".
3. O código de dedup de contatos (`IF NOT EXISTS`) funcionaria corretamente sem o LIMIT —
   a lógica de idempotência estava correta, apenas o escopo foi esquecido.

**Impacto real:**

- Apenas 1 ou 10 contatos foram migrados do TBChat para o Chatwoot SOURCE original.
- Todas as `N - (1 ou 10)` conversas subsequentes buscam o contato via
  `custom_attributes->>'external_id' = id_contact` e recebem `var_contact_id = NULL`.
- A conversa é inserida com `contact_id = NULL`.
- No Chatwoot, uma conversa sem contact_id é tecnicamente válida mas aparece como "contato
  desconhecido" em todas as views. O agente não consegue ver histórico, enviar mensagens
  proativas, ou vincular a um perfil de cliente.
- **Efeito cascata no SOURCE atual**: O chatwoot_dev1_db (SOURCE do pipeline Python) carrega
  esse legado — os contacts que foram migrados via LIMIT têm `custom_attributes.cpf` e
  `custom_attributes.external_id` (TBChat IDs). Os contatos NÃO migrados (a maioria)
  entrariam como contatos novos sem a rastreabilidade TBChat original.

---

### L-02 — MAX(display_id)+1: ALTO

**O que o código faz:**

```sql
-- Dentro do FOR loop por conversa:
SELECT MAX(display_id)+1 INTO var_display_id FROM public.conversations;
```

**Análise de race condition:**

Sob execução single-session e linear (um registro por vez), o padrão funciona corretamente:
cada iteração lê o MAX real e incrementa. O problema tem três vetores:

**Vetor 1 — Concorrência:**
Duas sessões PL/pgSQL em paralelo leem `MAX(display_id) = 500` simultaneamente. Ambas tentam
inserir `display_id = 501`. A segunda transação falha com `UniqueViolation` em
`index_conversations_on_display_id_and_account_id`. A conversa não é migrada, mas a mensagem
de erro é capturada silenciosamente pelo bloco externo DO $$ que não tem EXCEPTION handler
granular — o loop simplesmente para naquele ponto.

**Vetor 2 — Re-run após crash:**
Se a sessão foi interrompida no meio, o próximo `SELECT MAX(display_id)+1` já inclui as
conversas inseridas pelo run anterior (os COMMITs já foram persistidos). O re-run continua
com display_id correto — **mas** as conversas do run anterior já tiveram seus registros em
`conversations_tbchat` e `messages_tbchat` DELETADOS (via DELETE+COMMIT por iteração). Portanto,
o re-run tenta processar conversas cujas staging rows não existem mais. O cursor
`SELECT * FROM conversations_tbchat LIMIT 42329` retorna um conjunto diferente (menor) —
sem garantia de ordem determinística. Conversas que seriam processadas segundo podem ser
processadas antes, criando buraco de display_ids.

**Vetor 3 — Scope errado (single account vs. all):**
`SELECT MAX(display_id) FROM conversations` retorna o MAX global, não por account.
Se o sistema tem múltiplas contas, o display_id da conta A pode estar em 100 enquanto
o MAX global é 5000 (por conta B). Todas as novas conversas da conta A recebem
display_ids começando em 5001 — sem salto aparente, mas com numeração descontinuada
que confunde o histórico da conta A para os agentes.

**Comparativo com o atual:** O Python pré-carrega `MAX(display_id) por account` **fora do loop**
em um dicionário e usa um counter in-memory — correto para single-process. O risco residual
é dois processos simultâneos lendo o mesmo MAX (sem row-level lock), que é hipotético mas
não impossível em automação com retry.

---

### L-03 — contact_inboxes criado sem dedup: ALTO

**O que o código faz:**

```sql
-- Dentro do FOR loop por conversa:
INSERT INTO contact_inboxes(contact_id, inbox_id, source_id, ...)
VALUES (var_contact_id, var_inbox_id, gen_random_uuid(), ...)
RETURNING id INTO var_contact_inbox_id;
```

**Análise da explosão de registros:**

A constraint de unicidade em `contact_inboxes` no Chatwoot é:
```
UNIQUE (contact_id, inbox_id, source_id)
```

Como `source_id = gen_random_uuid()` é sempre diferente, cada INSERT cria um registro
**formalmente válido** — não há UniqueViolation. Para um contato com 50 conversas na mesma
inbox, isso cria 50 registros de `contact_inboxes` para o par `(contact_id, inbox_id)`.

**O que isso significa no domínio Chatwoot:**

No modelo de dados Chatwoot, `contact_inboxes` representa uma *sessão de canal* — a relação
entre um contato e um canal específico (ex: o número de WhatsApp do contato em um determinado
inbox). O `source_id` é o identificador externo dessa sessão (ex: o JID do WhatsApp).

Para canais de WhatsApp: ter 50 `contact_inboxes` para o mesmo par é absurdo — o contato tem
apenas um número de WhatsApp, portanto uma única sessão. O Chatwoot, ao carregar as conversas
do contato, executa:

```ruby
contact_inboxes = contact.contact_inboxes.where(inbox: inbox)
```

Com 50 registros, esse query retorna 50 "sessões" — todas apontando para o mesmo contato
no mesmo inbox, com IDs diferentes. A UI do Chatwoot mostra múltiplas sessões ativas para
o mesmo contato, o que confunde os agentes e quebra a rastreabilidade de qual sessão
originou cada conversa.

**Quantas duplicatas para 42k conversas?**

Se a distribuição média for 10 conversas por (contact_id, inbox_id), isso gera:
`42,329 / 10 = ~4,233 contact_inbox registros únicos necessários`
vs. `42,329 inseridos` = **~38,096 registros redundantes** na tabela.

O pipeline Python atual resolve isso com dedup por `(contact_id, inbox_id)` antes do INSERT —
e registra um alias no IDRemapper para que o `ConversationsMigrator` use o ID correto.

---

### L-04 — DELETE destrutivo: ALTO

**O que o código faz:**

```sql
-- Dentro de cada iteração (mesma transação antes do COMMIT):
INSERT INTO messages SELECT ... FROM messages_tbchat WHERE id_session = var_conversations_row.id;
DELETE FROM messages_tbchat WHERE id_session = var_conversations_row.id;
DELETE FROM conversations_tbchat WHERE id = var_conversations_row.id;
COMMIT;
```

**Análise de irreversibilidade:**

O DELETE está na mesma transação do INSERT — tecnicamente, se o INSERT falhar, o DELETE
é também revertido pelo rollback implícito. **Não há risco de perda na execução normal.**

O risco real é **pós-COMMIT bem-sucedido**: após cada iteração bem-sucedida, os dados
originais em `messages_tbchat` e `conversations_tbchat` são **permanentemente eliminados**.

**Cenário concreto de perda irrecuperável:**

1. Iteração 1000 commita com sucesso — dados da conversa 1000 deletados da staging.
2. Análise pós-migração revela que `contact_id` de conversa 1000 está errado (LIMIT 1 bug).
3. Para corrigir, seria necessário o dado original — que não existe mais.
4. A única fonte de verdade restante é o sistema TBChat original, se ainda estiver operacional.

**Implicação para o SOURCE atual (chatwoot_dev1_db):**

As mensagens com `content = "Image: https://tbchatuploads.s3..."` são o resultado deste
DELETE do legado. O arquivo original foi deletado da staging table; ficou apenas a URL
construída manualmente como conteúdo de texto. Se o bucket S3 `tbchatuploads` for
desativado, essas mensagens ficam com conteúdo textual de uma URL inacessível, sem
possibilidade de recuperação.

---

### L-06 — N+1 subqueries em messages: ALTO

**O que o código faz:**

```sql
INSERT INTO messages (...)
SELECT
    CASE WHEN message_type='text' THEN message
         ELSE CONCAT(INITCAP(message_type),': https://...', file_url)
    END AS content,
    (SELECT id FROM accounts WHERE name='Dr. Thiago Bianco') AS account_id,  -- subquery 1
    (SELECT inbox_id FROM conversations WHERE custom_attributes->>'external_id' = id_session) AS inbox_id,  -- subquery 2
    (SELECT id FROM conversations WHERE custom_attributes->>'external_id' = id_session) AS conversation_id,  -- subquery 3
    CASE WHEN type_in_message='RECEIVED'
         THEN (SELECT id FROM contacts WHERE custom_attributes->>'external_id' = id_contact)  -- subquery 4 (condicional)
         ELSE (SELECT id FROM users WHERE uid='admin@vya.digital')  -- subquery 5 (condicional)
    END AS sender_id
FROM messages_tbchat WHERE id_session = var_conversations_row.id;
```

**Este INSERT é executado UMA VEZ por conversa** (processando todas as mensagens daquela
conversa). Mas as subqueries correlacionadas **executam uma vez por linha retornada** (por mensagem).

**Análise de custo real:**

| Subquery | Índice disponível? | Custo estimado por execução |
|----------|-------------------|---------------------------|
| `accounts WHERE name=...` | Provavelmente `index_accounts_on_name` | O(log n) — rápido |
| `conversations WHERE custom_attributes->>'external_id' = id_session` | **SEM índice funcional em JSONB** | Sequential scan em 38k+ rows |
| `contacts WHERE custom_attributes->>'external_id' = id_contact` | **SEM índice funcional em JSONB** | Sequential scan em 38k+ rows |
| `users WHERE uid=...` | `index_users_on_uid` (unique) | O(1) — rápido |

**Para 310k mensagens:**
- 310k × 2 sequential scans em `conversations` (38k rows cada) ≈ **23.6 bilhões de comparações de row**
- 155k × 1 sequential scan em `contacts` (38k rows cada) ≈ **5.9 bilhões de comparações**

Na prática, o PostgreSQL faria cache agressivo de buffers, mas a query ainda seria medida
em horas. Subqueries 2 e 3 são IDÊNTICAS (mesma tabela, mesmo predicado) — poderiam ser
substituídas por um único JOIN, eliminando 50% do custo.

**Adicionalmente:** `custom_attributes->>'external_id' = CAST(id_session AS text)` é
uma comparação de tipo misto (JSONB text vs. VARCHAR) que pode inibir o uso de qualquer
índice criado posteriormente nessa expressão.

---

### A-02 — Status verbatim — conversas históricas abertas: CRÍTICO

**O que o pipeline atual faz:**

```python
new_row = dict(row)  # status copiado verbatim do SOURCE
```

**Análise de impacto operacional real:**

No Chatwoot, os valores de status têm significado funcional direto:

| status | Valor | Efeito no sistema |
|--------|-------|------------------|
| 0 = open | Aparece em todas as filas de agentes | Background jobs processam, notificações enviadas |
| 1 = resolved | Arquivado; não aparece em filas ativas | Sem processamento automático |
| 2 = pending | Aguarda primeiro contato do agente | Aparece em fila de pending |
| 3 = snoozed | Reativado automaticamente em `snoozed_until` | **ActionCable job reativa se `snoozed_until` < NOW()** |

**Cenário post-migração com o container corrigido:**

1. Migração completa, container aponta para `chatwoot004_dev1_db`.
2. Primeiro login de agente: interface carrega filas com `status=open`.
3. Todas as conversas migradas com status=0 do SOURCE aparecem como abertas.
4. Se o SOURCE tinha 15k conversas abertas de 2 anos, os agentes veem 15k + conversas ativas reais.
5. O agente não consegue distinguir históricas de ativas sem inspecionar `created_at`.
6. Pior caso com `status=snoozed` (valor 3): se `snoozed_until = '2024-01-15'` (passado),
   o background job `ConversationScheduledJob` reativa essas conversas como `open`
   **automaticamente** em background, podendo gerar notificações push para os agentes.

**Recomendação técnica**: Forçar `status=resolved` para todas as conversas migradas com
`created_at < (NOW() - '30 days')`. Conversas recentes (últimos 30 dias) preservam o
status original. Esta é uma decisão de negócio que deve ser explicitamente confirmada com
o cliente **antes** de ligar o container corrigido.

---

### A-03 — Dedup por phone — colisão silenciosa de identidade: CRÍTICO

**O que o pipeline atual faz:**

```python
# Em ContactsMigrator:
dst_phone_lkp: dict[tuple[int, str], int] = {}
...
phone = row.get("phone_number")
if phone:
    dest_id = dst_phone_lkp.get((acct_id, str(phone).strip().lower()))
```

**O caso de falha:**

No SOURCE, existe um erro de dados clássico em sistemas legados: dois contatos distintos
cadastrados com o mesmo número de telefone. Exemplo:

- SOURCE: Contato A = João Silva, phone=+5511999990000, id=1234
- SOURCE: Contato B = Maria Santos, phone=+5511999990000, id=5678
- DEST: já existe Contato X = João Silva, phone=+5511999990000, id=201

O ContactsMigrator dedup:
- Itera sobre os rows do SOURCE em ordem de `SELECT *` (sem ORDER BY garantido).
- Se Contato A (João, +55119...) aparece primeiro: `register_alias("contacts", 1234, 201)` ✓
- Quando Contato B (Maria, +55119...) aparece: também encontra `dst_phone_lkp[(1, "+5511999990000")] = 201`
  → `register_alias("contacts", 5678, 201)` — SILENCIOSAMENTE mapeia Maria → João.

**Resultado:**
- Todas as conversas e mensagens de Maria Santos (src contact_id=5678) são migradas com
  `contact_id = 201` (João Silva no DEST).
- No Chatwoot DEST, o perfil de João Silva mostra todas as conversas de Maria.
- Nenhum erro é lançado, nenhum log de WARNING específico para esta colisão.
- A única pista é a contagem de dedup: se mais registros foram deduped do que existem
  registros distintos no DEST, houve colisão.

**Dimensão real do problema:**

No contexto TBChat→Chatwoot (SOURCE atual), a população de contatos inclui dados migrados
pelo script legado com duas inconsistências de phone já documentadas:
- Script 1: `CONCAT('+', phone)` → `+5511999990000`
- Script 2: `TRIM(phone)` → `5511999990000` (sem `+`)

Um contato migrado pelo Script 1 e outro pelo Script 2 com o mesmo número BASE terão
phones `+5511999990000` vs `5511999990000` — que são strings diferentes. Neste caso, o
dedup NÃO ocorre (bom), mas os dois representam o mesmo contato físico (ruim). O dedup
atual com `.strip().lower()` não normaliza para E.164.

**Query de verificação:**

```sql
-- Contatos com mesmo phone no SOURCE (antes da dedup — rodar no SOURCE):
SELECT phone_number, COUNT(*) cnt, array_agg(id ORDER BY id) ids
FROM contacts
WHERE phone_number IS NOT NULL AND account_id = 1
GROUP BY phone_number
HAVING COUNT(*) > 1
ORDER BY cnt DESC
LIMIT 20;
```

---

### A-05 — authentication_token verbatim: ALTO (Segurança)

**O que o pipeline faz (UsersMigrator):**

O `UsersMigrator` NULL-out `reset_password_token` e `confirmation_token` — mas
**`authentication_token` é copiado verbatim**.

**Por que isso é crítico:**

`authentication_token` é a credencial de autenticação da API REST do Chatwoot:
`Authorization: Bearer <authentication_token>`. Enquanto o SOURCE (`chat.vya.digital`) estiver
ativo com os mesmos usuários, o mesmo token funciona em **ambas as instâncias simultaneamente**.

Qualquer chamada de API com esse token é indistinguível entre SOURCE e DEST:
- Se um integrador testa com a URL errada, ele MODIFICA dados no SOURCE pensando estar no DEST.
- Se um script de automação usar o token sem alterar a URL base, ele pode criar/deletar
  conversas no SOURCE inadvertidamente.
- Auditoria por token é inútil — não há como distinguir qual sistema foi alvo.

**Solução**: Após confirmar que a migração está completa e antes de ligar o container, executar:

```sql
-- No DEST (chatwoot004_dev1_db):
UPDATE users SET authentication_token = encode(gen_random_bytes(20), 'hex')
WHERE id IN (
  SELECT id_destino FROM migration_state WHERE tabela='users' AND status='ok'
);
```

---

### F-01 — migration_state desincronizada no re-run parcial: ALTO

**O fluxo de dados problemático:**

`_run_batches` carrega `already_done = get_migrated_ids(conn, table_name)` **antes** de
processar qualquer batch. Se a `migration_state` está populada mas as tabelas de dados foram
truncadas (cenário: "quero re-rodar limpo mas esqueço da migration_state"), o pipeline:

1. `already_done` = {todos os IDs já migrados antes}
2. Para cada row do SOURCE: `if id_origem in already_done: skipped += 1`
3. Todos os rows são skipped → nenhum INSERT ocorre
4. Exit code 0, log: "migrated=0 skipped=N failed=0"

O operador vê uma execução bem-sucedida que não fez nada. **Não há erro; não há warning**.
O DEST fica com tabelas truncadas mas com migration_state intacta.

**O caminho oposto é igualmente perigoso:**

Se truncar `migration_state` mas não as tabelas de dados:
1. `already_done` = {} (vazio)
2. O pipeline tenta inserir tudo novamente
3. PK collision: `id = remap(src_id)` no DEST já existe → `bulk_insert` falha
4. Batch inteiro é registrado em `migration_state` como `failed`
5. Exit code retornado depende do migrator (não é 3 para não-accounts)

**Nenhum dos dois cenários gera um aviso claro ao operador**.

---

## 3. PROBLEMAS DE FLUXO DE DADOS

### 3.1 A Entidade Raiz e o que acontece com falha parcial

**`accounts` é o pino mestre** de toda a hierarquia. O `AccountsMigrator` está configurado
com `raise SystemExit(3)` em qualquer batch failure — não há degrade gracioso. Isso é correto
porque:

- Sem `account_id` válido no DEST, nenhuma entidade pode ser inserida.
- Um `account_id` parcialmente migrado (alguns batches OK, outros falhos) criaria um estado
  onde parte das conversas tem `account_id` válido e parte tem FK dangling.

**O risco é diferente:** se o `IDRemapper` perde o estado (reinício de processo mid-migration
antes do accounts estar completo), os offsets são recomputados. Mas o `ConnectionFactory`
recalcula os offsets a cada inicialização, então o offset para `accounts` reflete o
`MAX(id)` no DEST **no momento da reinicialização** — que pode ser diferente do MAX no momento
da primeira execução se outros processos inseriram dados no DEST entre os dois runs.

### 3.2 Dependências de ordem: onde o pipeline está correto e onde tem lacunas

**Correto:**

```
accounts → inboxes → contacts → contact_inboxes → conversations → messages → attachments
```

Esta sequência respeita todas as dependências FK.

**Lacunas no pipeline:**

| Entidade ausente | Tabela Chatwoot | Dependência | Impacto |
|----------------|----------------|-------------|---------|
| conversation_participants | `conversation_participants` | FK → conversations, users | Assinaturas perdidas |
| notifications | `notifications` | FK → conversations, users | Transitório — aceitável |
| reports / v2_reports | `reports`, `v2_reports` | FK → accounts | Analytics histórico perdido |
| channel_email (SMTP config) | `channel_email` | channel de inbox | Configs de email perdidas se InboxesMigrator não cobrir |

**Nota sobre `webhooks`**: O pipeline inclui `WebhooksMigrator`, mas este copia webhooks do SOURCE
com as mesmas URLs. Se o DEST está em outro domínio, os webhooks apontam para destinos errados
(ex: URLs de staging do SOURCE). Isso deve ser revisto após a migração.

### 3.3 Tokens regenerados: risco de colisão

`website_token` e `hmac_token` são regenerados via `secrets.token_urlsafe(18/24)`.
Com 18 bytes de entropia, o espaço é $2^{144}$ — probabilidade de colisão com tokens
existentes no DEST é desprezível ($< 10^{-40}$). Tecnicamente seguro.

**O risco real aqui é diferente**: se o SOURCE ainda está ativo e alguma integração (ex: widget
de chat embarcado em um site) usa o `website_token` do SOURCE, essa integração **não funciona
mais no DEST** após a migração (tokens diferentes). Isso é intencional mas deve ser comunicado
aos integradores — cada widget precisa ser reconfigurado com o novo token do DEST.

### 3.4 Dedup de contacts: qual critério vence e quando isso dá errado

A ordem de prioridade no `ContactsMigrator`:
```
phone → email → identifier
```

**Cenário de conflito entre phone e identifier:**

Um contato WhatsApp no DEST tem:
- `phone_number = "+5511999990000"`
- `identifier = "+5511999990000@s.whatsapp.net"` (JID WhatsApp)

O mesmo contato no SOURCE tem:
- `phone_number = "+5511999990000"`
- `identifier = "5511999990000@s.whatsapp.net"` (JID sem prefixo `+`)

Eles representam **o mesmo contato físico** mas o `identifier` difere por um caractere (`+`).
O dedup por phone funciona corretamente aqui (mesmo número → mesmo contato). ✓

**Cenário problemático:**

- DEST: Contato X, phone=NULL, identifier="wa_session_abc"
- SOURCE: Contato Y, phone="+5511999", identifier="wa_session_abc"
- SOURCE: Contato Z, phone="+5511999", identifier="different_id"

Quando o pipeline processa Y: `phone` encontra NULL em DEST para "+5511999" (não existe lá)
→ tenta `email` → NULL → tenta `identifier` → encontra DEST X via "wa_session_abc".
Quando o pipeline processa Z: `phone` encontra que "+5511999" não está em `dst_phone_lkp`
(porque X não tem phone) → portanto Z **não** é deduplicado e é inserido como novo contato.

Resultado: Y mapeia para X (correto), Z é inserido separado (potencialmente duplicado de Y).

---

## 4. RISCOS RESIDUAIS PÓS-MIGRAÇÃO NO DEST ATUAL

Estado atual confirmado: pipeline executado contra `chatwoot004_dev1_db`, 13 inboxes
migrados (IDs 399-519), 309 conversas migradas. Container ainda aponta para o banco errado
(D11 pendente de resolução).

### Risco Residual 1 (CRÍTICO) — Conversas com status=open históricas

**Probabilidade de ocorrência**: Alta. O SOURCE (`chat.vya.digital`) é um sistema em produção
com conversas abertas reais. Ao corrigir o container, todos esses open históricos aparecem.

**Query de verificação:**

```sql
-- Rodar no chatwoot004_dev1_db (DEST):
SELECT
    c.status,
    CASE c.status
        WHEN 0 THEN 'open'
        WHEN 1 THEN 'resolved'
        WHEN 2 THEN 'pending'
        WHEN 3 THEN 'snoozed'
        ELSE 'unknown'
    END AS status_label,
    COUNT(*) AS total,
    COUNT(*) FILTER (WHERE c.created_at < NOW() - INTERVAL '30 days') AS older_than_30d,
    MIN(c.created_at) AS oldest,
    MAX(c.created_at) AS newest
FROM conversations c
WHERE c.id IN (
    SELECT ms.id_destino
    FROM migration_state ms
    WHERE ms.tabela = 'conversations' AND ms.status = 'ok'
)
GROUP BY c.status
ORDER BY c.status;
```

**Critério de aceitação**: Zero conversas com `status=snoozed` e `snoozed_until < NOW()`.
Decisão de negócio necessária para `status=open` com `created_at < NOW() - 30d`.

**Fix preventivo (executar ANTES de corrigir o container):**

```sql
-- Forçar resolved para conversas snoozed com prazo vencido:
UPDATE conversations
SET status = 1, snoozed_until = NULL
WHERE status = 3
  AND snoozed_until < NOW()
  AND id IN (SELECT id_destino FROM migration_state WHERE tabela='conversations' AND status='ok');

-- Opcional: forçar resolved para conversas open com mais de 30 dias:
-- UPDATE conversations
-- SET status = 1
-- WHERE status = 0
--   AND created_at < NOW() - INTERVAL '30 days'
--   AND id IN (SELECT id_destino FROM migration_state WHERE tabela='conversations' AND status='ok');
```

---

### Risco Residual 2 (ALTO) — Conversas sem contact_inbox_id

**Probabilidade de ocorrência**: Moderada. Ocorre especificamente para conversas cujo
`contact_inbox_id` SOURCE aponta para um `contact_inboxes` row que foi skipped por orphan FK
E para as quais não existe um par `(remapped_contact_id, remapped_inbox_id)` no DEST.

**Query de verificação:**

```sql
-- Conversas migradas com contact_inbox_id=NULL:
SELECT
    COUNT(*) AS total_migrated,
    COUNT(*) FILTER (WHERE contact_inbox_id IS NULL) AS ci_null_count,
    COUNT(*) FILTER (WHERE contact_id IS NULL) AS contact_null_count,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE contact_inbox_id IS NULL) / NULLIF(COUNT(*), 0),
        2
    ) AS pct_ci_null
FROM conversations
WHERE id IN (
    SELECT id_destino
    FROM migration_state
    WHERE tabela = 'conversations' AND status = 'ok'
);
```

**Query de verificação complementar — orphaned contact_inbox_id FKs:**

```sql
-- Conversas com contact_inbox_id apontando para registro inexistente:
SELECT COUNT(*) AS dangling_ci_fk
FROM conversations c
WHERE c.contact_inbox_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM contact_inboxes ci WHERE ci.id = c.contact_inbox_id
  )
  AND c.id IN (SELECT id_destino FROM migration_state WHERE tabela='conversations' AND status='ok');
```

**Critério de aceitação**: Zero conversas com contact_inbox_id FK dangling.
Para contact_inbox_id=NULL: documentar a porcentagem; se > 5%, investigar por que o
pair-lookup fallback não funcionou.

---

### Risco Residual 3 (ALTO) — authentication_token compartilhado SOURCE/DEST

**Probabilidade de ocorrência**: Certa (100%). O UsersMigrator copia authentication_token
verbatim. Enquanto ambas as instâncias estiverem ativas com os mesmos usuários, os tokens
são idênticos.

**Query de verificação:**

```sql
-- No DEST: quais usuários migrados têm authentication_token potencialmente duplicado
-- (não dá para comparar diretamente com SOURCE sem acesso ao SOURCE nesta query,
--  mas confirma que tokens não foram invalidados após migração):
SELECT
    u.id,
    u.email,
    LEFT(u.authentication_token, 8) || '...' AS token_prefix,  -- parcial por segurança
    ms.migrated_at
FROM users u
JOIN migration_state ms ON ms.id_destino = u.id AND ms.tabela = 'users' AND ms.status = 'ok'
WHERE u.authentication_token IS NOT NULL
ORDER BY ms.migrated_at DESC
LIMIT 20;
```

**Fix obrigatório antes de ligar o container:**

```sql
-- Regenerar authentication_token para todos os usuários migrados:
UPDATE users
SET authentication_token = encode(gen_random_bytes(20), 'hex'),
    updated_at = NOW()
WHERE id IN (
    SELECT id_destino
    FROM migration_state
    WHERE tabela = 'users' AND status = 'ok'
);
```

Este UPDATE deve ser executado **depois** que todos os usuários forem migrados e **antes**
de qualquer teste de API no DEST. O SOURCE continua funcionando com seus tokens antigos.

---

## 5. RECOMENDAÇÕES PRIORIZADAS

### P0 — Executar imediatamente (antes de qualquer coisa)

| # | Ação | Risco mitigado |
|---|------|---------------|
| 1 | Regenerar `authentication_token` para usuários migrados (SQL Risco 3) | A-05 |
| 2 | Verificar contagem de `status=snoozed` com `snoozed_until < NOW()` e forçar resolved | A-02 / F-04 |
| 3 | Confirmar com o cliente a decisão sobre conversas `status=open` históricas | A-02 |

### P1 — Executar antes de ligar o container corrigido

| # | Ação | Risco mitigado |
|---|------|---------------|
| 4 | Rodar as três queries de verificação (Riscos 1, 2, 3) | A-02, A-01, A-05 |
| 5 | Verificar `channel_id` dangling em inboxes (POS-01 do D13) | BUG-A |
| 6 | Verificar duplicatas de `display_id` por account | Potencial conflito de display_id |
| 7 | Documentar porcentagem de conversas com `contact_inbox_id=NULL` | A-01 |

### P2 — Verificações complementares de qualidade de dados

| # | Ação | Risco mitigado |
|---|------|---------------|
| 8 | Checar duplicatas de phone_number no SOURCE (query de Risco A-03) | A-03 |
| 9 | Confirmar que webhooks no DEST não apontam para URLs do SOURCE | Integração quebrada |
| 10 | Planejar migração de `conversation_participants` se necessário | F-02 |
| 11 | Revisar urls S3 TBChat em `messages.content` — comunicar ao cliente | L-04 legado |

### P3 — Para o próximo re-run (se necessário)

| # | Ação | Risco mitigado |
|---|------|---------------|
| 12 | Documentar procedimento explícito de truncate: sempre truncar migration_state E dados juntos | F-01 |
| 13 | Adicionar normalização E.164 no dedup de contacts (strip `+`, comparar sufixo numérico) | A-03 |
| 14 | Alterar `remap_fn=None` para contar separadamente (skip intencional vs. orphan FK) | A-04 |

---

## 6. SÍNTESE DIAGNÓSTICA

O legado SQL foi escrito como um **script de migração one-shot com debug incremental** —
o LIMIT 1/10 é a prova mais clara disso. O padrão `COMMIT por iteração + DELETE destrutivo`
é consistente com um script escrito para "rodar até o fim sem falhar", priorizando
simplicidade de execução sobre segurança de dados. O resultado foi uma migração que
**funcionou naquela noite** mas deixou o SOURCE com dados de qualidade heterogênea.

O pipeline Python atual resolve os problemas estruturais (race condition, dedup, offset
de IDs, idempotência) mas herda dois tipos de risco do legado:

1. **Risco de dados herdado**: o SOURCE que o Python migra já contém as imperfeições
   deixadas pelo SQL legado (phones sem E.164, contatos com NULL identifiers, mensagens
   com URLs S3 como texto).

2. **Risco de decisão operacional**: status verbatim e authentication_token verbatim não
   são bugs do pipeline — são decisões de design que têm consequências operacionais diretas
   que precisam de ação humana explícita antes do go-live.

O pipeline Python está tecnicamente correto para o que se propõe. Os três riscos residuais
mais graves são remediáveis com SQL direto e não requerem nova execução do pipeline.
