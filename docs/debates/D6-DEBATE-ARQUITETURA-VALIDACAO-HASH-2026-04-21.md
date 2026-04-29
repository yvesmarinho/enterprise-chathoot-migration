# D6 — DEBATE: Arquitetura de Validação Pós-Migração — Carga no DB vs. Processamento Local

**Data**: 2026-04-21
**Contexto**: D5-REVISAO identificou que a validação por hash é o método correto.
  Este debate responde a duas questões antes de implementar.
**Participantes**: @system-engineer, @dba-sql-expert, @python-expert

---

## Questões

1. O novo processo de validação por hash vai aumentar a carga no banco de dados?
2. Não seria mais produtivo usar recursos de análise de dados (Pandas, etc.) em lote
   neste computador ao invés de executar a comparação no banco?

---

## Análise — Q1: Carga no banco

### Medindo a carga do método atual (app/10_validar_api.py)

O script atual para cada mensagem executa:

```
1 × SELECT migration_state WHERE id_origem = ?    (lookup individual)
1 × SELECT messages WHERE id = ?                  (busca dest por PK)
→ Total: 2 queries × 239.439 mensagens = 478.878 queries para mensagens
```

Mais:

```
1 × SELECT migration_state WHERE id_origem = ?    por conversa  →  36.016 × 2 = 72.032
1 × SELECT migration_state WHERE id_origem = ?    por contato   →  5.966 × 2  = 11.932
1 × SELECT migration_state WHERE id_origem = ?    por attachment → 22.841 × 2 = 45.682
```

**Total estimado: ~608.000 queries individuais** para varrer toda a massa de dados.
Isso é um **anti-padrão N+1 em escala industrial** — extremamente agressivo ao banco.

### Método proposto 1 — Hash em SQL (bulk aggregado)

```sql
-- Uma query por account no SOURCE, uma no DEST
SELECT
    MD5(STRING_AGG(
        MD5(CONCAT_WS('§', COALESCE(content,''), message_type::text,
                      content_type::text,
                      TO_CHAR(created_at AT TIME ZONE 'UTC',
                              'YYYY-MM-DD HH24:MI:SS.US'))),
        '|' ORDER BY created_at, COALESCE(content,'')
    )) AS account_hash,
    COUNT(*) AS total
FROM messages
WHERE account_id = :account_id;
```

**Total de queries**: 2 queries por tabela × 5 accounts = **~40 queries** para toda a validação.
Redução de **99,99%** em relação ao método atual.

Porém: `STRING_AGG` sobre 239k linhas numa única query é uma **operação de alta memória no servidor**.
PostgreSQL precisa materializar todas as linhas, calcular cada MD5, e depois agregar.
Dependendo da configuração de `work_mem`, pode gerar spill para disco.

### Método proposto 2 — Bulk SELECT + Pandas local

```python
# SOURCE: uma query, retorna todas as linhas com campos de negócio
df_src = pd.read_sql("""
    SELECT account_id, message_type, content_type, created_at,
           MD5(CONCAT_WS('§', COALESCE(content,''),
                         message_type::text, content_type::text,
                         TO_CHAR(created_at AT TIME ZONE 'UTC',
                                 'YYYY-MM-DD HH24:MI:SS.US'))) AS msg_hash
    FROM messages
    WHERE account_id = ANY(%(ids)s)
""", src_engine, params={"ids": [1, 4, 17, 18, 25]})

# DEST: idem
df_dst = pd.read_sql("...", dest_engine, params=...)

# Comparação local — zero queries adicionais
missing = set(df_src["msg_hash"]) - set(df_dst["msg_hash"])
extra   = set(df_dst["msg_hash"]) - set(df_src["msg_hash"])
```

**Total de queries**: **2 queries** (1 SOURCE + 1 DEST) para mensagens.
O banco executa apenas 1 `SELECT` por banco — o trabalho pesado fica na máquina local.

### Comparativo de carga

| Método | Queries ao banco | Trabalho no servidor | Trabalho local |
|--------|-----------------|---------------------|----------------|
| Atual (N+1) | ~608.000 | 608.000 index lookups | mínimo |
| Hash SQL agregado | ~40 | `STRING_AGG` de 239k linhas | mínimo |
| Bulk + Pandas | **2–8** | `SELECT` com `MD5()` inline | DataFrame em memória |

**Vencedor em carga**: Bulk + Pandas — mínimo de queries, servidor só executa `SELECT`.

---

## Análise — Q2: Pandas local vs. processamento no banco

### Estimativa de volume de dados transferidos

| Tabela | Linhas | Campos de negócio | Tamanho estimado por linha | Total estimado |
|--------|--------|------------------|--------------------------|----------------|
| messages | 239.439 | content + 3 campos | ~150–500 bytes | ~60–120 MB |
| contacts | 5.966 | phone + email + name | ~80 bytes | < 1 MB |
| conversations | 36.016 | display_id + status + created_at | ~40 bytes | ~1.5 MB |
| attachments | 22.841 | external_url | ~100 bytes | ~2.3 MB |

**Total estimado: ~65–125 MB** transferidos da rede. Em conexão local (mesmo servidor),
a transferência é via loopback — latência < 1ms/pacote. Tempo estimado: 15–30s.

### Capacidade do ambiente local

A máquina local pode processar isso com folga:
- 125 MB de DataFrames em RAM: trivial (Python usa ~3–5× o tamanho dos dados → ~400–600 MB)
- Pandas `set()` operations sobre 239k hashes de 32 bytes = ~7MB de sets
- Tempo de processamento local: < 5s

### O que Pandas/local habilita que SQL não habilita facilmente

