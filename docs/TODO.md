# 📝 TODO — Enterprise Chatwoot Migration

**Last Updated**: 2026-05-13 — Sessão 13: D15-T1 EXECUTADO → Taxa de sucesso é temporal (98% recente vs 26% aleatório). Unimed Guaxupé SEM attachments migrados.
**Status**: 🔴 BLOQUEADOR — Validação de attachments S3: depende de policy de retenção (recente=98% OK, histórico=26% falha). Unimed Guaxupé não migrou attachments (0 de 1.847).

---

## 🔴 D15 — DESCOBERTA CRÍTICA: Migração S3 Incompleta

> Origem: [D15-DEBATE-MIGRACAO-S3-INCOMPLETA-2026-05-13.md](debates/D15-DEBATE-MIGRACAO-S3-INCOMPLETA-2026-05-13.md)

### P0 — Investigação Imediata (Sessão 13)

- [x] **D15-T1** ✅ Análise temporal: correlacionar `created_at` com taxa de sucesso/falha
  **RESULTADO**: Taxa de sucesso é **98% para recentes** (2025-2026) vs **26% para aleatórios** (mix 2020-2026).
  **CONCLUSÃO**: Arquivos antigos foram deletados do S3 ou nunca existiram. Arquivos recentes existem e são acessíveis.
  **ARTEFATO**: `.tmp/validacao_attachments_s3_20260513_120012.json` (100 recentes, 98 OK, 2 fail)

- [ ] **D15-T1.1** 🆕 Investigar por que Unimed Guaxupé NÃO tem attachments no DEST
  **DESCOBERTA**: SOURCE (account_id=25) tem 1.847 attachments, DEST (account_id=46) tem 0.
  **EVIDÊNCIA**: `.tmp/verificar_source_guaxupe.py` — 1.837 attachments com blob S3 válido no SOURCE.
  **AÇÕES**:
  - [ ] Verificar logs de migração do account 25 → 46
  - [ ] Verificar se migration script `01_migrar_account.py` inclui attachments
  - [ ] Decidir se é necessário re-executar migração de attachments para este account

- [ ] **D15-T2** Identificar bucket SOURCE correto
  - Consultar ops: qual bucket `chat.vya.digital` usa?
  - Testar blob_keys contra buckets candidatos
  - Verificar `config/storage.yml` no ambiente SOURCE

- [ ] **D15-T3** Contar attachments órfãos no SOURCE
  ```sql
  SELECT COUNT(*) FROM attachments att
  LEFT JOIN messages m ON m.id = att.message_id
  WHERE att.account_id = 17 AND m.id IS NULL;
  ```

### P1 — Decisões de Negócio (Próxima Sessão)

- [ ] **D15-B** Decisão: Ampliar escopo para migração S3 ou aceitar 26% de cobertura?
  - Opção 1: Aceitar como está (validação de metadados apenas)
  - Opção 2: Implementar fase 6 — Sync S3-to-S3
  - Opção 3: Investigar mais antes de decidir ✅ (recomendado)

- [ ] **D15-C** Definir taxa de sucesso aceitável para homologação
  - Consultar stakeholders sobre impacto de 74% de attachments com 404
  - Avaliar métricas de negócio: acesso a attachments, NPS, custo S3

### P2 — Implementação (Se D15-B = Opção 2)

- [ ] **D15-IMPL-1** Implementar sync S3-to-S3 (boto3 ou aws-cli)
- [ ] **D15-IMPL-2** Testar sync com account menor (ex: Sol Copernico)
- [ ] **D15-IMPL-3** Executar sync completo para todos os accounts migrados
- [ ] **D15-IMPL-4** Re-validar com `19_validar_attachments_s3.py`

---

## 🔴 D12 — AÇÕES OBRIGATÓRIAS ANTES DE LIGAR O CONTAINER

> Origem: [D12-ANALISE-CRITICA-LOGICA-NEGOCIO-FLUXO-DADOS-2026-04-24.md](debates/D12-ANALISE-CRITICA-LOGICA-NEGOCIO-FLUXO-DADOS-2026-04-24.md)

### P0 — Executar antes de reiniciar o serviço

