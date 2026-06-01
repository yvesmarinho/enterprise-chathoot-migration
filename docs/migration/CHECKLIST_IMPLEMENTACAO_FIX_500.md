# 📋 CHECKLIST DE IMPLEMENTAÇÃO — Erro 500 Fix

**Status**: 🟢 PRONTO PARA IMPLEMENTAÇÃO
**Data**: 2026-05-28
**Impacto**: 46,052 messages corrompidas em Account 69

---

## ✅ PRÉ-IMPLEMENTAÇÃO

- [ ] **Fazer backup** do banco DEST antes de aplicar fix
  ```bash
  pg_dump -U migration_user -h wfdb02.vya.digital chatwoot004_dev1_db \
    > chatwoot004_dev1_db_backup_20260528.sql
  ```

- [ ] **Revisar relatórios** de investigação
  - [x] `.tmp/debate_data_investigation_20260528_122944.json`
  - [x] `.tmp/debate_message_attachment_analysis_20260528_123132.json`
  - [x] `.tmp/debate_orphaned_inboxes_20260528_123208.json`

- [ ] **Revisar documentação**
  - [x] `docs/DEBATE_ERRO_500_RESULTADO_FINAL.md` (análise 5 personas)
  - [x] `docs/FIX_DEFENSIVO_ATTACHMENT_RB.md` (código)

- [ ] **Comunicar com stakeholders**
  - [ ] Informar que Account 69 (Guaxupé) será offline por ~30 minutos
  - [ ] Avisar que após fix, conversas carregarão normalmente

---

## 🔧 FASE 1: VALIDAÇÃO PRÉ-FIX

- [ ] **Conectar ao DEST DB**
  ```bash
  psql -U migration_user -h wfdb02.vya.digital -d chatwoot004_dev1_db
  ```

- [ ] **Rodar PRE-CHECKs** (linhas 1-50 de `fix_orphaned_inboxes.sql`)
  ```bash
  # Validar que problema realmente existe
  psql -U migration_user -h wfdb02.vya.digital -d chatwoot004_dev1_db \
    << 'SQL'
    BEGIN;
    SELECT 'PRE-CHECK 1' as test;
    SELECT COUNT(*) FROM inboxes WHERE id = 100;
    -- Esperado: 0

    SELECT 'PRE-CHECK 2' as test;
    SELECT id, name, account_id FROM inboxes WHERE id = 526 AND account_id = 69;
    -- Esperado: 1 row

    SELECT 'PRE-CHECK 3' as test;
    SELECT COUNT(*) FROM messages WHERE account_id = 69 AND inbox_id = 100;
    -- Esperado: ~46052

    ROLLBACK;
  SQL
  ```

- [ ] **Confirmar que checklist PRE-CHECK passou**
  - [ ] Inbox 100 não existe: ✅
  - [ ] Inbox 526 existe em Account 69: ✅
  - [ ] ~46,052 messages com inbox_id=100: ✅

---

## 🔨 FASE 2: APLICAR FIX SQL

- [ ] **Executar UPDATE** (linha 51+ de `fix_orphaned_inboxes.sql`)
  ```bash
  psql -U migration_user -h wfdb02.vya.digital -d chatwoot004_dev1_db \
    << 'SQL'
    BEGIN TRANSACTION;
    SET TRANSACTION ISOLATION LEVEL SERIALIZABLE;

    UPDATE messages
    SET inbox_id = 526
    WHERE account_id = 69 AND inbox_id = 100;

    -- Se está tudo OK:
    COMMIT;

    -- Se algo errado:
    -- ROLLBACK;
  SQL
  ```

- [ ] **Verificar que UPDATE completou**
  - [ ] Número de rows afetadas: esperado ~46,052

- [ ] **Registrar timestamp** de quando fix foi aplicado
  - Timestamp: `_________________________`

---

## ✅ FASE 3: VALIDAÇÃO PÓS-FIX

- [ ] **Rodar POST-CHECKs** (linhas 80+ de `fix_orphaned_inboxes.sql`)
  ```bash
  psql -U migration_user -h wfdb02.vya.digital -d chatwoot004_dev1_db \
    << 'SQL'
    SELECT 'POST-CHECK 1: Messages com inbox_id=100' as test;
    SELECT COUNT(*) FROM messages WHERE account_id = 69 AND inbox_id = 100;
    -- Esperado: 0

    SELECT 'POST-CHECK 2: Orphaned inboxes' as test;
    SELECT COUNT(*) FROM messages m
    WHERE account_id = 69 AND m.inbox_id NOT IN
    (SELECT id FROM inboxes WHERE account_id = 69);
    -- Esperado: 0

    SELECT 'POST-CHECK 3: Conversation 275037' as test;
    SELECT c.id, c.inbox_id, COUNT(*) as msg_count
    FROM conversations c
    LEFT JOIN messages m ON c.id = m.conversation_id
    WHERE c.id = 275037
    GROUP BY c.id, c.inbox_id;
    -- Esperado: conversation_inbox=526, msg_count=4
  SQL
  ```

