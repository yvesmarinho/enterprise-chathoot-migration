# 📦 Inventário Completo — Arquivos do Processo de Migração

**Projeto**: enterprise-chatwoot-migration
**Data**: 2026-05-24
**Sessão**: S23

---

## 📊 Visão Geral

| Categoria | Arquivos | Status |
|-----------|----------|--------|
| **Pipeline Principal** | 3 | ✅ Produção |
| **Migrators (módulos)** | 17 | ✅ Produção |
| **Scripts Diagnóstico (app/)** | 17 | ⚠️ Legado (uso ad-hoc) |
| **Scripts Operacionais (scripts/)** | 11 | ✅ Ativo |
| **Ferramentas (tools/)** | 1 pasta | ✅ Account Offboarding v1.0.0 |
| **Repositórios e Utils** | 7 | ✅ Produção |
| **Documentação** | 100+ | ✅ Ativo |

---

## 🚀 Pipeline Principal de Migração

### Produção (src/)

| Arquivo | Função | Status | Uso |
|---------|--------|--------|-----|
| [`src/migrar.py`](../src/migrar.py) | **Pipeline moderno** — Orquestra migração completa de 1 account via factory pattern | ✅ PROD | `uv run python -m src.migrar --source-key X --dest-key Y --account-id Z` |
| [`app/migrate_all_accounts.py`](../app/migrate_all_accounts.py) | **Pipeline all-accounts** — Migra todos os accounts do SOURCE para DEST | ✅ PROD | `uv run python app/migrate_all_accounts.py` |
| [`app/01_migrar_account.py`](../app/01_migrar_account.py) | **Pipeline legado** — Script original (SQL direto, sem ORM) | ⚠️ LEGADO | Não usar (manter por referência histórica) |

**Guardrails DEV-only:**
- ✅ `docker/entrypoint.sh` — Bloqueia DEST key=synchat-vya-digital se MIGRATION_ENV != prod
- ✅ `src/migrar.py` — Valida via `env_guard.py` antes de iniciar
- ✅ `app/migrate_all_accounts.py` — Valida via `env_guard.py` antes de loop

---

## 🧩 Migrators (Módulos de Migração)

**Localização**: `src/migrators/`

| Módulo | Responsabilidade | BKs (Business Keys) | Tabelas Afetadas |
|--------|------------------|---------------------|------------------|
| [`base_migrator.py`](../src/migrators/base_migrator.py) | **Classe abstrata** — Base para todos os migrators (dedup, remapping, logging) | — | — |
| [`accounts_migrator.py`](../src/migrators/accounts_migrator.py) | Migra accounts | `name` | `accounts` |
| [`users_migrator.py`](../src/migrators/users_migrator.py) | Migra users + account_users | `email` | `users`, `account_users` |
| [`contacts_migrator.py`](../src/migrators/contacts_migrator.py) | Migra contacts | `identifier` (telefone/email) | `contacts` |
| [`inboxes_migrator.py`](../src/migrators/inboxes_migrator.py) | Migra inboxes + channels | `name`, `phone_number` | `inboxes`, `channel_whatsapp`, `channel_api`, etc. |
| [`contact_inboxes_migrator.py`](../src/migrators/contact_inboxes_migrator.py) | Migra contact_inboxes (pivot contacts↔inboxes) | `source_id` | `contact_inboxes` |
| [`conversations_migrator.py`](../src/migrators/conversations_migrator.py) | Migra conversations | `identifier` (inbox + contact + source_id) | `conversations` |
| [`messages_migrator.py`](../src/migrators/messages_migrator.py) | Migra messages | `source_id` + `conversation_id` | `messages` |
| [`attachments_migrator.py`](../src/migrators/attachments_migrator.py) | Migra attachments (files S3) | — | `attachments` (via `messages`) |
| [`teams_migrator.py`](../src/migrators/teams_migrator.py) | Migra teams | `name` | `teams` |
| [`team_members_migrator.py`](../src/migrators/team_members_migrator.py) | Migra team_members | `team_id` + `user_id` | `team_members` |
| [`labels_migrator.py`](../src/migrators/labels_migrator.py) | Migra labels | `title` | `labels` |
| [`conversation_labels_migrator.py`](../src/migrators/conversation_labels_migrator.py) | Migra conversation_labels (pivot) | `conversation_id` + `label_id` | `conversation_labels` |
| [`canned_responses_migrator.py`](../src/migrators/canned_responses_migrator.py) | Migra canned_responses | `short_code` | `canned_responses` |
| [`custom_attribute_definitions_migrator.py`](../src/migrators/custom_attribute_definitions_migrator.py) | Migra custom_attribute_definitions | `attribute_key` | `custom_attribute_definitions` |
| [`webhooks_migrator.py`](../src/migrators/webhooks_migrator.py) | Migra webhooks | `url` | `webhooks` |