- [x] **D12-P0-1** `[A-05]` Verificar/regenerar tokens de autenticação SOURCE vs DEST — **CONCLUÍDO 2026-04-24: 95 colisões encontradas e corrigidas; 216 sessões Devise limpas no DEST.** Novo token admin (chatwoot004_dev1_db): `+bhADFGGkIHkUM06DnYgWfdYVdNn4Lte`. Token antigo inválido após container trocar para DB correto.
  ```sql
  UPDATE users SET authentication_token = encode(gen_random_bytes(20), 'hex'), updated_at = NOW()
  WHERE id IN (SELECT DISTINCT owner_id FROM access_tokens WHERE owner_type = 'User');
  ```
  Verificar duplicatas antes: `SELECT authentication_token, COUNT(*) FROM users GROUP BY authentication_token HAVING COUNT(*) > 1;`

- [x] **D12-P0-2** `[A-02 / F-04]` Quantificar conversas `snoozed` com prazo vencido — **CONCLUÍDO 2026-04-24: 0 snoozed no DEST** (nenhuma conversa com status=3; risco F-04 não se aplica)

- [x] **D12-P0-3** `[A-02]` Quantificar conversas `open` com mais de 30 dias — **CONCLUÍDO 2026-04-24: 124 conversas open históricas. DECISÃO: manter status open** (cliente confirmou, nenhuma ação necessária)

### P1 — Verificações pré-liberação para usuários

- [ ] **D12-P1-1** `[A-01]` Verificar conversas sem `contact_inbox_id` (FK dangling)
  ```sql
  SELECT COUNT(*) FILTER (WHERE contact_inbox_id IS NULL) AS ci_null,
         COUNT(*) FILTER (WHERE contact_id IS NULL) AS contact_null
  FROM conversations WHERE id > 156684 AND account_id = 1;
  ```

- [ ] **D12-P1-2** `[A-03]` Verificar colisões de phone no SOURCE (dedup silencioso)
  ```sql
  -- chatwoot_dev1_db (SOURCE)
  SELECT phone_number, COUNT(*) AS n FROM contacts
  WHERE account_id = 1 AND phone_number IS NOT NULL
  GROUP BY phone_number HAVING COUNT(*) > 1 ORDER BY n DESC LIMIT 20;
  ```

- [ ] **D12-P1-3** `[L-01]` Verificar contatos com `contact_id = NULL` herdados do legado
  ```sql
  -- chatwoot_dev1_db (SOURCE)
  SELECT COUNT(*) FROM conversations WHERE contact_id IS NULL AND account_id = 1;
  ```

- [ ] **D12-P1-4** `[F-02]` Avaliar se `conversation_participants` é relevante — criar migrador se necessário

- [ ] **D12-P1-5** `[A-05]` Confirmar webhooks/integrações do DEST não apontam para URLs do SOURCE

### P2 — Robustez para re-runs futuros

- [ ] **D12-P2-1** `[F-01]` Documentar procedimento de reset: truncar `migration_state` + tabelas de dados **juntos**
- [ ] **D12-P2-2** `[A-03]` Normalizar telefones E.164 no ContactsMigrator antes de novo run
- [ ] **D12-P2-3** `[F-03]` Definir prioridade de dedup explícita: `identifier > phone > email`

---

## 🔴 BLOQUEADOR ATIVO

- [ ] **TOKEN-ADMIN**: Obter token API de `administrator` em `account_id=1` (sugerido: `admin@vya.digital`, `user_id=1`)
  - Adicionar em `.secrets/generate_erd.json` sob chave `"vya-chat-dev-admin"`
  - Reexecutar `make validate-api` → esperado `api_conv=687` para account_id=1
  - Confirmar: 309 conversas migradas visíveis via API de admin

---

## 🔴 PENDENTE — Pós-Sessão 10 (2026-04-24)

> Itens abertos ao encerrar a sessão 10 — resolver na Sessão 11.

### P0 — Resequência e Membros de Inbox