- [ ] **Confirmar que todos POST-CHECKs passaram**
  - [ ] Nenhum message com inbox_id=100: ✅
  - [ ] Nenhum orphaned inbox: ✅
  - [ ] Conversation 275037 OK: ✅

---

## 🌐 FASE 4: TESTE DE API

- [ ] **Obter token de autenticação**
  ```bash
  TOKEN="<paste_token_from_vya-chat-dev_admin>"
  echo $TOKEN
  ```

- [ ] **Testar carregamento de conversas** (sem error 500)
  ```bash
  curl -s -H "Authorization: Bearer $TOKEN" \
    https://vya-chat-dev.vya.digital/api/v1/accounts/69/conversations \
    | jq '.payload[0]' | head -50

  # Esperado: 200 OK (não 500)
  # Esperado: conversas renderizando normalmente
  ```

- [ ] **Testar conversa específica 275037**
  ```bash
  curl -s -H "Authorization: Bearer $TOKEN" \
    https://vya-chat-dev.vya.digital/api/v1/accounts/69/conversations/275037 \
    | jq '.' | head -100

  # Esperado: 200 OK
  # Esperado: messages renderizando normalmente
  ```

- [ ] **Verificar no frontend**
  - [ ] Abrir https://vya-chat-dev.vya.digital
  - [ ] Login como admin@vya.digital
  - [ ] Account 69 (Guaxupé)
  - [ ] Carregar uma conversa
  - [ ] Verificar que **não há erro 500** ✅

---

## 💎 FASE 5: FIX DEFENSIVO (OPCIONAL — PÓS-VALIDAÇÃO)

- [ ] **Após confirmar que fix SQL funcionou**, considerar fix defensivo em Chatwoot
  - [ ] Criar branch: `git checkout -b fix/instagram-inbox-defensive`
  - [ ] Editar `app/models/attachment.rb` linha 84
  - [ ] Adicionar guard: `return false unless message.inbox`
  - [ ] Testar localmente
  - [ ] Push & criar PR

---

## 📊 FASE 6: MONITORAMENTO PÓS-FIX

- [ ] **Monitorar logs** por próximas 24h
  ```bash
  # Em vya-chat-dev container
  docker logs -f chatwoot-server 2>&1 | grep -i "instagram\|error 500\|attachment"
  ```

- [ ] **Validar que não há regressões**
  - [ ] Testar carregamento de conversas de outro account (ex: Account 1)
  - [ ] Testar envio de mensagens
  - [ ] Testar upload de attachments

- [ ] **Validar relatório de erros**
  - [ ] Verificar error tracking (se houver)
  - [ ] Confirmar que 500 errors desapareceram

---

## 🎓 FASE 7: DOCUMENTAÇÃO

- [ ] **Registrar resultado**
  ```bash
  echo "Fix applied: 2026-05-28 HH:MM:SS UTC
  Root cause: Inbox 100 orphaned (46,052 messages)
  Solution: UPDATE messages inbox_id 100 → 526
  Status: ✅ Conversas carregam normalmente
  " >> docs/SESSIONS/YYYY-MM-DD/FINAL_STATUS.md
  ```

- [ ] **Atualizar projeto memory**
  ```bash
  # Memory repo
  echo "## 2026-05-28 — Erro 500 Resolved
  - Root cause: Orphaned inbox FK
  - Fix: Remapped 46,052 messages inbox_id
  - Status: ✅ RESOLVED
  " >> /memories/repo/bugs.md
  ```

- [ ] **Criar issue de follow-up** para Chatwoot
  - [ ] Título: "Add defensive check for missing inbox references"
  - [ ] Body: Reference `docs/FIX_DEFENSIVO_ATTACHMENT_RB.md`

---

## ✅ CONCLUSÃO

- [ ] **Todos os checklists completados?** ✅
- [ ] **Conversas carregam normalmente?** ✅
- [ ] **Nenhum erro 500?** ✅
- [ ] **Stakeholders notificados?** ✅

### Status Final: 🟢 FIX IMPLEMENTADO COM SUCESSO

---

## 🚨 ROLLBACK PLAN (se necessário)

```bash
# Se algo der errado, rollback para o backup:
psql -U migration_user -h wfdb02.vya.digital chatwoot004_dev1_db \
  < chatwoot004_dev1_db_backup_20260528.sql
```

**Tempo de rollback**: ~5-10 minutos
**Impacto**: Account 69 conversas voltarão ao estado anterior (sem fix)

---

**Próximo passo**: Executar FASE 1 (Validação PRÉ-FIX)
