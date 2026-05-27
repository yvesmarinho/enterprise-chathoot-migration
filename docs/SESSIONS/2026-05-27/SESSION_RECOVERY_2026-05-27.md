# 🔄 Session Recovery — 2026-05-27

**Sessão anterior**: 2026-05-26
**Branch**: master
**Status dos IMPs**: D23/D24 concluídos; correções P0 de idempotência aplicadas; quality gates locais ainda pendentes (pytest/flake8/mypy no ambiente)
**Preset de ambiente para esta sessão (DEV)**: SOURCE=chat-vya-digital | DEST=vya-chat-dev

## Contexto Recuperado

A sessão de 2026-05-26 encerrou com estabilização do pipeline após restauração do DEST:

- ✅ D23 documentado: linha do tempo histórica da migração parcial (mensagens vs anexos)
- ✅ D24 resolvido: bootstrap on-demand para tabelas ausentes (`accounts`, `tags`/`taggings`)
- ✅ Formatação validada (`black --check src/`)
- ⚠️ Quality gates locais não executados por ausência de binários (`pytest`, `flake8`, `mypy`) no ambiente da sessão

Também foi confirmada recorrência do diagnóstico D18 no DEV:

- Attachments migrados no metadata, mas ActiveStorage ausente no SOURCE e no DEST para o recorte analisado
- Impacto funcional esperado: mensagens com anexo podem falhar na abertura (HTTP 500) sem remediation de ActiveStorage

## Itens P0 para Esta Sessão

- **S26-P0-1** Instalar dependências de qualidade ausentes no ambiente (`pytest`, `flake8`, `mypy`) e registrar baseline local.
- **S26-P0-2** Reexecutar gates de qualidade da sessão (`pytest`, `black --check`, `flake8`, `mypy`) após ajuste do ambiente.
- **S26-P0-3** Validar ciclo completo da migração para Unimed Guaxupé com estratégia segura (cleanup controlado ou `--force-overwrite` aprovado).

## Itens P1 Prioritários Herdados

- **D17-P1-1** Criar `WorkingHoursMigrator`
- **D17-P1-2** Criar `AutomationRulesMigrator` (JSONB com remapping de IDs)
- **D17-P1-3** Criar `MacrosMigrator` + `CampaignsMigrator`
- **D17-P1-4** Validar uso de SLAs por account (e migrator dedicado se necessário)
