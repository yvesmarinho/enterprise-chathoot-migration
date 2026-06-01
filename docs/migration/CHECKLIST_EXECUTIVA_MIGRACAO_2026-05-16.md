# ✅ CHECKLIST EXECUTIVA — Migração 16/05/2026

**Imprimir e usar como referência rápida durante a execução**

---

## PRÉ-MIGRAÇÃO (13:00 - 14:00)

### Infraestrutura
- [ ] SSH wfdb01/wfdb02 OK
- [ ] PostgreSQL SOURCE conectado
- [ ] PostgreSQL DEST conectado
- [ ] `.secrets/generate_erd.json` validado
- [ ] Python 3.12+ e dependências OK
- [ ] Espaço em disco >= 50GB

### Backup
- [ ] `pg_dump` DEST executado
- [ ] Backup verificado (restore teste)
- [ ] Snapshot servidor (se aplicável)

### Segurança (CRÍTICO)
- [ ] ✅ **authentication_token** regenerado no DEST
  ```sql
  UPDATE users SET authentication_token = encode(gen_random_bytes(20), 'hex'), updated_at = NOW()
  WHERE id IN (SELECT DISTINCT owner_id FROM access_tokens WHERE owner_type = 'User');
  ```
- [ ] Duplicatas verificadas (COUNT = 0)
  ```sql
  SELECT authentication_token, COUNT(*) FROM users
  GROUP BY authentication_token HAVING COUNT(*) > 1;
  ```
- [ ] Sessões Devise limpas
  ```sql
  TRUNCATE TABLE sessions;
  ```

### Preparação Código
- [ ] Git pull origin
- [ ] Virtual env recriado (`rm -rf .venv && uv venv && uv sync`)
- [ ] Logs anteriores arquivados

---

## EXECUÇÃO (14:00 - 18:00)

### Account 1: Sol Copernico (14:00 - 14:15)
```bash
uv run python app/01_migrar_account.py "Sol Copernico"
uv run python app/02_verificar.py "Sol Copernico"
uv run python app/06_verificar_erros.py "Sol Copernico"
```
- [ ] Migração OK
- [ ] Validação: contagens >= 95%
- [ ] Erros < 5%

### Account 2: Unimed Poços PF (14:30 - 14:50)
```bash
uv run python app/01_migrar_account.py "Unimed Poços PF"
uv run python app/02_verificar.py "Unimed Poços PF"
uv run python app/06_verificar_erros.py "Unimed Poços PF"
```
- [ ] Migração OK
- [ ] Validação: contagens >= 95%
- [ ] Erros < 5%

### Account 3: Unimed Poços PJ (15:05 - 15:30)
```bash
uv run python app/01_migrar_account.py "Unimed Poços PJ"
uv run python app/02_verificar.py "Unimed Poços PJ"
uv run python app/06_verificar_erros.py "Unimed Poços PJ"
```
- [ ] Migração OK
- [ ] Validação: contagens >= 95%
- [ ] Erros < 5%

### Account 4: Unimed Guaxupé (15:50 - 16:10)
```bash
uv run python app/01_migrar_account.py "Unimed Guaxupé"
uv run python app/02_verificar.py "Unimed Guaxupé"
uv run python app/06_verificar_erros.py "Unimed Guaxupé"
```
- [ ] Migração OK
- [ ] Validação: contagens >= 95%
- [ ] Erros < 5%
- [ ] ✅ S3 attachments verificados (já testados em produção)

### Account 5: Vya Digital (16:25 - 18:00) ⚠️ MAIOR
```bash
uv run python app/01_migrar_account.py "Vya Digital"
# Em terminal separado: tail -f logs/Vya_Digital_*.log
uv run python app/02_verificar.py "Vya Digital"
uv run python app/06_verificar_erros.py "Vya Digital"
```
- [ ] Migração OK (monitorar ativamente)
- [ ] Validação: contagens >= 95%
- [ ] Erros < 5%

---

