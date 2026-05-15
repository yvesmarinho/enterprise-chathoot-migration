# 🚀 RUNBOOK — Migração Chatwoot para Produção

**Data da Migração**: 16 de maio de 2026 às 14:00 BRT
**Versão**: 1.0.0
**Responsável**: [Nome do Responsável]
**Aprovador**: [Nome do Aprovador]

---

## 📋 RESUMO EXECUTIVO

### Objetivo
Migrar dados das seguintes accounts do Chatwoot SOURCE (`chat.vya.digital`) para o ambiente DEST (produção):

| Account SOURCE | Account ID | Estimativa Registros |
|----------------|------------|---------------------|
| Sol Copernico | 4 | ~5.000 |
| Unimed Poços PF | 18 | ~15.000 |
| Unimed Poços PJ | 17 | ~35.000 |
| Unimed Guaxupé | 25 | ~8.000 |
| Vya Digital | 1 | ~220.000 |

**Total estimado**: ~283.000 registros (contacts, conversations, messages, attachments)

### Estratégia
- **Tipo**: Migração MERGE com deduplicação por chave de negócio
- **Método**: Account-by-account (uma de cada vez)
- **Ordem**: Do menor para o maior (validação progressiva)
- **Rollback**: Backup completo do DEST antes da migração

### Janela de Manutenção
- **Início**: 16/05/2026 14:00 BRT
- **Duração estimada**: 4-6 horas
- **Término previsto**: 16/05/2026 20:00 BRT

---

## ⏱️ CRONOGRAMA DETALHADO

| Horário | Fase | Duração | Responsável |
|---------|------|---------|-------------|
| 13:00 - 13:30 | Checklist pré-migração | 30 min | Ops |
| 13:30 - 14:00 | Backup completo DEST | 30 min | DBA |
| 14:00 - 14:15 | Sol Copernico (account 4) | 15 min | Dev |
| 14:15 - 14:30 | Validação Sol Copernico | 15 min | QA |
| 14:30 - 14:50 | Unimed Poços PF (account 18) | 20 min | Dev |
| 14:50 - 15:05 | Validação Unimed PF | 15 min | QA |
| 15:05 - 15:30 | Unimed Poços PJ (account 17) | 25 min | Dev |
| 15:30 - 15:50 | Validação Unimed PJ | 20 min | QA |
| 15:50 - 16:10 | Unimed Guaxupé (account 25) | 20 min | Dev |
| 16:10 - 16:25 | Validação Unimed Guaxupé | 15 min | QA |
| 16:25 - 18:00 | Vya Digital (account 1) | 90 min | Dev |
| 18:00 - 18:30 | Validação Vya Digital | 30 min | QA |
| 18:30 - 19:00 | Validação S3 attachments | 30 min | Ops |
| 19:00 - 19:30 | Testes integração API | 30 min | QA |
| 19:30 - 20:00 | Go/No-Go e comunicação | 30 min | Gestão |

---

## ✅ CHECKLIST PRÉ-MIGRAÇÃO

### 1. Infraestrutura e Acesso

- [ ] **1.1** Acesso SSH ao servidor de migração (wfdb01 ou wfdb02) confirmado
- [ ] **1.2** Conectividade PostgreSQL SOURCE (`wfdb02.vya.digital:5432`) testada
- [ ] **1.3** Conectividade PostgreSQL DEST (produção) testada
- [ ] **1.4** Credenciais em `.secrets/generate_erd.json` validadas (SOURCE + DEST + API tokens)
- [ ] **1.5** Python 3.12+ e dependências (`psycopg2-binary`) instalados
- [ ] **1.6** Espaço em disco verificado (mínimo 50GB livre para logs/backup)

### 2. Backup e Segurança

- [ ] **2.1** Backup completo do banco DEST realizado
  ```bash
  pg_dump -h <DEST_HOST> -U <USER> -d <DEST_DB> -F c -f backup_dest_pre_migration_20260516.dump
  ```
- [ ] **2.2** Backup verificado (teste de restore em ambiente isolado)
- [ ] **2.3** Snapshot do servidor DEST (se aplicável)
- [ ] **2.4** Plano de rollback documentado e aprovado

