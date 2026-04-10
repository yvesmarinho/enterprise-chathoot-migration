# 📝 TODO — Enterprise Chathoot Migration

**Last Updated**: 2026-04-10T08:57:00Z (Session 2026-04-10)
**Status**: 🟢 Em andamento

---

## 🟠 Em Progresso

### P0 — Implementação (Sessão 2026-04-10)
- [ ] Gerar `speckit.tasks` — último passo pré-implementação
- [ ] Implementar `src/factory/connection_factory.py`
- [ ] Implementar `src/utils/id_remapper.py` + `log_masker.py` + `fk_validator.py`
- [ ] Implementar `src/repository/base_repository.py` + `migration_state_repository.py`
- [ ] Implementar `src/migrators/base_migrator.py` + migrators por entidade (ordem FK)
- [ ] Implementar `src/migrar.py` (entrypoint)

## 🔵 Pendente

### P0 — Especificação
- [ ] Preencher `objetivo.yaml` (problem_statement, success_statement, scope, escopo Chatwoot)
- [ ] Definir versões do Chatwoot: origem e destino da migração
- [ ] Definir quais dados serão migrados (conversões, contatos, contas, labels?)
- [ ] Mapear banco de dados origem/destino (PostgreSQL?)

### P1 — Setup Técnico
- [ ] Configurar estrutura inicial do projeto (`src/`) com módulos base
- [ ] Setup do ambiente Python: `make install-deps` + validar `pyproject.toml`
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
