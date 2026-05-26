# 📚 Índice — Enterprise Chatwoot Migration

**Projeto**: `enterprise-chatwoot-migration`
**Criado em**: 2026-04-09T11:37:54Z
**Last Updated**: 2026-05-26 (Sessão 26 — D21 bug crítico idempotência + correções P0 implementadas)
**Last Session**: 2026-05-26 (Sessão 26 — Bug D21: pipeline não-idempotente corrigido; validação account + mapeamento deduplicação + --force-overwrite)

---

## Documentação Principal

| Arquivo | Descrição |
|---------|-----------|
| [README.md](../README.md) | Documentação pública |
| [TODO.md](TODO.md) | Tarefas pendentes |
| [TODAY_ACTIVITIES.md](TODAY_ACTIVITIES.md) | Atividades do dia |

## 🚀 Migração em Produção (16/05/2026 14:00 BRT)

| Arquivo | Descrição |
|---------|-----------|
| [**RUNBOOK_MIGRACAO_PRODUCAO_2026-05-16.md**](RUNBOOK_MIGRACAO_PRODUCAO_2026-05-16.md) | **Runbook completo** — Procedimentos, validações, rollback, troubleshooting (800 linhas) |
| [**CHECKLIST_EXECUTIVA_MIGRACAO_2026-05-16.md**](CHECKLIST_EXECUTIVA_MIGRACAO_2026-05-16.md) | **Quick reference** — Checklist resumida para impressão e consulta rápida (200 linhas) |

## Sessões de Trabalho

```
SESSIONS/
├── 2026-04-09/           ← Sessão 1: scaffold + especificação completa (speckit)
│   ├── DAILY_ACTIVITIES_2026-04-09.md
│   ├── SESSION_REPORT_2026-04-09.md
│   └── PRE_SPEC_ANALYSIS_REPORT.md
├── 2026-04-10/           ← Sessão 2: análise + diagnóstico + spec v2 (encerrada)
│   ├── SESSION_RECOVERY_2026-04-10.md
│   ├── DAILY_ACTIVITIES_2026-04-10.md
│   └── FINAL_STATUS_2026-04-10.md
├── 2026-04-13/           ← Sessão 3: RUN-8 executado (276.819 registros, 5/5 accounts OK)
│   └── DAILY_ACTIVITIES_2026-04-13.md
├── 2026-04-14/           ← Sessão 4: RUN-11 completo + D4 + relatorio_consolidado_pipeline
│   ├── DAILY_ACTIVITIES_2026-04-14.md
│   ├── SESSION_REPORT_2026-04-14.md
│   └── FINAL_STATUS_2026-04-14.md
└── 2026-04-20/           ← Sessão 6: D5-A1→A5 + B1 — validação API spec implementada (EXIT 2, orphan_messages C1 pendente)
    ├── SESSION_RECOVERY_2026-04-20.md
    ├── DAILY_ACTIVITIES_2026-04-20.md
    ├── SESSION_REPORT_2026-04-20.md
    └── FINAL_STATUS_2026-04-20.md
├── 2026-04-22/           ← Sessão 8: D7 — diagnóstico visibilidade Marcus (display_id resequenciado, conv migradas ✅)
│   ├── DAILY_ACTIVITIES_2026-04-22.md
│   ├── SESSION_REPORT_2026-04-22.md
│   ├── SESSION_RECOVERY_2026-04-22.md
│   └── FINAL_STATUS_2026-04-22.md
└── 2026-04-24/           ← Sessão 10: D11 root cause (container DB errado) resolvido, 309 convs migradas, BUG-06 corrigido em app/01_migrar_account.py
    ├── SESSION_RECOVERY_2026-04-24.md
    ├── DAILY_ACTIVITIES_2026-04-24.md
    ├── SESSION_REPORT_2026-04-24.md
    └── FINAL_STATUS_2026-04-24.md
├── 2026-05-13/           ← Sessão 13: D15 — Descoberta crítica: migração S3 incompleta (98% recentes OK, 26% histórico falha)
│   ├── SESSION_RECOVERY_2026-05-13.md
│   ├── DAILY_ACTIVITIES_2026-05-13.md
│   └── FINAL_STATUS_2026-05-13.md
├── 2026-05-14/           ← Sessão 14: Ferramental S3 — criado CLI check_s3_attachments.py, organizado .tmp/ → docs/evidencias/
│   ├── SESSION_RECOVERY_2026-05-14.md
│   └── DAILY_ACTIVITIES_2026-05-14.md
├── 2026-05-15/           ← Sessão 15: Preparação para produção — runbook completo, checklist executiva, D15-T1.1 resolvido
│   ├── SESSION_RECOVERY_2026-05-15.md
│   └── DAILY_ACTIVITIES_2026-05-15.md
└── 2026-05-16/           ← Sessão 16: Migração prod Unimed Guaxupé — Docker daemon deploy wfdb01, 4 usuários criados, container rodando
    ├── DAILY_ACTIVITIES_2026-05-16.md
    └── FINAL_STATUS_2026-05-16.md
└── 2026-05-18/           ← Sessão 19: DEV migration validada — Unimed Guaxupé 4092 convs 100% integridade; bug fixes conversations/webhooks migrators; _ENV_PRESETS["dev"] corrigido; MCP GitHub configurado
    ├── DAILY_ACTIVITIES_2026-05-18.md
    ├── SESSION_RECOVERY_2026-05-18.md
    └── FINAL_STATUS_2026-05-18.md
└── 2026-05-20/           ← Sessão 21: D16 root cause HTTP500 confirmada; ajustes no fluxo legado all-accounts; deploy wfdb01
    ├── DAILY_ACTIVITIES_2026-05-20.md
    ├── SESSION_RECOVERY_2026-05-20.md
    └── FINAL_STATUS_2026-05-20.md
└── 2026-05-21/           ← Sessão 22: investigação Guaxupé chat x synchat + plano DEV-only de reset/revisão
    ├── DAILY_ACTIVITIES_2026-05-21.md
    ├── SESSION_RECOVERY_2026-05-21.md
    ├── INVESTIGACAO_GUAXUPE_CHAT_SYNCHAT_2026-05-21.md
    ├── PLANO_E_TAREFAS_RESET_E_MIGRACAO_DEV_ONLY_2026-05-21.md
    └── FINAL_STATUS_2026-05-21.md
```

