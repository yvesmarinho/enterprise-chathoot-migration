# D5-REV — REVISÃO DO MÉTODO DE VALIDAÇÃO PÓS-MIGRAÇÃO

**Data**: 2026-04-21
**Substitui**: `D5-DEBATE-SPEC-VALIDACAO-API-2026-04-20.md` (parcialmente — seções de método)
**Participantes**: @system-engineer, @dba-sql-expert, @python-expert, @chatwoot-expert
**Gatilho**: execução de `make validate-api-deep SAMPLE=5` revelou erro conceitual de design
  na implementação atual de `app/10_validar_api.py`.

---

## Erro Conceitual Identificado

### Sintoma observado no log

```
FIELD message.conversation_id src=42072 dest=198756 match=False
FIELD message.account_id      src=1     dest=1      match=True
FIELD message.content         src='🚀…' dest='🚀…'  match=True
```

O campo `conversation_id` reporta `match=False` em 100% das mensagens. O mesmo ocorre
para `contact_id`, `inbox_id`, `sender_id`, `message_id` — todos os IDs de referência
interna. Esses falsos negativos **poluem completamente o sinal de validação**.

### Causa raiz

A implementação atual usa dois mecanismos como fonte de verdade:

| Mecanismo | Uso no código | Problema |
|-----------|--------------|---------|
| `migration_state` (id_origem → id_destino) | lookup de ID DEST dado ID SOURCE | Circular: valida o migrador com dados do próprio migrador |
| `_compare_fields()` field-by-field | Compara todos os campos incluindo IDs internos | IDs são **sempre diferentes** após migração; geram 100% de ruído |

### Definição do problema correto

> **IDs são endereços de memória do banco, não dados.** Numa migração MERGE,
> todos os IDs de referência interna (conversation_id, message_id, contact_id, inbox_id)
> são remapeados obrigatoriamente. Comparar IDs entre SOURCE e DEST **nunca é um sinal
> de integridade de dados**.
>
> O dado real são os **campos de negócio**: conteúdo da mensagem, número de telefone,
> e-mail, timestamp, tipo, status — aquilo que o usuário final enxerga.

---

## Análise por Entidade — Chaves de Negócio vs. Campos de Ruído

### `contacts`

| Campo | Tipo | Comparável? | Justificativa |
|-------|------|-------------|--------------|
| `phone_number` | BK primária | ✅ Sim | Identifica univocamente o contato |
| `email` | BK primária | ✅ Sim | Identifica univocamente o contato |
| `name` | BK secundária | ✅ Sim | Deve ser preservado |
| `identifier` | BK externa | ✅ Sim | Chave do CRM de origem |
| `custom_attributes` | dados | ✅ Sim (hash) | Conteúdo JSON — deve chegar intacto |
| `id` | PK interna | ❌ Ruído | Remapeado pela migração |
| `account_id` | FK interna | ❌ Ruído | Remapeado (1→1, 4→47, 17→17…) |
| `pubsub_token` | gerado | ❌ Ruído | Regenerado pelo Chatwoot no DEST |
| `created_at` | metadado | ⚠️ Fraco | Pode divergir por timezone ou re-insert |
| `updated_at` | metadado | ❌ Ruído | Atualizado pelo Chatwoot pós-migração |

**Chave de match**: `(phone_number, email)` — um ou ambos não nulos.

### `conversations`

| Campo | Tipo | Comparável? | Justificativa |
|-------|------|-------------|--------------|
| `display_id` | BK de negócio | ✅ Sim | ID visível ao agente; deve ser preservado |
| `status` | dado | ✅ Sim | Estado da conversa (open/resolved/pending) |
| `additional_attributes.src_id` | rastreamento | ✅ Sim | Migrador grava src_id aqui |
| `created_at` | dado | ✅ Sim (com tolerância) | Data de criação da conversa |
| `id` | PK interna | ❌ Ruído | Remapeado |
| `contact_id` | FK interna | ❌ Ruído | Remapeado |
| `inbox_id` | FK interna | ❌ Ruído | Remapeado |
| `assignee_id` | FK interna | ❌ Ruído | Remapeado (user pode não existir no DEST) |
| `updated_at` | metadado | ❌ Ruído | Atualizado pelo Chatwoot |

**Chave de match**: `additional_attributes->>'src_id'` no DEST, ou `(contact_id_dest, created_at)` como fallback.
> Nota: o migrador já grava `src_id` em `additional_attributes` — essa é a âncora correta.

### `messages`

| Campo | Tipo | Comparável? | Justificativa |
|-------|------|-------------|--------------|
| `content` | dado central | ✅ Sim (hash MD5) | Conteúdo da mensagem |
| `message_type` | dado | ✅ Sim | incoming/outgoing/activity/template |
| `content_type` | dado | ✅ Sim | text/input_select/cards/etc. |
| `created_at` | dado | ✅ Sim | Timestamp original da mensagem |
| `private` | dado | ✅ Sim | Nota privada vs. pública |
| `sender_type` | dado | ✅ Sim | Contact/User/AgentBot |
| `id` | PK interna | ❌ Ruído | Remapeado |
| `conversation_id` | FK interna | ❌ Ruído | Remapeado |
| `account_id` | FK interna | ❌ Ruído | Remapeado |
| `sender_id` | FK interna | ❌ Ruído | Remapeado (user/contact IDs) |
| `updated_at` | metadado | ❌ Ruído | Atualizado pelo Chatwoot |