### 3. Configurações Críticas (D12)

- [ ] **3.1** ✅ **CRÍTICO** — Regenerar `authentication_token` no DEST
  ```sql
  -- Executar ANTES de iniciar a migração
  UPDATE users
  SET authentication_token = encode(gen_random_bytes(20), 'hex'),
      updated_at = NOW()
  WHERE id IN (
      SELECT DISTINCT owner_id FROM access_tokens WHERE owner_type = 'User'
  );
  ```
- [ ] **3.2** Verificar duplicatas de `authentication_token` (deve retornar 0)
  ```sql
  SELECT authentication_token, COUNT(*)
  FROM users GROUP BY authentication_token HAVING COUNT(*) > 1;
  ```
- [ ] **3.3** ✅ **CRÍTICO** — Limpar sessões Devise antigas no DEST
  ```sql
  -- Evita problemas de autenticação após migração
  DELETE FROM active_storage_blobs WHERE created_at < NOW() - INTERVAL '90 days';
  TRUNCATE TABLE sessions;
  ```
- [ ] **3.4** Confirmar que webhooks/integrações do DEST usam URLs corretas (não apontam para SOURCE)

### 4. Validação do Ambiente SOURCE

- [ ] **4.1** Inspecionar volumes de dados SOURCE por account
  ```bash
  uv run python app/00_inspecionar.py "Sol Copernico"
  uv run python app/00_inspecionar.py "Unimed Poços PF"
  uv run python app/00_inspecionar.py "Unimed Poços PJ"
  uv run python app/00_inspecionar.py "Unimed Guaxupé"
  uv run python app/00_inspecionar.py "Vya Digital"
  ```
- [ ] **4.2** Verificar contatos com phone duplicado no SOURCE (colisão A-03)
  ```sql
  -- chatwoot_dev1_db (SOURCE)
  SELECT phone_number, COUNT(*) AS n, array_agg(id) AS ids
  FROM contacts
  WHERE account_id IN (1,4,17,18,25) AND phone_number IS NOT NULL
  GROUP BY phone_number HAVING COUNT(*) > 1
  ORDER BY n DESC LIMIT 20;
  ```
- [ ] **4.3** Verificar conversas órfãs (contact_id = NULL) no SOURCE
  ```sql
  SELECT account_id, COUNT(*) FROM conversations
  WHERE account_id IN (1,4,17,18,25) AND contact_id IS NULL
  GROUP BY account_id;
  ```

### 5. Preparação do Código

- [ ] **5.1** Branch de produção atualizado (`git pull origin 001-enterprise-chatwoot-migration`)
- [ ] **5.2** Virtual environment recriado (`rm -rf .venv && uv venv && uv sync`)
- [ ] **5.3** Testes unitários executados (se existirem)
  ```bash
  uv run pytest tests/
  ```
- [ ] **5.4** Logs de migração anterior arquivados
  ```bash
  mkdir -p logs/archive/$(date +%Y%m%d)
  mv logs/*.jsonl logs/archive/$(date +%Y%m%d)/ 2>/dev/null || true
  ```

### 6. Comunicação

- [ ] **6.1** Notificação enviada aos usuários finais (manutenção programada)
- [ ] **6.2** Canal de comunicação da equipe ativo (Slack/Teams/Discord)
- [ ] **6.3** Contatos de emergência confirmados
- [ ] **6.4** Stakeholders avisados (início da janela de manutenção)

---

## 🚀 PROCEDIMENTO DE EXECUÇÃO

### FASE 1 — Sol Copernico (Account 4) [14:00 - 14:15]

#### 1.1 Executar Migração
```bash
cd /path/to/enterprise-chathoot-migration
source .venv/bin/activate  # ou use: uv run

# Migração
uv run python app/01_migrar_account.py "Sol Copernico"
```

**Saídas esperadas**:
- Log em `logs/Sol_Copernico_YYYYMMDD_HHMMSS.log`
- Erros (se houver) em `logs/erros_Sol_Copernico.jsonl`
- Mensagem final: `✅ Migração concluída: Sol Copernico`

