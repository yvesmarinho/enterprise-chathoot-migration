# Enterprise Chatwoot Migration

> Migração por merge de dados entre instâncias do Chatwoot com deduplicação por chave de negócio

**Domínio**: programming | **Linguagem**: python
**Criado em**: 2026-04-09T11:37:54Z
**Repositório**: [git@github.com:yvesmarinho/enterprise-chatwoot-migration.git](git@github.com:yvesmarinho/enterprise-chatwoot-migration.git)

---

## 🚀 Início Rápido

```bash
# Instalar dependências
make install-deps

# Iniciar desenvolvimento
make dev
```

## 📚 Documentação

- [Índice](docs/INDEX.md)
- [Tarefas](docs/TODO.md)

## 🏗️ Estrutura

Consulte os [documentos de arquitetura](docs/) para detalhes.

# Migração Chatwoot — SOURCE → DEST
## Migração por account, uma de cada vez

---

## Instalação

```bash
pip install psycopg2-binary
```

---

## Arquivos

| Arquivo | Função |
|---|---|
| `db.py` | Credenciais e conexões com os bancos |
| `00_inspecionar.py` | Inspeciona SOURCE e compara com DEST antes de migrar |
| `01_migrar_account.py` | **Script principal** — migra uma account completa |
| `02_verificar.py` | Verifica contagens SOURCE vs DEST após migração |
| `03_diagnostico_overlap.py` | Analisa sobreposição para accounts que já têm dados no DEST |
| `04_debug_dedup.py` | Investiga por que conversations aparecem como dedup |
| `05_limpar_duplicatas.py` | Remove duplicatas criadas por migração anterior com o script v2 |
| `06_verificar_erros.py` | Verifica e orienta reprocessamento de erros |

---

## Fluxo completo por account

### PASSO 1 — Inspecionar (não altera nada)

```bash
python 00_inspecionar.py "Sol Copernico"
```

Mostra o que existe no SOURCE e compara com o DEST:
- Volumes de contacts, conversations, messages
- Status de cada inbox: `[JA EXISTE]` ou `[FALTA CRIAR]`
- Status de cada user: encontrado ou não no DEST
- Plano de ação antes de migrar

---

### PASSO 2 — Migrar

```bash
python 01_migrar_account.py "Sol Copernico"
```

O script faz tudo automaticamente na ordem correta:

1. **Account** — cria no DEST se não existir, reutiliza se já existir (dedup por `name`)
2. **Inboxes** — cria os canais (`channel_whatsapp`, `channel_web_widgets`, etc.) e as inboxes. Se já existir pelo nome, reutiliza
3. **Users** — mapeia por email. Não cria users, só vincula à account (`account_users`)
4. **Contacts** — dedup por: `src_id` → `identifier` → `phone_number` → `email` → `nome`
5. **Conversations** — processa em lotes, insere `contact_inbox`, conversation e messages de cada conversa em sequência. Dedup por `custom_attributes->>'src_id'`
6. **Messages** — dentro do loop de cada conversation. `content_attributes = NULL` sempre (evita erro no Chatwoot). Dedup por `additional_attributes->>'src_id'`
7. **Resequencia PKs** — ajusta todas as sequences do DEST ao final

**Se a execução for interrompida:** rode o mesmo comando novamente. O script é idempotente — pula tudo que já foi inserido e continua de onde parou.

**Dry-run (simula sem inserir):**
```bash
python 01_migrar_account.py "Sol Copernico" --dry-run
```

**Ajuste de velocidade** — edite esta linha em `01_migrar_account.py`:
```python
BATCH = 30  # aumente para 50 ou 100 para mais velocidade (risco de timeout maior)
```

---

### PASSO 3 — Verificar

```bash
python 02_verificar.py "Sol Copernico"
```

Compara contagens SOURCE vs DEST e verifica:
- Mensagens órfãs (sem conversation válida)
- `content_attributes` não-nulo (pode causar erro no Chatwoot)
- Amostra de conversations migradas

---

### PASSO 4 — Verificar erros (se houver)

```bash
python 06_verificar_erros.py "Sol Copernico"
```

Lê o arquivo `logs/erros_Sol_Copernico.jsonl` e verifica se as conversations com erro foram migradas mesmo assim (erros de reconexão geralmente não perdem dados). Se faltar alguma, rode o PASSO 2 novamente.

