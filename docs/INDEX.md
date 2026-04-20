# 📚 Índice — Enterprise Chathoot Migration

**Projeto**: `enterprise-chathoot-migration`
**Criado em**: 2026-04-09T11:37:54Z
**Last Updated**: 2026-04-20
**Last Session**: 2026-04-20 (encerrada — D5-A1→A5 implementados, B1 executado EXIT 2, orphan_messages C1 pendente)

---

## Documentação Principal

| Arquivo | Descrição |
|---------|-----------|
| [README.md](../README.md) | Documentação pública |
| [TODO.md](TODO.md) | Tarefas pendentes |
| [TODAY_ACTIVITIES.md](TODAY_ACTIVITIES.md) | Atividades do dia |

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
```

## Debates e Decisões

| Arquivo | Descrição |
|---------|-----------|
| [debates/D3-DEBATE-REGRAS-MIGRACAO-2026-04-10.md](debates/D3-DEBATE-REGRAS-MIGRACAO-2026-04-10.md) | 9 erros + 6 decisões de migração (estratégia MERGE) |
| [debates/D4-DEBATE-CONTACTS-ORPHANS-2026-04-14.md](debates/D4-DEBATE-CONTACTS-ORPHANS-2026-04-14.md) | 31.568 contacts orphans no SOURCE — decisão: ACEITAR como data decay |
| [debates/D5-DEBATE-SPEC-VALIDACAO-API-2026-04-20.md](debates/D5-DEBATE-SPEC-VALIDACAO-API-2026-04-20.md) | Spec validação API pós-migração — gaps A1–A5 + plano B1–C2 |
| [debates/D5-SQL-VALIDACAO-PROFUNDA-2026-04-20.sql](debates/D5-SQL-VALIDACAO-PROFUNDA-2026-04-20.sql) | SQL queries para validação profunda (sanity checks) |

## Scripts de Relatório (reutilizáveis)

| Script | Descrição | Uso |
|--------|-----------|-----|
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
| [`app/10_validar_api.py`](../app/10_validar_api.py) | **NOVO** — Validação API pós-migração: counts, deep scan, sanity, exit codes (D5) |
| [`tmp/diagnostico_20260410_165333.txt`](../tmp/diagnostico_20260410_165333.txt) | Baseline 18KB (2026-04-10) |

---

*Gerado por scaffold.py em 2026-04-09T11:37:54Z — atualizado manualmente em 2026-04-20 (encerramento sessão 6)*
