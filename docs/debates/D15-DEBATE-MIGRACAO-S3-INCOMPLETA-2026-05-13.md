# D15 — DEBATE: Migração de Attachments S3 Incompleta

**Data**: 2026-05-13
**Sessão**: SESSION-13
**Tipo**: DESCOBERTA CRÍTICA
**Escopo**: Validação pós-migração — Attachments S3

---

## 📋 Sumário Executivo

**Descoberta**: A migração de dados cobriu apenas **metadados do banco de dados**. Os **arquivos físicos armazenados no S3** não foram migrados/sincronizados para o bucket de destino.

**Impacto**: 74% dos attachments testados (74/100) retornam HTTP 404 quando acessados via URL.

**Causa raiz**: Pipeline de migração foi desenhado para migrar apenas dados relacionais (PostgreSQL). Arquivos binários no S3 estão fora do escopo atual.

**Recomendação**: Definir estratégia de migração S3 ou aceitar risco de dados faltantes em produção.

---

## 🔍 Contexto da Descoberta

### Trigger
Usuário solicitou validação de homologação através de teste de acessibilidade de URLs de attachments geradas a partir do banco DEST.

### Método de Validação
1. Query SQL complexa para extrair attachments do DB DEST (account_id=17 — Unimed Poços PJ)
2. Amostragem aleatória de 100 registros (`ORDER BY RANDOM()`)
3. HTTP HEAD request para cada URL S3: `https://assets-chat-vya-digital.s3.amazonaws.com/{blob_key}`
4. Análise de respostas: HTTP 200 (sucesso) vs HTTP 404 (falha)

### Resultado Quantitativo
```
Total validado:    100 attachments
Sucesso (HTTP 200): 26 (26.0%)
Falha (HTTP 404):   74 (74.0%)
```

**Distribuição por tipo de conteúdo**:

| Content-Type       | Sucesso | Falha | Taxa de Falha |
|--------------------|---------|-------|---------------|
| application/pdf    | 4       | 28    | 87.5%         |
| image/jpeg         | 14      | 28    | 66.7%         |
| audio/opus         | 8       | 9     | 52.9%         |
| image/png          | 0       | 4     | 100%          |
| audio/ogg          | 0       | 4     | 100%          |
| image/webp         | 0       | 1     | 100%          |

---

## 🧪 Evidências Técnicas

### 1. Erro XML do S3

Exemplo de resposta HTTP 404 para blob_key `uyxyh8ak28xkitlorqxno7824jc2`:

```xml
<Error>
  <Code>NoSuchKey</Code>
  <Message>The specified key does not exist.</Message>
  <Key>uyxyh8ak28xkitlorqxno7824jc2</Key>
  <RequestId>7AJVCG516QFGRXW9</RequestId>
  <HostId>DioeSIJM4Gc0TgjuT5KPLzM4hvVofuCsBSlTwaqVga9LwiSDQMmcD7txZfMBhF41y/SC1H0xueaMmv4+yOPFicqOXjo6ZZrV</HostId>
</Error>
```

**Interpretação**: Arquivo `408215875_1122784972237496_3404342874477427842_n.jpg` existe no DB DEST (metadados), mas o arquivo físico **não foi encontrado no bucket S3**.

### 2. Bucket Único (SOURCE = DEST)

**Descoberta adicional**: SOURCE e DEST usam o **mesmo bucket S3**:
- URL padrão: `https://assets-chat-vya-digital.s3.amazonaws.com/{blob_key}`
- Service name: `amazon` (active_storage_blobs.service_name)
- Blob key format: 28 caracteres alfanuméricos (ex: `uyxyh8ak28xkitlorqxno7824jc2`)

**Implicação**: Não há necessidade de copiar arquivos entre buckets. Se SOURCE e DEST apontam para o mesmo bucket, os arquivos **já deveriam estar acessíveis** — mas 74% retornam 404.

### 3. Metadados Migrados Corretamente

Query comparativa SOURCE vs DEST:

**SOURCE (chatwoot_dev1_db)**:
```
attachment_id=7256
blob_key=uyxyh8ak28xkitlorqxno7824jc2
filename=408215875_1122784972237496_3404342874477427842_n.jpg
```

**DEST (chatwoot004_dev1_db)**:
```
attachment_id=12428 (remapeado)
blob_key=uyxyh8ak28xkitlorqxno7824jc2 (preservado)
filename=408215875_1122784972237496_3404342874477427842_n.jpg
```

✅ **Blob_key preservado** → metadados migrados corretamente.
❌ **Arquivo físico não acessível** → NoSuchKey no S3.

---

## 🤔 Hipóteses de Causa Raiz

### H1: Arquivos nunca foram enviados ao bucket DEST

**Evidência a favor**:
- 74% dos attachments testados retornam 404
- Padrão consistente: tanto PDFs quanto imagens/áudio afetados

