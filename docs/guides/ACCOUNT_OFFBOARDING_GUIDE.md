# 🗑️ Guia Operacional — Account Offboarding Chatwoot

**Versão**: 1.0.0  
**Data**: 2026-05-24  
**Projeto**: enterprise-chatwoot-migration

---

## 📋 Visão Geral

Este guia documenta o processo operacional de **offboarding completo de accounts Chatwoot** — desde auditoria até remoção permanente de dados. Aplica-se a:

- ✅ Término de contrato com cliente
- ✅ Remoção de dados LGPD/GDPR
- ✅ Limpeza de migrações incorretas
- ✅ Remoção de accounts de teste em ambientes DEV

---

## ⚠️ Considerações Legais e de Compliance

### LGPD/GDPR
- Remoção de dados pessoais deve seguir política interna de retenção
- Manter evidências de remoção (outputs JSON da ferramenta)
- Confirmar com jurídico/compliance antes de deletar dados de produção

### Contrato e SLA
- Verificar prazo de retenção contratual antes de executar
- Notificar cliente sobre remoção iminente (se aplicável)
- Backup preventivo para janela de recuperação (se política exigir)

### Auditoria
- Salvar outputs JSON em local seguro
- Registrar ticket/chamado com justificativa e aprovação
- Documentar quem executou, quando, e qual account_id

---

## 🔧 Ferramental

**Localização**: `tools/account_offboarding/`

| Script | Função | Output |
|--------|--------|--------|
| `inspect.py` | Auditoria read-only (quantas linhas por tabela) | JSON: `<db_key>_account_<id>_audit_YYYYMMDD_HHMMSS.json` |
| `cleanup.py` | Remoção completa (DELETE com confirmação interativa) | JSON: `<db_key>_account_<id>_cleanup_YYYYMMDD_HHMMSS.json` |

**Documentação completa**: [`tools/account_offboarding/README.md`](../../tools/account_offboarding/README.md)

---

## 📊 Workflow Operacional

### Fase 1: Preparação

#### 1.1. Confirmar account_id
```sql
-- Conectar ao banco (via psql, DBeaver, etc.)
SELECT id, name FROM accounts WHERE id = 999;
```

**Validar:**
- ✅ ID está correto
- ✅ Nome do cliente corresponde
- ✅ Não há confusão com outro account

#### 1.2. Verificar dependências ativas
```sql
-- Última atividade
SELECT MAX(created_at) AS ultima_msg FROM messages WHERE account_id = 999;
SELECT MAX(created_at) AS ultima_conv FROM conversations WHERE account_id = 999;

-- Usuários ativos
SELECT u.email FROM users u
JOIN account_users au ON au.user_id = u.id
WHERE au.account_id = 999;
```

**Alertas:**
- 🔴 Se `ultima_msg` ou `ultima_conv` for recente (< 30 dias) → **REVALIDAR** com solicitante
- 🔴 Se usuários ativos > 0 → **CONFIRMAR** que desativação foi feita

#### 1.3. Preparar configuração

```bash
cd tools/account_offboarding

# Copiar template
cp config.json.example config.json

# Editar
vim config.json
```

**config.json:**
```json
{
  "db_key": "synchat-vya-digital",
  "account_id": 999,
  "secrets_file": "../../.secrets/generate_erd.json"
}
```

---

### Fase 2: Auditoria (Read-Only)

#### 2.1. Executar inspect.py

```bash
uv run python inspect.py --config config.json
```

**ou via CLI direto:**
```bash
uv run python inspect.py --db-key synchat-vya-digital --account-id 999
```

#### 2.2. Revisar output

**Terminal:**
```
[inspect] Conectando a 'synchat-vya-digital'…
[inspect] Banco: chatwoot004_db  |  account_id: 999
[inspect] 48 tabelas com coluna account_id…

[inspect] 18 tabelas com dados do account 999:
  messages                    : 12,450
  attachments                 : 234
  reporting_events            : 8,921
  contact_inboxes             : 1,876
  conversations               : 1,523
  contacts                    : 987
  working_hours               : 42
  notification_settings       : 15
  inboxes                     : 7
  agent_bot_inboxes           : 3
  inbox_members               : 12
  team_memberships            : 5
  teams                       : 2
  canned_responses            : 18
  labels                      : 9
  webhooks                    : 2
  account_users               : 4
  campaigns                   : 1

[inspect] Total de linhas: 26,109
[inspect] Relatório salvo em: synchat-vya-digital_account_999_audit_20260524_143022.json
```