## Evidências de Validação S3

| Arquivo | Descrição |
|---------|-----------|
| [`evidencias/validacao_attachments_s3_20260513_120012.json`](evidencias/validacao_attachments_s3_20260513_120012.json) | **CRÍTICO** — 100 attachments recentes (2025-2026): 98 OK, 2 fail (98% success rate) |
| [`evidencias/validacao_attachments_s3_20260513_*.json`](evidencias/) | Validações históricas Session 13: 26% success rate (aleatórios 2020-2026) |
| [`evidencias/check_s3_attachments_20260514_*.json`](evidencias/) | Validações Session 14: account 1 (100% success), account 46 (0 attachments) |

## Debates e Decisões

| Arquivo | Descrição |
|---------|-----------|
| [debates/D3-DEBATE-REGRAS-MIGRACAO-2026-04-10.md](debates/D3-DEBATE-REGRAS-MIGRACAO-2026-04-10.md) | 9 erros + 6 decisões de migração (estratégia MERGE) |
| [debates/D4-DEBATE-CONTACTS-ORPHANS-2026-04-14.md](debates/D4-DEBATE-CONTACTS-ORPHANS-2026-04-14.md) | 31.568 contacts orphans no SOURCE — decisão: ACEITAR como data decay |
| [debates/D5-DEBATE-SPEC-VALIDACAO-API-2026-04-20.md](debates/D5-DEBATE-SPEC-VALIDACAO-API-2026-04-20.md) | Spec validação API pós-migração — gaps A1–A5 + plano B1–C2 |
| [debates/D5-SQL-VALIDACAO-PROFUNDA-2026-04-20.sql](debates/D5-SQL-VALIDACAO-PROFUNDA-2026-04-20.sql) | SQL queries para validação profunda (sanity checks) |
| [debates/D5-REVISAO-METODO-VALIDACAO-2026-04-21.md](debates/D5-REVISAO-METODO-VALIDACAO-2026-04-21.md) | Revisão do método de validação API — D5 (2026-04-21) |
| [debates/D6-DEBATE-ARQUITETURA-VALIDACAO-HASH-2026-04-21.md](debates/D6-DEBATE-ARQUITETURA-VALIDACAO-HASH-2026-04-21.md) | D6 — Arquitetura de validação por hash MD5 + BKs + resultados finais |
| [debates/D7-DEBATE-VISIBILIDADE-MARCOS-2026-04-22.md](debates/D7-DEBATE-VISIBILIDADE-MARCOS-2026-04-22.md) | D7 — Visibilidade Marcus pós-migração — causa: display_id resequenciado (BUG-04) |
| [debates/D15-DEBATE-MIGRACAO-S3-INCOMPLETA-2026-05-13.md](debates/D15-DEBATE-MIGRACAO-S3-INCOMPLETA-2026-05-13.md) | **D15 — CRÍTICO** — Migração S3 incompleta: 74% attachments HTTP 404, metadados OK mas arquivos físicos ausentes |
| [debates/D16-DEBATE-HTTP500-CONVERSACOES-POS-MIGRACAO-2026-05-20.md](debates/D16-DEBATE-HTTP500-CONVERSACOES-POS-MIGRACAO-2026-05-20.md) | **D16** — HTTP500 em conversações pós-migração DEV: causa raiz confirmada em ActiveStorage |
| [debates/D16-PLANO-INVESTIGACAO-HTTP500-2026-05-20.md](debates/D16-PLANO-INVESTIGACAO-HTTP500-2026-05-20.md) | Plano faseado de investigação/correção/validação para o incidente D16 |
| [debates/D18-ANALISE-ACTIVESTORAGE-AUSENTE-2026-05-26.md](debates/D18-ANALISE-ACTIVESTORAGE-AUSENTE-2026-05-26.md) | **D18** — Mensagens não abrem em DEV: root cause = ActiveStorage nunca migrado (tabelas ausentes do pipeline) |
| [debates/D19-UNIQUEVIOLATION-ACTIVESTORAGE-BLOBS-2026-05-26.md](debates/D19-UNIQUEVIOLATION-ACTIVESTORAGE-BLOBS-2026-05-26.md) | **D19** — UniqueViolation em active_storage_blobs.key após adicionar migrator (fix: deduplicação) |
| [debates/D21-BUG-CRITICO-IDEMPOTENCIA-DEDUPLICACAO-GLOBAL-2026-05-26.md](debates/D21-BUG-CRITICO-IDEMPOTENCIA-DEDUPLICACAO-GLOBAL-2026-05-26.md) | **D21 — 🔴 CRÍTICO** — Pipeline não-idempotente: deduplicação global + ausência de validação account name → 100% skip + account vazio |