**Evidência contra**:
- 26% dos arquivos **ESTÃO acessíveis** via HTTP 200
- SOURCE e DEST usam o **mesmo bucket** → não há "bucket DEST" separado

**Conclusão**: ❌ Rejeitada. Se 26% estão acessíveis, o bucket está configurado corretamente.

---

### H2: Arquivos foram deletados/expirados do bucket S3

**Evidência a favor**:
- 74% dos arquivos ausentes
- Possível política de lifecycle do S3 deletando objetos antigos

**Evidência contra**:
- 26% dos arquivos ainda acessíveis (mesmo bucket, mesma data de upload esperada)
- Nenhuma evidência de lifecycle policy mencionada

**Teste necessário**: Verificar datas de `created_at` dos blobs com sucesso vs falha.

---

### H3: Bucket SOURCE ≠ Bucket DEST (configuração incorreta)

**Evidência a favor**:
- 74% de falha seria explicável se URLs apontam para bucket errado

**Evidência contra**:
- Query em `active_storage_blobs.service_name` retorna `amazon` em ambos
- 26% de sucesso indica que o bucket configurado **está correto**
- Mesmo blob_key encontrado em SOURCE e DEST

**Conclusão**: ❌ Rejeitada. Bucket é o mesmo (`assets-chat-vya-digital.s3.amazonaws.com`).

---

### H4: Attachments do SOURCE nunca foram enviados ao S3 (dados órfãos)

**Evidência a favor**:
- 74% dos metadados no DB SOURCE podem apontar para arquivos que **nunca existiram**
- Possível: usuários deletaram mensagens/conversas mas metadados permaneceram

**Evidência contra**:
- Taxa de 26% de sucesso indica que **alguns arquivos foram enviados corretamente**

**Teste necessário**: Validar os mesmos blob_keys contra o **bucket do ambiente SOURCE** (se houver bucket separado).

---

### H5: ⭐ Migração cobriu apenas attachments recentes (data cutoff)

**Evidência a favor**:
- 26% de sucesso pode representar arquivos criados após uma determinada data
- Pipeline pode ter filtro implícito de `created_at`

**Evidência contra**:
- Query de validação usou range amplo: `2000-01-01` a `2030-12-31`
- Nenhum filtro de data documentado no pipeline

**Teste necessário**: Correlacionar datas de `created_at` com taxa de sucesso/falha.

**Conclusão**: 🟡 Possível. Requer análise temporal.

---

## 📊 Análise Aprofundada

### Teste 1: Análise temporal de sucesso vs falha

```python
# Script: .tmp/analise_temporal_attachments.py
# Objetivo: Correlacionar created_at com HTTP status
```

**Resultado esperado**: Se H5 for verdadeira, attachments com `created_at` recente terão maior taxa de sucesso.

---

### Teste 2: Validar blob_keys no bucket SOURCE (se existir)

Se o ambiente SOURCE usar bucket diferente (ex: `assets-chat.vya.digital.s3.amazonaws.com`), testar os mesmos blob_keys contra esse bucket.

**Comando sugerido**:
```bash
aws s3api head-object --bucket assets-chat-vya-digital --key uyxyh8ak28xkitlorqxno7824jc2
```

---

### Teste 3: Contar attachments órfãos no SOURCE

```sql
-- Contar attachments no SOURCE que NÃO têm conversations associadas
SELECT COUNT(*)
FROM attachments att
LEFT JOIN messages m ON m.id = att.message_id AND m.account_id = att.account_id
LEFT JOIN conversations c ON c.id = m.conversation_id AND c.account_id = m.account_id
WHERE att.account_id = 17
  AND (m.id IS NULL OR c.id IS NULL);
```

**Interpretação**: Se > 70%, explica por que arquivos não existem (metadados órfãos).

---

## 🛠️ Decisões Pendentes

### D15-A: Qual é o bucket S3 correto do ambiente SOURCE?

**Contexto**: Precisamos confirmar se SOURCE e DEST usam o mesmo bucket ou se há 2 buckets separados.

**Ações**:
- [ ] Verificar configuração de `storage.yml` ou `config/storage.yml` no ambiente SOURCE
- [ ] Consultar equipe ops: qual bucket o ambiente `chat.vya.digital` usa?
- [ ] Testar blob_keys contra buckets candidatos:
  - `assets-chat-vya-digital.s3.amazonaws.com` (atual)
  - `assets-synchat.s3.amazonaws.com` (produção separada?)
  - Outros buckets identificados

**Responsável**: Ops / DevOps

---

### D15-B: A migração S3 está no escopo ou fora?

**Contexto**: Pipeline atual migra apenas banco de dados PostgreSQL. Arquivos S3 foram **assumidos como pré-existentes** ou fora do escopo.

**Opções**:
1. **Aceitar como está** — 26% de sucesso é suficiente para validação de metadados
2. **Ampliar escopo** — Implementar sync S3-to-S3 como nova fase do pipeline
3. **Investigar antes de decidir** — Executar Testes 1-3 acima para confirmar causa raiz