**JSON gerado:**
```json
{
  "db_key": "synchat-vya-digital",
  "database": "chatwoot004_db",
  "account_id": 999,
  "timestamp": "2026-05-24T14:30:22",
  "tables_with_data": {
    "messages": {"count": 12450, "strategy": "direct"},
    "attachments": {"count": 234, "strategy": "direct"},
    ...
  },
  "total_rows": 26109
}
```

#### 2.3. Validação da auditoria

**Checklist:**
- [ ] Total de linhas é compatível com tamanho esperado do cliente
- [ ] Tabelas críticas (`messages`, `conversations`, `contacts`) aparecem na lista
- [ ] JSON foi salvo e pode ser anexado ao ticket/chamado
- [ ] Não há sinais de dados ativos recentes (validar via SQL se necessário)

**⚠️ Se total_rows > 1 milhão** → considerar backup seletivo antes de prosseguir.

---

### Fase 3: Dry-Run (Simulação)

#### 3.1. Executar cleanup.py --dry-run

```bash
uv run python cleanup.py --db-key synchat-vya-digital --account-id 999 --dry-run
```

#### 3.2. Revisar output

**Terminal:**
```
[dry-run] Conectando a 'synchat-vya-digital' (READ-ONLY)…
[dry-run] Banco: chatwoot004_db  |  account_id: 999

[dry-run] Pré-contagem (42 tabelas):
  messages                    : 12,450
  attachments                 : 234
  reporting_events            : 8,921
  mentions                    : 0
  conversation_participants   : 0
  csat_survey_responses       : 127
  applied_slas                : 0
  sla_events                  : 0
  contact_inboxes             : 1,876
  conversations               : 1,523
  contacts                    : 987
  agent_bot_inboxes           : 3
  inbox_members               : 12
  working_hours               : 42
  channel_api                 : 0
  channel_whatsapp            : 5
  channel_web_widgets         : 2
  channel_email               : 0
  channel_facebook_pages      : 0
  channel_telegram            : 0
  channel_sms                 : 0
  channel_twilio_sms          : 0
  channel_line                : 0
  channel_twitter_profiles    : 0
  inboxes                     : 7
  agent_bots                  : 0
  notification_settings       : 15
  notifications               : 0
  team_memberships            : 5
  teams                       : 2
  portal_members              : 0
  categories                  : 0
  articles                    : 0
  folders                     : 0
  portals                     : 0
  labels                      : 9
  canned_responses            : 18
  automation_rules            : 0
  macros                      : 0
  campaigns                   : 1
  dashboard_apps              : 0
  custom_attribute_definitions: 0
  custom_filters              : 0
  custom_roles                : 0
  data_imports                : 0
  email_templates             : 0
  sla_policies                : 0
  webhooks                    : 2
  integrations_hooks          : 0
  telegram_bots               : 0
  account_users               : 4
  accounts                    : 1

[dry-run] Total a deletar: 26,246 linhas

[dry-run] ✅ Nenhuma modificação feita (dry-run).
[dry-run] Relatório salvo em: synchat-vya-digital_account_999_cleanup_20260524_143245.json
```

#### 3.3. Validação do dry-run

**Checklist:**
- [ ] Total no dry-run (~26.246) é compatível com inspect (~26.109)
- [ ] Diferença é apenas a linha em `accounts` (inspect não conta, cleanup sim)
- [ ] JSON de dry-run foi salvo
- [ ] Não há tabelas inesperadas com valores muito altos

**⚠️ Se discrepância > 5%** → investigar via `inspect.py` novamente.

---

### Fase 4: Aprovação

#### 4.1. Documentar evidências

**Anexar ao ticket/chamado:**
- ✅ Output do `inspect.py` (JSON + print screen do terminal)
- ✅ Output do `cleanup.py --dry-run` (JSON + print screen)
- ✅ SQL de verificação de última atividade
- ✅ Justificativa (término contrato, LGPD, etc.)