#### 1.2 Validação Imediata
```bash
# Contagens SOURCE vs DEST
uv run python app/02_verificar.py "Sol Copernico"

# Verificar erros (se houver)
uv run python app/06_verificar_erros.py "Sol Copernico"
```

**Critérios de Go/No-Go**:
- ✅ Contagens DEST >= 95% das contagens SOURCE
- ✅ Nenhum erro crítico em `erros_*.jsonl` (reconexões são OK)
- ✅ Mensagens órfãs = 0 ou < 1% do total
- ✅ `content_attributes` não-nulo = 0

**Ação se No-Go**: Investigar erro, corrigir e re-executar (script é idempotente)

---

### FASE 2 — Unimed Poços PF (Account 18) [14:30 - 14:50]

Repetir FASE 1 substituindo "Sol Copernico" por "Unimed Poços PF"

```bash
uv run python app/01_migrar_account.py "Unimed Poços PF"
uv run python app/02_verificar.py "Unimed Poços PF"
uv run python app/06_verificar_erros.py "Unimed Poços PF"
```

---

### FASE 3 — Unimed Poços PJ (Account 17) [15:05 - 15:30]

Repetir FASE 1 substituindo por "Unimed Poços PJ"

```bash
uv run python app/01_migrar_account.py "Unimed Poços PJ"
uv run python app/02_verificar.py "Unimed Poços PJ"
uv run python app/06_verificar_erros.py "Unimed Poços PJ"
```

---

### FASE 4 — Unimed Guaxupé (Account 25) [15:50 - 16:10]

**⚠️ NOTA IMPORTANTE**: Teste de attachments na produção confirmou que **todos os arquivos S3 estão acessíveis** para este account.

```bash
uv run python app/01_migrar_account.py "Unimed Guaxupé"
uv run python app/02_verificar.py "Unimed Guaxupé"
uv run python app/06_verificar_erros.py "Unimed Guaxupé"
```

**Validação adicional S3** (após migração):
```bash
uv run python scripts/check_s3_attachments.py \
    --instance chatwoot_prod \
    --account-id <DEST_ACCOUNT_ID> \
    --limit 100 \
    --date-start 2025-01-01
```

---

### FASE 5 — Vya Digital (Account 1) [16:25 - 18:00]

**⚠️ ACCOUNT MAIOR** — ~220.000 registros. Monitorar progresso ativamente.

```bash
# Migração (duração estimada: 60-90 min)
uv run python app/01_migrar_account.py "Vya Digital"

# Validação
uv run python app/02_verificar.py "Vya Digital"
uv run python app/06_verificar_erros.py "Vya Digital"
```

**Monitoramento durante execução**:
```bash
# Em terminal separado
tail -f logs/Vya_Digital_*.log
```

**Sinais de problema**:
- ❌ Loop parado (sem novas linhas por > 5 min em fase de messages)
- ❌ Erros de conexão repetidos (> 10 reconexões na mesma conversa)
- ❌ `psycopg2.OperationalError` persistente

**Ação corretiva**: Interromper (Ctrl+C), investigar, ajustar BATCH size se necessário, re-executar.

---

### FASE 6 — Validação S3 Global [18:30 - 19:00]

```bash
# Account 1 (Vya Digital)
uv run python scripts/check_s3_attachments.py \
    --instance chatwoot_prod \
    --account-id <ACCOUNT_1_DEST_ID> \
    --limit 200 \
    --date-start 2025-01-01

# Account 25 (Unimed Guaxupé)
uv run python scripts/check_s3_attachments.py \
    --instance chatwoot_prod \
    --account-id <ACCOUNT_25_DEST_ID> \
    --limit 100 \
    --date-start 2024-01-01

# Account 17 (Unimed Poços PJ)
uv run python scripts/check_s3_attachments.py \
    --instance chatwoot_prod \
    --account-id <ACCOUNT_17_DEST_ID> \
    --limit 100 \
    --date-start 2024-01-01
```

