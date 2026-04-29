# 📅 Daily Activities — 2026-04-21

**Branch**: `001-enterprise-chatwoot-migration`
**Sessão**: SESSION-2026-04-21 (Sessão 7)

---

## 🕐 Início de Sessão

- **Hora início**: 2026-04-21T00:00Z
- **Contexto recuperado**: FINAL_STATUS_2026-04-20.md → D5-B2/B3/C1 pendentes
- **Branch**: `001-enterprise-chatwoot-migration` ✅ up to date

---

<!-- Atividades serão registradas abaixo com separador --- -->

---

## 🔧 Atividades da Sessão

### A1 — Retomada de app/11_validar_hash.py
- **Hora**: 2026-04-21 (início da sessão)
- **Ação**: Retomada do script de validação por hash MD5 criado na sessão anterior (2026-04-21)
- **Contexto**: Script validava integridade pós-migração usando MD5 de campos de negócio + Pandas set-difference
- **Status**: ✅ Em execução

### A2 — Bug: BK de conversations incorreta
- **Hora**: 2026-04-21
- **Bug**: `display_id` era usado como business key de `conversations`, mas é **sempre renumerado** no DEST (MAX + offset por account), mesmo para accounts 1→1
- **Evidência**: Comparação mostrou grande quantidade de "missing" falso-positivo
- **Correção**: BK alterada para `created_at + status`
- **Validação**: `created_at` preservado bit-a-bit; 0 duplicatas em 36.016 rows
- **Status**: ✅ Corrigido

### A3 — Bug: BK de attachments incorreta
- **Hora**: 2026-04-21
- **Bug**: `external_url` era parte do hash de `attachments`, mas é `NULL` em 100% dos 22.841 registros → colapsava tudo em apenas 6 hashes únicos (falso positivo "todos ok")
- **Evidência**: `SELECT COUNT(DISTINCT external_url) FROM attachments` → 6 (todos NULL exceto 5)
- **Correção**: BK alterada para `file_type + created_at`
- **Status**: ✅ Corrigido

### A4 — Consolidação de pastas temporárias
- **Hora**: 2026-04-21
- **Problema**: Existência de dois diretórios temporários: `tmp/` e `.tmp/`
- **Ação**: 28 arquivos de `tmp/` movidos para `.tmp/`; `tmp/` removida
- **Correção colateral**: `app/05_diagnostico_completo.py` — caminho `tmp/` → `.tmp/`
- **Status**: ✅ Concluído

### A5 — Criação de scripts/cleanup-tmp.sh
- **Hora**: 2026-04-21
- **Ação**: Script de limpeza de `.tmp/` com suporte a `--dry-run` e `--verbose`
- **Integração**: `make clean` agora executa `cleanup-tmp.sh --verbose`
- **Integração 2**: `session-end.prompt.md` — Passo 10 atualizado para usar `.tmp/` e `.gitkeep`
- **Status**: ✅ Criado

### A6 — Execução final da validação por hash MD5
- **Hora**: 2026-04-21 (final da sessão)
- **Resultado**:

| Tabela | SOURCE rows | src hashes únicos | Missing (perda) | Extra (pré-DEST) | Status |
|--------|-------------|-------------------|-----------------|------------------|--------|
| contacts | 7.300 | 7.207 | **246 (3,41%)** | 2.317 | ⚠️ missing+extra |
| conversations | 36.016 | 36.016 | **0 (0%)** | 6.313 | ✅ extra apenas |
| messages | 239.439 | 239.439 | **0 (0%)** | 125.994 | ✅ extra apenas |
| attachments | 22.841 | 22.840 | **0 (0%)** | 12.041 | ✅ extra apenas |

- **Conclusão**: Nenhuma perda de dados em conversations, messages e attachments. 246 contacts missing → pendência para próxima sessão
- **Status**: ✅ Validação concluída

---

## 🏁 Encerramento da Sessão

- **Hora encerramento**: 2026-04-21 (ritual session-end executado)
- **Commit de encerramento**: `d837915`
- **Status geral**: ✅ Fase de validação hash concluída
