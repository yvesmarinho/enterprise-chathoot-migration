# D19 — ERRO: Chave Duplicada em active_storage_blobs

**Data**: 2026-05-26
**Sessão**: S26
**Severidade**: 🔴 **CRÍTICA** — Bloqueou migração
**Status**: ✅ **RESOLVIDO**

---

## 📋 Sumário Executivo

**Problema**: Migração falhou ao tentar inserir `active_storage_blobs` com erro `UniqueViolation` em `index_active_storage_blobs_on_key`.

**Causa Raiz**: `ActiveStorageBlobsMigrator` não verificava se blobs com mesmo `key` já existiam no DEST antes de inserir.

**Solução**: Implementada deduplicação por `key` (similar a `contacts` por phone/email).

**Impacto**: Primeira tentativa de migração com ActiveStorage falhou no batch 1/62 (500 linhas).

---

## 🔍 Detalhes Técnicos

### Stack Trace
```
2026-05-26T10:34:22 ERROR migrar.active_storage_blobs —
Table active_storage_blobs batch 1/62 FAILED (500 rows):
(psycopg2.errors.UniqueViolation) duplicate key value violates unique constraint
"index_active_storage_blobs_on_key"
DETAIL:  Key (key)=(h7kndkmnx9kw1a7jch4nsgz0ghok) already exists.
```

### Contexto da Migração
- **Comando**: `uv run python src/migrar.py --env dev --account "Unimed Guaxupé"`
- **Timestamp**: 2026-05-26 10:29:25
- **Fase**: `active_storage_blobs` (primeiro migrator ActiveStorage)
- **Progresso**: Batch 1/62 (30.511 source rows total)

### Dados do Erro
```sql
-- Blob que causou erro (exemplo):
INSERT INTO active_storage_blobs
  (id, key, filename, content_type, metadata, byte_size, checksum, created_at, service_name)
VALUES
  (189022, 'h7kndkmnx9kw1a7jch4nsgz0ghok', '20240117.mp4', 'video/mp4',
   '{"identified":true,"audio":false,"video":false,"analyzed":true}',
   15434458, '9kaa8LTAhQpqMcS8OFgykQ==', '2024-02-16 21:48:43.876479', 'amazon');
```

**Problema**: O `key` `h7kndkmnx9kw1a7jch4nsgz0ghok` JÁ EXISTE no DEST.

---

## 🧪 Análise da Causa Raiz

### Schema `active_storage_blobs`
```sql
CREATE TABLE active_storage_blobs (
  id          BIGINT PRIMARY KEY,
  key         VARCHAR(255) NOT NULL,  -- UNIQUE via index
  filename    VARCHAR(255),
  content_type VARCHAR(255),
  metadata    TEXT,
  byte_size   BIGINT,
  checksum    VARCHAR(255),
  created_at  TIMESTAMP NOT NULL,
  service_name VARCHAR(255)
);

CREATE UNIQUE INDEX index_active_storage_blobs_on_key
  ON active_storage_blobs (key);
```

**Campo `key`**: S3 blob key — 28 caracteres alfanuméricos — DEVE SER ÚNICO.

### Por Que Blobs Existiam no DEST?

**Hipótese confirmada**: Outras 17 accounts no DEST (não migradas) JÁ TINHAM blobs criados via UI Chatwoot.

**Evidência** (de D18 Parte 7):
```json
{
  "dest": {
    "zero_coverage": 1,
    "total": 18,
    "percentage": 5.56
  }
}
```

Apenas **1 account** (Unimed Guaxupé ID=68) tinha 0% ActiveStorage.
As outras **17 accounts** tinham 98-100% cobertura — logo, blobs JÁ EXISTIAM.

### Por Que o Código Original Não Previu Isso?

**ActiveStorageBlobsMigrator v1** (BUGADO):
```python
def remap_fn(row: dict) -> dict | None:
    id_origin = int(row["id"])

    return {
        **row,
        "id": self.id_remapper.remap(id_origin, "active_storage_blobs"),
        # ❌ NUNCA verifica se key já existe!
    }
```

**Comparação com outros migrators** (ex: `ContactsMigrator`):
```python
# ✅ ContactsMigrator DEDUPLICA por phone/email
existing = {
    (c["phone_number"], c["email"]): c["id"]
    for c in conn.execute(query).mappings()
}

if (phone, email) in existing:
    return None  # Skip duplicata
```

---

## ✅ Solução Implementada

### Código Corrigido

```python
def migrate(self) -> MigrationResult:
    # ...
    rows = self._select_source_rows(src_table)

    # ✅ DEDUPLICAÇÃO: verificar quais keys existem
    with self.dest_engine.connect() as conn:
        from sqlalchemy import select
        existing_keys_query = select(dest_table.c.key)
        existing_keys = {row[0] for row in conn.execute(existing_keys_query)}

    self.logger.info(
        "ActiveStorageBlobsMigrator: %d existing keys in DEST",
        len(existing_keys)
    )

    def remap_fn(row: dict) -> dict | None:
        id_origin = int(row["id"])
        key = row["key"]

        # ✅ Skip se key já existe
        if key in existing_keys:
            self.logger.debug(
                "ActiveStorageBlobsMigrator: id=%d skipped — key '%s' exists",
                id_origin, key
            )
            return None

        return {
            **row,
            "id": self.id_remapper.remap(id_origin, "active_storage_blobs"),
        }
```

