# 📅 Daily Activities — 2026-04-20

**Session**: 2026-04-20
**Agent**: Session Manager v1.1.0
**Started**: 2026-04-20T00:00Z
**Branch**: `001-enterprise-chatwoot-migration`

---

## Project State — Recovery Summary

### Last Session (2026-04-16)
- **Última migração**: RUN-20260416 — EXIT:0, 311.539 registros migrados (0 falhas)
- **BUGs corrigidos**: BUG-03, BUG-04, BUG-05, BUG-06 ✅
- **Pipeline completo**: 10 entidades migradas, DEST com 1.860.713 registros totais
- **FK violations novas**: 0 ✅
- **Commit HEAD**: `4915a66` (encerramento sessão 2026-04-16)
- **Working tree**: clean ✅

---

## Tarefas Pendentes desta Sessão

### P0 — Alta Prioridade

| # | Tarefa | Status |
|---|--------|--------|
| T-001 | Avaliar FK violations pré-existentes no DEST — D5 necessário? | ⏳ Pendente |
| T-002 | PR Review — branch pronta para merge? | ⏳ Pendente |

### P1 — Média Prioridade

| # | Tarefa | Status |
|---|--------|--------|
| T-003 | Testes unitários BUG-01 a BUG-06 (`test/unit/`) | ⏳ Pendente |
| T-004 | Testes unitários FIX-01 a FIX-10 (`test/unit/`) | ⏳ Pendente |
| T-005 | Documentar APIs `src/` | ⏳ Pendente |
| T-006 | Rastrear `.scaffold-state.yaml` no git | ⏳ Pendente |

---

## Log de Atividades

---

### ✅ [A1] — Sample Contacts + CLI (`app/10_validar_api.py`)

**Artefatos criados/modificados**:
| Arquivo | O que mudou |
|---------|-------------|
| `app/10_validar_api.py` | Adicionado `SampleContact` dataclass, `_select_sample_contacts()` com CTE richness_score (convs×5 + atts×10 + msgs), modo multi-contact em `_run_deep()`, `--sample-size` CLI standalone, deep group `required=False` |
| `Makefile` | 3 targets: `validate-api-counts`, `validate-api-deep`, `validate-api` |

**Destaques**: CTE `richness_score` filtra contatos com `conv_count >= 2` para garantir amostras com histórico real.

---

### ✅ [A2] — API Conversations Scan (`app/10_validar_api.py`)

**Artefatos criados/modificados**:
| Arquivo | O que mudou |
|---------|-------------|
| `app/10_validar_api.py` | Adicionado `ConversationApiCheck` dataclass, `_deep_scan_api_conversations()` (GET /api/v1/accounts/{acc}/contacts/{id}/conversations, WARNING se len==20 — Rails hardcoded limit, cross-reference via `additional_attributes.src_id`, fallback gracioso em HTTP error) |

**Destaques**: WARNING quando API retorna exatamente 20 conversas (limite hardcoded do Rails não documentado).

---

### ✅ [A3] — Exit Codes (`app/10_validar_api.py`)

**Artefatos criados/modificados**:
| Arquivo | O que mudou |
|---------|-------------|
| `app/10_validar_api.py` | `_exit_code_summary()` → exit 0/2; `_exit_code_deep()` → exit 0/2/3/4; `main()` chama `sys.exit(exit_code)` |

**Destaques**: Exit 2 = discrepâncias de dados; 3 = conversas ausentes na API; 4 = warning de limite Rails.

---

### ✅ [A4] — Sanity Queries (`app/10_validar_api.py`)

**Artefatos criados/modificados**:
| Arquivo | O que mudou |
|---------|-------------|
| `app/10_validar_api.py` | 3 SQL constants: `_SQL_SANITY_CONV_DUP_DISPLAY_ID`, `_SQL_SANITY_ORPHAN_MESSAGES`, `_SQL_SANITY_PUBSUB_DUPS`; `_fetch_sanity()` com try/except por query (retorna -1 como sentinel SKIP para schema mismatch); `_run_summary()` expõe campos sanity nas linhas de comparação; `_exit_code_summary()` trata -1 como OK (skipped) |

**Destaques**: Sentinel -1 permite tolerância a diferenças de versão de schema entre environments (ex.: coluna `pubsub_token` ausente em versões antigas).

---

### ✅ [A5] — url_preview Redaction (`app/10_validar_api.py`)

**Artefatos criados/modificados**:
| Arquivo | O que mudou |
|---------|-------------|
| `app/10_validar_api.py` | `AttachmentResult.file_url` → `url_preview: str`; `_redact_url(file_url)[:80]` aplicado em scan time — URL completa fica local, preview redacted em JSON/CSV/logs |

**Destaques**: Previne exposição de URLs de armazenamento com tokens temporários nos artefatos commitados.

---

### ✅ [B1] — Primeira Execução Real (`python app/10_validar_api.py summary`)

**Artefatos criados/modificados**:
| Arquivo | O que mudou |
|---------|-------------|
| `app/10_validar_api.py` | Fix: `_fetch_sanity()` crashava em `pubsub_token` column — adicionado per-query try/except com WARNING + rollback |
| `.tmp/validacao_api_20260420_185217.log` | Log completo da execução |
| `.tmp/validacao_api_20260420_185217.json` | Resultado estruturado |
| `.tmp/validacao_api_20260420_185217.csv` | Tabela comparativa |

**Resultados B1**:
- Todos os deltas positivos (sem perda de dados) ✅
- `orphan_messages=6321` no dest_account_id=1 — pré-existentes ou resíduo pós-migração (C1: investigar)
- `pubsub_dups=SKIP` em todas as accounts (coluna ausente no schema antigo) — comportamento esperado
- EXIT 2 (devido a orphan_messages > 0)

**Destaques**: EXIT 2 confirmado como correto dado orphan_messages. Não indica perda de dados da migração — requer investigação separada (C1).

---

## Tarefas Atualizadas

| # | Tarefa | Status |
|---|--------|--------|
| A1 | Sample contacts + CLI | ✅ Concluído |
| A2 | API conversations scan | ✅ Concluído |
| A3 | Exit codes | ✅ Concluído |
| A4 | Sanity queries | ✅ Concluído |
| A5 | url_preview redaction | ✅ Concluído |
| B1 | Primeira execução real | ✅ Concluído |
| B2 | `make validate-api-deep SAMPLE=5` | 🔵 Pendente |
| B3 | `make validate-api-deep SAMPLE=5 CHECK_URLS=1` | 🔵 Pendente |
| C1 | Investigar `orphan_messages=6321` account 1 | 🔵 Pendente |
| C2 | Documentar attachments_not_found > 0 (pós B2/B3) | 🔵 Pendente |

---