**Critério de sucesso**:
- ✅ Taxa de sucesso >= 95% para attachments recentes (2025-2026)
- ✅ Taxa de sucesso >= 25% para attachments históricos (2020-2024) — aceito (S3 retention policy)
- ✅ Nenhum attachment com erro HTTP 500 (erro de servidor)

**Outputs**: Relatórios JSON em `.tmp/check_s3_attachments_*.json`

---

### FASE 7 — Validação API e Integridade [19:00 - 19:30]

#### 7.1 Validação API (D5)

```bash
# Contagens macro
make validate-api-counts

# Deep scan (amostra)
make validate-api-deep SAMPLE=10
```

**Critérios de sucesso**:
- ✅ Exit code = 0 (all OK) ou 2 (warnings aceitos)
- ✅ `api_conv` >= 80% de `db_conv` (visibilidade API aceitável)
- ✅ Nenhum erro HTTP 500 na API
- ✅ Orphan messages < 5% do total (aceito se pré-existente)

#### 7.2 Validação Hash MD5 (D6)

```bash
make validate-hash TABLES=contacts,conversations,messages,attachments
```

**Critérios de sucesso**:
- ✅ Conversations: missing < 5%, extra = 0
- ✅ Messages: missing < 5%, extra = 0
- ✅ Contacts: missing < 10% (aceito devido a colisões de dedup)
- ✅ Attachments: missing < 30% (aceito devido a S3 retention)

**Outputs**: Relatórios JSON em `.tmp/validacao_hash_*.json`

---

## 🔄 PLANO DE ROLLBACK

### Cenário 1 — Falha Durante a Migração (antes de completar)

**Ação**: Interromper execução (Ctrl+C) e decidir:

#### Opção A — Continuar (se <= 20% de erros)
```bash
# Script é idempotente — re-executar
uv run python app/01_migrar_account.py "<Account Name>"
```

#### Opção B — Rollback Completo
```bash
# 1. Restore do backup
pg_restore -h <DEST_HOST> -U <USER> -d <DEST_DB> \
    -c -F c backup_dest_pre_migration_20260516.dump

# 2. Verificar integridade pós-restore
psql -h <DEST_HOST> -U <USER> -d <DEST_DB> -c "
    SELECT tablename, n_live_tup FROM pg_stat_user_tables
    WHERE schemaname = 'public' AND n_live_tup > 0
    ORDER BY n_live_tup DESC LIMIT 20;
"

# 3. Limpar migration_state (se existir)
psql -h <DEST_HOST> -U <USER> -d <DEST_DB> -c "TRUNCATE TABLE migration_state;"

# 4. Comunicar rollback aos stakeholders
```

**Duração estimada**: 30-45 min

---

### Cenário 2 — Problemas Pós-Migração (descobertos após 2h)

**Sintomas**:
- Conversas invisíveis para usuários
- Attachments com 404 em massa (> 50%)
- Erros de autenticação generalizados

**Ação**:

#### 2.1 Análise Rápida
```sql
-- Conversas migradas com problemas
SELECT status, COUNT(*) FROM conversations
WHERE created_at >= '2026-05-16 14:00:00'::timestamp
GROUP BY status;

-- Attachments com problemas
SELECT COUNT(*) FILTER (WHERE file_type IS NULL) AS sem_tipo,
       COUNT(*) FILTER (WHERE account_id IS NULL) AS sem_account
FROM attachments
WHERE created_at >= '2026-05-16 14:00:00'::timestamp;
```

#### 2.2 Rollback Seletivo (se < 3 accounts afetadas)
```sql
-- Deletar registros migrados de UMA account
BEGIN;

DELETE FROM messages WHERE conversation_id IN (
    SELECT id FROM conversations
    WHERE account_id = <DEST_ACCOUNT_ID>
      AND created_at >= '2026-05-16 14:00:00'::timestamp
);

DELETE FROM conversations
WHERE account_id = <DEST_ACCOUNT_ID>
  AND created_at >= '2026-05-16 14:00:00'::timestamp;

DELETE FROM contact_inboxes
WHERE contact_id IN (
    SELECT id FROM contacts
    WHERE account_id = <DEST_ACCOUNT_ID>
      AND created_at >= '2026-05-16 14:00:00'::timestamp
);

DELETE FROM contacts
WHERE account_id = <DEST_ACCOUNT_ID>
  AND created_at >= '2026-05-16 14:00:00'::timestamp;

-- COMMIT apenas se tudo estiver OK
COMMIT;
```