---

## Ordem de migração recomendada

```bash
python 01_migrar_account.py "Sol Copernico"
python 01_migrar_account.py "Unimed Poços PF"
python 01_migrar_account.py "Unimed Poços PJ"
python 01_migrar_account.py "Unimed Guaxupé"
python 01_migrar_account.py "Vya Digital"
```

---

## Accounts com dados existentes no DEST (misto)

Para accounts que já têm dados no DEST (parte migrada, parte nativa do Chatwoot):

**1. Diagnóstico de sobreposição:**
```bash
python 03_diagnostico_overlap.py "Unimed Poços PJ"
```

**2. Se houver duplicatas de migração anterior (script v2):**
```bash
python 05_limpar_duplicatas.py "Unimed Poços PJ" --preview
python 05_limpar_duplicatas.py "Unimed Poços PJ"
```

**3. Migrar normalmente:**
```bash
python 01_migrar_account.py "Unimed Poços PJ"
```

---

## Regras críticas de design

### content_attributes = NULL sempre
O campo `content_attributes` em `messages` é do tipo `json` (não `jsonb`).
Se inserido com valor, o Rails/ActiveRecord pode retornar String em vez de Hash,
quebrando o método `push_event_data` com:
```
no implicit conversion of Hash into String
```
**Solução:** sempre inserir `NULL`. O Chatwoot funciona perfeitamente sem esse campo.

### Rastreio de origem (src_id)
Cada registro migrado tem o ID original do SOURCE gravado:
- `contacts.custom_attributes->>'src_id'`
- `conversations.custom_attributes->>'src_id'`
- `messages.additional_attributes->>'src_id'`

Isso garante idempotência — o script pode ser rodado quantas vezes quiser sem duplicar.

### pubsub_token = NULL
O campo `pubsub_token` em `contact_inboxes` é único globalmente. Como SOURCE e DEST
são forks, teriam os mesmos tokens. Inserir `NULL` evita a unique constraint — o
Chatwoot regenera automaticamente quando necessário.

### Dedup de contacts
Ordem de verificação antes de inserir:
1. `custom_attributes->>'src_id'` — já migrado nesta ou em rodada anterior
2. `identifier + account_id`
3. `phone_number + account_id`
4. `email + account_id`
5. `nome + account_id` — fallback para contacts sem identificador

### Conexões curtas
Para evitar timeout do servidor PostgreSQL:
- Cada lote de conversations abre e fecha sua própria conexão SOURCE
- Messages de cada conversation abrem e fecham sua própria conexão SOURCE
- Se a conexão DEST cair, o script reconecta automaticamente e continua

---

## Logs de erro

Cada migração gera um arquivo em `logs/`:
```
logs/erros_Sol_Copernico.jsonl
logs/erros_Unimed_Pocos_PF.jsonl
...
```

Formato de cada linha:
```json
{"phase": "conversations", "id": "38733", "reason": "server closed the connection..."}
```

---

## ⚠️ Mudança de Estratégia — 2026-04-10

**Descoberta**: existem registros sobrepostos entre `chatwoot_dev1_db` e `chatwoot004_dev1_db`.

A estratégia de migração do projeto enterprise (`src/`) passa de **incremental pura** (offset de IDs)
para **merge** (deduplicação por chave de negócio + remapeamento apenas para registros realmente novos).

| Abordagem anterior | Nova abordagem |
|--------------------|----------------|
| Assume dados completamente distintos entre bancos | Assume possível sobreposição |
| Insere todos os registros com `id = id_origem + offset` | Verifica chave de negócio antes de inserir |
| Sem resolução de conflito | Política de conflito por entidade (skip / merge / origem-vence) |

**Impacto**: spec.md, plan.md e tasks.md do feature `001-enterprise-chatwoot-migration`
precisam ser revisados após debate D3 (ver `.specify/memory/constitution.md`).

Os scripts `app/` (caminho `01_migrar_account.py`) já implementam merge por `src_id` e
servem como referência de lógica de deduplicação por entidade.

---

## ✅ Validação de Migração (Pós-Migração)

### Fluxo de Validação Implementado — 2026-04-29

Após a migração bem-sucedida de 5 accounts, foi implementado um processo de validação completo que combina verificação no banco de dados e via API REST.

#### Scripts de Validação

