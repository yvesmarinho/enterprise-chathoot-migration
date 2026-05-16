# 📊 Final Status — 2026-05-16 (Sessão 16)

**Branch**: `001-enterprise-chatwoot-migration`
**Sessão**: 2026-05-16 14:10 → ~17:00 BRT
**Foco**: Execução de migração em produção — Unimed Guaxupé

---

## Implementações Concluídas Esta Sessão

- ✅ **PROD-1**: Refactoring `app/db.py` — env vars `MIGRATION_SOURCE_KEY`/`MIGRATION_DEST_KEY` obrigatórias
- ✅ **PROD-2**: 4 usuários ausentes criados no DEST prod (dest_ids 358-361)
- ✅ **PROD-3**: Infraestrutura Docker adaptada para produção (daemon mode, env vars, defaults de prod)
- ✅ **PROD-4**: Deploy em wfdb01 + container `chatwoot-migrator-unimed_guaxup` iniciado como daemon

---

## Estado da Migração

| Account | SOURCE ID | DEST ID | Status |
|---------|-----------|---------|--------|
| Unimed Guaxupé | 25 | 45 | 🟡 EM EXECUÇÃO (container daemon wfdb01) |
| Sol Copernico | 4 | — | ⏳ Pendente |
| Unimed Poços PF | 18 | — | ⏳ Pendente |
| Unimed Poços PJ | 17 | — | ⏳ Pendente |
| Vya Digital | 1 | — | ⏳ Pendente |

---

## Artefatos Modificados Esta Sessão

| Artefato | Tipo | Descrição |
|----------|------|-----------|
| `app/db.py` | Python | Env var-based DB selection |
| `docker/docker-compose.yml` | Docker | MIGRATION_SOURCE_KEY/DEST_KEY + prod defaults |
| `docker/entrypoint.sh` | Shell | Validação env vars + banner prod |
| `docker/deploy-to-wfdb01.sh` | Shell | Daemon mode (`-d`), container name auto, prod defaults |
| `docs/RUNBOOK_MIGRACAO_PRODUCAO_2026-05-16.md` | Docs | Container como método primário, account-id=45 |
| `.tmp/create_missing_users.py` | Python | Script para criar 4 usuários ausentes |
| `docs/avaliação_do_processo.md` | Docs | Avaliação do processo (criado pelo usuário) |

---

## Decisões Técnicas desta Sessão

- **D-PROD-1**: DEST prod `account_id=45` (não 46 — confirmado via API `/profile`)
- **D-PROD-2**: Container nome = `chatwoot-migrator-unimed_guaxup` (normalização automática do account name)
- **D-PROD-3**: `docker compose run -d` sobre SSH funciona corretamente — o que bloqueia é o `docker build` (verbose mas termina). Para futuros runs sem rebuild, usar SSH direto com `< /dev/null`.
- **D-PROD-4**: Migration idempotente — re-execução segura, sem necessidade de restore do banco

---

## Próximas Ações (P0 para próxima sessão)

1. **Aguardar/verificar conclusão do container**:
   ```bash
   fwknop --rc-file ~/.fwknoprc -n wfdb01 && sleep 3
   ssh -p 5010 archaris@wfdb01.vya.digital 'docker ps -a --filter name=chatwoot-migrator-unimed_guaxup'
   ssh -p 5010 archaris@wfdb01.vya.digital 'docker logs --tail 50 chatwoot-migrator-unimed_guaxup'
   ```

2. **Validações pós-migração Unimed Guaxupé**:
   ```bash
   export MIGRATION_SOURCE_KEY=chat-vya-digital
   export MIGRATION_DEST_KEY=synchat-vya-digital
   uv run python app/02_verificar.py "Unimed Guaxupé"
   uv run python app/06_verificar_erros.py "Unimed Guaxupé"
   uv run python scripts/check_s3_attachments.py --instance synchat-vya-digital --account-id 45 --limit 100
   ```

3. **Migração dos demais accounts** (via container ou local):
   - Sol Copernico (account 4)
   - Unimed Poços PF (account 18)
   - Unimed Poços PJ (account 17)
   - Vya Digital (account 1) — maior volume

4. **Go/No-Go final após todas as validações**

---

## Contexto para Recuperação

- **Infraestrutura**: Container `chatwoot-migrator-unimed_guaxup` (ID: `9f13b2337b26`) rodando no wfdb01 como daemon. Migration idempotente.
- **Env vars obrigatórias**: `MIGRATION_SOURCE_KEY=chat-vya-digital` e `MIGRATION_DEST_KEY=synchat-vya-digital`
- **DEST account_id**: **45** (prod). Não confundir com dev (46).
- **Inbox Cobrança** (WhatsApp): criada automaticamente pelo migrator como inbox_id=428.
- **4 usuários criados**: dest_ids 358-361 — mapeados no DEST para account_id=45.
- **SSH wfdb01**: porta 5010, user archaris, requer fwknop SPA antes de cada conexão.
- **REMOTE_DIR**: `~/chatwoot-migration` (pré-existente desde dev migration).
- **Para re-deploy sem rebuild**: `./docker/deploy-to-wfdb01.sh --run` (sem `--build`)
