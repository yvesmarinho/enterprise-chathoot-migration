# Research: Enterprise Chatwoot Migration

**Branch**: `001-enterprise-chatwoot-migration`
**Phase**: 0 — Pre-design research
**Date**: 2026-04-09
**Status**: Completo — nenhum NEEDS CLARIFICATION pendente

---

## R-001: Estratégia de Bulk Insert com ID Remapping — SQLAlchemy 2.0

**Decision**: `session.execute(insert(Table), list_of_dicts)` com Core bulk insert, dentro de
transação explícita por batch de 500 registros. IDs remapeados no Python antes da inserção.

**Rationale**: SQLAlchemy Core bulk insert com lista de dicts (não ORM `add_all`) é a abordagem
de maior throughput para inserções em massa em versões 2.x. Evita overhead de ORM unit-of-work.
Transação por batch garante atomicidade granular: falha em um batch de 500 não desfaz os
batches anteriores (idempotência + relatório de falhas por ID).

**Alternatives considered**:
- `psycopg2.extras.execute_batch` direto: descartado — bypassa SQLAlchemy e viola Fabric
  Pattern (ConnectionFactory não gerenciaria o cursor)
- ORM `session.bulk_insert_mappings`: deprecated em SQLAlchemy 2.0
- `COPY FROM` / `pg_dump`: descartado — não respeita remapeamento de IDs nem idempotência

**References**: SQLAlchemy 2.0 "ORM-Enabled INSERT, UPDATE, and DELETE" docs; PEP 249

---

## R-002: Padrão de Offset Constante por Sessão

**Decision**: `offset_table[tabela] = SELECT MAX(id) FROM chatwoot004_dev1_db.tabela` executado
uma única vez no início da sessão, antes do primeiro insert. O offset é mantido em dict em memória
durante toda a execução.

**Rationale**: Calcular o offset uma vez garante consistência de FKs: se novos registros chegarem
no destino durante a execução (improvável em DEV, mas defensivo), o offset não muda e não há
colisão de IDs. A tabela `migration_state` serve como fonte de verdade para idempotência, não o
offset.

**Alternatives considered**:
- Re-calcular offset antes de cada entidade: descartado — criaria inconsistência entre `accounts`
  e `contacts` se registros chegassem entre as duas etapas
- Usar UUIDs como IDs alternativos: descartado — Chatwoot usa integer PKs nativamente; mudar
  exigiria DDL nas tabelas da aplicação

---

## R-003: Mascaramento de Dados Sensíveis em Log

**Decision**: Handler de logging customizado `MaskingHandler` que sobrescreve `emit()` e aplica
regexes antes de qualquer escrita (stdout ou arquivo). Regexes cobrem: e-mail, CPF/CNPJ,
telefone BR, nomes próprios (fallback: mascarar qualquer valor de coluna identificada como
`sensitive_columns`).

**Rationale**: Filtro aplicado no handler (não no formatter) garante que mascaramento ocorre
independente do nível de log. Abordagem de lista `sensitive_columns` por tabela é mais precisa
que regex puro (evita falsos positivos em IDs numéricos ou URLs S3).

**Sensitive columns por entidade**:
| Entidade | Colunas sensíveis |
|---|---|
| contacts | name, email, phone_number, identifier, additional_attributes |
| users | name, email, phone_number |
| conversations | additional_attributes, meta |
| messages | content, content_attributes |
| accounts | name |

**Alternatives considered**:
- Logging com `%(message)s` truncado: insuficiente — não impede que IDs sejam correlacionados
- Desabilitar log de conteúdo completamente: descartado — impossibilita diagnóstico de falhas
- PII detection library (Presidio): overhead desnecessário para um script one-shot

---

## R-004: Tabela `migration_state` — Schema e Estratégia de Idempotência

**Decision**: DDL criado automaticamente na primeira execução via SQLAlchemy `metadata.create_all`.
Schema definitivo:

```sql
CREATE TABLE IF NOT EXISTS migration_state (
    id          BIGSERIAL PRIMARY KEY,
    tabela      VARCHAR(100) NOT NULL,
    id_origem   BIGINT       NOT NULL,
    id_destino  BIGINT,
    status      VARCHAR(20)  NOT NULL DEFAULT 'ok',  -- 'ok' | 'failed'
    migrated_at TIMESTAMP    NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_migration_state UNIQUE (tabela, id_origem)
);
CREATE INDEX IF NOT EXISTS ix_migration_state_tabela ON migration_state(tabela);
```

**Rationale**: `UNIQUE (tabela, id_origem)` garante idempotência: `INSERT ... ON CONFLICT DO NOTHING`
por registro já migrado. `id_destino` permite auditoria bidirecional. `status='failed'` permite
filtrar e re-tentar apenas falhas sem re-processar sucessos.

