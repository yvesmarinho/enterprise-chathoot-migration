# 📝 TODO — Enterprise Chathoot Migration

**Last Updated**: 2026-04-09T09:00:00Z (Session 2026-04-09)
**Status**: 🟢 Em andamento

---

## 🟠 Em Progresso

*(nenhum)*

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
