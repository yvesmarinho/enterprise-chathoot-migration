# 🔄 Session Recovery — 2026-05-26

**Sessão anterior**: 2026-05-24
**Branch**: master
**Status dos IMPs**: Migração DEV Unimed Guaxupé bem-sucedida; gaps P0 (D17) identificados; offboarding tool documentado

## Contexto Recuperado

Última sessão (S23 — 2026-05-24) foi dividida em 3 partes:

### 1. Documentação do Account Offboarding Tool
- ✅ Criados `tools/account_offboarding/README.md` e `docs/guides/ACCOUNT_OFFBOARDING_GUIDE.md`
- ✅ Atualizado `docs/INDEX.md` e criado `docs/INVENTARIO_COMPLETO_ARQUIVOS_MIGRACAO.md`
- ✅ 3 commits realizados e pushed para origin/master

### 2. Análise D17 — Cobertura de Tabelas
- ✅ Comparação entre `cleanup.py` (52 tabelas) vs `migrar.py` (15 tabelas) → gap de 37 tabelas
- ✅ Identificados 3 gaps P0 (mentions, conversation_participants, reporting_events)
- ✅ Identificados 10 gaps P1 (working_hours, automation_rules, macros, SLAs, etc.)

### 3. Teste de Migração DEV — Unimed Guaxupé
- ✅ Account "Unimed Guaxupé" (ID: 25) migrado para vya-chat-dev.vya.digital
- ✅ 60.030 de 81.710 registros migrados (73,4%)
- ✅ Dados core 100% migrados: 8.190 conversas, 46.010 mensagens, 1.513 contacts, 1.932 anexos
- ✅ Validação FK: 12 relações validadas, 0 orphans no escopo migrado
- ⚠️ Orphans identificados (contact_inboxes: 7.336, conversation_labels: 14.333) — hipótese: outros accounts

## Itens P0 para Esta Sessão

- **D17-P0-1** Criar `MentionsMigrator` (tabela `mentions` — menções @user em mensagens)
- **D17-P0-2** Criar `ConversationParticipantsMigrator` (tabela `conversation_participants` — participantes multi-user)
- **D17-P0-3** Validar uso de `portals` por account (se COUNT > 0 → criar suite de migrators para help center)
- **D17-P0-4** Comunicar stakeholders sobre perda de `reporting_events` (analytics históricos não migrados) OU criar migrator seletivo