**Idempotency query pattern**:
```python
# Antes de cada batch: filtrar IDs ainda não migrados
already_done = session.execute(
    select(migration_state.c.id_origem)
    .where(migration_state.c.tabela == table_name)
    .where(migration_state.c.status == 'ok')
).scalars().all()
batch = [r for r in batch if r['id'] not in already_done_set]
```

**Alternatives considered**:
- Arquivo JSON local: descartado — não atômico, corrompível, não consultável via SQL
- SQLite local: descartado — adiciona dependência sem vantagem sobre tabela no destino

---

## R-005: Ordem de Migração por Grafo de FK

**Decision**: Ordem sequencial obrigatória por dependência:

```
accounts (raiz)
  ├── inboxes       -- FK: account_id
  ├── users         -- FK: account_id
  ├── teams         -- FK: account_id
  ├── labels        -- FK: account_id
  └── contacts      -- FK: account_id
        └── conversations  -- FK: contact_id, inbox_id, account_id
              ├── messages      -- FK: conversation_id, account_id
              └── attachments   -- FK: message_id
```

**Rationale**: schema_sha1 idêntico confirma que o grafo de FK é o mesmo nas duas instâncias.
A ausência de FKs circulares foi verificada via ERD em `docs/db_erd/`. FKs entre `conversations`
e `users`/`teams`/`labels` são nullable — não bloqueiam a ordem acima.

**Known inconsistencies na origem (migrar no estado atual)**:
- Conversations sem `contact_id` válido: registrar no relatório, skip
- Messages sem `conversation_id` válido: registrar no relatório, skip

---

## R-006: pytest-cov — Configuração para 90% fail_under

**Decision**: `pyproject.toml` com seção `[tool.pytest.ini_options]` + `[tool.coverage.report]`:

```toml
[tool.pytest.ini_options]
addopts = "--cov=src --cov-report=term-missing --cov-fail-under=90"
testpaths = ["test"]

[tool.coverage.run]
source = ["src"]
omit = ["src/migrar.py"]  # entrypoint — testado por integration tests

[tool.coverage.report]
fail_under = 90
show_missing = true
```

**Rationale**: `--cov-fail-under=90` em `addopts` garante que `make test` falha se cobertura
cair abaixo de 90% sem nenhuma flag extra. `src/migrar.py` excluído da cobertura de unit tests
(coberto por `test/integration/test_migration_flow.py`).

**Alternatives considered**:
- `.coveragerc` separado: desnecessário quando `pyproject.toml` já existe no projeto
- 100% coverage: rejeitado pelo owner (Q4 do speckit.clarify) — custo de mocks para caminhos
  de erro raros não justifica o ganho

---

## R-007: Conexão PostgreSQL sem SSL — psycopg2-binary

**Decision**: `create_engine(url, connect_args={"sslmode": "disable"})`. Parâmetro `options`
removido (servidor rejeita `statement_timeout` como startup parameter — validado em D1).

**Rationale**: Confirmado empiricamente: `wfdb02.vya.digital` não aceita `options="-c statement_timeout=..."`.
SSL desabilitado conforme `.secrets/generate_erd.json` (`"SSL": false`). Conexões criadas
exclusivamente via `ConnectionFactory` — nenhum módulo acessa o banco diretamente.

**Connection string pattern**:
```python
url = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{database}"
engine = create_engine(url, connect_args={"sslmode": "disable"}, pool_pre_ping=True)
```

`pool_pre_ping=True` detecta conexões mortas antes do uso (proteção contra idle timeout da VPS).

---

## Summary: Decisions Finalized

| ID | Decisão | Status |
|----|---------|--------|
| R-001 | Bulk insert via SQLAlchemy Core, batch=500, transação por batch | ✅ Definido |
| R-002 | Offset constante por sessão, calculado uma vez no início | ✅ Definido |
| R-003 | MaskingHandler no logging, sensitive_columns por tabela | ✅ Definido |
| R-004 | Tabela `migration_state` com UNIQUE(tabela, id_origem) + DDL auto | ✅ Definido |
| R-005 | Ordem FK: accounts→inboxes→users→teams→labels→contacts→conversations→messages→attachments | ✅ Definido |
| R-006 | pytest-cov 90% fail_under em pyproject.toml | ✅ Definido |
| R-007 | psycopg2 sslmode=disable, sem options, pool_pre_ping=True | ✅ Definido |

**Nenhum NEEDS CLARIFICATION remanescente. Prosseguir para Phase 1 (Design).**
