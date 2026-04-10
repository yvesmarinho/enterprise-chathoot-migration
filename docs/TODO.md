# 📝 TODO — Enterprise Chathoot Migration

**Last Updated**: 2026-04-10T18:10:00Z (Session 2026-04-10 — encerramento) ✅ Análise + Diagnóstico Concluídos
**Status**: 🟢 Em andamento

---

## 🟠 Em Progresso

### P0 — Implementação (Próxima Sessão)
- [ ] Gerar `speckit.tasks` — último passo pré-implementação (**P0 imediato**)
- [ ] Investigar anomalia E5-INV: `content_attributes` 23.530 registros — verificar formato real
- [ ] Verificar colisões de `source_id` entre SOURCE e DEST (prerequisito FR-003)
- [ ] Implementar `src/factory/connection_factory.py`
- [ ] Implementar `src/utils/id_remapper.py` + `log_masker.py` + `fk_validator.py`
- [ ] Implementar `src/repository/base_repository.py` + `migration_state_repository.py`
- [ ] Implementar `src/migrators/base_migrator.py` + migrators por entidade (ordem FK)
- [ ] Implementar `src/migrar.py` (entrypoint)

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
- [ ] Implementar conector origem (Chatwoot API ou DB direto)
- [ ] Implementar conector destino
- [ ] Implementar lógica de transformação de dados
- [ ] Adicionar testes unitários
- [ ] Documentar APIs/interfaces

## ✅ Concluído

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
