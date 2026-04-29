# Implementation Plan: Enterprise Chatwoot Migration

**Branch**: `001-enterprise-chatwoot-migration` | **Date**: 2026-04-09 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `.specify/features/001-enterprise-chatwoot-migration/spec.md`

## Summary

Migração incremental e idempotente de todos os dados de `chatwoot_dev1_db` (origem, somente
leitura) para `chatwoot004_dev1_db` (destino, leitura/escrita), utilizando o Fabric Design
Pattern com Factory + Repository. IDs remapeados via offset (`novo_id = id_origem + max(id_destino)`, onde `offset = MAX(id)` calculado uma única vez por sessão — se tabela vazia no destino, offset=0 e IDs da origem são preservados),
inserção em batches de 500 registros por transação, estado rastreado em tabela `migration_state`
no destino. Interface: `python src/migrar.py`. ~418k registros de origem.

## Technical Context

**Language/Version**: Python 3.12+
**Primary Dependencies**: SQLAlchemy 2.0.49 (Core + ORM), psycopg2-binary 2.9.11, alembic 1.18.4 (referência), ruff 0.15.10, black 26.3.1, pytest 9.0.3, pytest-cov
**Storage**: PostgreSQL 16.10 — `wfdb02.vya.digital:5432`, sem SSL (`sslmode=disable`). Dois bancos: `chatwoot_dev1_db` (read-only) e `chatwoot004_dev1_db` (read-write).
**Testing**: pytest + doctest integrado; cobertura mínima 90% (`--fail-under=90`) nos módulos críticos.
**Target Platform**: Linux (execução local com acesso de rede à VPS)
**Project Type**: CLI script (data migration tool)
**Performance Goals**: Migrar ~418k registros em < 2 horas. Batch de 500 registros minimiza roundtrips mantendo granularidade de recovery.
**Constraints**: `sslmode=disable`; credenciais exclusivamente de `.secrets/generate_erd.json`; `chatwoot_dev1_db` somente leitura; mascaramento automático de dados sensíveis em todos os outputs; offset calculado uma única vez por sessão.
**Scale/Scope**: Origem: 418.828 registros / 9 entidades. Destino atual: 1.756.173 registros. Volume total pós-migração: ~2.175k registros.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Princípio | Status | Evidência |
|-----------|--------|-----------|
| I. Fabric Design Pattern | ✅ PASS | `ConnectionFactory` + `Migrator` por entidade + `Repository` definidos na estrutura de código |
| II. Integridade & Remapeamento de IDs | ✅ PASS | `id_remapper.py` com offset constante por sessão; FK graph explícito em FR-003 |
| III. Segurança & Privacidade | ✅ PASS | `log_masker.py` obrigatório; creds só de `.secrets/`; `chatwoot_dev1_db` read-only |
| IV. Idempotência & Execução Incremental | ✅ PASS | Tabela `migration_state` no destino; verificação antes de cada insert |
| V. Qualidade por Contrato | ✅ PASS | ruff + black + docstring RST + doctest + pytest 90% coverage |

**Resultado**: Nenhuma violação. Prosseguir para Phase 0.

## Project Structure

### Documentation (this feature)

```text
.specify/features/001-enterprise-chatwoot-migration/
├── plan.md              # Este arquivo
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── cli-contract.md
└── tasks.md             # Phase 2 output (/speckit.tasks — NÃO criado aqui)
```

### Source Code (repository root)

```text
src/
├── migrar.py                        # Entrypoint único: orquestra migrators em ordem de FK
├── factory/
│   └── connection_factory.py        # Cria engines SQLAlchemy (origem RO, destino RW)
├── repository/
│   ├── base_repository.py           # CRUD genérico com SQLAlchemy Core
│   └── migration_state_repository.py # Acesso à tabela migration_state
├── migrators/
│   ├── base_migrator.py             # Contrato abstrato Fabric
│   ├── accounts_migrator.py
│   ├── inboxes_migrator.py
│   ├── users_migrator.py
│   ├── teams_migrator.py
│   ├── labels_migrator.py
│   ├── contacts_migrator.py
│   ├── conversations_migrator.py
│   ├── messages_migrator.py
│   └── attachments_migrator.py
├── utils/
│   ├── id_remapper.py               # Cálculo de offset e remapeamento de FKs
│   ├── log_masker.py                # Mascaramento automático de dados sensíveis
│   └── fk_validator.py             # Validação pós-migração de integridade referencial
└── reports/
    ├── validation_reporter.py       # Relatório final por tabela
    └── poc_reporter.py              # Classificação POC dry-run + report

test/
├── unit/
│   ├── test_id_remapper.py
│   ├── test_log_masker.py
│   ├── test_fk_validator.py
│   ├── test_connection_factory.py
│   ├── test_accounts_migrator.py
│   ├── test_inboxes_migrator.py
│   ├── test_users_migrator.py
│   ├── test_teams_migrator.py
│   ├── test_labels_migrator.py
│   ├── test_contacts_migrator.py
│   ├── test_conversations_migrator.py
│   ├── test_messages_migrator.py
│   └── test_attachments_migrator.py
└── integration/
    └── test_migration_flow.py

.tmp/                                # Logs de execução (não versionado)
    └── migration_YYYYMMDD_HHMMSS.log
```

**Structure Decision**: Single project (Option 1). CLI script sem frontend. Toda a lógica
em `src/` com Fabric Pattern. `test/` espelha `src/` para cobertura 1:1 por módulo.

## Complexity Tracking

> Nenhuma violação de Constitution identificada — seção não aplicável.