#### 2.3 Rollback Total (se >= 3 accounts afetadas)
Usar procedimento do Cenário 1 - Opção B.

---

## 🔧 TROUBLESHOOTING

### Problema 1: "psycopg2.OperationalError: connection already closed"

**Causa**: Timeout de conexão PostgreSQL durante migração longa.

**Solução**:
```bash
# Script já tem lógica de reconexão automática
# Se persistir (> 10 reconexões), verificar firewall/network

# Ajustar timeout no servidor (temporário)
psql -h <DEST_HOST> -U <USER> -d <DEST_DB> -c "
    ALTER SYSTEM SET statement_timeout = '600s';
    SELECT pg_reload_conf();
"
```

---

### Problema 2: "Migração muito lenta (< 100 registros/min)"

**Causa**: BATCH size muito pequeno ou índices ausentes.

**Solução**:
```python
# Editar app/01_migrar_account.py
BATCH = 50  # aumentar de 30 para 50 ou 100

# Re-executar (script é idempotente)
```

---

### Problema 3: "Conversas migradas não aparecem na UI do Chatwoot"

**Causa provável**: Permissões de `inbox_members` ausentes.

**Diagnóstico**:
```sql
-- Verificar se usuário tem acesso aos inboxes migrados
SELECT u.email, i.name AS inbox_name, im.id AS inbox_member_id
FROM users u
LEFT JOIN inbox_members im ON im.user_id = u.id
LEFT JOIN inboxes i ON i.id = im.inbox_id
WHERE u.email = 'usuario@exemplo.com'
  AND i.account_id = <DEST_ACCOUNT_ID>;
```

**Solução**:
```bash
# Migrar inbox_members (ainda não implementado no pipeline principal)
# Ver TODO.md: S11-P0-1

# Workaround manual:
psql -h <DEST_HOST> -U <USER> -d <DEST_DB> -c "
    INSERT INTO inbox_members (inbox_id, user_id, created_at, updated_at)
    SELECT i.id, u.id, NOW(), NOW()
    FROM inboxes i
    CROSS JOIN users u
    WHERE i.account_id = <DEST_ACCOUNT_ID>
      AND u.email IN ('user1@example.com', 'user2@example.com')
    ON CONFLICT DO NOTHING;
"
```

---

### Problema 4: "Attachments com HTTP 404 em massa (> 50%)"

**Causa**: Bucket S3 incorreto ou credenciais de acesso inválidas.

**Diagnóstico**:
```bash
# Verificar bucket no DEST
psql -h <DEST_HOST> -U <USER> -d <DEST_DB> -c "
    SELECT DISTINCT
        SUBSTRING(file_url FROM 'https://([^/]+)/') AS bucket
    FROM attachments
    WHERE account_id = <DEST_ACCOUNT_ID>
    LIMIT 10;
"

# Testar acesso a um attachment específico
curl -I "https://assets-chat-vya-digital.s3.amazonaws.com/<BLOB_KEY>"
```

**Solução**:
- Se bucket errado: atualizar configuração do Chatwoot
- Se S3 inacessível: verificar IAM roles/policies
- Se arquivos realmente ausentes: decisão de negócio (aceitar ou re-upload)

---

### Problema 5: "Exit code 2 no validate-api (orphan_messages > 0)"

**Causa**: Mensagens órfãs pré-existentes no DEST (não causadas pela migração).

**Verificação**:
```sql
-- Checar se orphan_messages são pré-migração
SELECT COUNT(*) FROM messages m
LEFT JOIN conversations c ON c.id = m.conversation_id
WHERE m.created_at >= '2026-05-16 14:00:00'::timestamp
  AND c.id IS NULL;
```

**Decisão**:
- Se orphans são pré-migração: **ACEITAR** (exit code 2 é warning, não erro)
- Se orphans são pós-migração: **INVESTIGAR** e possivelmente rollback

