# 🔄 Session Recovery — 2026-05-19

**Sessão anterior**: 2026-05-18 (Sessão 19)
**Branch**: `master` (sincronizado com `origin/master` — commit `a3419b9`)
**Status dos IMPs**: Ver tabela abaixo

---

## Contexto Recuperado

### Sessão 19 (2026-05-18) — O que foi feito

- **Migração DEV validada** com 100% de integridade para **Unimed Guaxupé**:
  - 4.092 conversas, 22.992 mensagens, 1.513 contatos — tudo 100%
  - 0 NULL `contact_inbox_id`, 0 duplicados `display_id`
- **3 bugs críticos corrigidos** nos migrators (`conversations_migrator.py`, `webhooks_migrator.py`, `_ENV_PRESETS["dev"]`)
- **Pipeline aprovado** para uso em produção: `src/migrar.py --env prod --account "Nome"`
- **GitHub MCP** configurado em `.vscode/mcp.json`
- **Bump de segurança**: urllib3 → 2.7.0, mako → 1.3.12

### Estado do Repositório

- Branch: `master` (sincronizado com origin)
- Arquivo com modificação não commitada: `docs/SESSIONS/2026-05-18/FINAL_STATUS_2026-05-18.md`
- Último commit: `a3419b9` — `fix(security): bump urllib3 to 2.7.0 and mako to 1.3.12`

---

## IMPs e Fases

| IMP/Fase | Título | Status |
|----------|--------|--------|
| Pipeline `src/migrar.py` | `--env {dev,prod} --account "Nome"` | ✅ Concluído |
| Migração DEV — Unimed Guaxupé | Teste completo | ✅ Concluído (Sessão 19) |
| Migração PROD — Sol Copernico (4→44) | Pipeline novo | 🔵 Pendente |
| Migração PROD — Unimed Poços PF (18→45) | Pipeline novo | 🔵 Pendente |
| Migração PROD — Unimed Poços PJ (17→17) | Pipeline novo | 🔵 Pendente |
| Migração PROD — Unimed Guaxupé (25→45) | Pipeline novo | 🔵 Pendente |
| Migração PROD — Vya Digital (1→1) | Pipeline novo | 🔵 Pendente |
| Testes unitários | BUG-01→06 + FIX-01→10 | 🔵 Pendente |
| Migração S3 (D15) | Sync attachments físicos | 🔵 Decisão pendente |

---

## Itens P0 para Esta Sessão

1. **Executar migração PRODUÇÃO** (seguir ordem do RUNBOOK):
   - `uv run python -m src.migrar --env prod --account "Sol Copernico" --verbose`
   - `uv run python -m src.migrar --env prod --account "Unimed Poços PF" --verbose`
   - `uv run python -m src.migrar --env prod --account "Unimed Poços PJ" --verbose`
   - `uv run python -m src.migrar --env prod --account "Unimed Guaxupé" --verbose`
   - `uv run python -m src.migrar --env prod --account "Vya Digital" --verbose`
2. **PREP-1**: Backup completo do banco DEST antes da migração prod
3. **Validações pós-migração** por account após cada execução

## Referências Rápidas

- RUNBOOK: `docs/RUNBOOK_MIGRACAO_PRODUCAO_2026-05-16.md`
- CHECKLIST: `docs/CHECKLIST_EXECUTIVA_MIGRACAO_2026-05-16.md`
- Credenciais: `.secrets/generate_erd.json`
- `_ENV_PRESETS["dev"] = ("chatwoot_dev", "chatwoot004_dev")` — **NÃO alterar**
- `_ENV_PRESETS["prod"] = ("chat-vya-digital", "synchat-vya-digital")` — para produção
