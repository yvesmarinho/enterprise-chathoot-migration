# 🔄 Session Recovery — 2026-05-18 (Sessão 19)

**Sessão anterior**: 2026-05-17 (Sessão 18)
**Branch**: `001-enterprise-chatwoot-migration`
**Status**: `up to date` com origin — working tree clean

---

## Contexto Recuperado

### O que foi feito na Sessão 18

- **S18-01**: `BaseMigrator` recebeu `account_id_filter` + helper `_select_source_rows()`
- **S18-02**: `src/migrar.py` ganhou flags `--env {dev,prod}` e `--account NOME`
- **S18-03**: 13 migrators atualizados com `_select_source_rows()` em `migrate()` e `_fetch_all_source_rows()`
- **S18-04**: `users_migrator.py` — filtro especial via `account_users` join (users não tem `account_id` direto)
- **S18-05**: Docker — `PIPELINE=full` / `MIGRATION_ENV` em `entrypoint.sh`, `docker-compose.yml`, `deploy-to-wfdb01.sh`
- **S18-06**: RUNBOOK v1.2.0 atualizado com pipeline completo por account

### Arquitetura Atual do Pipeline

```
src/migrar.py --env prod --account "Nome"
   ├── --env prod → SOURCE=chat-vya-digital / DEST=synchat-vya-digital
   ├── --account → account_id_filter = <ID do SOURCE>
   └── Migrators: accounts → inboxes → users → teams → labels →
                  contacts → contact_inboxes → conversations →
                  messages → attachments → conversation_labels
```

Idempotência: `migration_state` table rastreia src_id → dest_id por tabela.

---

## Estado da Migração (pré Sessão 19)

| Account | SOURCE ID | DEST ID | Status |
|---------|-----------|---------|--------|
| Unimed Guaxupé | 25 | 46 | 🔄 Reexecutar pipeline completo (teams/labels/attachments faltaram) |
| Sol Copernico | 4 | ? | ⏳ Pendente |
| Unimed Poços PF | 18 | ? | ⏳ Pendente |
| Unimed Poços PJ | 17 | ? | ⏳ Pendente |
| Vya Digital | 1 | ? | ⏳ Pendente |

---

## Itens P0 para Esta Sessão

1. **Re-executar Unimed Guaxupé** com pipeline completo:
   ```bash
   ACCOUNT_NAME="Unimed Guaxupé" ./docker/deploy-to-wfdb01.sh --build --run
   ```
2. **Validar** após migração (S3 + API + hash)
3. **Migrar demais accounts** (Sol Copernico → Unimed Poços PF → Unimed Poços PJ → Vya Digital)
4. **Preparativos pendentes** (PREP-1 backup, PREP-2 tokens, PREP-3 sessions, PREP-4 duplicatas)

---

## Arquivos-Chave

| Arquivo | Papel |
|---------|-------|
| `src/migrar.py` | Entry point pipeline completo |
| `src/migrators/base_migrator.py` | `account_id_filter` + `_select_source_rows()` |
| `docker/entrypoint.sh` | `PIPELINE=full/legacy` + `ACCOUNT_NAME` |
| `docker/deploy-to-wfdb01.sh` | Deploy no servidor wfdb01 |
| `docs/RUNBOOK_MIGRACAO_PRODUCAO_2026-05-16.md` | Runbook v1.2.0 |
| `.secrets/generate_erd.json` | Credenciais SOURCE (chat-vya-digital) + DEST (synchat-vya-digital) |