**Padrão de uso:**
```python
from src.factory.connection_factory import ConnectionFactory
from src.migrators.contacts_migrator import ContactsMigrator

src_conn = ConnectionFactory.create("chat-vya-digital")
dest_conn = ConnectionFactory.create("vya-chat-dev")
migrator = ContactsMigrator(src_conn, dest_conn, account_id=1)
migrator.migrate()
```

**Ordem de execução (src/migrar.py):**
1. accounts
2. users
3. contacts
4. inboxes
5. contact_inboxes
6. conversations
7. messages
8. attachments
9. teams
10. team_members
11. labels
12. conversation_labels
13. canned_responses
14. custom_attribute_definitions
15. webhooks

---

## 🧪 Scripts de Diagnóstico (app/)

**Status**: Legado — Criados durante desenvolvimento/debugging. Uso ad-hoc.

| Script | Função | Última Modificação |
|--------|--------|--------------------|
| [`00_inspecionar.py`](../app/00_inspecionar.py) | Inspeciona volumes SOURCE vs DEST | 2026-04-14 |
| [`01_migrar_account.py`](../app/01_migrar_account.py) | **Pipeline legado** (SQL direto) | 2026-04-24 (BUG-06 fix) |
| [`02_verificar.py`](../app/02_verificar.py) | Verificação pós-migração básica | 2026-04-13 |
| [`03_diagnostico_overlap.py`](../app/03_diagnostico_overlap.py) | Diagnóstico de sobreposição de dados (debate D3) | 2026-04-10 |
| [`04_debug_dedup.py`](../app/04_debug_dedup.py) | Debug de lógica de deduplicação | 2026-04-10 |
| [`05_diagnostico_completo.py`](../app/05_diagnostico_completo.py) | 14 blocos SOURCE vs DEST | 2026-04-14 |
| [`06_verificar_erros.py`](../app/06_verificar_erros.py) | Verificação de erros FK violations | 2026-04-14 |
| [`07_diagnostico_attachment_display_id.py`](../app/07_diagnostico_attachment_display_id.py) | Debug display_id em attachments | 2026-04-20 |
| [`08_diagnostico_perda_dados.py`](../app/08_diagnostico_perda_dados.py) | Diagnóstico de perda de dados pós-migração | 2026-04-20 |
| [`09_importar_tbchat.py`](../app/09_importar_tbchat.py) | Importação de dados de sistema legado tbchat | 2026-04-13 |
| [`10_validar_api.py`](../app/10_validar_api.py) | **Validação API** — counts, deep scan, sanity (D5) | 2026-04-20 |
| [`11_validar_hash.py`](../app/11_validar_hash.py) | **Validação hash MD5** — Pandas set-difference (D6) | 2026-04-21 |
| [`12_diagnostico_marcos.py`](../app/12_diagnostico_marcos.py) | Diagnóstico visibilidade usuário Marcos | 2026-04-22 |
| [`13_migrar_inbox_members.py`](../app/13_migrar_inbox_members.py) | Migração de inbox_members (não incluído na pipeline principal) | 2026-04-22 |
| [`14_verificar_conv_marcos.py`](../app/14_verificar_conv_marcos.py) | Verificação de conversações do Marcos pós-migração | 2026-04-22 |
| [`15_diagnostico_inbox125.py`](../app/15_diagnostico_inbox125.py) | Debug inbox_id=125 | 2026-04-22 |
| [`16_diagnostico_visibilidade_marcus.py`](../app/16_diagnostico_visibilidade_marcus.py) | Debug visibilidade Marcus (D7) | 2026-04-22 |
| [`db.py`](../app/db.py) | **Helper DB** — Conexão simplificada para scripts ad-hoc | Ativo |

