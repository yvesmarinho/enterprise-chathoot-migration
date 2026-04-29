# 📊 Final Status — 2026-04-22

**Branch**: `001-enterprise-chatwoot-migration`
**Sessão**: SESSION-2026-04-22 (Sessão 8) — 16:19 → 19:15
**Commits**: `0e87539` (D7 v2 arquitetura corrigida) + `bb70a70` (diagnóstico conclusivo)
**Branch status**: ⇡2 (2 commits ahead of origin, ainda não pushed)

---

## Debates Encerrados Esta Sessão

### ✅ D7 — Visibilidade Marcus — ENCERRADO

**Sintoma original**: `marcos.andrade@vya.digital` não visualiza conversa de 14/11/2025 em `vya-chat-dev.vya.digital`.

**Diagnóstico percorrido**:
1. `make verify-marcus-conv` → reportou "MIGRATION_GAP" (falso negativo — buscava `src_id` que não existe em `additional_attributes`)
2. `make diagnose-inbox-gap` → inbox_id=125 foi migrado com `status=ok` → `id_destino=521`
3. `make diagnose-marcus-visibility` → todas as 3 conversas migradas; Marcus é admin + assignee

**Causa raiz real**: **display_id resequenciado** pelo BUG-04 (anti-colisão):

| SOURCE display_id | DEST display_id | DEST conv_id | assignee |
|------------------|-----------------|--------------|---------|
| 1091 | **1848** | 219045 | None |
| 1092 | **1849** | 219046 | None |
| **1093** | **1850** | 219047 | 88 (Marcus) ✓ |

Marcus procura `display_id=1093` — esse número não existe no DEST porque virou `1850`.

**Hipóteses descartadas**:
- H7 (conta errada): ❌ Q3 = Vya Digital selecionada
- H8 (Redis cache): ❌ Q7 = persiste após logout/login

**Ação imediata** para Marcus:
- Navegar em `vya-chat-dev.vya.digital` → All Conversations → inbox `wea004 (521)` → data 14/11/2025 → encontrará `display_id=1850`

---

## Artefatos Criados Esta Sessão

| Artefato | Tipo | Finalidade |
|----------|------|-----------|
| `docs/debates/D7-DEBATE-VISIBILIDADE-MARCOS-2026-04-22.md` | Debate | Diagnóstico completo D7 — seções 0–13 |
| `app/12_diagnostico_marcos.py` | Script | Diagnóstico multicamada Marcus |
| `app/14_verificar_conv_marcos.py` | Script | Verificação conversa específica por data |
| `app/15_diagnostico_inbox125.py` | Script | Diagnóstico inbox_id=125 SOURCE |
| `app/16_diagnostico_visibilidade_marcus.py` | Script | Diagnóstico visibilidade/role/assignee |
| `Makefile` targets | Config | `diagnose-agent`, `verify-marcus-conv`, `diagnose-inbox-gap`, `diagnose-marcus-visibility` |
| `scripts/git-commit-with-file.sh` | Script | Enforce P0 — commits via arquivo |

---

## Estado Geral das Frentes

| Frente | Status |
|--------|--------|
| Pipeline de migração (T001–T045) | ✅ Concluído — 311.539 registros, 0 falhas |
| D3 — Estratégia MERGE | ✅ Concluído |
| D4 — Contacts orphans | ✅ Concluído (aceito como data decay) |
| D5 — Validação API | 🟠 Parcialmente — B2/B3 e C1 pendentes |
| D6 — Validação Hash MD5 | 🟡 Quase — contacts 246 missing (3,41%) C1 pendente |
| D7 — Visibilidade Marcus | ✅ **ENCERRADO** — display_id resequenciado explicado |

---

## Problemas Conhecidos / Pendências

### Urgência baixa
1. **D7-A1**: Verificar DEST display_id de `conv_id=200501` (SOURCE display_id=1003)
2. **D7-A3**: Reatribuir conv_ids 219045, 219046 a Marcus (assignee=None)
3. **D5-B2/B3**: Executar `make validate-api-deep SAMPLE=5` (deep scan + CHECK_URLS)
4. **D5-C1**: Investigar `orphan_messages=6321` no dest_account_id=1
5. **D6-C1**: Investigar 246 contacts missing (3,41%) — BK `phone+email` imprecisa?

### Dívida técnica
- Adicionar `src_display_id` e `src_inbox_id` a `additional_attributes` em futuras migrações (melhoria de rastreabilidade)
- Testes unitários BUG-01→BUG-06 ainda pendentes

---

## Próximas Ações — P0 para Próxima Sessão

1. **Push dos 2 commits pendentes**: `git push origin 001-enterprise-chatwoot-migration`
2. **Informar Marcus** sobre os novos display_ids (1848, 1849, 1850 → inbox wea004/521)
3. **D7-A1**: `SELECT id, display_id, inbox_id, assignee_id FROM conversations WHERE id = 200501;` (no DEST)
4. Retomar D5-B2/B3 se necessário

---

## Contexto para Recuperação

**Setup**: branch `001-enterprise-chatwoot-migration`, 2 commits ahead of origin.

**Comandos úteis ao retomar**:
```bash
git push origin 001-enterprise-chatwoot-migration   # push pendente
make diagnose-marcus-visibility                      # re-executar diagnóstico
make verify-marcus-conv CONV_DATE=2025-11-14        # verificação rápida
```

**Arquivo mais importante**: `docs/debates/D7-DEBATE-VISIBILIDADE-MARCOS-2026-04-22.md` — seção 13 tem o diagnóstico completo e ações corretivas.

**Nota arquitetural importante** (não esquecer):
```
chat.vya.digital    → chatwoot_dev1_db    (SOURCE, read-only)
synchat.vya.digital → chatwoot004_dev1_db (DEST, read-write)
API SOURCE: chat.vya.digital
API DEST:   vya-chat-dev.vya.digital  ← NÃO usar synchat
```