| Análise | SQL puro | Pandas local |
|---------|----------|-------------|
| Hash de conteúdo (MD5) | ✅ com `pgcrypto` | ✅ nativo |
| Set difference (perdas/extras) | ❌ sem `dblink` | ✅ trivial |
| Agrupamento por account | ✅ | ✅ |
| Análise de duplicatas (deduplicação pós-migração) | ⚠️ trabalhoso | ✅ `duplicated()` |
| Exportação para CSV/Excel/JSON | ❌ fora do banco | ✅ trivial |
| Filtros ad-hoc sem nova query | ❌ nova query | ✅ df filtrado |
| Cross-DB comparison sem `dblink` | ❌ impossível em SQL | ✅ 2 DataFrames |
| Visualização de distribuição de perdas | ❌ fora do banco | ✅ `value_counts()` |
| Re-análise sem reconectar ao banco | ❌ | ✅ salvar parquet/pickle |

### Risco de Pandas: volume de conteúdo

O campo `content` das mensagens pode conter texto longo. Se a migração incluiu mensagens
com conteúdo de vários KB cada (e.g. templates HTML, JSON de cards), o volume real pode
ser maior do que estimado. Mitigação: **usar `MD5()` no SQL antes de transferir** — em vez
de trazer o `content` completo, trazer apenas o hash calculado no servidor:

```sql
-- Transfere apenas hashes — 32 bytes por linha, não o conteúdo completo
SELECT
    account_id,
    MD5(CONCAT_WS('§',
        COALESCE(content, ''),
        message_type::text,
        content_type::text,
        TO_CHAR(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS.US')
    )) AS msg_hash,
    created_at  -- para diagnóstico quando hash diverge
FROM messages
WHERE account_id = ANY(%(ids)s)
```

**Resultado**: 239.439 linhas × ~50 bytes = **~12 MB** transferidos. Processamento: < 5s.

---

## Perspectiva @dba-sql-expert — O papel correto do banco

O banco deve fazer o que faz melhor: **filtrar, indexar e calcular `MD5()` inline**.
A comparação entre os dois conjuntos de hashes é uma operação de teoria de conjuntos —
Python/Pandas é o ambiente natural para isso, não SQL (que exigiria `dblink` indisponível).

Arquitetura correta:

```
SOURCE DB    ──[ SELECT + MD5() ]──▶ df_src  ─┐
                                               ├─▶  Pandas  ─▶  relatório
DEST DB      ──[ SELECT + MD5() ]──▶ df_dst  ─┘
```

O banco é tratado como **fonte de dados**, não como motor de análise. Isso é especialmente
correto quando os dois bancos são instâncias separadas (mesmo que no mesmo servidor).

---

## Perspectiva @system-engineer — Arquitetura do novo script

### Proposta: `app/11_validar_hash.py`

Separado do `app/10_validar_api.py` por responsabilidade:

| Script | Responsabilidade |
|--------|-----------------|
| `app/10_validar_api.py` | Validação via API REST + contagens + sanidade |
| `app/11_validar_hash.py` | Validação de integridade de conteúdo por hash (DB-only) |

Modo de execução proposto:

```bash
# Validação completa de todas as tabelas
python app/11_validar_hash.py

# Apenas mensagens, apenas accounts específicos
python app/11_validar_hash.py --tables messages --accounts 1 4

# Salvar DataFrames para análise offline
python app/11_validar_hash.py --save-parquet
```

### Pipeline interno

```
1. Carregar account_map de migration_state              (1 query)
2. Para cada tabela [contacts, conversations, messages, attachments]:
   a. SELECT + MD5() no SOURCE → df_src                 (1 query)
   b. SELECT + MD5() no DEST   → df_dst                 (1 query)
   c. Pandas: missing = src - dest | extra = dest - src
   d. Pandas: duplicados = dest[dest.duplicated('hash')]
3. Gerar relatório consolidado em .tmp/
   - JSON com resumo por tabela (counts, missing, extra, dups)
   - CSV com hashes divergentes (para drill-down manual)
4. sys.exit(0) se missing == 0, sys.exit(2) se missing > 0
```

**Total de queries ao banco: 8–10** (2 por tabela × 4–5 tabelas).

---

## Decisão

### D6-DEC-01 — Usar Bulk SELECT + Pandas (não hash SQL agregado)

**Decisão**: Implementar `app/11_validar_hash.py` com Pandas.
- 2 queries por tabela (SOURCE + DEST)
- `MD5()` calculado no servidor (só hashes trafegam pela rede)
- Comparação de conjuntos em Python
- Sem `dblink`, sem N+1, sem `STRING_AGG` de 239k linhas

**Justificativa**: menor carga no banco, máxima flexibilidade de análise, sem dependências
externas além de `pandas` (já presente no `pyproject.toml` ou fácil de adicionar).

### D6-DEC-02 — `MD5()` no servidor, não no cliente

**Decisão**: Calcular o hash no SQL (`MD5(CONCAT_WS(...))`) antes de transferir os dados.
Isso reduz o volume de rede de ~65–125 MB para **~12 MB** e evita trazer conteúdo de
mensagens para a memória local.

### D6-DEC-03 — Salvar resultados em parquet para re-análise

**Decisão**: Opção `--save-parquet` persiste os DataFrames em `.tmp/` para análise
ad-hoc sem necessidade de reconectar ao banco. Útil para auditoria futura.

---

## Próximo passo

Implementar `app/11_validar_hash.py` com as decisões D6-DEC-01, D6-DEC-02 e D6-DEC-03.
Dependência nova: `pandas` (verificar se já está no `pyproject.toml`).