**Recomendação**: Mover scripts úteis para `scripts/` e deprecar o resto. Manter apenas `01_migrar_account.py` por referência histórica.

---

## 🛠️ Scripts Operacionais (scripts/)

| Script | Função | Status | Uso |
|--------|--------|--------|-----|
| [`check_chatwoot_versions.py`](../scripts/check_chatwoot_versions.py) | Verifica versão do Chatwoot em SOURCE e DEST | ✅ Ativo | `uv run python scripts/check_chatwoot_versions.py` |
| [`check_conversations.py`](../scripts/check_conversations.py) | Verifica integridade de conversations | ✅ Ativo | `uv run python scripts/check_conversations.py` |
| [`check_db_schema.py`](../scripts/check_db_schema.py) | Compara schemas SOURCE vs DEST | ✅ Ativo | `uv run python scripts/check_db_schema.py` |
| [`check_inbox_mapping.py`](../scripts/check_inbox_mapping.py) | Verifica mapeamento de inboxes SOURCE→DEST | ✅ Ativo | `uv run python scripts/check_inbox_mapping.py` |
| [`check_s3_attachments.py`](../scripts/check_s3_attachments.py) | **CLI S3** — Valida acessibilidade de attachments S3 via HTTP | ✅ Ativo | `uv run python scripts/check_s3_attachments.py --instance chatwoot004_dev --account-id 1 --limit 100` |
| [`cleanup-tmp.sh`](../scripts/cleanup-tmp.sh) | Limpeza de `.tmp/` com `--dry-run` e `--verbose` | ✅ Ativo | `./scripts/cleanup-tmp.sh --verbose` |
| [`git-commit-with-file.sh`](../scripts/git-commit-with-file.sh) | **Git commit via arquivo** (obrigatório por copilot-rules P0) | ✅ Ativo | `./scripts/git-commit-with-file.sh /tmp/commit.txt` |
| [`load-mcp.sh`](../scripts/load-mcp.sh) | Carrega MCP servers (Model Context Protocol) | ✅ Ativo | `./scripts/load-mcp.sh` |
| [`rollback_account.py`](../scripts/rollback_account.py) | **Rollback** — Remove account migrado do DEST | ⚠️ Legado | Substituído por `tools/account_offboarding/cleanup.py` |
| [`start-migration-bg.sh`](../scripts/start-migration-bg.sh) | Inicia migração em background | ✅ Ativo | `./scripts/start-migration-bg.sh` |
| [`test_api_endpoints.py`](../scripts/test_api_endpoints.py) | Testa endpoints da API Chatwoot | ✅ Ativo | `uv run python scripts/test_api_endpoints.py` |
| [`validate_api.py`](../scripts/validate_api.py) | Validação API pós-migração | ✅ Ativo | `uv run python scripts/validate_api.py` |
| [`validate_migration.py`](../scripts/validate_migration.py) | Validação geral pós-migração | ✅ Ativo | `uv run python scripts/validate_migration.py` |

**Subpastas:**
- `scripts/lib/` — Bibliotecas compartilhadas
- `scripts/logs/` — Logs de execução
- `scripts/reports/` — Scripts de relatório (ver seção abaixo)

---

## 📊 Scripts de Relatório (scripts/reports/)

