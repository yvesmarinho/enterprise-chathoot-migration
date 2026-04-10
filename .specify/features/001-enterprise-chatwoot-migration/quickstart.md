# Quickstart: Enterprise Chatwoot Migration

**Branch**: `001-enterprise-chatwoot-migration`
**Date**: 2026-04-09

---

## Pré-requisitos

- Python 3.12+ (`python --version`)
- `uv` instalado (`uv --version`)
- Acesso de rede a `wfdb02.vya.digital:5432`
- Arquivo `.secrets/generate_erd.json` preenchido com credenciais válidas
- Backup de `chatwoot004_dev1_db` confirmado pelo owner

---

## Setup (uma vez)

```bash
# 1. Clonar e entrar no diretório
cd /home/yves_marinho/Documentos/DevOps/Vya-Jobs/enterprise-chathoot-migration

# 2. Instalar dependências
uv sync

# 3. Verificar conexão e versões dos bancos
python scripts/check_chatwoot_versions.py
```

Saída esperada de (3): tabela com schema_sha1, última migration e contagens por tabela.

---

## Executar a Migração

```bash
# Execução completa
python src/migrar.py

# Dry-run (sem escrita)
python src/migrar.py --dry-run

# Migrar apenas uma tabela (ex: para testes)
python src/migrar.py --only-table contacts

# Verbose (debug)
python src/migrar.py --verbose
```

O log é exibido em stdout e salvo simultaneamente em `.tmp/migration_YYYYMMDD_HHMMSS.log`.

---

## Executar Testes

```bash
# Todos os testes + cobertura
make test
# ou diretamente:
uv run pytest

# Apenas unit tests
uv run pytest test/unit/

# Lint + format check
make lint
```

Cobertura mínima: **90%** nos módulos críticos. `make test` falha se abaixo disso.

---

## Verificar Resultado

```bash
# Relatório de validação (gerado automaticamente ao final)
cat .tmp/migration_YYYYMMDD_HHMMSS_report.txt

# Consulta rápida ao migration_state (via psql)
psql -h wfdb02.vya.digital -U <user> -d chatwoot004_dev1_db \
  -c "SELECT tabela, COUNT(*) as total, SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) as falhas FROM migration_state GROUP BY tabela ORDER BY MIN(migrated_at);"
```

---

## Re-execução após Falha

O script é idempotente. Após qualquer falha:

```bash
# Simplesmente re-executar — registros já migrados não são duplicados
python src/migrar.py
```

Em caso de falha catastrófica (exit code 3), restaurar o backup antes de re-executar:
1. Restaurar `chatwoot004_dev1_db` a partir do backup
2. Re-executar `python src/migrar.py`

---

## Estrutura de Arquivos Relevantes

```
src/migrar.py                   ← Entrypoint
src/factory/connection_factory.py
src/utils/id_remapper.py
src/utils/log_masker.py
test/unit/                      ← Testes unitários
.secrets/generate_erd.json      ← Credenciais (não versionado)
.tmp/migration_*.log            ← Logs de execução (não versionado)
.specify/features/001-enterprise-chatwoot-migration/
├── spec.md                     ← Especificação
├── plan.md                     ← Este plano
├── research.md                 ← Decisões técnicas
├── data-model.md               ← Modelo de dados
└── contracts/cli-contract.md  ← Contrato da interface CLI
```
