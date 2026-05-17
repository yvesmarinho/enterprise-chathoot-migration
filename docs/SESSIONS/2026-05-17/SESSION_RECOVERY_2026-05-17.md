# 🔄 Session Recovery — 2026-05-17

**Sessão anterior**: 2026-05-16 (Sessão 16)
**Branch**: `001-enterprise-chatwoot-migration`
**Status dos IMPs**: Migração em produção — Unimed Guaxupé em execução

---

## Contexto Recuperado

### Última Sessão (2026-05-16)
- Refactoring `app/db.py` → env vars obrigatórias (`MIGRATION_SOURCE_KEY`/`MIGRATION_DEST_KEY`)
- 4 usuários ausentes criados no DEST prod (dest_ids 358-361)
- Infraestrutura Docker adaptada para produção (daemon mode)
- Container `chatwoot-migrator-unimed_guaxup` (ID: `9f13b2337b26`) iniciado como daemon no wfdb01
- Commit final: `55dcd93` — chore: INDEX.md + .tmp/ cleanup pós sessão 16

### Estado da Migração

| Account | SOURCE ID | DEST ID | Status |
|---------|-----------|---------|--------|
| Unimed Guaxupé | 25 | 45 | 🔍 Verificar container (pode ter concluído) |
| Sol Copernico | 4 | — | ⏳ Pendente |
| Unimed Poços PF | 18 | — | ⏳ Pendente |
| Unimed Poços PJ | 17 | — | ⏳ Pendente |
| Vya Digital | 1 | — | ⏳ Pendente |

### Fatos Críticos
- **DEST account_id Unimed Guaxupé**: **45** (prod). NÃO confundir com dev (46).
- **Env vars obrigatórias**: `MIGRATION_SOURCE_KEY=chat-vya-digital` e `MIGRATION_DEST_KEY=synchat-vya-digital`
- **SSH wfdb01**: porta 5010, user `archaris`, requer `fwknop SPA` antes de cada conexão
- **Migration é idempotente** — re-execução segura
- **Inbox Cobrança** (WhatsApp) Unimed Guaxupé: criada automaticamente como inbox_id=428

---

## Itens P0 para Esta Sessão

1. **Verificar status do container** `chatwoot-migrator-unimed_guaxup` no wfdb01
2. **Validações pós-migração Unimed Guaxupé** (VAL-1, VAL-2, VAL-S3, VAL-API, VAL-HASH)
3. **Iniciar migração dos demais accounts** (Sol Copernico → Unimed Poços PF → Unimed Poços PJ → Vya Digital)
4. **Go/No-Go final** após todas as validações

---

## Referências Rápidas

- Runbook: [`docs/RUNBOOK_MIGRACAO_PRODUCAO_2026-05-16.md`](../RUNBOOK_MIGRACAO_PRODUCAO_2026-05-16.md)
- Checklist: [`docs/CHECKLIST_EXECUTIVA_MIGRACAO_2026-05-16.md`](../CHECKLIST_EXECUTIVA_MIGRACAO_2026-05-16.md)
- TODO: [`docs/TODO.md`](../TODO.md)