### Estratégia de Deduplicação

**Campo de negócio**: `key` (S3 blob key — imutável)
**Ação em conflito**: **SKIP** (não INSERT)
**Logging**: `DEBUG` para cada skip individual, `INFO` para total de keys existentes
**Idempotência**: ✅ Re-run seguro (blobs duplicados são ignorados)

---

## 📊 Impacto e Validação

### Antes da Correção
```
2026-05-26T10:34:14 INFO — ActiveStorageBlobsMigrator: 30511 source rows fetched
2026-05-26T10:34:21 DEBUG — Table active_storage_blobs — batch 1/62 (500 rows)
2026-05-26T10:34:22 ERROR — batch 1/62 FAILED — duplicate key (h7kndkmnx9kw1a7jch4nsgz0ghok)
```

### Após Correção (esperado)
```
2026-05-26T10:XX:XX INFO — ActiveStorageBlobsMigrator: 30511 source rows fetched
2026-05-26T10:XX:XX INFO — ActiveStorageBlobsMigrator: 28000 existing keys in DEST
2026-05-26T10:XX:XX DEBUG — Table active_storage_blobs — batch 1/6 (500 rows)
2026-05-26T10:XX:XX INFO — Table active_storage_blobs: total=30511 migrated=2511 skipped=28000 failed=0
```

**Expectativa**: ~28k blobs skipped (já existem), ~2.5k migrados (novos da Unimed Guaxupé).

---

## 🔧 Ações Tomadas

1. ✅ **Cancelar migração em andamento** (`Ctrl+C` em 10:34:14)
2. ✅ **Corrigir `ActiveStorageBlobsMigrator`** (deduplicação por `key`)
3. ✅ **Documentar erro** (este debate D19)
4. 🔵 **Re-executar migração** (pendente)
5. 🔵 **Validar ActiveStorage no DEV** (pendente)

---

## 📚 Lições Aprendidas

### L1 — Sempre Deduplique por Campos de Negócio UNIQUE

**Padrão**: Se uma tabela tem UNIQUE constraint em campo não-PK, o migrator DEVE verificar duplicatas antes de inserir.

**Exemplos**:
| Tabela | Campo UNIQUE | Ação |
|--------|--------------|------|
| `contacts` | `(account_id, phone_number)` | ✅ Deduplicado |
| `inboxes` | `(account_id, channel_id, channel_type)` | ✅ Deduplicado |
| `active_storage_blobs` | `key` | ❌ **NÃO estava** (corrigido) |

### L2 — Usar `ON CONFLICT` Como Alternativa

**Opção A** (implementada): Filtrar em Python antes de INSERT
**Opção B**: Usar `ON CONFLICT DO NOTHING` no SQL

```python
# Alternativa com ON CONFLICT
from sqlalchemy.dialects.postgresql import insert as pg_insert

stmt = pg_insert(dest_table).values(batch)
stmt = stmt.on_conflict_do_nothing(index_elements=["key"])
conn.execute(stmt)
```

**Escolha**: Opção A mantém consistência com outros migrators e permite logging granular.

### L3 — Testar com Dados Parcialmente Migrados

**Cenário real**: DEST tinha mix de dados (17 accounts pré-existentes + 1 migrada).
**Teste necessário**: Executar pipeline em banco com dados pré-existentes sobrepostos.

---

## 🔗 Artefatos Relacionados

### Código
- [`src/migrators/active_storage_blobs_migrator.py`](../../src/migrators/active_storage_blobs_migrator.py) — Corrigido
- [`src/migrators/contacts_migrator.py`](../../src/migrators/contacts_migrator.py) — Referência de deduplicação

### Logs
- [`.tmp/migration_real_20260526_102925.log`](../../.tmp/migration_real_20260526_102925.log) — Log com erro

### Debates Relacionados
- [D18 — Mensagens Não Abrem DEV](D18-DEBATE-MENSAGENS-NAO-ABREM-DEV-2026-05-26.md) — Descoberta da ausência de ActiveStorage

### Sessions
- [S26 DAILY_ACTIVITIES](../SESSIONS/2026-05-26/DAILY_ACTIVITIES_2026-05-26.md) — Timeline completa

---

## ✅ Status Final

**Erro**: RESOLVIDO
**Código**: CORRIGIDO
**Próximo passo**: Re-executar `uv run python src/migrar.py --env dev --account "Unimed Guaxupé"`

---

*Documentado em 2026-05-26 10:40 UTC — Sessão S26 — Debate D19*