#### 4.2. Obter aprovações necessárias

**Roles típicos (adaptar à política interna):**
- ✅ Gestor do projeto/produto
- ✅ Jurídico/Compliance (se dados de produção)
- ✅ DBA sênior ou Tech Lead (se ambiente PROD)

#### 4.3. Confirmar janela de execução

- ✅ Horário de menor impacto (fora de pico)
- ✅ Não há manutenções programadas conflitantes
- ✅ Equipe de suporte está ciente (caso cliente entre em contato)

---

### Fase 5: Execução

#### 5.1. Preparar ambiente

**Se PROD:**
```bash
# Opcional: snapshot do banco ANTES (via infra/DBA)
# Ex: AWS RDS snapshot, PostgreSQL pg_dump seletivo, etc.
```

**Confirmar conexão:**
```bash
# Testar que secrets file está correto
uv run python inspect.py --db-key synchat-vya-digital --account-id 999 | head -n 5
```

#### 5.2. Executar cleanup.py --execute

```bash
uv run python cleanup.py --db-key synchat-vya-digital --account-id 999 --execute
```

**Confirmação interativa:**
```
═══════════════════════════════════════════════════════════════
⚠️  CONFIRMAÇÃO OBRIGATÓRIA ⚠️
═══════════════════════════════════════════════════════════════

Você está prestes a DELETAR PERMANENTEMENTE todos os dados de:

  DATABASE    : chatwoot004_db
  ACCOUNT_ID  : 999
  TOTAL LINHAS: 26,246

Esta operação NÃO pode ser desfeita.

Digite o account_id (999) para confirmar, ou CTRL+C para cancelar:
```

**Digite `999` e pressione Enter.**

#### 5.3. Acompanhar execução

**Output esperado:**
```
[execute] SET SESSION default_transaction_read_only = off
[execute] Executando 42 operações DELETE…
  ✓ messages                    : 12,450 linhas deletadas
  ✓ attachments                 : 234 linhas deletadas
  ✓ reporting_events            : 8,921 linhas deletadas
  ...
  ✓ account_users               : 4 linhas deletadas
  ✓ accounts                    : 1 linhas deletadas

[execute] Total deletado: 26,246 linhas
[execute] Pós-verificação (tudo deve ser 0):
  messages                    : 0
  attachments                 : 0
  reporting_events            : 0
  ...
  accounts                    : 0

[execute] ✅ COMMIT executado com sucesso.
[execute] Relatório salvo em: synchat-vya-digital_account_999_cleanup_20260524_143520.json
```

**Validação imediata:**
- ✅ Todas as pós-verificações mostram `0`
- ✅ `COMMIT executado com sucesso` apareceu
- ✅ JSON foi salvo

**⚠️ Se aparecer erro:**
```
[execute] ❌ ERRO durante execução:
[execute] psycopg2.errors.ForeignKeyViolation: update or delete on table "X" violates foreign key constraint "Y"
[execute] ❌ ROLLBACK executado.
```

**Ação:** Investigar tabela/FK não coberta no `_STEPS` de `cleanup.py`. **NÃO reexecutar** sem análise. Contatar desenvolvedor da ferramenta.

---

### Fase 6: Validação Pós-Execução

#### 6.1. Executar inspect.py novamente

```bash
uv run python inspect.py --db-key synchat-vya-digital --account-id 999
```

**Output esperado:**
```
[inspect] 0 tabelas com dados do account 999
[inspect] Total de linhas: 0
```

**Se output != 0:**
- 🔴 **ALERTA CRÍTICO** — Dados residuais detectados
- Investigar quais tabelas ainda têm dados
- Possivelmente FK não coberta ou estratégia de busca falhou
- **NÃO encerrar** sem resolução

#### 6.2. Validação SQL direta

```sql
-- Confirmar account não existe mais
SELECT * FROM accounts WHERE id = 999;
-- Resultado esperado: 0 rows

-- Spot checks em tabelas principais
SELECT COUNT(*) FROM messages WHERE account_id = 999;
SELECT COUNT(*) FROM conversations WHERE account_id = 999;
SELECT COUNT(*) FROM contacts WHERE account_id = 999;
SELECT COUNT(*) FROM inboxes WHERE account_id = 999;
-- Todos devem retornar 0

-- FK-based tables (usar mesma lógica do cleanup.py)
SELECT COUNT(*) FROM contact_inboxes WHERE contact_id IN (SELECT id FROM contacts WHERE account_id = 999);
-- Deve retornar 0
```

