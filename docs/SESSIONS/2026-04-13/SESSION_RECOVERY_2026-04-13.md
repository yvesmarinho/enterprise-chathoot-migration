# 🔍 Session Recovery — 2026-04-13

**Recovered from**: Sessão 2026-04-10 (commit `0f34d32`)
**Project**: `enterprise-chatwoot-migration`
**Branch**: `001-enterprise-chatwoot-migration`
**Recovery time**: 2026-04-13T10:53:00Z

---

## Estado Recuperado

### Git State
- **HEAD**: `0f34d32` — `docs(session-end): encerramento 2026-04-10`
- **Branch**: `001-enterprise-chatwoot-migration` (synced with origin)
- **Untracked**: `docs/P-O-C-constitution.md` — novo artefato (POC dry-run)

### Fases do Projeto

| Fase | Status |
|------|--------|
| Constitution / Spec / Clarify / Plan | ✅ Concluído |
| Data Model / CLI Contract / Quickstart | ✅ Concluído |
| Diagnóstico baseline | ✅ Concluído (2026-04-10) |
| `speckit.tasks` | 🔵 Pendente (P0) |
| Implementação `src/` | 🔵 Pendente |
| Testes | 🔵 Pendente |

### Volumes SOURCE (`chatwoot_dev1_db`)

| Entidade | Volume | Observação |
|----------|--------|------------|
| conversations | 36.016 | 5.727 órfãs (descartar) |
| messages | 239.439 | 1.429 órfãs (descartar) |
| contacts | 38.868 | — |
| accounts | ~7 | 2 deletadas (id=2, id=6) |
| conversation_participants | 22.919 | 0 FK quebradas |

---

## P0 Tasks Pendentes

1. **`speckit.tasks`** — Decompor implementação em tarefas técnicas (pré-req para codificar)
2. **POC Dry-Run** (`docs/P-O-C-constitution.md`) — Novo artefato identificado; executar código de migração em modo dry-run, gerar amostras de 10 casos por ocorrência
3. **E5-INV revisita** — 23.530 mensagens `content_attributes` não-NULL — formato real a confirmar
4. **`source_id` colisões** — Verificar sobreposição SOURCE ↔ DEST antes de FR-003
5. **Iniciar `src/factory/connection_factory.py`** → utils → repository → migrators

---

## Decisões Vigentes

| ID | Decisão |
|----|---------|
| D3-A | Estratégia MERGE (não incremental) |
| D3-B | Descartar orphan records (account_id=2,6) |
| D3-C | Preservar `content_attributes` + amostrar |
| D3-D | Verificar colisões `source_id` antes de preservar |
| D3-E | Copiar metadados de attachments sem `external_url` |
| D3-F | Merge de accounts por `name`; FK usa `id_destino` resolvido |
| FR-013 | `pubsub_token = NULL` pós-migração (segurança) |

---

## Novos Artefatos Detectados

| Arquivo | Status | Ação |
|---------|--------|------|
| `docs/P-O-C-constitution.md` | Untracked | Avaliar, definir escopo do POC dry-run |