- [x] **S10-P0-1** Re-executar pipeline completo `app/01_migrar_account.py "Vya Digital"` — **CONCLUÍDO 2026-04-27** (banco restaurado; fases 0-5 executadas; sequences resequenciadas via `.tmp/fix_sequences.py`)
- [ ] **S11-P0-1** Migrar `inbox_members` para os novos inboxes (397-409):
  - ⚠️ `app/13_migrar_inbox_members.py` depende de `migration_state` — tabela **não existe** no DEST
  - Adaptar script para resolver mapeamentos por nome (inbox) e email (user) diretamente
  - Usar `docker/` para executar no wfdb01 (baixa latência)
- [ ] **S11-P0-2** Aguardar confirmação validação ops e executar `make validate-api` com token admin → esperado `api_conv` para account_id=1
- [ ] **S11-P0-3** Validar inboxes visíveis no frontend para usuários não-admin após migração de `inbox_members`

### P1 — Outros Accounts SOURCE

- [ ] **S11-P1-1** Aplicar migração para account SOURCE "Sol Copernico" (`account_id=4`) — usar `docker/` no wfdb01
- [ ] **S11-P1-2** Aplicar migração para account SOURCE "Unimed Poços PJ" (`account_id=17`)
- [ ] **S11-P1-3** Aplicar migração para account SOURCE "Unimed Poços PF" (`account_id=18`)
- [ ] **S11-P1-4** Aplicar migração para account SOURCE "Unimed Guaxupé" (`account_id=25`)

### P2 — Infra Docker (criada Sessão 11)

- [x] **S11-DOCKER** Criar `docker/` para executar migração no wfdb01 (mesmo datacenter wfdb02) — **CONCLUÍDO 2026-04-27** commit `2619dd9`
- [x] **S11-DOCKER-FIX** Corrigir deploy-to-wfdb01.sh: fwknop SPA + porta 5010 + user archaris — **CONCLUÍDO 2026-04-27** commit `0ed9d4f`
- [ ] **S11-DOCKER-TEST** Testar build e execução completa no wfdb01 (aguarda validação ops)

---

## ✅ D7 — Visibilidade Marcus: RESOLVIDO (2026-04-23)

- [x] **D7-G1**: Verificar inbox_id=125 SOURCE → `wea004`, `Channel::Api`, `account_id=1` ✅ 2026-04-22
- [x] **D7-G3**: Checar migration_state para conv_ids 62361–62363 → todos `status=ok` ✅ 2026-04-22
- [x] **D7-A1**: conv_id=200501 → DEST `display_id=1843`, `inbox_id=428`, `assignee_id=88` ✅ 2026-04-23
- [x] **D7-A2**: Mensagem formal enviada a Marcus: SOURCE `display_id=1093` → DEST `display_id=1850`; SOURCE `display_id=1003` → DEST `display_id=1843` ✅ 2026-04-23
- [x] **D7-A3**: conv_ids 62361/62362 tinham `assignee_id=None` na SOURCE — migração correta, sem ação ✅ 2026-04-23
- [x] **D7-Q**: display_id=1003 SOURCE → DEST display_id=1843 confirmado ✅ 2026-04-23
- [ ] **D7-A4**: Opcional — renomear inbox_id=521 para `wea004 (migrado)` — requer aprovação gestor

---

## 🟠 Em Progresso

