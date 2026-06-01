# 📚 KNOWLEDGE BASE — Enterprise Chatwoot Migration

**Gerado em**: 2026-05-19 (Sessão 20)
**Propósito**: Consolidação completa de todo o histórico do projeto para recuperação rápida de contexto.
**Escopo**: Todos os arquivos em `docs/`, estado das memórias MCP, histórico de sessões 1–20.

---

## Índice

1. [Visão Geral do Projeto](#1-visão-geral-do-projeto)
2. [Arquitetura e Ambientes](#2-arquitetura-e-ambientes)
3. [Pipeline de Migração](#3-pipeline-de-migração)
4. [Accounts e Mapeamentos](#4-accounts-e-mapeamentos)
5. [Histórico de Sessões](#5-histórico-de-sessões)
6. [Bugs e Correções](#6-bugs-e-correções)
7. [Debates Técnicos (D3–D15)](#7-debates-técnicos-d3d15)
8. [Decisões Arquiteturais](#8-decisões-arquiteturais)
9. [Artefatos Críticos S3](#9-artefatos-críticos-s3)
10. [Problema HTTP 500 (Sessão 20)](#10-problema-http-500-sessão-20)
11. [Índice Completo de Arquivos docs/](#11-índice-completo-de-arquivos-docs)
12. [Referências Rápidas](#12-referências-rápidas)

---

## 1. Visão Geral do Projeto

**Projeto**: enterprise-chatwoot-migration
**Criado em**: 2026-04-09
**Objetivo**: Migrar dados relacionais (PostgreSQL) de `chat.vya.digital` (SOURCE) para `synchat.vya.digital` (DEST produção), via ambiente DEV intermediário `vya-chat-dev.vya.digital`.

**Repositório**: `git@github.com:yvesmarinho/enterprise-chatwoot-migration.git`
**Branch principal**: `master`
**Último commit relevante**: `a3419b9` — fix segurança urllib3+mako (2026-05-18)

**Stack tecnológica**:
- Python 3.12+ / SQLAlchemy 2.0.49 / psycopg2-binary 2.9.11
- `uv` como gerenciador de ambiente
- pytest 9.0.3 / ruff 0.15.10 / black 26.3.1
- PostgreSQL 16.10 em `wfdb02.vya.digital:5432`, `sslmode=disable`

**Comandos essenciais**:
```bash
# DEV
uv run python -m src.migrar --env dev --account "Unimed Guaxupé" --verbose
# PROD
uv run python -m src.migrar --env prod --account "Sol Copernico" --verbose
```

---

## 2. Arquitetura e Ambientes

### 2.1 Topologia

```
chat.vya.digital  ──── chatwoot_dev1_db  ──── (SOURCE, read-only)
                                              key: chatwoot_dev / chat-vya-digital

synchat.vya.digital ── chatwoot_db  ─────── (DEST PROD, read-write)
                                              key: synchat-vya-digital

vya-chat-dev.vya.digital ─ chatwoot004_dev1_db ─ (DEST DEV, read-write)
                                                    key: chatwoot004_dev / chatwoot004_dev (local)
```

**ATENÇÃO**: `synchat.vya.digital` é o site de PRODUÇÃO. **Nunca usar como referência de DEST para DEV**.
**ATENÇÃO**: `chatwoot004_dev1_db` não é o mesmo que `chatwoot004_dev_db` (sem `1`) — container do DEV aponta para `chatwoot004_dev1_db`.

### 2.2 Bancos de Dados

| Papel | Host | Porta | Banco | Chave .secrets |
|-------|------|-------|-------|---------------|
| SOURCE DEV | `wfdb02.vya.digital` | 5432 | `chatwoot_dev1_db` | `chatwoot_dev` |
| DEST DEV | `wfdb02.vya.digital` | 5432 | `chatwoot004_dev1_db` | `chatwoot004_dev` |
| SOURCE PROD | `wfdb02.vya.digital` | 5432 | `chatwoot_db` | `chat-vya-digital` |
| DEST PROD | `wfdb02.vya.digital` | 5432 | `chatwoot004_db` | `synchat-vya-digital` |

### 2.3 Credenciais e Segurança

- Arquivo de credenciais: `.secrets/generate_erd.json` (formato JSON, **não versionado**)
- API token DEST DEV: `5to6j4U3rhpsEVJcEQWHKFXJ` (obtido de `access_tokens`, owner_id=1)
- `admin@vya.digital` é **administrador global** em TODAS as instâncias Chatwoot — não distinguir entre instâncias por presença/ausência deste admin
- **Segurança pré-migração PROD**: Regenerar `authentication_token` de todos os usuários no DEST

### 2.4 Chatwoot Version

Versão: August 2024 (`20240820191716` — última migration encontrada no banco).

---

## 3. Pipeline de Migração

### 3.1 Entrypoint Principal

```
src/migrar.py --env {dev|prod} --account "Nome do Account" [--verbose]
```

`--env dev` → SOURCE=`chatwoot_dev`, DEST=`chatwoot004_dev`
`--env prod` → SOURCE=`chat-vya-digital`, DEST=`synchat-vya-digital`

### 3.2 Ordem dos Migrators (sequencial, obrigatória)

```
accounts → inboxes → users → teams → labels →
contacts → contact_inboxes → conversations →
messages → attachments → conversation_labels →
(canned_responses) → (webhooks)
```

**Nota S18**: `team_members`, `custom_attribute_definitions` ausentes — ver GAP-team_members e GAP-custom_attrs (D13).

### 3.3 Filtro por Account

`BaseMigrator._select_source_rows(src_table)`:
- Tabelas com `account_id`: `WHERE account_id = :account_id_filter`
- `accounts`: `WHERE id = :account_id_filter`
- `users`: `JOIN account_users WHERE account_id = :account_id_filter` (caso especial)

### 3.4 Idempotência

Tabela `migration_state` no DEST rastreia `src_id → dest_id` por tabela. Re-execução segura sem duplicação. Garantido por FIX-09 (pré-load de `get_migrated_id_pairs()` no startup).

### 3.5 Step 7b — Resequenciamento de Sequences

Após migração, resetar 11 sequences via `setval(seq, COALESCE(MAX(id), 1))`:
- conversations, messages, contacts, contact_inboxes, inboxes, accounts, users, teams, labels, webhooks, attachments

### 3.6 Estratégia de Merge (D3)

- **Tipo**: MERGE (não incremental)
- **Deduplicação**: por chave de negócio (nome/slug/email/phone)
- Registros sobrepostos entre SOURCE e DEST tratados via dedup antes do remapeamento de IDs
- `display_id` resequenciado por account para evitar colisão (BUG-04)

### 3.7 Pipeline Legado (histórico)

Antes de `src/migrar.py`, o pipeline legado usava scripts `app/01_migrar_account.py` etc. (fases 0–5). Esses scripts ainda existem para referência mas o **pipeline novo (`src/migrar.py`) é o correto para produção**.

---

## 4. Accounts e Mapeamentos

### 4.1 Mapeamento DEV (chatwoot_dev1_db → chatwoot004_dev1_db)

| Account | SOURCE ID | DEST ID (old pipeline) | DEST ID (pipeline novo) | Status |
|---------|-----------|------------------------|--------------------------|--------|
| Vya Digital | 1 | 1 | — | Pipeline legado executado (S10) |
| Sol Copernico | 4 | 44 | — | Pipeline legado executado |
| Unimed Poços PJ | 17 | 17 | — | Pipeline legado executado |
| Unimed Poços PF | 18 | 45 | — | Pipeline legado executado |
| Unimed Guaxupé | 25 | 46 | **69** | Pipeline novo executado ✅ S19 |

**Nota**: account_id=69 (pipeline novo) tem 4092 convs, 22992 msgs, 0 falhas. Account_id=46 (pipeline legado) tinha gaps (sem teams/labels/attachments completos).

### 4.2 Mapeamento PROD (chatwoot_db → chatwoot004_db)

| Account | SOURCE ID | DEST ID (PROD) | Status |
|---------|-----------|----------------|--------|
| Sol Copernico | 4 | 44 | 🔵 Pendente (novo pipeline) |
| Unimed Poços PF | 18 | 45 | 🔵 Pendente (novo pipeline) |
| Unimed Poços PJ | 17 | 17 | 🔵 Pendente (novo pipeline) |
| Unimed Guaxupé | 25 | 45 | 🔵 Pendente (novo pipeline) |
| Vya Digital | 1 | 1 | 🔵 Pendente (novo pipeline) |

**Nota D-PROD-1**: DEST prod `account_id=45` para Unimed Guaxupé (confirmado via API `/profile` em S16).

### 4.3 Qualidade dos Dados SOURCE

- 7.300 contacts válidos, 31.568 orphans (D4 — aceitar como data decay)
- 36.016 conversations, 239.439 messages, 38.868 contacts (total)
- 5.727 conversations órfãs (sem FK válida)
- Cobertura pós-migração: 91.2% contacts, 95.0% conversations, 94.8% messages, 0 novas FK violations

---

## 5. Histórico de Sessões

| Sessão | Data | Foco Principal | Resultado |
|--------|------|----------------|-----------|
| S1 | 2026-04-09 | Scaffold inicial | Branch master, pyproject.toml, estrutura base |
| S2 | 2026-04-10 | D3 — Estratégia MERGE | Spec v2, Constitution, FR-013 |
| S3 | 2026-04-13 | FIX-01→FIX-10 | RUN-8: 276.819 registros, 0 falhas |
| S4 | 2026-04-14 | D4 contacts orphans | RUN-11: 311.539, FK=0, DEST total 1.860.713 |
| S5 | 2026-04-16 | BUG-03→BUG-06 | contact_inboxes_migrator criado |
| S6 | 2026-04-20 | D5 — Validação API | app/10_validar_api.py, exit codes semânticos |
| S7 | 2026-04-21 | D6 — Hash MD5 | app/11_validar_hash.py, 0% perda convs/msgs |
| S8 | 2026-04-22 | D7 — Visibilidade Marcus | display_id resequenciado (BUG-04 causa raiz) |
| S9 | 2026-04-23 | D8/D9 — PermissionFilter | Root cause invisibilidade: inlet_members=0 |
| S10 | 2026-04-24 | D11 — Container apontava DB errado | 309 convs Vya Digital migradas, BUG-06 fix |
| S11 | 2026-04-27 | Docker infra, sequences | Infra Docker completa, fix_sequences.py |
| S12 | entre S11 e S13 | Validação multi-account | 80% geral, 100% exceto Vya Digital (4%) |
| S13 | 2026-05-13 | D15 — S3 incompleto | 74% falha (aleatório), 98% OK (recentes) |
| S14 | 2026-05-14 | CLI check_s3_attachments.py | Vya Digital 100% success 2025 |
| S15 | 2026-05-15 | RUNBOOK + CHECKLIST criados | Produção confirmada viável |
| S16 | 2026-05-16 | Docker prod + execução Unimed Guaxupé | Pipeline legado sem teams/labels/attachments |
| S17/S18 | 2026-05-17 | src/migrar.py completo | BaseMigrator.account_id_filter, 13 migrators |
| S19 | 2026-05-18 | BUG-CONV/HOOK/ENV + migração DEV | Unimed Guaxupé DEV: 4092 convs, 0 falhas ✅ |
| **S20** | 2026-05-19 | Diagnóstico HTTP 500 + KB | ROOT CAUSE NÃO ENCONTRADO, KB gerado |

---

## 6. Bugs e Correções

### FIX-01 a FIX-10 (S3 — 2026-04-13)

| FIX | Arquivo | Descrição |
|-----|---------|-----------|
| FIX-01 | base_repository.py | Transação aninhada (bulk_insert) |
| FIX-02 | users_migrator.py | pubsub_token UniqueViolation |
| FIX-03 | users_migrator.py | reset_password_token / confirmation_token → NULL |
| FIX-04 | teams/labels migrators | Dedup pre-step para contas merged |
| FIX-05 | account_users migrator | INSERT por linha + ON CONFLICT DO NOTHING |
| FIX-06 | migration_state_repository.py | Pre-load IDRemapper no startup |
| FIX-07 | base_repository.py | record_success_bulk() — 1 INSERT por batch |
| FIX-08 | contacts_migrator.py | Dedup usa record_success_bulk |
| FIX-09 | id_remapper.py | **CRÍTICO**: get_migrated_id_pairs() pré-carregado |
| FIX-10 | conversations_migrator.py | UUID sempre regenerado com uuid.uuid4() |

> **Lição FIX-09**: Mapeamentos DEVEM ser restaurados do `migration_state` ao iniciar (sem isso: FK drift em restart).
> **Lição FIX-10**: UUIDs de conversations NUNCA copiados do SOURCE.

### BUG-03 a BUG-06 (S4–S5 — 2026-04-16)

| BUG | Arquivo | Problema | Impacto |
|-----|---------|----------|---------|
| BUG-03 | conversations_migrator.py | contact_id orphan → FK violation | null-out quando contact não migrado |
| BUG-04 | conversations_migrator.py | display_id colide entre accounts | **display_id SOURCE ≠ DEST pós-migração** |
| BUG-05 | — | contact_inboxes_migrator.py inexistente | Criado |
| BUG-06 | app/01_migrar_account.py | dc.autocommit=True com transação aberta | dc.commit() antes de autocommit |

### BUG-A, BUG-B (S9 — 2026-04-23)
Em `app/10_validar_api.py`: verbose desnecessário e retorno -1 ambíguo. Corrigidos.

### BUG-CONV, BUG-HOOK, BUG-ENV (S19 — 2026-05-18)

| BUG | Arquivo | Problema | Impacto |
|-----|---------|----------|---------|
| BUG-CONV | src/migrators/conversations_migrator.py | `migrate()` não filtrava por account | **CRÍTICO**: migrava conversas de todos os accounts |
| BUG-HOOK | src/migrators/webhooks_migrator.py | `_fetch_all_source_rows()` sem filtro | ALTO: webhooks de outros accounts |
| BUG-ENV | src/migrar.py | `_ENV_PRESETS["dev"]` apontava produção | **CRÍTICO**: banco prod como SOURCE em DEV |

### D13 — Bugs Críticos (identificados antes de S18, corrigidos em S18)

| ID | Arquivo | Problema |
|----|---------|----------|
| BUG-B | inboxes_migrator.py | Sem dedup para contas merged → inboxes duplicados |
| BUG-C | teams_migrator.py, labels_migrator.py | Dedup por `remap(id)==id` incorreto |
| GAP-team_members | migrar.py | `team_members` ausente da pipeline |
| GAP-conv_labels | migrar.py | `conversation_labels` ausente |
| GAP-custom_attrs | migrar.py | `custom_attribute_definitions` ausente |
| CRED-channels | inboxes_migrator.py | Credenciais WhatsApp/FB/Telegram copiadas verbatim |

---

## 7. Debates Técnicos (D3–D15)

### D3 — Regras de Migração (2026-04-10)
**Decisões**: Estratégia MERGE confirmada (não incremental). Regra R1 ("cliente ativo/inativo") removida — schema Chatwoot não suporta semântica. Todos os registros processados indistintamente.
**Arquivo**: `docs/debates/D3-DEBATE-REGRAS-MIGRACAO-2026-04-10.md`

### D4 — Contacts Orphans (2026-04-14)
**Decisão**: 31.568 contacts orphans no SOURCE **aceitos como data decay**. Skip intencional sem geração de erro.
**Arquivo**: `docs/debates/D4-DEBATE-CONTACTS-ORPHANS-2026-04-14.md`

### D5 — Validação API Spec (2026-04-20)
**Decisão**: Gaps A1–A5 documentados. Plano B1–C2. Método de validação via hash MD5 + BKs.
**Arquivos**: `D5-DEBATE-SPEC-VALIDACAO-API-2026-04-20.md`, `D5-SQL-VALIDACAO-PROFUNDA-2026-04-20.sql`, `D5-REVISAO-METODO-VALIDACAO-2026-04-21.md`

### D6 — Hash MD5 Validation (2026-04-21)
**Resultado**: 0% perda em conversations, messages, attachments. Contacts: 3,41% missing (BK phone+email NULL).
**Arquivo**: `docs/debates/D6-DEBATE-ARQUITETURA-VALIDACAO-HASH-2026-04-21.md`

### D7 — Visibilidade Marcus (2026-04-22, resolvido 2026-04-23)
**Causa raiz**: `display_id` resequenciado (SOURCE 1093 → DEST 1850). Usuário buscava pelo display_id original.
**Causa arquitetural**: Topologia corrigida (chat.vya.digital=SOURCE, vya-chat-dev.vya.digital=DEST API).
**Arquivo**: `docs/debates/D7-DEBATE-VISIBILIDADE-MARCOS-2026-04-22.md`

### D8 — API 404 Chatwoot (2026-04-23)
**Análise**: Endpoints 404 para inboxes migrados (IDs 399–519). Causa: `PermissionFilterService` filtra agents por `inbox_members`. Admin global não afetado.
**Arquivo**: `docs/debates/D8-ANALISE-404-CHATWOOT-API-2026-04-23.md`

### D9 — Conversas Invisíveis (2026-04-23)
**Causa raiz**: 13 inboxes migrados com `member_count=0` → 309 conversas invisíveis para agent token.
**Fluxo**: `ConversationFinder` → `PermissionFilterService` → admin? return all / agent? WHERE inbox_id IN user.inboxes.
**Arquivo**: `docs/debates/D9-ANALISE-CODIGO-CHATWOOT-CONVERSAS-INVISIVEIS-2026-04-23.md`

### D10 — SQL Legado vs Python Atual (2026-04-24)
**Conclusão**: Pipeline Python novo é superior ao SQL legado. SQL legado mantido apenas como referência.
**Arquivo**: `docs/debates/D10-DEBATE-SQL-LEGADO-VS-PYTHON-ATUAL-2026-04-24.md`

### D11 — Inboxes Migrados Invisíveis (2026-04-24, resolvido)
**Causa raiz (BUG D11)**: Container `vya-chat-dev.vya.digital` apontava para `chatwoot004_dev_db` (ERRADO) — não para `chatwoot004_dev1_db` (correto). `.env` estava correto, processo ainda usava config antiga.
**Resolução**: Container recriado → 31 inboxes visíveis.
**Arquivo**: `docs/debates/D11-DEBATE-INBOXES-MIGRACAO-INVISIVEL-2026-04-24.md`

### D12 — Análise Crítica Lógica de Negócio (2026-04-24)
**Escopo**: Análise funcional do domínio Chatwoot e fluxo de dados pós-migração.
**Arquivos**: `D12-ANALISE-CRITICA-LOGICA-NEGOCIO-FLUXO-DADOS-2026-04-24.md`, `D12-ANALISE-FUNCIONAL-DOMINIO-CHATWOOT-2026-04-24.md`

### D13 — Análise Código + Recomendações (2026-04-24)
**Veredito**: 3 especialistas → NÃO EXECUTAR (antes das correções). 6 bugs críticos + 5 não-bloqueadores.
**Correções aplicadas**: Em S18 e S19 (BUG-B, BUG-C, BUG-CONV, BUG-HOOK, BUG-ENV, GAP-team_members, GAP-conv_labels).
**Arquivo**: `docs/debates/D13-ANALISE-CODIGO-RECOMENDACOES-ESPECIALISTAS-2026-04-24.md`

### D14 — Análise Crítica Lógica de Negócio v2 (2026-04-24)
**Arquivo**: `docs/debates/D14-ANALISE-CRITICA-LOGICA-NEGOCIO-FLUXO-DADOS-2026-04-24.md`

### D15 — S3 Incompleto (2026-05-13)
**Descoberta CRÍTICA**: 74% dos attachments (amostra aleatória) retornam HTTP 404. Causa: **pipeline migrou apenas metadados** — arquivos físicos S3 não foram migrados.
**Detalhe**: SOURCE e DEST usam o **mesmo bucket S3** (`assets-chat-vya-digital.s3.amazonaws.com`). O problema é que arquivos históricos foram deletados pela política de retenção S3.
**Recentes (2025-2026)**: 98% OK.
**Decisão pendente**: Aceitar perda de arquivos históricos ou executar sync S3 específico.
**Arquivo**: `docs/debates/D15-DEBATE-MIGRACAO-S3-INCOMPLETA-2026-05-13.md`

### Q1 — Questionário (2026-04-23)
**Arquivo**: `docs/debates/Q1-QUESTIONARIO-INFORMACOES-FALTANTES-2026-04-23.md`

---

## 8. Decisões Arquiteturais

| ID | Data | Decisão | Impacto |
|----|------|---------|---------|
| FR-013 | S2 | `pubsub_token = NULL` obrigatório pós-migração | Cada instância gera próprio token |
| D3 | S2 | Estratégia MERGE (não incremental) | Deduplicação por chave de negócio obrigatória |
| D4 | S4 | 31.568 contacts orphans = data decay (skip) | 91.2% cobertura de contacts |
| BUG-04 | S5 | display_id SOURCE ≠ DEST (resequenciado) | Usuários precisam usar novo display_id |
| D-S16/D-PROD-1 | S16 | DEST prod account_id=45 para Unimed Guaxupé | Via API /profile |
| D-S19 | S19 | Pipeline novo aprovado para produção | `src/migrar.py --env prod` como entrypoint oficial |
| D11 | S10 | Container recriado apontando para chatwoot004_dev1_db | Fim dos inboxes invisíveis |
| D15 | S13 | Migração S3 pendente — decisão separada | Aceitar histórico com lacunas ou sync S3 |

---

## 9. Artefatos Críticos S3

### Validações realizadas

| Arquivo | Data | Descrição | Resultado |
|---------|------|-----------|-----------|
| `evidencias/validacao_attachments_s3_20260513_120012.json` | S13 | 100 attachments recentes (2025-2026) account 17 | **98% OK (2 fail)** |
| `evidencias/validacao_attachments_s3_20260513_114457.json` | S13 | Amostra aleatória (2020-2026) | **26% OK (74% fail)** |
| `evidencias/check_s3_attachments_20260514_092556.json` | S14 | Account 1 (Vya Digital) | **100% OK** |
| `evidencias/check_s3_attachments_20260514_092619.json` | S14 | Account 46 (Unimed Guaxupé DEV) | **0 attachments** |

### Script CLI de validação S3

```bash
uv run python scripts/check_s3_attachments.py \
  --instance chatwoot004_dev \
  --account-id 69 \
  --limit 100 \
  --date-start 2025-01-01
```

Bucket: `assets-chat-vya-digital.s3.amazonaws.com`
Formato blob_key: 28 caracteres alfanuméricos

---

## 10. Problema HTTP 500 (Sessão 20)

**Status**: NÃO RESOLVIDO (2026-05-19)

### Sintoma
```
GET /api/v1/accounts/69/conversations?status=open    → HTTP 500 ❌
GET /api/v1/accounts/69/conversations?status=pending → HTTP 500 ❌
GET /api/v1/accounts/69/conversations?status=resolved → HTTP 200 ✅
GET /api/v1/accounts/69/conversations?status=snoozed  → HTTP 200 ✅ (0 resultados)
GET /api/v1/accounts/69/conversations/{display_id}    → HTTP 200 ✅
GET /api/v1/accounts/1/conversations?status=open      → HTTP 200 ✅
```

### Dados relevantes (account_id=69, open)
- 660 conversas status=open, 6 status=pending
- 100% channel=Channel::Whatsapp, inbox_id=526
- 659/660 com `waiting_since IS NOT NULL`
- 617/660 com `assignee_id IS NULL` (43 têm: user_id=4 ou 115)
- team_id=NULL em 100%
- channel_whatsapp: id=38, phone=+553588628436, provider=whatsapp_cloud

### Verificações realizadas (todas OK, 0 orphans)
- FK: contact_id, assignee_id, contact_inbox_id, team_id
- Taggings: 0 orphan tag_ids
- sla_policy_id: todos NULL
- campaign_id: todos NULL
- Sender polymorphic (messages): User=2, Contact=1698, None=1243 — 0 orphans
- ActiveStorage blobs para contacts/assignees: 0 orphans
- Schema SOURCE = DEST: idêntico
- conversation_participants: 0 para account 69

### Hipóteses não testadas
1. `account_users` para user_id=4 e 115 com account_id=69 — verificar se existem entradas corretas
2. `waiting_since` timestamps (2025-10-27 a 2026-05-15) — possível nil/format error Ruby
3. 188 orphan `active_storage_attachments` na DB total — verificar se afetam convs abertas
4. `unattended` scope ou outro scope de open aplicado diferente de resolved

### Contexto técnico (ConversationFinder Rails)
```ruby
# Status filter — mesmo para todos os status:
where(status: params[:status] || DEFAULT_STATUS)
# Includes — mesmo para todos:
includes(:taggings, :inbox, { assignee: { avatar_attachment: [:blob] } },
         { contact: { avatar_attachment: [:blob] } }, :team, :contact_inbox)
```
O erro é Ruby-level, não visível em SQL. A diferença entre open/pending (falha) e resolved (200) provavelmente está nos dados que disparam uma exceção durante o eager loading.

---

## 11. Índice Completo de Arquivos docs/

### Raiz

| Arquivo | Descrição |
|---------|-----------|
| `INDEX.md` | Índice geral do projeto — referência de navegação por categoria |
| `KNOWLEDGE_BASE.md` | **Este arquivo** — consolidação completa para recuperação de contexto |
| `RUNBOOK_MIGRACAO_PRODUCAO_2026-05-16.md` | RUNBOOK v1.2.0 (~800 linhas) — procedimento completo de migração PROD, janela 14:00 BRT, conexões, ambientes, execução por account, rollback |
| `CHECKLIST_EXECUTIVA_MIGRACAO_2026-05-16.md` | Checklist (~200 linhas) — pré-migração, execução, pós-migração por account, segurança |
| `PIPELINE-MIGRAÇÃO-DADOS.TXT` | Diagrama ASCII do pipeline completo (Fase 0→5) — SOURCE/DEST, fases, tabelas |
| `PROJECT_CREATION_SUMMARY.md` | Resumo da criação do projeto em 2026-04-09 — estrutura de pastas, template usado |
| `P-O-C-constitution.md` | POC "dry-run" — gerar amostras de 10 casos de cada ocorrência, relatório de análise |
| `avaliação_do_processo.md` | 3 melhorias identificadas: creds fixas, sem migração de usuários, Docker não no RUNBOOK original |
| `vya-chat-dev-env.txt` | Variáveis de ambiente do container vya-chat-dev: POSTGRES_DATABASE=chatwoot004_dev1_db, HOST=82.197.64.145 |
| `message.txt` | Mensagem de commit |
| `TODO.md` | TODO geral: 5 accounts PROD pendentes, PREP-1→5, VAL-1/2/S3/API/HASH/GO |
| `TODAY_ACTIVITIES.md` | Arquivo histórico de atividades (Sessão 10) |

### architecture/

| Arquivo | Descrição |
|---------|-----------|
| `architecture/README.md` | Documentação de arquitetura — diagramas C4, estrutura |

### debates/

| Arquivo | Descrição |
|---------|-----------|
| `debates/README.md` | Índice dos debates técnicos |
| `debates/D3-DEBATE-REGRAS-MIGRACAO-2026-04-10.md` | 9 erros + 6 decisões — estratégia MERGE, R1 removida |
| `debates/D4-DEBATE-CONTACTS-ORPHANS-2026-04-14.md` | 31.568 contacts orphans — decisão: aceitar como data decay |
| `debates/D5-DEBATE-SPEC-VALIDACAO-API-2026-04-20.md` | Spec validação API — gaps A1–A5, plano B1–C2 |
| `debates/D5-SQL-VALIDACAO-PROFUNDA-2026-04-20.sql` | SQL queries para sanity checks de validação |
| `debates/D5-REVISAO-METODO-VALIDACAO-2026-04-21.md` | Revisão do método de validação (D5 continuação) |
| `debates/D6-DEBATE-ARQUITETURA-VALIDACAO-HASH-2026-04-21.md` | Hash MD5 + BKs — 0% perda convs/msgs, 3.41% contacts |
| `debates/D7-DEBATE-VISIBILIDADE-MARCOS-2026-04-22.md` | Visibilidade Marcus — display_id resequenciado (BUG-04) |
| `debates/D8-ANALISE-404-CHATWOOT-API-2026-04-23.md` | API 404 para inboxes migrados — PermissionFilterService |
| `debates/D9-ANALISE-CODIGO-CHATWOOT-CONVERSAS-INVISIVEIS-2026-04-23.md` | Código Chatwoot Rails — ConversationFinder, PermissionFilter |
| `debates/D10-DEBATE-SQL-LEGADO-VS-PYTHON-ATUAL-2026-04-24.md` | SQL legado vs pipeline Python — Python aprovado |
| `debates/D11-ANALISE-INTEGRIDADE-PIPELINE-MIGRACAO-2026-04-24.md` | Análise de integridade do pipeline |
| `debates/D11-DEBATE-INBOXES-MIGRACAO-INVISIVEL-2026-04-24.md` | Inboxes invisíveis — container apontando DB errado (causa raiz) |
| `debates/D12-ANALISE-CRITICA-LOGICA-NEGOCIO-FLUXO-DADOS-2026-04-24.md` | Análise crítica de lógica de negócio |
| `debates/D12-ANALISE-FUNCIONAL-DOMINIO-CHATWOOT-2026-04-24.md` | Análise funcional do domínio Chatwoot |
| `debates/D13-ANALISE-CODIGO-RECOMENDACOES-ESPECIALISTAS-2026-04-24.md` | Veredito 3 especialistas: 6 bugs críticos, NÃO EXECUTAR (antes das correções) |
| `debates/D14-ANALISE-CRITICA-LOGICA-NEGOCIO-FLUXO-DADOS-2026-04-24.md` | Análise crítica lógica de negócio v2 |
| `debates/D15-DEBATE-MIGRACAO-S3-INCOMPLETA-2026-05-13.md` | **CRÍTICO** — S3 74% HTTP 404, apenas metadados migrados, bucket único |
| `debates/Q1-QUESTIONARIO-INFORMACOES-FALTANTES-2026-04-23.md` | Questionário sobre informações faltantes |

### decisions/

| Arquivo | Descrição |
|---------|-----------|
| `decisions/README.md` | ADRs (Architecture Decision Records) — índice |

### evidencias/

| Arquivo | Descrição |
|---------|-----------|
| `evidencias/validacao_attachments_s3_20260513_*.json` | Série de validações S3 da Sessão 13 (26% success amostra aleatória) |
| `evidencias/validacao_attachments_s3_20260513_120012.json` | **CRÍTICO** — 100 recentes: 98% OK (referência de validação prod) |
| `evidencias/check_s3_attachments_20260514_092556.json` | Account 1 (Vya Digital): 100% success |
| `evidencias/check_s3_attachments_20260514_092619.json` | Account 46 (Unimed Guaxupé DEV): 0 attachments |
| `evidencias/check_s3_attachments_*.md` | Relatórios legíveis das validações S3 |

### guides/

| Arquivo | Descrição |
|---------|-----------|
| `guides/README.md` | Guias operacionais |

### SESSIONS/

| Pasta | Descrição Resumida |
|-------|--------------------|
| `SESSIONS/2026-04-09/` | S1 — Scaffold, PRE_SPEC_ANALYSIS_REPORT |
| `SESSIONS/2026-04-10/` | S2 — D3 estratégia MERGE |
| `SESSIONS/2026-04-13/` | S3 — FIX-01→10, RUN-8 |
| `SESSIONS/2026-04-14/` | S4 — RUN-11, D4 contacts orphans |
| `SESSIONS/2026-04-16/` | S5 — BUG-03→06, contact_inboxes_migrator |
| `SESSIONS/2026-04-20/` | S6 — validar_api.py, D5 |
| `SESSIONS/2026-04-21/` | S7 — validar_hash.py, D6 |
| `SESSIONS/2026-04-22/` | S8 — D7 visibilidade Marcus |
| `SESSIONS/2026-04-23/` | S9 — D8/D9 PermissionFilter |
| `SESSIONS/2026-04-24/` | S10 — D11 container fix, 309 convs Vya Digital |
| `SESSIONS/2026-04-27/` | S11 — Docker infra, sequences, inbox_members |
| `SESSIONS/2026-04-29/` | S12 — RELATORIO_VALIDACAO_MIGRACAO.md (80% geral) + GUIA_ALTERACOES_TECNICAS.md |
| `SESSIONS/2026-05-13/` | S13 — D15 S3 descoberta crítica |
| `SESSIONS/2026-05-14/` | S14 — CLI check_s3_attachments.py |
| `SESSIONS/2026-05-15/` | S15 — RUNBOOK + CHECKLIST criados |
| `SESSIONS/2026-05-16/` | S16 — Docker prod, execução legado Unimed Guaxupé |
| `SESSIONS/2026-05-17/` | S18 — src/migrar.py pipeline completo, 13 migrators |
| `SESSIONS/2026-05-18/` | S19 — BUG-CONV/HOOK/ENV, migração DEV 100% ✅ |
| `SESSIONS/2026-05-19/` | S20 — HTTP 500 diagnóstico (inconcluso) + geração KNOWLEDGE_BASE |

### Relatório especial S12
`SESSIONS/2026-04-29/RELATORIO_VALIDACAO_MIGRACAO.md` — Validação 500 registros (100/account):
- Sol Copernico (4→44): 97% ✅
- Unimed Poços PJ (17→17): 100% ✅
- Unimed Poços PF (18→45): 99% ✅
- Unimed Guaxupé (25→46): 100% ✅
- Vya Digital (1→1): **4%** ⚠️ (display_id remapeado — busca por display_id antigo falha)

### sql_code_old/
Scripts SQL legados de migração (`scriptImportacaoChatToSynchat.sql`, `scriptImportacaoTbChatChatWoot.sql`) — mantidos como referência histórica.

### templates/
Templates de documentos de sessão (SESSION_RECOVERY, DAILY_ACTIVITIES, FINAL_STATUS, SESSION_REPORT).

### copilot/
Configurações e prompts do GitHub Copilot para o projeto.

### retrospectives/
Documentos de retrospectiva do projeto.

---

## 12. Referências Rápidas

### Comandos de migração

```bash
# DEV — Unimed Guaxupé (para testar)
uv run python -m src.migrar --env dev --account "Unimed Guaxupé" --verbose

# PROD — executar por esta ordem
uv run python -m src.migrar --env prod --account "Sol Copernico" --verbose
uv run python -m src.migrar --env prod --account "Unimed Poços PF" --verbose
uv run python -m src.migrar --env prod --account "Unimed Poços PJ" --verbose
uv run python -m src.migrar --env prod --account "Unimed Guaxupé" --verbose
uv run python -m src.migrar --env prod --account "Vya Digital" --verbose
```

### Credenciais (referências, não valores)

```bash
# .secrets/generate_erd.json — instâncias disponíveis:
# chatwoot_dev, chatwoot004_dev, chat-vya-digital, synchat-vya-digital
# API token DEST DEV: access_tokens table, owner_id=1, owner_type=User
```

### Segurança pré-produção obrigatória

```sql
-- Regenerar authentication_token para evitar cross-instance access
UPDATE users SET authentication_token = encode(gen_random_bytes(20), 'hex'), updated_at = NOW()
WHERE id IN (SELECT DISTINCT owner_id FROM access_tokens WHERE owner_type = 'User');
-- Verificar duplicatas
SELECT authentication_token, COUNT(*) FROM users
GROUP BY authentication_token HAVING COUNT(*) > 1;
-- Limpar sessões
TRUNCATE TABLE sessions;
```

### Regra de diagnóstico

Sempre criar scripts em `.tmp/`, sempre salvar output como JSON (`json.dump(..., ensure_ascii=False)`), sempre ler via `read_file` (nunca via `cat`). Ver `workflow-preferences.md` do usuário.

### Arquivos de código principais

| Arquivo | Propósito |
|---------|-----------|
| `src/migrar.py` | Entrypoint CLI (flags `--env`, `--account`, `--verbose`) |
| `src/migrators/base_migrator.py` | BaseMigrator — `account_id_filter`, `_select_source_rows()` |
| `src/migrators/conversations_migrator.py` | Migrator de conversas (BUG-CONV corrigido) |
| `src/migrators/users_migrator.py` | Migrator especial via account_users JOIN |
| `src/migrators/contact_inboxes_migrator.py` | Criado no BUG-05 (S5) |
| `src/repository/id_remapper.py` | IDRemapper com pre-load de migration_state |
| `app/db.py` | DB connection via env vars MIGRATION_SOURCE_KEY/MIGRATION_DEST_KEY |
| `docker/deploy-to-wfdb01.sh` | Deploy SSH via fwknop + porta 5010 |
| `scripts/check_s3_attachments.py` | CLI validação S3 (--instance, --account-id, --limit, --date-start) |

---

*Documento gerado em 2026-05-19 (Sessão 20). Atualizar incrementalmente com cada nova sessão.*
