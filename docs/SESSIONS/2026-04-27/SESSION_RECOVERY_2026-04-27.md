# 🔄 Session Recovery — 2026-04-27

**Sessão anterior**: 2026-04-24 (Sessão 10)
**Branch**: `001-enterprise-chatwoot-migration`
**Commit HEAD**: `152c809` — `fix(migrar): corrige BUG-06 set_session dentro de transação em Phase 5`
**Status dos IMPs**: Fases 0-4 ✅ | Fase 5 (sequences) ❌ BUG-06 corrigido, pendente re-execução

---

## Contexto Recuperado

### O Que Foi Feito na Sessão 10 (2026-04-24)

1. **D11 resolvido**: container `vya-chat-dev.vya.digital` recriado apontando para `chatwoot004_dev1_db` (banco correto)
2. **D12-P0 (3 itens)**: tokens regenerados (95 colisões corrigidas), 0 snoozed, 124 open mantidos
3. **Migração fases 0-4** para `account_id=1` ("Vya Digital"):
   - 13 inboxes criadas (IDs 397-409), 1 mapeada (`wea004` → id 372)
   - 179 contatos inseridos | 942 dedup | 0 erros
   - 309 conversas + 13.164 mensagens migradas com 0 erros
4. **BUG-06** diagnosticado e corrigido: `set_session` chamado dentro de transação na Phase 5 (resequência de sequences)
5. **Sequences NÃO resequenciadas**: fase 5 não completou — risco de colisão em novos INSERTs no DEST

### Estado Atual do Working Tree

- `app/01_migrar_account.py` — **MODIFICADO (não commitado)**: BUG-06 corrigido (commit `152c809` já contém o fix, mas o arquivo ainda aparece como modified no git status — verificar diff antes de continuar)

---

## ⚠️ Atenção Pré-Re-Execução

- As **309 conversas já existem** no DEST (account_id=1)
- `migration_state` registra essas 309 como `status=ok` → re-run pode tentar inserir duplicatas
- **Opção preferencial**: executar apenas a fase 5 isolada (resequência de sequences)
- Token admin disponível: ver `.secrets/generate_erd.json` chave `vya-chat-dev-admin`

---

## Itens P0 para Esta Sessão (Sessão 11)

### Críticos (em ordem de execução)

1. **S10-P0-1** — Re-executar migração OR executar fase 5 isolada para resequenciar sequences
2. **S10-P0-2** — Migrar `inbox_members` para inboxes 397-409 (`app/13_migrar_inbox_members.py`)
3. **S10-P0-3** — Validar inboxes visíveis no frontend para usuários não-admin
4. **TOKEN-ADMIN** — Reexecutar `make validate-api` com token admin → esperado `api_conv=687`

### D12 Pendentes

- **D12-P1-1** a **D12-P1-5** — Verificações pré-liberação (FKs dangles, phone colisões, webhooks)

### Outros Accounts P1 (após validação account_id=1)

- Sol Copernico (`account_id=4`), Unimed Poços PJ (17), Unimed Poços PF (18), Unimed Guaxupé (25)
