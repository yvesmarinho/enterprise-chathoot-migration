# 📋 Daily Activities — 2026-05-17 (Sessão 18)

**Branch**: `001-enterprise-chatwoot-migration`
**Foco**: Correção do pipeline `src/migrar.py` — suporte a `--env {dev,prod}` e `--account`, migração por account ou todas de uma vez; atualização Docker; RUNBOOK v1.2.0
**Início**: 09:53 BRT
**Término**: ~fim do dia

---

### ✅ [S18-01] — `BaseMigrator`: `account_id_filter` + `_select_source_rows()`

**Contexto**: O pipeline `src/migrar.py` migrava **todas** as accounts do SOURCE sem filtro, o que seria perigoso em produção (polluting DEST com accounts indesejadas).

**Solução**: Adicionado parâmetro `account_id_filter: int | None = None` ao `BaseMigrator.__init__()` e método auxiliar `_select_source_rows(src_table)` que aplica `WHERE id = ?` (para `accounts`) ou `WHERE account_id = ?` (demais tabelas) quando o filtro está definido.

**Artefatos criados/modificados**:
| Arquivo | O que mudou |
|---------|-------------|
| `src/migrators/base_migrator.py` | `account_id_filter` param + `_select_source_rows()` helper |

---

### ✅ [S18-02] — `src/migrar.py`: flags `--env` e `--account`

**Contexto**: Não havia atalho CLI para selecionar DEV vs PROD nem para filtrar uma account específica.

**Solução**:
- `--env {dev,prod}` → pré-define `MIGRATION_SOURCE_KEY` e `MIGRATION_DEST_KEY` via `_ENV_PRESETS`
- `--account "Nome"` → resolve account por nome (case-insensitive) no SOURCE e passa `account_id_filter` para todos os migrators
- Sem `--account` → migra todas as accounts (comportamento original)
- `_ENV_PRESETS = {"dev": ("chatwoot_dev", "chatwoot004_dev"), "prod": ("chat-vya-digital", "synchat-vya-digital")}`
- Corrigido F841: `offsets = remapper.compute_offsets(...)` → `remapper.compute_offsets(...)` (retorno não usado)

**Artefatos criados/modificados**:
| Arquivo | O que mudou |
|---------|-------------|
| `src/migrar.py` | `import os`, `_ENV_PRESETS`, `--env`, `--account`, resolução `account_id_filter`, F841 fix |

**Uso**:
```bash
uv run python src/migrar.py --env prod --account "Unimed Guaxupé"
uv run python src/migrar.py --env prod          # todas as accounts
uv run python src/migrar.py --env dev --dry-run # DEV dry-run
```

---

### ✅ [S18-03] — Todos os migrators: `_select_source_rows()` aplicado

**Contexto**: 13 migrators tinham `conn.execute(src_table.select())` direto — ignoravam o filtro de account.

**Solução**: Substituída a chamada direta por `self._select_source_rows(src_table)` em `migrate()` e `_fetch_all_source_rows()` de cada migrator.

**Artefatos criados/modificados**:
| Arquivo | O que mudou |
|---------|-------------|
| `src/migrators/accounts_migrator.py` | `migrate()` + `_fetch_all_source_rows()` |
| `src/migrators/inboxes_migrator.py` | idem |
| `src/migrators/labels_migrator.py` | idem |
| `src/migrators/teams_migrator.py` | idem |
| `src/migrators/contacts_migrator.py` | idem |
| `src/migrators/conversations_migrator.py` | idem |
| `src/migrators/messages_migrator.py` | idem |
| `src/migrators/attachments_migrator.py` | idem |
| `src/migrators/canned_responses_migrator.py` | idem |
| `src/migrators/custom_attribute_definitions_migrator.py` | idem |
| `src/migrators/webhooks_migrator.py` | idem |
| `src/migrators/contact_inboxes_migrator.py` | idem |
| `src/migrators/team_members_migrator.py` | idem |

---

### ✅ [S18-04] — `users_migrator.py`: filtro via `account_users`

**Contexto**: A tabela `users` não tem coluna `account_id` direta — o vínculo é via `account_users`. O helper `_select_source_rows` não era suficiente.