| Script | Função | Output | Uso |
|--------|--------|--------|-----|
| [`relatorio_qualidade_source.py`](../scripts/reports/relatorio_qualidade_source.py) | Qualidade dos dados do SOURCE (6 blocos) | `.tmp/relatorio_qualidade_source_*.txt` | `python3 scripts/reports/relatorio_qualidade_source.py` |
| [`relatorio_qualidade_dest.py`](../scripts/reports/relatorio_qualidade_dest.py) | Qualidade dos dados do DEST (7 blocos) | `.tmp/relatorio_qualidade_dest_*.txt` | `python3 scripts/reports/relatorio_qualidade_dest.py` |
| [`relatorio_qualidade_migracao.py`](../scripts/reports/relatorio_qualidade_migracao.py) | Comparativo SOURCE vs DEST: cobertura, gaps, integridade | `.tmp/relatorio_qualidade_migracao_*.txt` | `python3 scripts/reports/relatorio_qualidade_migracao.py` |
| [`relatorio_consolidado_pipeline.py`](../scripts/reports/relatorio_consolidado_pipeline.py) | Consolida F1→F2→F3: volumes, deltas, FK violations, cobertura | `.tmp/relatorio_consolidado_pipeline_*.txt` | `python3 scripts/reports/relatorio_consolidado_pipeline.py` |

**Nota:** Esses scripts foram criados para gerar evidências de qualidade durante o desenvolvimento (2026-04-14). Uso atual: ad-hoc para validação.

---

## 🗑️ Ferramentas (tools/)

### tools/account_offboarding/ (v1.0.0)

**Criado em**: 2026-05-24 (Sessão 23)

| Arquivo | Função | Status |
|---------|--------|--------|
| [`README.md`](../tools/account_offboarding/README.md) | Documentação completa da ferramenta | ✅ v1.0.0 |
| [`inspect.py`](../tools/account_offboarding/inspect.py) | **Auditoria read-only** — 48+ tabelas via direct + FK discovery | ✅ v1.0.0 |
| [`cleanup.py`](../tools/account_offboarding/cleanup.py) | **Remoção completa** — 40+ tabelas, FK-aware, transação única | ✅ v1.0.0 |
| [`config.json.example`](../tools/account_offboarding/config.json.example) | Template de configuração | ✅ v1.0.0 |

**Uso:**
```bash
# Auditoria
uv run python tools/account_offboarding/inspect.py --db-key vya-chat-dev --account-id 44

# Dry-run
uv run python tools/account_offboarding/cleanup.py --db-key vya-chat-dev --account-id 44 --dry-run

# Execução
uv run python tools/account_offboarding/cleanup.py --db-key vya-chat-dev --account-id 44 --execute
```

**Outputs:** JSON em `tools/account_offboarding/<db_key>_account_<id>_<operation>_YYYYMMDD_HHMMSS.json`

**Casos de uso:**
- ✅ Offboarding de cliente (término de contrato)
- ✅ Limpeza de migração incorreta (ex: account_id=45)
- ✅ Remoção de accounts de teste

**Testado contra:**
- `chatwoot004_dev1_db` (account_id=44, 864 linhas) ✅
- `chatwoot004_db` (account_id=45, 2.339 linhas) ✅

---

## 🧰 Repositórios e Utils (src/)

### src/repository/

| Módulo | Função |
|--------|--------|
| [`base_repository.py`](../src/repository/base_repository.py) | **Classe abstrata** — Base para repositórios com métodos CRUD genéricos |
| [`migration_state_repository.py`](../src/repository/migration_state_repository.py) | Gerencia estado de migração (tracking de account_id, timestamp, status) |

### src/utils/

| Módulo | Função |
|--------|--------|
| [`env_guard.py`](../src/utils/env_guard.py) | **Guardrail DEV-only** — Valida MIGRATION_ENV e DEST key (bloqueia prod em dev) |
| [`fk_validator.py`](../src/utils/fk_validator.py) | Valida integridade referencial (FK violations) pós-migração |
| [`id_remapper.py`](../src/utils/id_remapper.py) | Gerencia mapeamento de IDs SOURCE→DEST (via dicionário em memória) |
| [`log_masker.py`](../src/utils/log_masker.py) | Mascara dados sensíveis em logs (emails, telefones, tokens) |