**Chave de match (hash de conteúdo)**:
```sql
MD5(CONCAT_WS('§',
    COALESCE(content, ''),
    message_type::text,
    content_type::text,
    TO_CHAR(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS.US')
))
```

### `attachments`

| Campo | Tipo | Comparável? | Justificativa |
|-------|------|-------------|--------------|
| `external_url` | BK de negócio | ✅ Sim | URL do arquivo — estável (S3 path) |
| `file_type` | dado | ✅ Sim | image/audio/video/file |
| `id` | PK interna | ❌ Ruído | Remapeado |
| `message_id` | FK interna | ❌ Ruído | Remapeado |
| `account_id` | FK interna | ❌ Ruído | Remapeado |

**Chave de match**: `external_url` — é o path do arquivo no storage (S3/local), não muda.

---

## Recursos PostgreSQL para Validação por Hash

### Opção 1 — `MD5()` nativo (sem extensão)

Disponível em todas as versões do PostgreSQL. Suficiente para comparação de integridade
(não é criptografia — apenas fingerprint de conteúdo).

```sql
-- Hash de mensagem por conteúdo de negócio
SELECT
    MD5(CONCAT_WS('§',
        COALESCE(content, ''),
        message_type::text,
        content_type::text,
        TO_CHAR(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS.US')
    )) AS msg_hash,
    COUNT(*) AS n
FROM messages
WHERE account_id = :account_id
GROUP BY msg_hash
ORDER BY n DESC;
```

### Opção 2 — `pgcrypto` → `SHA-256`

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Hash mais robusto (SHA-256) por mensagem
SELECT
    encode(
        digest(
            CONCAT_WS('§',
                COALESCE(content, ''),
                message_type::text,
                created_at::text
            )::bytea,
            'sha256'
        ),
        'hex'
    ) AS msg_sha256
FROM messages
WHERE conversation_id = :dest_conv_id
ORDER BY created_at;
```

### Opção 3 — `EXCEPT` entre SOURCE e DEST (cross-DB via Python)

O operador `EXCEPT` retorna as linhas do primeiro `SELECT` que não aparecem no segundo.
Como SOURCE e DEST são bancos **distintos no mesmo servidor**, a comparação é feita no
Python com dois result sets:

```python
# Python — comparação por hash sem dblink
src_hashes = {row[0] for row in src_conn.execute(text(SQL_MSG_HASHES), params)}
dest_hashes = {row[0] for row in dest_conn.execute(text(SQL_MSG_HASHES), params)}