**Solução**:
- `migrate()`: após fetch de `users` e `account_users`, filtra `rows` e `au_rows` por `account_id_filter` via `account_users`
- `_fetch_all_source_rows()`: aplicada a mesma lógica (usada pelo modo POC)

**Artefatos criados/modificados**:
| Arquivo | O que mudou |
|---------|-------------|
| `src/migrators/users_migrator.py` | Filtro via `account_users` em `migrate()` e `_fetch_all_source_rows()` |

---

### ✅ [S18-05] — Docker: suporte a `PIPELINE=full` e `MIGRATION_ENV`

**Contexto**: O container (`entrypoint.sh`) estava hardcodado para `app/01_migrar_account.py` (pipeline legado, sem teams/labels/attachments).

**Solução**:
- `entrypoint.sh`: Nova variável `PIPELINE` (padrão `full`) — se `full` usa `src/migrar.py`; se `legacy` usa `app/01_migrar_account.py`. Também `MIGRATION_ENV` passado via `--env`.
- `docker-compose.yml`: Adicionadas `PIPELINE: "${PIPELINE:-full}"` e `MIGRATION_ENV: "${MIGRATION_ENV:-prod}"`.
- `deploy-to-wfdb01.sh`: Adicionadas variáveis `PIPELINE` e `MIGRATION_ENV`; passadas nos comandos `docker compose run` de `--run` e `--all`.

**Artefatos criados/modificados**:
| Arquivo | O que mudou |
|---------|-------------|
| `docker/entrypoint.sh` | `PIPELINE` + `MIGRATION_ENV` vars; branching `full` vs `legacy`; `ALL_ACCOUNTS` usa `src/migrar.py` se `full` |
| `docker/docker-compose.yml` | `PIPELINE` e `MIGRATION_ENV` no `environment` |
| `docker/deploy-to-wfdb01.sh` | `PIPELINE` e `MIGRATION_ENV` definidos e passados no `docker compose run` |

**Uso**:
```bash
# Uma account, pipeline completo, PROD
ACCOUNT_NAME="Unimed Guaxupé" ./docker/deploy-to-wfdb01.sh --build --run

# Todas as accounts, PROD
./docker/deploy-to-wfdb01.sh --all

# DEV dry-run
ACCOUNT_NAME="Unimed Guaxupé" MIGRATION_ENV=dev DRY_RUN=true ./docker/deploy-to-wfdb01.sh --run
```

---

### ✅ [S18-06] — RUNBOOK v1.2.0

**Contexto**: RUNBOOK estava usando `app/01_migrar_account.py` como script principal e não documentava a possibilidade de migrar todas as accounts de uma vez.

**Mudanças**:
- Versão 1.1.0 → 1.2.0
- FASE 1.1 reescrita com `src/migrar.py --env prod --account "..."` como caminho principal
- Nova seção **1.1b — Migrar TODAS as Accounts**
- Rollback e Troubleshooting atualizados para novo pipeline
- Troubleshooting Problema 3: note que `src/migrar.py` já migra teams/labels/inbox_members automaticamente
- Nova seção final: **Variáveis de Ambiente — Referência Rápida** (tabela completa de flags CLI e docker)

**Artefatos criados/modificados**:
| Arquivo | O que mudou |
|---------|-------------|
| `docs/RUNBOOK_MIGRACAO_PRODUCAO_2026-05-16.md` | v1.2.0 — pipeline completo, por account ou todas, referência rápida |

---

## 🔍 Destaques para Próxima Sessão

1. **Pipeline pronto** — `src/migrar.py --env prod --account "..."` cobre o pipeline completo (teams, labels, contacts, contact_inboxes, conversations, messages, attachments, conversation_labels)
2. **Próximo passo imediato** — Executar a migração de Unimed Guaxupé com o pipeline completo para corrigir o gap de teams/labels/attachments:
   ```bash
   ACCOUNT_NAME="Unimed Guaxupé" ./docker/deploy-to-wfdb01.sh --build --run
   ```
3. **Validar após migração** — `app/02_verificar.py "Unimed Guaxupé"` e `scripts/check_s3_attachments.py`
4. **Demais accounts pendentes** — Sol Copernico (4), Unimed Poços PF (18), Unimed Poços PJ (17), Vya Digital (1)