---

## 📊 CRITÉRIOS DE SUCESSO FINAL

| Métrica | Target | Aceitável | Crítico |
|---------|--------|-----------|---------|
| **Migração completa** | 5/5 accounts | 4/5 accounts | < 3/5 accounts |
| **Contagens DB** | 100% SOURCE → DEST | >= 95% | < 90% |
| **Visibilidade API** | 100% | >= 80% | < 70% |
| **Attachments S3 (recentes)** | 100% OK | >= 95% OK | < 90% OK |
| **Attachments S3 (históricos)** | 50% OK | >= 25% OK | < 10% OK |
| **Erros críticos** | 0 | 0 | > 0 |
| **Tempo total** | < 5h | < 6h | > 8h |

---

## 📞 CONTATOS E RESPONSÁVEIS

| Papel | Nome | Contato | Disponibilidade |
|-------|------|---------|-----------------|
| **Tech Lead** | [Nome] | [Email/Telefone] | 13:00 - 21:00 |
| **DBA** | [Nome] | [Email/Telefone] | 13:00 - 21:00 |
| **DevOps** | [Nome] | [Email/Telefone] | 13:00 - 21:00 |
| **QA Lead** | [Nome] | [Email/Telefone] | 14:00 - 20:00 |
| **Product Owner** | [Nome] | [Email/Telefone] | On-call |
| **Suporte N3** | [Nome] | [Email/Telefone] | On-call |

---

## 📝 LOG DE EXECUÇÃO

**Instruções**: Preencher em tempo real durante a execução.

| Horário | Fase | Status | Observações |
|---------|------|--------|-------------|
| 13:00 | Checklist pré-migração iniciado | ⏳ | |
| 13:30 | Backup DEST iniciado | ⏳ | |
| 14:00 | Sol Copernico iniciado | ⏳ | |
| 14:15 | Sol Copernico validação | ⏳ | |
| 14:30 | Unimed PF iniciado | ⏳ | |
| ... | ... | ... | |

**Status**: ⏳ Em progresso | ✅ Concluído | ⚠️ Com avisos | ❌ Erro

---

## 🎯 GO/NO-GO FINAL (19:30)

**Decisor**: [Nome do Product Owner/Tech Lead]

### Checklist Go-Live

- [ ] Todas as 5 accounts migradas com sucesso
- [ ] Validações API: exit code 0 ou 2 (warnings aceitos)
- [ ] Validações hash: missing < 10%
- [ ] Validações S3: success rate >= 95% (recentes)
- [ ] Nenhum erro crítico registrado
- [ ] Testes manuais de login e navegação: OK
- [ ] Stakeholders notificados

**Decisão**: ☐ GO ☐ NO-GO

**Justificativa**:
```
[Preencher com justificativa detalhada da decisão]
```

**Próximos passos (se GO)**:
1. Comunicar término da manutenção aos usuários
2. Monitoramento intensivo por 48h
3. Post-mortem agendado para [data]

**Próximos passos (se NO-GO)**:
1. Executar rollback imediato (Cenário 1 - Opção B)
2. Investigação de causa raiz
3. Reagendamento da migração para [data]

---

## 📚 REFERÊNCIAS

- [README.md](../README.md) — Documentação geral do projeto
- [docs/TODO.md](TODO.md) — Tarefas e bloqueadores conhecidos
- [docs/debates/D12-ANALISE-CRITICA-LOGICA-NEGOCIO-FLUXO-DADOS-2026-04-24.md](debates/D12-ANALISE-CRITICA-LOGICA-NEGOCIO-FLUXO-DADOS-2026-04-24.md) — Análise de riscos
- [docs/debates/D15-DEBATE-MIGRACAO-S3-INCOMPLETA-2026-05-13.md](debates/D15-DEBATE-MIGRACAO-S3-INCOMPLETA-2026-05-13.md) — Validação S3

---

**Versão**: 1.0.0
**Data de criação**: 2026-05-15
**Última atualização**: 2026-05-15
**Aprovado por**: [Nome e Assinatura]