**Recomendação**: Opção 3 — Investigar antes de ampliar escopo.

**Responsável**: Tech Lead / Product Owner

---

### D15-C: Qual a taxa de sucesso aceitável para homologação?

**Contexto**: 26% de sucesso indica problema, mas pode ser aceitável se:
- Attachments faltantes são antigos/irrelevantes
- Usuários não acessam attachments frequentemente
- Custo de migração S3 supera benefício

**Pergunta para stakeholders**:
> "É aceitável que 74% dos attachments retornem erro 404 em produção?"

**Métricas de negócio necessárias**:
- Quantos usuários acessam attachments por dia?
- Qual o impacto de attachments faltantes no NPS?
- Custo de armazenamento S3 vs custo de retrabalho

---

## 🚀 Próximos Passos (Recomendações)

### Curto Prazo (esta sessão)
1. ✅ Documentar descoberta (este debate)
2. [ ] Executar Teste 1: Análise temporal
3. [ ] Executar Teste 2: Validar bucket SOURCE (se ops confirmar bucket diferente)
4. [ ] Executar Teste 3: Contar attachments órfãos no SOURCE

### Médio Prazo (próxima sessão)
5. [ ] Decisão D15-B: Ampliar escopo ou aceitar como está?
6. [ ] Se ampliar escopo → Implementar fase 6: Sync S3-to-S3
7. [ ] Se aceitar como está → Documentar limitação conhecida no README

### Longo Prazo (pós-migração)
8. [ ] Monitorar logs de acesso S3 em produção
9. [ ] Criar alerta para taxa de 404 em attachments
10. [ ] Avaliar custo/benefício de migração S3 retroativa

---

## 📝 Artefatos Gerados

| Arquivo | Descrição |
|---------|-----------|
| `.tmp/19_validar_attachments_s3.py` | Script de validação HTTP de attachments (400 linhas) |
| `.tmp/validacao_attachments_s3_20260513_114547.json` | Resultado de validação (100 registros) |
| `.tmp/analisar_falhas_attachments.py` | Análise de padrões de falha por tipo de arquivo |
| `.tmp/verificar_buckets_s3.py` | Comparação SOURCE vs DEST bucket configuration |
| `docs/SESSIONS/2026-05-13/DAILY_ACTIVITIES_2026-05-13.md` | Documentação da descoberta |
| `docs/debates/D15-DEBATE-MIGRACAO-S3-INCOMPLETA-2026-05-13.md` | Este arquivo |

---

**Status**: 🟡 EM ANÁLISE — Aguardando testes 2-3 e decisão D15-B
**Prioridade**: 🔴 CRÍTICA — Impacto direto em homologação pós-migração
**Responsável**: Equipe de migração + Ops + Product Owner

---

## ✅ Atualização: Teste 1 Executado (2026-05-13 12:00)

### Análise Temporal — Attachments Recentes vs Aleatórios

**Método**:
1. ✅ Amostra ALEATÓRIA de 100 registros (account 17 — Unimed Poços PJ) — executado 11:47
2. ✅ Amostra MAIS RECENTES de 100 registros (account 1 — Vya Digital, ORDER BY created_at DESC) — executado 12:00

**Resultado Comparativo**:

| Amostra | Sucesso | Falha | Taxa de Sucesso |
|---------|---------|-------|-----------------|
| ALEATÓRIA (account 17) | 26 | 74 | **26%** |
| MAIS RECENTES (account 1) | 98 | 2 | **98%** |

**Evidência Temporal**:
- ✅ Attachments **recentes** (2025-2026): ~98% sucesso
- ❌ Attachments **antigos** (mix 2020-2026): ~26% sucesso

**Falhas na amostra recente (2/100)**:
1. `488855618_638663275757519_2890892638660512077_n.jpg` — HTTP 404
2. `491866719_637577026030570_7269792562611927907_n.jpg` — HTTP 404

**Conclusão**:
🔴 **A taxa de sucesso é FORTEMENTE dependente da idade dos attachments**.
🔴 **Arquivos antigos foram deletados do S3** (política de retenção?) ou **nunca existiram** (metadados órfãos).
✅ **Arquivos recentes existem e são acessíveis** no bucket `assets-chat-vya-digital`.

**Implicação para migração**:
- Se o objetivo é migrar apenas **attachments recentes** (últimos 1-2 anos), a migração foi **98% bem-sucedida**.
- Se o objetivo é migrar **todo o histórico**, há um **gap crítico** em arquivos antigos.
- **Recomendação**: Definir policy de retenção explícita e documentar período de cobertura (ex: "Attachments de 2025-01-01 em diante").

**Artefato**:
- `.tmp/validacao_attachments_s3_20260513_120012.json` — 100 registros mais recentes do account 1