#### 6.3. Arquivar evidências

**Salvar em local seguro:**
- ✅ JSON do `inspect.py` pré-cleanup
- ✅ JSON do `cleanup.py --dry-run`
- ✅ JSON do `cleanup.py --execute`
- ✅ JSON do `inspect.py` pós-cleanup (confirmando 0)
- ✅ Print screens de terminal (opcional mas recomendado)
- ✅ Ticket/chamado com aprovações

**Nomenclatura sugerida:**
```
evidencias_offboarding_account999_20260524/
├── 01_inspect_pre.json
├── 02_cleanup_dryrun.json
├── 03_cleanup_execute.json
├── 04_inspect_post.json
└── 05_aprovacoes.pdf
```

---

## 🔒 Segurança e Controles

### Proteções Implementadas na Ferramenta

| Proteção | Descrição |
|----------|-----------|
| **Read-only default** | `inspect.py` usa `set_session(readonly=True, autocommit=True)` |
| **Transaction safety** | `cleanup.py` usa transação única — ROLLBACK automático em erro |
| **Interactive confirmation** | Usuário deve digitar `account_id` para prosseguir |
| **Dry-run obrigatório** | Workflow recomenda sempre executar `--dry-run` antes de `--execute` |
| **Post-verification** | Após DELETE, recontagem confirma 0 linhas (detecta FKs esquecidas) |
| **Audit trail** | Todos os outputs salvos em JSON com timestamp |

### Restrições de Permissão

**Role PostgreSQL `migration_user`:**
- `default_transaction_read_only = on` (segurança padrão)
- `cleanup.py` executa `SET SESSION default_transaction_read_only = off` antes de DELETEs
- Apenas usuários com este role podem executar a ferramenta

**Secrets file:**
- `.secrets/generate_erd.json` contém credenciais
- **NUNCA versionado** (`.gitignore` global do projeto)
- Acesso restrito (file permissions `600` recomendado)

---

## 🐛 Troubleshooting

### Problema 1: "cannot execute DELETE in a read-only transaction"

**Causa:** Role `migration_user` tem `default_transaction_read_only = on`

**Solução:** Já implementada no `cleanup.py` (linha ~150):
```python
cur.execute("SET SESSION default_transaction_read_only = off")
conn.commit()
```

Se erro persistir, verificar se usuário tem permissão para alterar session param.

---

### Problema 2: "ForeignKeyViolation" durante cleanup

**Causa:** Tabela com FK não coberta em `_STEPS`, ou ordem de deleção incorreta

**Diagnóstico:**
1. Ler mensagem de erro — identifica tabela/constraint
2. Verificar se tabela está em `_STEPS` de `cleanup.py`
3. Verificar ordem (tabela dependente deve vir ANTES da pai)

**Correção:**
1. Adicionar entrada em `_STEPS` na posição correta
2. Reexecutar `--dry-run` para confirmar
3. Abrir issue/ticket para manutenção da ferramenta

**⚠️ NUNCA ignorar FK violation** — pode indicar integridade referencial comprometida.

---

### Problema 3: inspect.py mostra 0, mas cleanup encontra linhas

**Causa conhecida:** Tabela `accounts` usa coluna `id`, não `account_id`. `inspect.py` não encontra, mas `cleanup.py` sim.

**Impacto:** Diferença de ~1 linha (a própria linha da tabela `accounts`). **Esperado**.

**Outro caso:** FK-based tables onde `inspect.py` não descobriu a FK automaticamente.

**Solução:** Confiar no `cleanup.py` (mais completo). Se discrepância > 10%, investigar via SQL manual.

---

### Problema 4: Timeout em bancos grandes

**Sintoma:** Processo trava ou timeout após 30s–60s

**Causa:** Account muito grande (> 1 milhão de linhas), DELETE lento

**Solução 1 (curto prazo):**
```python
# Em cleanup.py, aumentar statement_timeout
cur.execute("SET statement_timeout = '600s'")  # 10 minutos
```