missing_in_dest = src_hashes - dest_hashes    # perda de dados
extra_in_dest   = dest_hashes - src_hashes    # dados espúrios/duplicados
```

### Opção 4 — `dblink` (cross-DB em SQL puro)

Se SOURCE e DEST estiverem no **mesmo servidor PostgreSQL** (é o caso — ambos em
`wfdb02.vya.digital:5432`), `dblink` permite `EXCEPT` direto em SQL:

```sql
-- [DEST] Requer: CREATE EXTENSION IF NOT EXISTS dblink;
-- Mensagens presentes no SOURCE que estão ausentes no DEST (perda de dados)
SELECT src_hash
FROM dblink(
    'dbname=chatwoot_dev1_db host=wfdb02.vya.digital user=... password=...',
    $$
    SELECT MD5(CONCAT_WS('§',
        COALESCE(content, ''),
        message_type::text,
        content_type::text,
        TO_CHAR(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS.US')
    )) AS msg_hash
    FROM messages
    WHERE account_id = 1
    $$
) AS src(src_hash text)

EXCEPT

SELECT MD5(CONCAT_WS('§',
    COALESCE(content, ''),
    message_type::text,
    content_type::text,
    TO_CHAR(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS.US')
)) AS msg_hash
FROM messages
WHERE account_id = 1;
```

> ⚠️ `dblink` requer permissão `SUPERUSER` ou `pg_read_all_data` na conexão de destino.
> Verificar disponibilidade no servidor antes de adotar essa opção.

### Opção 5 — Agregado de hash por account (macro-check rápido)

```sql
-- Hash do conjunto completo de mensagens por account
-- Se MD5_agg(SOURCE) == MD5_agg(DEST), os dados são idênticos em conteúdo
SELECT
    account_id,
    MD5(STRING_AGG(
        MD5(CONCAT_WS('§',
            COALESCE(content, ''),
            message_type::text,
            content_type::text,
            TO_CHAR(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS.US')
        )),
        '|' ORDER BY
            TO_CHAR(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS.US'),
            COALESCE(content, '')
    )) AS account_content_hash,
    COUNT(*) AS total_messages
FROM messages
WHERE account_id = :account_id
GROUP BY account_id;
```

> Nota: `STRING_AGG` com `ORDER BY` exige determinismo — ordenar por `(created_at, content)`
> garante que o hash seja o mesmo independente da ordem de inserção.

---

## Proposta de Arquitetura Revisada

### Hierarquia de confiança na validação

```
Nível 1 — Macro (counts)           ← já implementado em modo `summary`
    COUNT(*) por account × tabela
    Sanidade: orphans, display_id dups, pubsub dups

Nível 2 — Hash por account         ← NOVO: substitui `_compare_fields()`
    MD5(STRING_AGG(...)) por account
    → Se igual: 100% dos dados de conteúdo chegaram intactos
    → Se diferente: drill-down por hash individual

Nível 3 — Hash por linha           ← NOVO: substitui `_deep_scan_message()`
    MD5(content || type || created_at) por linha
    EXCEPT entre SOURCE e DEST (Python-side)
    → Identifica exatamente quais linhas diferem

Nível 4 — API check                ← já implementado, mas como enriquecimento
    GET /contacts/{id} — confirma acessibilidade pela camada de aplicação
    GET /contacts/{id}/conversations — confirma exposição pela API
    HEAD external_url — confirma acessibilidade do storage
```

### O que muda no `app/10_validar_api.py`

| Hoje (errado) | Proposto (correto) |
|---------------|-------------------|
| `_compare_fields()` compara todos os campos incluindo IDs | Comparar apenas campos de negócio; IDs são excluídos completamente |
| Falso negativo: `conversation_id match=False` em 100% das msgs | Sem comparação de `conversation_id`; esse campo nunca é signal |
| Match feito por `migration_state id_origem → id_destino` exclusivamente | Match primário por chave de negócio; `migration_state` como auxílio secundário |
| Sem hash de conteúdo | `MD5(content §  message_type § created_at)` por mensagem |
| Sem visão de conjunto por account | Hash agregado por account (Nível 2) como check rápido |
| Sem detecção de dados extras no DEST | `dest_hashes - src_hashes` detecta duplicação |

### Novo campo de resultado: `content_hash_match`

```python
@dataclass
class MessageResult:
    src_id:             int
    dest_id:            int | None
    found_in_dest:      bool
    content_hash_src:   str        # MD5 dos campos de negócio no SOURCE
    content_hash_dest:  str | None # MD5 dos campos de negócio no DEST
    content_hash_match: bool       # content_hash_src == content_hash_dest
    # REMOVIDO: field-by-field com IDs — 100% ruído
```

---

## Decisão Proposta

### D5-DEC-01 — Abandonar `_compare_fields()` para IDs internos

**Decisão**: Remover `conversation_id`, `message_id`, `contact_id`, `inbox_id`,
`sender_id`, `account_id` do `_compare_fields()`. Esses campos nunca serão signal.

### D5-DEC-02 — Adotar hash MD5 de conteúdo como métrica primária

**Decisão**: Para `messages`, usar `MD5(content || message_type || created_at)` como
fingerprint. Para `attachments`, usar `external_url` como BK. Para `contacts`,
usar `(phone_number, email)`.

### D5-DEC-03 — Adicionar modo `hash` ao script

**Decisão**: Novo modo `python app/10_validar_api.py hash --account-src 1`
que executa:
1. Hash por linha no SOURCE (N hashes)
2. Hash por linha no DEST (M hashes)
3. `src - dest` = perdas | `dest - src` = extras
4. Hash agregado por account (fingerprint rápido)

### D5-DEC-04 — Avaliar `dblink` para validação em SQL puro

**Decisão**: Verificar se a role de acesso ao DEST possui permissão para `dblink`.
Se sim, o modo `hash` pode ser implementado com `EXCEPT` em SQL puro (mais eficiente).
Se não, o Python executa as duas queries separadamente e faz a comparação em memória
(set difference). Latência estimada para 239k mensagens: ~10s por connection.

---

## Questões Abertas

| # | Questão | Bloqueante? |
|---|---------|------------|
| Q1 | `dblink` está disponível e com permissão no servidor? | Sim — define implementação SQL vs. Python |
| Q2 | `created_at` é preservado bit-a-bit ou há drift de timezone durante migração? | Sim — define tolerância no hash |
| Q3 | `external_url` de attachments é o mesmo no SOURCE e DEST (migrador não alterou)? | Sim — define BK de attachments |
| Q4 | `additional_attributes->>'src_id'` foi populado em 100% das conversas migradas? | Sim — define âncora de match para conversas |

---

## Próximos Passos

1. **[IMEDIATO]** Verificar Q1: `SELECT * FROM pg_extension WHERE extname = 'dblink';` no DEST
2. **[IMEDIATO]** Verificar Q3: comparar `external_url` de 10 attachments SOURCE vs DEST via `migration_state`
3. **[IMEDIATO]** Verificar Q4: `SELECT COUNT(*) FROM conversations WHERE additional_attributes->>'src_id' IS NULL` no DEST
4. **[IMPLEMENTAÇÃO]** Adicionar modo `hash` em `app/10_validar_api.py` (ou novo `app/11_validar_hash.py`)
5. **[IMPLEMENTAÇÃO]** Refatorar `_compare_fields()` — remover campos de ID, focar em campos de negócio