### src/factory/

| Módulo | Função |
|--------|--------|
| [`connection_factory.py`](../src/factory/connection_factory.py) | **Factory de conexões** — Cria conexões PostgreSQL via `.secrets/generate_erd.json` |

---

## 📋 Configuração e Infraestrutura

| Arquivo | Função | Status |
|---------|--------|--------|
| [`pyproject.toml`](../pyproject.toml) | **Gerenciador Python** — Dependências, versões, scripts | ✅ Ativo |
| [`Makefile`](../Makefile) | Tarefas comuns (install, test, lint, format, clean) | ✅ Ativo |
| [`.github/copilot-instructions.md`](../.github/copilot-instructions.md) | **Instruções GitHub Copilot** — Regras P0, estrutura, tecnologias | ✅ Ativo |
| [`.secrets/generate_erd.json`](../.secrets/generate_erd.json) | **Secrets file** — Credenciais PostgreSQL (NUNCA versionado) | ✅ Ativo |
| [`docker/Dockerfile`](../docker/Dockerfile) | Imagem Docker para migração | ✅ Ativo |
| [`docker/docker-compose.yml`](../docker/docker-compose.yml) | Compose para ambiente local | ✅ Ativo |
| [`docker/entrypoint.sh`](../docker/entrypoint.sh) | Entrypoint com guardrail DEV-only | ✅ Ativo |
| [`docker/deploy-to-wfdb01.sh`](../docker/deploy-to-wfdb01.sh) | Deploy para servidor wfdb01 | ✅ Ativo |
| [`main.py`](../main.py) | Entrypoint alternativo (uso interno) | ⚠️ Avaliar necessidade |

---

## 📚 Documentação

### docs/

| Arquivo/Pasta | Descrição | Status |
|---------------|-----------|--------|
| [`INDEX.md`](../docs/INDEX.md) | **Índice mestre** — Links para toda documentação | ✅ Atualizado (S23) |
| [`TODO.md`](../docs/TODO.md) | Tarefas pendentes | ✅ Ativo |
| [`TODAY_ACTIVITIES.md`](../docs/TODAY_ACTIVITIES.md) | Atividades do dia (depreciado — usar `SESSIONS/YYYY-MM-DD/`) | ⚠️ Legado |
| [`KNOWLEDGE_BASE.md`](../docs/KNOWLEDGE_BASE.md) | Base de conhecimento consolidada | ✅ Ativo |
| [`RUNBOOK_MIGRACAO_PRODUCAO_2026-05-16.md`](../docs/RUNBOOK_MIGRACAO_PRODUCAO_2026-05-16.md) | **Runbook produção** — 800 linhas (procedimentos, validações, rollback) | ✅ Produção |
| [`CHECKLIST_EXECUTIVA_MIGRACAO_2026-05-16.md`](../docs/CHECKLIST_EXECUTIVA_MIGRACAO_2026-05-16.md) | **Checklist executiva** — Quick reference 200 linhas | ✅ Produção |
| [`SECURITY.md`](../SECURITY.md) | Política de segurança | ✅ Ativo |
| [`README.md`](../README.md) | Documentação pública do projeto | ✅ Ativo |

### docs/guides/

| Arquivo | Descrição | Status |
|---------|-----------|--------|
| [`ACCOUNT_OFFBOARDING_GUIDE.md`](../docs/guides/ACCOUNT_OFFBOARDING_GUIDE.md) | **Guia operacional offboarding** — Workflow, segurança, troubleshooting | ✅ Criado S23 |

### docs/templates/

| Arquivo | Descrição | Status |
|---------|-----------|--------|
| [`SESSION_DOCS_STYLE_GUIDE.md`](../docs/templates/SESSION_DOCS_STYLE_GUIDE.md) | Style guide para documentação de sessões | ✅ Criado S23 |

### docs/debates/

**18 debates** documentados (D1–D16 + variações). Exemplos:

| Debate | Tema | Data |
|--------|------|------|
| `D3-DEBATE-REGRAS-MIGRACAO-2026-04-10.md` | Estratégia MERGE vs incremental | 2026-04-10 |
| `D5-DEBATE-SPEC-VALIDACAO-API-2026-04-20.md` | Spec validação API pós-migração | 2026-04-20 |
| `D6-DEBATE-ARQUITETURA-VALIDACAO-HASH-2026-04-21.md` | Validação por hash MD5 + BKs | 2026-04-21 |
| `D7-DEBATE-VISIBILIDADE-MARCOS-2026-04-22.md` | Visibilidade Marcus (display_id bug) | 2026-04-22 |
| `D15-DEBATE-MIGRACAO-S3-INCOMPLETA-2026-05-13.md` | Migração S3 incompleta (74% HTTP 404) | 2026-05-13 |
| `D16-DEBATE-HTTP500-CONVERSACOES-POS-MIGRACAO-2026-05-20.md` | HTTP500 em conversações (ActiveStorage) | 2026-05-20 |

### docs/SESSIONS/

**23 sessões** documentadas (2026-04-09 até 2026-05-24).

**Estrutura típica:**
```
SESSIONS/YYYY-MM-DD/
├── SESSION_RECOVERY_YYYY-MM-DD.md     # Contexto inicial
├── DAILY_ACTIVITIES_YYYY-MM-DD.md     # Atividades cronológicas
├── SESSION_REPORT_YYYY-MM-DD.md       # Relatório final
└── FINAL_STATUS_YYYY-MM-DD.md         # Status de encerramento
```

**Últimas sessões:**
- S21 (2026-05-21): Investigação Guaxupé chat x synchat + plano DEV-only reset
- S22 (2026-05-21): Plano e tarefas consolidadas
- S23 (2026-05-24): Account offboarding tool + limpeza prod + guardrails DEV-only

### docs/evidencias/

**Outputs de validação S3**, diagnósticos, relatórios consolidados.

Exemplos:
- `validacao_attachments_s3_20260513_120012.json` (98% success rate recentes)
- `check_s3_attachments_20260514_*.json` (validações Session 14)
- Relatórios de migração (RUN-8, RUN-11, RUN-20260416)

### docs/architecture/

Documentação de arquitetura (ERDs, diagramas, decisões arquiteturais).

### docs/db_erd/

ERDs gerados automaticamente via `generate_erd.py`:
- `chatwoot_dev_db/`
- `chatwoot004_dev_db/`

---

## 🔐 Secrets e Credenciais

| Arquivo | Localização | Status | Versionado? |
|---------|-------------|--------|-------------|
| `.secrets/generate_erd.json` | Raiz do projeto | ✅ Ativo | ❌ NUNCA (`.gitignore`) |
| `config.json` (account_offboarding) | `tools/account_offboarding/` | ⚠️ Local only | ❌ NUNCA (usar `.example`) |

**Keys configuradas em `.secrets/generate_erd.json`:**

| Key | Stage | DB | Purpose |
|-----|-------|----|---------|
| `chatwoot_dev` | dev | `chatwoot_dev1_db` | SOURCE DEV |
| `chatwoot004_dev` | dev | `chatwoot004_dev1_db` | DEST DEV (antigo) |
| `vya-chat-dev` | dev | `chatwoot004_dev1_db` | DEST DEV (API-enabled) |
| `chat-vya-digital` | prod | `chatwoot_db` | SOURCE PROD (read-only) |
| `synchat-vya-digital` | prod | `chatwoot004_db` | DEST PROD (read-write) |

**⚠️ Regras P0:**
- ✅ NUNCA versionar secrets
- ✅ NUNCA logar credenciais (usar `log_masker.py`)
- ✅ File permissions `600` em `.secrets/`

---

## 📦 Outputs e Artefatos

### .tmp/

**Padrão**: Outputs temporários de diagnóstico, análise, dry-runs.

**Limpeza**: `./scripts/cleanup-tmp.sh --verbose`