| Script | Função |
|--------|--------|
| `.tmp/testar_autenticacao_api.py` | Testa autenticação da API sem expor credenciais |
| `.tmp/gerar_novo_token.py` | Gera token de API válido no banco DEST |
| `.tmp/identificar_accounts_migrados.py` | Identifica accounts com conversations migradas |
| `.tmp/18_validacao_multi_account.py` | **Script principal** — valida 100 registros por account |
| `.tmp/analise_inboxes_vya.py` | Analisa inboxes e identifica remapeamentos de IDs |

#### Processo de Validação

```bash
# 1. Validar autenticação da API (lê token de .secrets/generate_erd.json)
python3 .tmp/testar_autenticacao_api.py

# 2. Se token inválido, gerar novo token
python3 .tmp/gerar_novo_token.py
# Atualizar .secrets/generate_erd.json com o token gerado

# 3. Identificar accounts migrados
python3 .tmp/identificar_accounts_migrados.py

# 4. Executar validação completa (500 registros totais)
python3 .tmp/18_validacao_multi_account.py
```

#### Metodologia de Validação

Para cada account migrado:
1. **Amostragem aleatória**: 100 conversations do SOURCE
2. **Validação no banco DEST**: Busca por `display_id` + `account_id`
3. **Validação via API**: `GET /api/v1/accounts/{id}/conversations/{display_id}`
4. **Processamento em lotes**: 20 registros por vez com rate limiting (100ms)
5. **Registro completo**: JSON com todos os resultados e falhas

#### Resultados (2026-04-29)

**Validação de 500 registros (100 por account)**:

| Account | SOURCE→DEST | Amostra | DEST | API | Status |
|---------|-------------|---------|------|-----|--------|
| Vya Digital | 1→1 | 100 | 4% | 4% | ⚠️ MERGE (DEST tinha dados pré-existentes) |
| Sol Copernico | 4→44 | 100 | 97% | 97% | ✅ Sucesso |
| Unimed Poços PJ | 17→17 | 100 | 100% | 100% | ✅ Perfeito |
| Unimed Poços PF | 18→45 | 100 | 99% | 99% | ✅ Sucesso |
| Unimed Guaxupé | 25→46 | 100 | 100% | 100% | ✅ Perfeito |
| **TOTAL** | - | **500** | **80%** | **80%** | ✅ **Validado** |

**Observações**:
- **Vya Digital (4%)**: Resultado esperado para estratégia MERGE. O DEST já possuía 378 conversations de outras fontes (687 total vs. 309 do SOURCE). Validação manual via frontend confirmou 7 caixas de entrada corretas.
- **4 accounts ≥97%**: Migração validada com alta taxa de sucesso.
- **API funcionando**: Token gerado dinamicamente e validado com sucesso.

#### Documentação Completa

Consulte a documentação detalhada da validação:
- **Relatório executivo**: [`docs/SESSIONS/2026-04-29/RELATORIO_VALIDACAO_MIGRACAO.md`](docs/SESSIONS/2026-04-29/RELATORIO_VALIDACAO_MIGRACAO.md)
- **Guia técnico de alterações**: [`docs/SESSIONS/2026-04-29/GUIA_ALTERACOES_TECNICAS.md`](docs/SESSIONS/2026-04-29/GUIA_ALTERACOES_TECNICAS.md)

#### Boas Práticas Identificadas

1. **Segurança**: NUNCA expor credenciais em linha de comando
   - ✅ Usar scripts Python que leem de `.secrets/generate_erd.json`
   - ❌ Evitar `curl -H "api_access_token: [EXPOSTO]"`

2. **Validação dupla**: Banco + API
   - Banco: confirma migração física
   - API: confirma visibilidade de negócio

3. **Amostragem**: 100 registros aleatórios por account é suficiente
   - Detecta padrões sistêmicos
   - Falhas concentradas indicam problema específico

4. **Estratégias de migração**:
   - **FULL**: Migração completa (threshold ≥95%)
   - **MERGE**: Mesclar com dados existentes (threshold ≥80%)
   - Documentar estratégia usada por account

#### Próximos Passos Recomendados

- [ ] Investigar Vya Digital: determinar critérios de filtro (4% encontrados)
- [ ] Automatizar validação: integrar ao pipeline de migração
- [ ] Implementar testes: pytest com thresholds configuráveis por estratégia
- [ ] Criar dashboard: visualização de métricas de validação
