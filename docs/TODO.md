# 📝 TODO — Enterprise Chathoot Migration

**Last Updated**: 2026-04-20 — D5-A1→A5 ✅ implementados, B1 ✅ executado (EXIT 2 — orphan_messages C1 pendente)
**Status**: 🟢 Em andamento

---

## 🟠 Em Progresso

### P0 — Validação API (D5) — Em andamento (Sessão 2026-04-20)
- [x] D5-A1: Sample contacts + CLI (CTE richness_score, `--sample-size`, Makefile targets) ✅ 2026-04-20
- [x] D5-A2: API conversations scan (`ConversationApiCheck`, Rails limit warning, cross-ref src_id) ✅ 2026-04-20
- [x] D5-A3: Exit codes semânticos (0/2/3/4) ✅ 2026-04-20
- [x] D5-A4: Sanity queries com tolerância a schema mismatch (sentinel -1) ✅ 2026-04-20
- [x] D5-A5: url_preview redaction (`AttachmentResult` refatorado) ✅ 2026-04-20
- [x] D5-B1: Primeira execução real — EXIT 2 esperado (orphan_messages=6321, todos deltas positivos) ✅ 2026-04-20
- [ ] D5-B2: `make validate-api-deep SAMPLE=5` — confirmar deep scan funcional
- [ ] D5-B3: `make validate-api-deep SAMPLE=5 CHECK_URLS=1` — confirmar redação de URLs
- [ ] D5-C1: Investigar `orphan_messages=6321` no dest_account_id=1 — pré-existente ou resíduo?
- [ ] D5-C2: Documentar attachments_not_found se > 0 (pós B2/B3)

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