**Exemplos:**
- `relatorio_qualidade_source_20260414.txt`
- `relatorio_consolidado_pipeline_20260414-151436.txt`
- `cleanup_account45.py` (script específico de limpeza prod)
- `reset_dry_run_srcid.py` (dry-run de reset)
- `inspect_fk_account45.py` (inspeção FK-based account_id=45)

### tools/account_offboarding/*.json

**Padrão**: Outputs de auditoria e cleanup (evidências permanentes).

**Exemplos:**
- `synchat-vya-digital_account_45_audit_20260524_120445.json`
- `vya-chat-dev_account_44_cleanup_20260524_115828.json`

### logs/

Logs de execução da pipeline (stdout/stderr capturados).

**Padrão**: `logs/migration_YYYYMMDD_HHMMSS.log`

### app/logs/

Logs de scripts ad-hoc (app/).

---

## 🧪 Testes

**Localização**: `test/`

| Pasta | Descrição |
|-------|-----------|
| `test/unit/` | Testes unitários (pytest) |
| `test/integration/` | Testes de integração |
| `test/conftest.py` | Fixtures compartilhados |

**Cobertura**: ~60% (atualizado 2026-04-20)

**Executar:**
```bash
make test
# ou
uv run pytest test/
```

---

## 📊 Métricas do Projeto

### Volumes de Código

| Tipo | Quantidade | Linhas Estimadas |
|------|------------|------------------|
| Scripts Python (src/) | 25 | ~3.500 |
| Scripts Python (app/) | 17 | ~4.000 |
| Scripts Python (scripts/) | 15 | ~2.000 |
| Ferramentas (tools/) | 2 | ~800 |
| Testes (test/) | 15 | ~1.200 |
| Documentação (docs/) | 100+ | ~15.000 |
| **TOTAL** | **170+** | **~26.500** |

### Volumes de Migração (última execução RUN-20260416)

| Tabela | SOURCE | DEST | Cobertura |
|--------|--------|------|-----------|
| contacts | 220.502 | 201.502 | 91.4% |
| conversations | 36.016 | 34.215 | 95.0% |
| messages | 338.434 | 320.847 | 94.8% |
| inboxes | 62 | 62 | 100% |
| users | 28 | 28 | 100% |
| accounts | 5 | 5 | 100% |

**Total migrado**: ~1.860.713 registros (todos os accounts)

---

## 🎯 Próximos Passos

### Fase C (Homologação DEV)

- [ ] T9: Code review pipeline com devops-expert
- [ ] T10: Executar reset completo em chatwoot004_dev1_db
- [ ] T11: Re-migrar 5 accounts em DEV (fresh migration)
- [ ] T12: Validação API completa (D5)
- [ ] T13: Validação hash completa (D6)
- [ ] T14: Spot checks manuais (inboxes, conversations, attachments S3)

### Fase D (Migração PROD)

- [ ] T15: Aprovação stakeholders
- [ ] T16: Scheduling janela de migração
- [ ] T17: Backup completo SOURCE e DEST
- [ ] T18: Migração PROD (via runbook)
- [ ] T19: Validação pós-migração PROD
- [ ] T20: Handover para operações

### Melhorias da Ferramenta (Account Offboarding)

- [ ] v1.1.0: Suporte a lotes para accounts > 1M linhas
- [ ] v1.1.0: Modo `--force` (skip confirmação, para CI/CD)
- [ ] v1.2.0: Rollback via backup seletivo
- [ ] v1.2.0: Dashboard web de auditoria

---

## 📝 Notas de Manutenção

### Quando Atualizar Este Inventário

- ✅ Novo script criado em `app/`, `scripts/`, ou `src/`
- ✅ Nova ferramenta adicionada em `tools/`
- ✅ Novo migrator criado
- ✅ Mudança significativa na estrutura de pastas
- ✅ Deprecação de scripts/arquivos

### Responsável

**Equipe**: DevOps / Data Engineering
**Última Atualização**: 2026-05-24 (Sessão 23)
**Próxima Revisão**: 2026-06-01 (ou após conclusão Fase D)

---

**Fim do Inventário**
