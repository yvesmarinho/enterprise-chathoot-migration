# 🔄 Session Recovery — 2026-05-20

**Sessão anterior**: 2026-05-19 (Sessão 20 — Scripts reorganizados + BUG-SENDER corrigido)
**Branch**: `master`
**Status dos IMPs**: Pipeline validado em DEV — pronto para produção

## Contexto Recuperado

**Última sessão (2026-05-19 — Sessão 20)**: Dividida em 2 partes principais:

### Parte 1: Code Review + Migração DEV Completa
- ✅ **BUG-SENDER** corrigido em `messages_migrator.py` — sender_type='Contact' agora remapeia sender_id via `migrated_contacts`
- ✅ **VALIDATION-REFACTOR** — `fk_validator.py` + `validation_reporter.py` + `migrar.py` — account-scoped queries implementadas
- ✅ **MIGRATION-DEV-UNIMED** — Migração DEV Unimed Guaxupé executada: 35.976 registros, 0 erros, FK integrity 100% clean

### Parte 2: Reorganização de Scripts
- ✅ **SCRIPTS-REFACTOR** — 7 scripts refatorados com argparse (CLI parametrizado):
  - `validate_migration.py`, `check_conversations.py`, `check_inbox_mapping.py`
  - `check_db_schema.py`, `rollback_account.py`, `test_api_endpoints.py`, `validate_api.py`
- ✅ **SCRIPTS-CREDENTIALS** — Credenciais externalizadas para `.secrets/`:
  - DB: `.secrets/generate_erd.json` (env vars `MIGRATION_SOURCE_KEY`/`MIGRATION_DEST_KEY`)
  - API: `.secrets/chatwoot_api_tokens.json` (instance→{base_url, token})
- ✅ **SCRIPTS-DOCS** — Documentação completa: `scripts/README.md` (300+ linhas, exemplos de uso, troubleshooting)
- ✅ **CLEANUP-TMP** — `.tmp/` limpo: 45 arquivos deletados (diag scripts + outputs antigos), 4 preservados (essenciais)

## Itens P0 para Esta Sessão

De acordo com `docs/TODO.md`:

1. **PREP-1**: Backup completo do banco DEST (produção) antes de iniciar migrações
2. **PREP-2**: ✅ **CRÍTICO** — Regenerar authentication_token no DEST (SQL pronto)
3. **PREP-3**: Limpar sessões Devise antigas no DEST
4. **PREP-4**: Verificar duplicatas de phone no SOURCE
5. **PREP-5**: Notificar usuários finais (manutenção programada)
6. **MIGRAÇÃO PRODUÇÃO**: Executar migração para os 5 accounts seguindo ordem do RUNBOOK:
   - Sol Copernico (account 4)
   - Unimed Poços PF (account 18)
   - Unimed Poços PJ (account 17)
   - Unimed Guaxupé (account 25)
   - Vya Digital (account 1)
7. **Validações pós-migração**: `uv run python app/02_verificar.py "Nome"` para cada account

## Estado Atual do Projeto

- **Pipeline**: ✅ Validado 100% em DEV (Unimed Guaxupé — 4092 convs, FK integrity clean)
- **Bugs conhecidos**: TODOS resolvidos (BUG-SENDER foi o último)
- **Scripts**: 7 utilitários operacionais em `./scripts/` com docs completa
- **Working tree**: clean (último commit: `0072293`)
- **Branch**: `master` (sync com origin/master)

---