**Solução 2 (longo prazo):**
- Deletar em lotes (LIMIT 10000, loop)
- Usar `DELETE ... RETURNING id` para tracking
- Considerar `TRUNCATE` se tabela puder ser esvaziada completamente (não aplicável aqui)

---

### Problema 5: JSON com encoding incorreto

**Sintoma:** Caracteres especiais aparecem como `\uXXXX`

**Causa:** `ensure_ascii=True` (default do `json.dump`)

**Solução (já implementada):**
```python
json.dump(result, f, indent=2, default=str, ensure_ascii=False)
```

Se caracteres ainda aparecem errados, verificar encoding do terminal (`export LANG=pt_BR.UTF-8`).

---

## 📊 Métricas e KPIs

### Tempo de Execução (estimativas)

| Tamanho do Account | Linhas Totais | Tempo Inspect | Tempo Cleanup |
|-------------------|---------------|---------------|---------------|
| Pequeno (teste)    | < 1.000       | < 5s          | < 10s         |
| Médio (cliente SMB)| 1.000–50.000  | 5s–15s        | 10s–60s       |
| Grande (cliente enterprise) | 50.000–500.000 | 15s–60s | 1min–5min |
| Muito grande       | > 500.000     | > 60s         | > 5min        |

**Nota:** Tempos variam com carga do banco, índices, etc.

### Evidências de Execução (Sessão 23)

| Account ID | DB | Linhas | Tempo Cleanup | Status |
|------------|-----|--------|---------------|--------|
| 44         | chatwoot004_dev1_db | 864 | ~8s | ✅ COMMIT OK (dev test) |
| 45         | chatwoot004_db | 2.339 | ~15s | ✅ COMMIT OK (prod cleanup) |

---

## 🔄 Ciclo de Vida da Ferramenta

### Versão Atual: 1.0.0

**Criada em:** 2026-05-24 (Sessão 23)  
**Testada contra:** Chatwoot schema v3.x, PostgreSQL 16.10

### Roadmap

**v1.1.0 (futuro):**
- [ ] Suporte a deleção em lotes para accounts > 1M linhas
- [ ] Modo `--force` (skip confirmação interativa, para automação CI/CD)
- [ ] Output em formato CSV além de JSON
- [ ] Integração com sistemas de auditoria/SIEM

**v1.2.0 (futuro):**
- [ ] Suporte a rollback via backup seletivo (restaurar account deletado)
- [ ] Dashboard web para visualizar auditoria antes de deletar
- [ ] Dry-run com análise de impacto (ex: quantos usuários perdem acesso)

### Manutenção

**Responsável:** Equipe de DevOps/Data Engineering  
**Ciclo de revisão:** A cada upgrade major do Chatwoot (verificar novas tabelas)

**Quando atualizar `cleanup.py`:**
- ✅ Nova versão do Chatwoot adiciona tabelas com `account_id`
- ✅ Schema migration adiciona novas FKs para `accounts`, `inboxes`, `conversations`, etc.
- ✅ Bug report de FK violation não coberta

---

## 📚 Referências

- **README da ferramenta**: [`tools/account_offboarding/README.md`](../../tools/account_offboarding/README.md)
- **Código fonte**: [`tools/account_offboarding/inspect.py`](../../tools/account_offboarding/inspect.py), [`cleanup.py`](../../tools/account_offboarding/cleanup.py)
- **Evidências (Sessão 23)**: `docs/SESSIONS/2026-05-24/`
- **Plano de cleanup (Unimed Guaxupé)**: [`docs/SESSIONS/2026-05-21/PLANO_E_TAREFAS_RESET_E_MIGRACAO_DEV_ONLY_2026-05-21.md`](../SESSIONS/2026-05-21/PLANO_E_TAREFAS_RESET_E_MIGRACAO_DEV_ONLY_2026-05-21.md)
- **Copilot instructions**: [`.github/copilot-instructions.md`](../../.github/copilot-instructions.md)

---

**Aprovado por:** [Nome do Tech Lead / DBA Sênior]  
**Data de aprovação:** [YYYY-MM-DD]  
**Próxima revisão:** [YYYY-MM-DD] (sugestão: a cada 6 meses ou upgrade do Chatwoot)