## 🐛 Correções de Bugs

| Arquivo | Descrição |
|---------|-----------|
| [**CORRECOES_P0_BUG_D21_2026-05-26.md**](CORRECOES_P0_BUG_D21_2026-05-26.md) | **Correções P0 Bug D21** — Validação de account pré-existente + registro de mapeamentos em skips + --force-overwrite flag

## Scripts de Relatório (reutilizáveis)

| Script | Descrição | Uso |
|--------|-----------|-----|
| [`scripts/check_s3_attachments.py`](../scripts/check_s3_attachments.py) | **NOVO** — CLI para validar acessibilidade de attachments S3 via HTTP (conexão via .secrets, relatório JSON detalhado) | `uv run python scripts/check_s3_attachments.py --instance chatwoot004_dev --account-id 1 --limit 100 --date-start 2025-01-01 --date-end 2025-12-31` |
| [`scripts/reports/relatorio_qualidade_source.py`](../scripts/reports/relatorio_qualidade_source.py) | Qualidade dos dados do SOURCE (6 blocos) | `python3 scripts/reports/relatorio_qualidade_source.py` |
| [`scripts/reports/relatorio_qualidade_dest.py`](../scripts/reports/relatorio_qualidade_dest.py) | Qualidade dos dados do DEST (7 blocos) | `python3 scripts/reports/relatorio_qualidade_dest.py` |
| [`scripts/reports/relatorio_qualidade_migracao.py`](../scripts/reports/relatorio_qualidade_migracao.py) | Comparativo SOURCE vs DEST: cobertura, gaps, integridade | `python3 scripts/reports/relatorio_qualidade_migracao.py` |
| [`scripts/reports/relatorio_consolidado_pipeline.py`](../scripts/reports/relatorio_consolidado_pipeline.py) | **NOVO** — Consolida F1→F2→F3: volumes, deltas, FK violations, cobertura | `python3 scripts/reports/relatorio_consolidado_pipeline.py` |