### P0 — Validação API (D5) — Em andamento
- [x] D5-A1: Sample contacts + CLI (CTE richness_score, `--sample-size`, Makefile targets) ✅ 2026-04-20
- [x] D5-A2: API conversations scan (`ConversationApiCheck`, Rails limit warning, cross-ref src_id) ✅ 2026-04-20
- [x] D5-A3: Exit codes semânticos (0/2/3/4) ✅ 2026-04-20
- [x] D5-A4: Sanity queries com tolerância a schema mismatch (sentinel -1) ✅ 2026-04-20
- [x] D5-A5: url_preview redaction (`AttachmentResult` refatorado) ✅ 2026-04-20
- [x] D5-B1: Primeira execução real — EXIT 2 esperado (orphan_messages=6321, todos deltas positivos) ✅ 2026-04-20
- [x] D5-B2 batch: Batch optimization aplicado (2 queries/conv, 3x mais rápido) ✅ 2026-04-23
- [x] BUG-A: `_fetch_sanity()` pubsub_token — downgrade warning→debug ✅ 2026-04-23
- [x] BUG-B: `_run_summary()` `meta.all_count` vs `data.all_count` ✅ 2026-04-23
- [x] Fix endpoint: `synchat` → `vya-chat-dev` em `_load_api_config()` ✅ 2026-04-23
- [ ] **TOKEN-ADMIN**: Reexecutar `make validate-api` com token admin → esperado `api_conv=687` account_id=1
- [ ] D5-B2: Confirmar deep scan funcional com token admin
- [ ] D5-B3: `make validate-api-deep SAMPLE=5 CHECK_URLS=1` — confirmar redação de URLs
- [ ] D5-C1: Investigar `orphan_messages=6321` no dest_account_id=1 — pré-existente (baixa prioridade)
- [ ] D5-C2: Documentar attachments_not_found se > 0 (pós B2/B3)

### P0 — Validação Hash MD5 (D6) ✅ Concluído (Sessão 2026-04-21)
- [x] D6-1: Corrigir BK de `conversations` — `display_id` → `created_at + status` ✅ 2026-04-21
- [x] D6-2: Corrigir BK de `attachments` — `external_url` (100% NULL) → `file_type + created_at` ✅ 2026-04-21
- [x] D6-3: Executar validação final — conversations ✅ | messages ✅ | attachments ✅ | contacts ⚠️ ✅ 2026-04-21
- [x] D6-4: Consolidar `tmp/` → `.tmp/` (único diretório temp) ✅ 2026-04-21
- [x] D6-5: Criar `scripts/cleanup-tmp.sh` + integrar ao `make clean` ✅ 2026-04-21
- [ ] D6-C1: Investigar 246 contacts missing (3,41%) — BK `phone+email` pode ser imprecisa para contatos sem phone? (próxima sessão)

### P0 — Pipeline Pós-BUG-06 ✅ Concluído (2026-04-16)
- [x] BUG-03: `conversations_migrator` — contact_id orphan → null-out em vez de skip
- [x] BUG-04: `conversations_migrator` — display_id resequenciado por account (MAX DEST)
- [x] BUG-05: Criado `src/migrators/contact_inboxes_migrator.py` (novo migrador)
- [x] BUG-06: `users_migrator` — merge por email em vez de `+migrated`
- [x] Pipeline executado: 311.539 migrados, 0 falhas, exit:0 ✅
- [x] Validação manual: conv_id=42070 ✅ | FK violations novas = 0 ✅

### P1 — Qualidade de Código
- [ ] Adicionar testes unitários BUG-01 a BUG-06 (`test/unit/`)
- [ ] Adicionar testes unitários FIX-01 a FIX-10 (`test/unit/`)
- [ ] Documentar APIs/interfaces (`src/`)

### P0 — FK Violations Pré-existentes no DEST
- [ ] Avaliar FK violations pré-existentes detectadas no relatório 2026-04-16 — D5 necessário?
- [ ] Decidir: limpeza de orphans ou aceitar como data decay (similar a D4)

### P0 — POC Dry-Run (Pré-Migração de Produção) — ✅ Concluído
- [x] TPOC001: Implementar `src/reports/poc_reporter.py` (`Outcome` enum, `RecordSample`, `POCResult`, `POCReporter`)
- [x] TPOC002: Adicionar `poc_classify()` a `BaseMigrator` + 9 migrators concretos (`_table_name`, `_fetch_all_source_rows`, `_classify_row_poc`)
- [x] TPOC003: Adicionar flag `--poc` a `src/migrar.py`
- [x] TPOC004: Executar `python src/migrar.py --dry-run --poc` contra bancos reais e validar report
- [x] TPOC005: Implementar `test/unit/test_poc_reporter.py`

## 🔵 Pendente

### P0 — Especificação
- [x] Preencher `objetivo.yaml` (problem_statement, success_statement, scope, escopo Chatwoot)
- [x] Definir versões do Chatwoot: origem e destino da migração
- [x] Definir quais dados serão migrados (conversões, contatos, contas, labels?)
- [x] Mapear banco de dados origem/destino (PostgreSQL?)

