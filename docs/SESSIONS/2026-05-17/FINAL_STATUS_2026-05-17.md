# 📊 Final Status — 2026-05-17 (Sessão 18)

**Branch**: `001-enterprise-chatwoot-migration`
**Sessão**: 09:53 BRT → fim do dia
**Tipo**: Sessão de implementação — pipeline completo + Docker + RUNBOOK

---

## IMPs Concluídos Esta Sessão

- ✅ **S18-01**: `BaseMigrator` — `account_id_filter` + `_select_source_rows()` helper
- ✅ **S18-02**: `src/migrar.py` — flags `--env {dev,prod}` e `--account NOME` + fix F841
- ✅ **S18-03**: 13 migrators atualizados com `_select_source_rows()`
- ✅ **S18-04**: `users_migrator.py` — filtro especial via `account_users` join
- ✅ **S18-05**: Docker — `PIPELINE=full` / `MIGRATION_ENV` em `entrypoint.sh`, `docker-compose.yml`, `deploy-to-wfdb01.sh`
- ✅ **S18-06**: RUNBOOK v1.2.0 — pipeline completo, por account ou todas, referência rápida

---

## Estado Geral da Migração

| Account | SOURCE ID | DEST ID | Status |
|---------|-----------|---------|--------|
| Unimed Guaxupé | 25 | 46 | 🔄 Reexecutar pipeline completo |
| Sol Copernico | 4 | ? | 🔵 Pendente |
| Unimed Poços PF | 18 | ? | 🔵 Pendente |
| Unimed Poços PJ | 17 | ? | 🔵 Pendente |
| Vya Digital | 1 | ? | 🔵 Pendente |

---

## Arquitetura do Pipeline Após Sessão 18

```
src/migrar.py --env prod --account "Unimed Guaxupé"
   │
   ├── --env prod → MIGRATION_SOURCE_KEY=chat-vya-digital
   │               MIGRATION_DEST_KEY=synchat-vya-digital
   │
   ├── --account "Nome" → SELECT id FROM accounts WHERE LOWER(name)=LOWER(:name)
   │                       → account_id_filter=25
   │
   └── Migrators (em ordem):
       accounts → inboxes → users → teams → labels →
       contacts → contact_inboxes → conversations →
       messages → attachments → conversation_labels
       │
       └── BaseMigrator._select_source_rows(src_table)
           ├── accounts: WHERE id = 25
           ├── tabelas com account_id: WHERE account_id = 25
           └── users: via account_users join (caso especial)
```

**Idempotência**: `migration_state` table no DEST rastreia src_id → dest_id por tabela. Re-execução segura.

---

## Próximas Ações (P0 para Sessão 19)

1. **Re-executar Unimed Guaxupé com pipeline completo** (corrigir gap de teams/labels/attachments):
   ```bash
   cd /home/yves_marinho/Documentos/DevOps/Vya-Jobs/enterprise-chathoot-migration
   ACCOUNT_NAME="Unimed Guaxupé" ./docker/deploy-to-wfdb01.sh --build --run
   ```
2. **Validar após migração**:
   ```bash
   export MIGRATION_SOURCE_KEY=chat-vya-digital
   export MIGRATION_DEST_KEY=synchat-vya-digital
   uv run python app/02_verificar.py "Unimed Guaxupé"
   uv run python scripts/check_s3_attachments.py --instance synchat-vya-digital --account-id 46 --limit 100
   ```
3. **Migrar demais accounts** (Sol Copernico, Unimed Poços PF, Unimed Poços PJ, Vya Digital):
   ```bash
   ACCOUNT_NAME="Sol Copernico" ./docker/deploy-to-wfdb01.sh --run
   ```

---

## Decisões Técnicas desta Sessão

- **D-S18-1**: Pipeline legado (`app/01_migrar_account.py`) mantido como `PIPELINE=legacy` no Docker para compatibilidade retroativa, mas o padrão passou a ser `PIPELINE=full` (`src/migrar.py`).
- **D-S18-2**: `users` não tem `account_id` direto — filtro feito via `account_users` join em vez de `_select_source_rows()`. Esse caso especial está encapsulado em `users_migrator.py`.
- **D-S18-3**: `contact_inboxes` e `team_members` não precisam de filtro explícito — são naturalmente filtrados pelo FK-orphan skipping quando as tabelas pai (contacts, teams) já foram filtradas.
- **D-S18-4**: `conversation_labels` usa `text()` SQL direto (não `src_table.select()`) e é filtrado via `migrated_convs` (FK skipping). Nenhuma mudança necessária.

---

## Contexto para Recuperação

**Onde parar**: Todas as mudanças de código commitadas. Pipeline pronto.

**Setup para retomar**:
```bash
cd /home/yves_marinho/Documentos/DevOps/Vya-Jobs/enterprise-chathoot-migration
git pull origin 001-enterprise-chatwoot-migration
uv sync
```

**Arquivo de secrets**: `.secrets/generate_erd.json` — chaves `chat-vya-digital` (SOURCE PROD) e `synchat-vya-digital` (DEST PROD)

**Riscos/bloqueios conhecidos**:
- Container em wfdb01 requer fwknop SPA antes de SSH: `fwknop --rc-file ~/.fwknoprc -n wfdb01 && sleep 3`
- Unimed Guaxupé já tem dados parciais migrados (contacts + conversations via pipeline legado) — o pipeline completo é idempotente e vai apenas adicionar teams/labels/attachments faltantes