## Outputs de Relatório (últimos gerados)

| Arquivo | Descrição |
|---------|-----------|
| [`tmp/relatorio_qualidade_source_20260414.txt`](../tmp/relatorio_qualidade_source_20260414.txt) | SOURCE: 7.300 contacts válidos, 31.568 orphans, 36.016 conversations |
| [`tmp/relatorio_qualidade_migracao_20260414.txt`](../tmp/relatorio_qualidade_migracao_20260414.txt) | Migração: 91.2% contacts, 95.0% conversations, 94.8% messages, 0 violações novas || [`tmp/relatorio_qualidade_dest_20260416-142816.txt`](../tmp/relatorio_qualidade_dest_20260416-142816.txt) | DEST pós-RUN-20260416: 1.860.713 registros, FK violations novas = 0 |
| [`tmp/relatorio_qualidade_dest_20260414-151041.txt`](../tmp/relatorio_qualidade_dest_20260414-151041.txt) | DEST F3 pós-RUN-11: contacts 201.502, FK violations = 0 |
| [`tmp/relatorio_consolidado_pipeline_20260414-151436.txt`](../tmp/relatorio_consolidado_pipeline_20260414-151436.txt) | **Pipeline consolidado F1→F2→F3**: volumes, deltas, FK, cobertura |
## Tooling de Diagnóstico (legado)

| Arquivo | Descrição |
|---------|----------|
| [`app/05_diagnostico_completo.py`](../app/05_diagnostico_completo.py) | 14 blocos SOURCE vs DEST |
| [`app/10_validar_api.py`](../app/10_validar_api.py) | Validação API pós-migração: counts, deep scan, sanity, exit codes (D5) |
| [`app/11_validar_hash.py`](../app/11_validar_hash.py) | **NOVO** — Validação por hash MD5: Pandas set-difference, BKs por tabela, missing/extra (D6) |

## Scripts de Manutenção

| Script | Descrição | Uso |
|--------|-----------|-----|
| [`scripts/cleanup-tmp.sh`](../scripts/cleanup-tmp.sh) | **NOVO** — Limpeza de `.tmp/` com `--dry-run` e `--verbose` | `./scripts/cleanup-tmp.sh --verbose` |

## 🗑️ Account Offboarding Tool

**Localização**: `tools/account_offboarding/`

| Arquivo | Descrição |
|---------|-----------|
| [**README.md**](../tools/account_offboarding/README.md) | **Documentação completa** — Guia de uso, casos de uso, segurança, troubleshooting |
| [`inspect.py`](../tools/account_offboarding/inspect.py) | **Auditoria read-only** — Identifica quantos registros existem para um account_id (48+ tabelas via direct + FK discovery) |
| [`cleanup.py`](../tools/account_offboarding/cleanup.py) | **Remoção completa** — Deleta TODOS os dados do account (40+ tabelas, ordem FK-aware, transação única) |
| [`config.json.example`](../tools/account_offboarding/config.json.example) | Template de configuração (db_key, account_id, secrets_file) |

**Casos de uso:**
- ✅ Offboarding de cliente (término de contrato)
- ✅ Limpeza de migração incorreta (ex: account_id=45 migrado para produção por engano)
- ✅ Remoção de accounts de teste em DEV

**Uso básico:**
```bash
# 1. Auditoria
uv run python tools/account_offboarding/inspect.py --db-key vya-chat-dev --account-id 44

# 2. Dry-run
uv run python tools/account_offboarding/cleanup.py --db-key vya-chat-dev --account-id 44 --dry-run

# 3. Execução (confirmação interativa obrigatória)
uv run python tools/account_offboarding/cleanup.py --db-key vya-chat-dev --account-id 44 --execute
```

**Criado em**: 2026-05-24 (Sessão 23)
**Testado contra**: chatwoot004_dev1_db (account_id=44, 864 linhas), chatwoot004_db (account_id=45, 2.339 linhas)

---

*Gerado por scaffold.py em 2026-04-09T11:37:54Z — atualizado manualmente em 2026-05-24 (account offboarding tool, S23)*