### P1 — Setup Técnico
- [x] Configurar estrutura inicial do projeto (`src/`) com módulos base
- [x] Setup do ambiente Python: `make install-deps` + validar `pyproject.toml`
- [ ] Rastrear `.scaffold-state.yaml` no git (arquivo não monitorado)

### P2 — Desenvolvimento
- [x] Implementar conector origem (DB direto via `ConnectionFactory`)
- [x] Implementar conector destino
- [x] Implementar lógica de transformação de dados
- [x] Adicionar testes unitários
- [ ] Documentar APIs/interfaces

## ✅ Concluído

- [x] D6 validação hash: `app/11_validar_hash.py` — BKs corrigidas + execução final: conversations ✅, messages ✅, attachments ✅, contacts ⚠️ 246 missing (2026-04-21)
- [x] D6 consolidação tmp: `tmp/` → `.tmp/` + `scripts/cleanup-tmp.sh` + `make clean` integrado (2026-04-21)
- [x] D5-A1→A5 + B1: `app/10_validar_api.py` — spec validação API implementado + 1ª execução real (EXIT 2 expected) (2026-04-20)
- [x] RUN-20260416 completo: Exit:0 — BUG-01→BUG-06 corrigidos, 311.539 registros migrados (0 falhas) (2026-04-16)
- [x] `src/migrators/contact_inboxes_migrator.py` criado — `contact_inboxes` adicionado ao pipeline (2026-04-16)
- [x] RUN-11 completo: Exit:0 — contacts 5.966 + conversations 36.016 + messages 239.439 + attachments 22.841 migrados (2026-04-14)
- [x] D4 formalizado: contacts orphans account_ids {2,3,5,6,10} → skip intencional, não falha (2026-04-14)
- [x] `scripts/reports/relatorio_consolidado_pipeline.py` criado — relatório comparativo F1→F2→F3 (2026-04-14)
- [x] Scaffold inicial gerado (2026-04-09T11:37:54Z)
- [x] Primeira sessão inicializada e documentada (2026-04-09)
- [x] Pre-spec analysis concluído — D1 resolvida (schema_sha1 idêntico) (2026-04-09)
- [x] `speckit.constitution` gerado (2026-04-09)
- [x] `speckit.specify` (spec.md) gerado — 3 US, 12 FR, 8 SC (2026-04-09)
- [x] `speckit.clarify` — 5/5 questões respondidas (2026-04-09)
- [x] `speckit.plan` — artefatos de design: plan, research, data-model, cli-contract, quickstart (2026-04-09)
- [x] Branch `001-enterprise-chatwoot-migration` criada e pushed (2026-04-09)
- [x] D3-DEBATE: Estratégia de migração MERGE consolidada — 9 erros + 6 decisões (2026-04-10)
- [x] Diagnóstico completo executado — baseline capturado em `tmp/diagnostico_20260410_165333.txt` (2026-04-10)
- [x] Investigações concluídas: T2-DEEP ✅ | 5727-INV ✅ | E5-INV ✅ | 1429-INV ✅ | PARTICIPANTS-INV ✅ (2026-04-10)
- [x] SQL legados analisados — 6 padrões críticos extraídos (2026-04-10)
- [x] `speckit.clarify` segunda rodada — Q1–Q5 respondidas (2026-04-10)
- [x] Spec atualizada: FR-002, 003, 004, 005, 007, 013 + SC-001 corrigido (2026-04-10)
- [x] Commit `5dafbdc` + push origin/001-enterprise-chatwoot-migration (2026-04-10)
- [x] `speckit.tasks` gerado — T001–T045 documentados (2026-04-10)
- [x] Implementação T001–T045 concluída: `src/` inteiramente implementado (9 migrators + infra + testes) (2026-04-13)
- [x] RUN-8 completo: conversations 33.255 + messages 221.933 + attachments 21.581 migrados com 0 failed (2026-04-13)
- [x] 10 bug fixes aplicados (FIX-01 a FIX-10) — bugs de UniqueViolation, FK drift, token collision corrigidos (2026-04-13)