## VALIDAÇÃO FINAL (18:30 - 19:30)

### S3 Attachments (18:30 - 19:00)
```bash
# Vya Digital
uv run python scripts/check_s3_attachments.py \
    --instance chatwoot_prod --account-id <ID> --limit 200 --date-start 2025-01-01

# Unimed Guaxupé
uv run python scripts/check_s3_attachments.py \
    --instance chatwoot_prod --account-id <ID> --limit 100 --date-start 2024-01-01

# Unimed Poços PJ
uv run python scripts/check_s3_attachments.py \
    --instance chatwoot_prod --account-id <ID> --limit 100 --date-start 2024-01-01
```
- [ ] Taxa sucesso >= 95% (recentes 2025-2026)
- [ ] Taxa sucesso >= 25% (históricos 2020-2024) — aceito

### API e Integridade (19:00 - 19:30)
```bash
make validate-api-counts
make validate-api-deep SAMPLE=10
make validate-hash TABLES=contacts,conversations,messages,attachments
```
- [ ] API: exit code 0 ou 2 (warnings OK)
- [ ] API: api_conv >= 80% de db_conv
- [ ] Hash: conversations missing < 5%
- [ ] Hash: messages missing < 5%
- [ ] Hash: contacts missing < 10%

---

## GO/NO-GO (19:30)

### Critérios Mínimos
- [ ] 5/5 accounts migradas
- [ ] Validações API: OK ou warnings aceitos
- [ ] Validações hash: missing < 10%
- [ ] S3: success rate >= 95% (recentes)
- [ ] Zero erros críticos

**Decisão**: ☐ GO ☐ NO-GO

**Responsável**: ___________________________

**Hora**: _________

---

## ROLLBACK (se necessário)

### Rollback Completo
```bash
# 1. Restore backup
pg_restore -h <DEST_HOST> -U <USER> -d <DEST_DB> \
    -c -F c backup_dest_pre_migration_20260516.dump

# 2. Limpar migration_state
psql -h <DEST_HOST> -U <USER> -d <DEST_DB> -c "TRUNCATE TABLE migration_state;"

# 3. Comunicar stakeholders
```

### Rollback Seletivo (1 account)
```sql
BEGIN;
DELETE FROM messages WHERE conversation_id IN (
    SELECT id FROM conversations WHERE account_id = <ID>
    AND created_at >= '2026-05-16 14:00:00'::timestamp
);
DELETE FROM conversations WHERE account_id = <ID>
    AND created_at >= '2026-05-16 14:00:00'::timestamp;
DELETE FROM contact_inboxes WHERE contact_id IN (
    SELECT id FROM contacts WHERE account_id = <ID>
    AND created_at >= '2026-05-16 14:00:00'::timestamp
);
DELETE FROM contacts WHERE account_id = <ID>
    AND created_at >= '2026-05-16 14:00:00'::timestamp;
COMMIT;
```

---

## TROUBLESHOOTING RÁPIDO

### Conexão perdida
```bash
# Script reconecta automaticamente
# Se persistir (>10x): verificar firewall
```

### Migração lenta (< 100 reg/min)
```python
# Editar app/01_migrar_account.py
BATCH = 50  # aumentar para 100
```

### Conversas invisíveis na UI
```sql
-- Adicionar inbox_members manualmente
INSERT INTO inbox_members (inbox_id, user_id, created_at, updated_at)
SELECT i.id, u.id, NOW(), NOW()
FROM inboxes i CROSS JOIN users u
WHERE i.account_id = <ID> AND u.email IN ('user@example.com')
ON CONFLICT DO NOTHING;
```

---

## CONTATOS EMERGÊNCIA

| Papel | Nome | Telefone |
|-------|------|----------|
| Tech Lead | __________ | __________ |
| DBA | __________ | __________ |
| DevOps | __________ | __________ |
| PO | __________ | __________ |

---

**Versão**: 1.0.0 | **Data**: 2026-05-15
