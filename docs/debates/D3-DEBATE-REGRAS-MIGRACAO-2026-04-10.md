# DEBATE D3: Análise das Regras de Migração — Pontos em Aberto, Erros e Possibilidades

**Data**: 2026-04-10
**Participantes**: @yvesmarinho, GitHub Copilot (moderador/relator)
**Status**: ABERTO — aguarda decisões do owner
**Documento base**: `objetivo-init.yaml`, `objetivo.yaml`, `constitution.md` v2.0.1, `spec.md` Session 2026-04-10
**Arquivo de referência**: `docs/sql_code_old/scriptImportacaoChatToSynchat.sql`, `scriptImportacaoTbChatChatWoot.sql`

---

## Contexto

Este debate é mapeado como **D3** na `constitution.md` e foi aberto em 2026-04-10 quando a
estratégia de migração foi alterada de **incremental** para **merge**. O objetivo é revisar
criticamente todas as regras de migração declaradas nos artefatos do projeto, identificar
contradições, erros, ambiguidades e oportunidades de melhoria antes de destravar a fase
de especificação (`speckit.plan`) e implementação.

**Regras originais convocadas** (de `objetivo-init.yaml` / `objetivo.yaml`):

> 1. Validar se o Cliente está ativo nas duas bases
> 2. Caso o Cliente esteja inativo na base destino, sobrepor todos os dados
> 3. Caso haja conflitos clientes ativos e demais informações chaves, gerar relatório detalhado para análise posterior

---

## Questões Centrais

1. O que significa "Cliente ativo/inativo" no contexto do schema Chatwoot?
2. As regras originais ainda se aplicam com a estratégia de merge adotada?
3. Há erros ou contradições entre as regras atuais nos artefatos?
4. Quais possibilidades de melhoria existem para as regras atuais?

---

## PARTE 1 — Regras Originais: Análise Crítica

### Regra R1: "Validar se o Cliente está ativo nas duas bases"

**Problema crítico**: A regra é **não implementável como escrita** porque:

- O schema do Chatwoot (verificado em `schema_migrations`) **não possui um campo `active` ou `status`
  na tabela `accounts` com semântica de "ativo/inativo"** como negócio.
- O campo `accounts.status` existe no schema mas representa o estado operacional da conta na
  plataforma, não a "atividade de negócio" (ex: se tem conversas recentes, se está em uso).
- Não há definição clara de "client" — pode ser `accounts`, pode ser `contacts`, pode ser ambos.

**Possibilidades de interpretação**:

| Interpretação | Critério sugerido | Risco |
|---|---|---|
| A — Account com conversas recentes | `conversations.created_at > NOW() - INTERVAL '90 days'` | Define "recente" arbitrariamente |
| B — Account com `status = 'active'` no Chatwoot | Campo `accounts.status` | Status operacional ≠ "uso ativo" |
| C — Account com pelo menos 1 user ativo | `users.availability_status = 'online'` | Depende de sessão, não histórico |
| D — Account com qualquer registro recente | Qualquer write nos últimos N dias | Mais abrangente, menos preciso |
| **E — Remover esta regra (recomendada)** | Não distinguir ativo/inativo | Estratégia merge já cobre todos os casos |

**Recomendação**: A estratégia de merge adotada (FR-005 na spec) já trata ambos os casos
(ativo e inativo de forma uniforme). **Remover ou reformular R1** para: "Todos os registros de
ambos os bancos são processados indistintamente pelo pipeline de merge; não há pré-filtragem por
estado de atividade de account".

---

### Regra R2: "Caso o Cliente esteja inativo na base destino, sobrepor todos os dados"

**Problema — Conflito Direto com a Estratégia Atual (FR-005):**

A regra R2 implica **UPDATE completo / overwrite** quando o destino está inativo.
A estratégia de merge aprovada (Session 2026-04-10 Q1) define **apenas preenchimento de campos
NULL** (não sobrescrita de campos preenchidos).

| Comportamento | R2 original | FR-005 atual |
|---|---|---|
| Campo preenchido no destino | **Sobrescreve** com valor da origem | **Preserva** o valor do destino |
| Campo NULL no destino | Preenche com origem | Preenche com origem |
| ID do registro destino | Troca pelo ID da origem | **Preserva** o ID do destino |
| Controle de estado | Não definido | `dedup-merged` em `migration_state` |

**Implicação**: R2 e FR-005 são mutuamente exclusivos para o caso "inativo". Qual prevalece?

**Possibilidades**:

**Opção A — Manter FR-005 (merge conservador)** — recomendada para ambientes DEV com dados ativos:
- Nunca sobrescreve campos preenchidos
- Seguro, auditável
- Desvantagem: pode manter dados desatualizados/incompletos no destino se a origem tiver versões mais recentes

**Opção B — Manter R2 com condição de atividade**:
- Exige definir "inativo" (ver R1 — problema circular)
- Overwrite completo pode corromper vínculos de FK no destino (conversas vinculadas ao registro destino passariam a referenciar o ID da origem)
- Risco alto de inconsistência referencial

**Opção C — Campos com `updated_at` mais recente vencem (origin-wins por campo)**:
- Comparar `updated_at` campo a campo
- Mais preciso, mas requer colunas `updated_at` em todas as entidades (nem todas têm)

**Decisão necessária de @yvesmarinho**: ☐ Opção A / ☐ Opção B / ☐ Opção C

---

### Regra R3: "Caso haja conflitos, gerar relatório detalhado para análise posterior"

**Status: Parcialmente coberta, mas incompleta.**

A spec (FR-007) gera relatório com `tabela | origem_total | migrado_nesta_exec | destino_total | falhas`.
Porém o relatório **não inclui**:

- Detalhes dos registros em conflito que foram `dedup-merged` (quais campos foram preenchidos)
- Registros com match em chave de negócio MÚLTIPLA (ex: contact encontrado por email mas com
  phone diferente)
- Conflitos entre accounts com mesmo nome mas atributos divergentes

**Possibilidade de melhoria**:
Adicionar ao relatório uma seção `CONFLITOS RESOLVIDOS` com:
- `tabela | id_origem | id_destino | chave_match | campos_preenchidos_no_merge | status`

---

## PARTE 2 — Erros e Inconsistências Identificadas nos Artefatos

### E1 — Inconsistência na Fórmula do Offset (CRÍTICO)

**Localização:** `spec.md` FR-002 vs `constitution.md` Princípio II

| Artefato | Definição |
|---|---|
| `spec.md` FR-002 | `offset = max(id_destino) + 1` |
| `constitution.md` Princípio II | `offset = max(id_destino)` e `novo_id = id_origem + offset` |

**Problema**: As duas definições produzem IDs diferentes.

Com `offset = max(id_destino) + 1` (spec):
- max_dest = 100, id_origem = 1 → novo_id = 1 + 101 = **102** (ID 101 é pulado!)
- max_dest = 100, id_origem = 2 → novo_id = 2 + 101 = **103**

Com `offset = max(id_destino)` (constitution):
- max_dest = 100, id_origem = 1 → novo_id = 1 + 100 = **101** (correto, sem gap)
- max_dest = 100, id_origem = 2 → novo_id = 2 + 100 = **102**

**O correto é `offset = max(id_destino)` (sem `+1`)** — garante que `novo_id` começa exatamente
em `max_dest + 1` para o menor ID de origem (tipicamente 1), sem lacunas.

**Ação necessária**: Corrigir `spec.md` FR-002 para `offset = max(id_destino)`.

---

### E2 — `contact_inboxes` Ausente da Ordem FK em FR-003 (ALTO RISCO)

**Localização:** `spec.md` FR-003

**Ordem atual**:
```
accounts → inboxes → users → teams → labels → contacts → conversations → messages → attachments
```

**Problema**: `contact_inboxes` está na tabela de chaves de negócio da constitution mas
**não aparece em FR-003**. Essa entidade liga `contacts` a `inboxes` e é referenciada por
`conversations` (`contact_inbox_id` FK).

**Ordem correta sugerida**:
```
accounts → inboxes → users → teams → labels → contacts → contact_inboxes → conversations → messages → attachments
```

**Impacto se não corrigido**: Conversations migradas referenciam `contact_inbox_id` que pode
não existir no destino → FK violation em massa na tabela `conversations`.

---

### E3 — `users` na Ordem de Migração com Política "NÃO CRIAR" (CONTRADIÇÃO)

**Localização:** `spec.md` FR-003 vs `constitution.md` Princípio II (tabela de business keys, linha `users`)

**Contradição**:
- FR-003 lista `users` na ordem de migração (implica migração ativa)
- Constitution: `users` — política: "mapear — NÃO criar"

**Interpretação correta**: `users` não migra registros — apenas constrói um mapa
`id_usuario_origem → id_usuario_destino` por match de email. Esse mapa é consumido pelos
migrators de `conversations` (campo `assignee_id`) e `messages` (campo `author_id`).

**Problema não resolvido**: Se um `user` da origem **não tiver match** de email no destino:
- Qual `assignee_id` recebe a conversation? `NULL`? Skip da conversation? Abort?
- Isso afeta potencialmente **todas as conversations** com agentes que existem só na origem.

**Ação necessária**: Definir política explícita para usuários sem match por email.

| Opção | Comportamento | Risco |
|---|---|---|
| A — `assignee_id = NULL` | Conversation migra sem responsável | Conversas órfãs no destino |
| B — Skip da conversation | Conversation não é migrada | Perda de dados |
| C — Criar usuário placeholder | Cria user especial "MIGRADO_SEM_MATCH" | Sujo, mas rastreável |
| **D — Logar warning, `assignee_id = NULL`, continuar** (recomendada) | Conversation migra com responsável nulo | Aceitável para DEV |

---

### E4 — `conversations.display_id` — Regra de Cálculo Incompleta (MÉDIO RISCO)

**Localização:** `objetivo.yaml` → `special_field_rules`, `constitution.md` Princípio II

**Regra atual**: `MAX(display_id)+1 calculado por sessão no destino`

**Problema**: `display_id` é **sequencial por `account_id`** no Chatwoot, não global.

Se a regra for aplicada como `MAX(display_id) global`, pode acontecer:
- Destino tem account_id=1 com max display_id=5000 e account_id=2 com max display_id=50
- O cálculo global retorna 5001
- Conversations para account_id=2 recebem display_id=5001, 5002, 5003... (errado — deveria ser 51, 52, 53)

**Regra correta**: `MAX(display_id WHERE account_id = X) + 1` por conta de destino, calculado
uma vez no início da sessão e incrementado em memória por account à medida que novos registros
são inseridos.

---

### E5 — `messages.content_attributes = NULL` Causa Perda Permanente de Metadados (IMPACTO ALTO)

**Localização:** `constitution.md` Princípio II / `objetivo.yaml` → `special_field_rules`

**Regra atual**: `messages.content_attributes` → SEMPRE NULL

**Motivo declarado**: Tipo `json` (não `jsonb`); Rails retorna String em vez de Hash ao usar
`push_event_data`, quebrando o evento.

**Problema**: `content_attributes` pode conter metadados de negócio que **não podem ser
recuperados** (ex: razão de fechamento da conversa, dados de bot, integração de webhook).
Forçar NULL causa perda irreversível.

**Possibilidades**:

| Opção | Descrição | Risco |
|---|---|---|
| A — NULL unconditional (atual) | Descarta tudo | Perda de dados, simples de implementar |
| B — `::text` (serializar como texto) | `content_attributes::text` no select, `NULL` no insert | Preserva data em outro campo; requer campo extra |
| C — `to_jsonb(content_attributes)` cast | PostgreSQL: `INSERT ... content_attributes = to_jsonb(src.content_attributes)` | Converte json→jsonb, pode funcionar no schema |
| **D — Verificar se campo é de tipo json ou jsonb no destino** | Se destino usa jsonb, inserir diretamente | Requer inspeção de schema por instância |

**Investigação necessária**: Confirmar o tipo real de `messages.content_attributes` em
`chatwoot004_dev1_db` com `SELECT data_type FROM information_schema.columns WHERE table_name='messages' AND column_name='content_attributes'`.

---

### E6 — `contact_inboxes.pubsub_token = NULL` vs Código Chatwoot (RISCO OPERACIONAL)

**Localização:** `constitution.md` / `objetivo.yaml` → `special_field_rules`

**Regra atual**: `SEMPRE NULL`

**Problema**: O Chatwoot **gera `pubsub_token` automaticamente via callback Rails** quando um
`contact_inbox` é criado. Se inserido com `NULL`, o campo permanecerá NULL até que a aplicação
o regenere via callback.

Em ambiente DEV, isso pode ser aceitável. Em **produção**, contato sem `pubsub_token` não recebe
notificações push em tempo real.

**Confirmação necessária**: Este projeto é somente para DEV — validar que NULL é aceitável para o ambiente alvo.

---

### E7 — Sem Estratégia de Rollback por Entidade (RISCO)

**Localização:** `spec.md` "Edge Cases" + `objetivo.yaml` → `implementation_rules.error_handling_policy`

**Situação atual**: Falha em `accounts` → abort com exit code 3. Demais entidades: registrar e continuar.

**Problema não coberto**: Se `conversations` falha em 40% dos registros (ex: `account_id` não
mapeado), a execução continua com `messages`. Mas as `messages` das conversations que falharam
serão inseridas sem conversation_id válido (FK violation) ou mapeadas para conversations
inexistentes.

**Situação de risco**: Falha em entidade intermediária pode **cascatear** falhas para entidades
dependentes de forma silenciosa (registros que chegam no destino com FK apontando para nada).

**Possibilidade de melhoria**: Threshold de falha por entidade:
- Se % de falha > N% em `conversations`, pausar migração de `messages` e emitir alerta.
- Definir N (sugestão: 20%).

---

### E8 — `accounts` Chave de Negócio por `name` é Frágil (MÉDIO RISCO)

**Localização:** `constitution.md` business_keys, `objetivo.yaml` → `business_keys.accounts`

**Chave atual**: `name` (apenas)

**Problema**: Accounts com o mesmo nome em instâncias diferentes **podem ser empresas diferentes**.
Exemplo: conta "Teste" em `chatwoot_dev1_db` pode ser uma empresa diferente de "Teste" em
`chatwoot004_dev1_db`.

Ao usar `name` como chave única, o migrator **fundirá duas empresas diferentes** como se fossem
a mesma — e todos os contacts/conversations da origem serão associados à account do destino.

**Impacto**: Alto — mistura de dados de clientes distintos sob o mesmo account_id.

**Opções de mitigação**:

| Opção | Descrição |
|---|---|
| A — Usar `name` (atual) | Simples, funciona se ambas as instâncias têm os mesmos tenants |
| B — Listar accounts manualmente em config | Owner define mapeamento explícito `id_origem → id_destino` por account |
| C — Gerar relatório de colisões antes de migrar | Mostrar ao operador quais accounts colidem pelo nome para confirmação manual |
| **D — B + C combinados** | Configuração manual + confirmação antes de executar (recomendada para N=5 accounts) |

**Nota**: Com apenas **5 accounts na origem**, uma verificação manual antes da migração é
factível e elimina o risco.

---

### E9 — Sem Definição de Escopo de Migração por Account (POSSIBILIDADE)

**Situação atual**: O script migra TODOS os registros de TODAS as accounts da origem.

**Possibilidade de melhoria**: Flag `--account-id=X` para migrar dados de uma account específica.

**Benefício**: Permite testar a migração com uma única account antes de executar para todas.
Com 5 accounts na origem (volumes variados), migrar por account é mais controlável.

**Complexidade adicional**: Filtro de account_id deve ser propagado para TODAS as entidades
dependentes (contacts, conversations, messages, attachments, inboxes, teams, labels...).

---

## PARTE 3 — Pontos sem Cobertura nas Regras Atuais

### P1 — `conversation_participants` e outras tabelas pivot não mapeadas

A spec FR-003 lista as entidades principais mas o Chatwoot possui tabelas pivot adicionais:
- `conversation_participants` (FK → conversations + users)
- `team_memberships` (FK → teams + users)
- `account_users` (FK → accounts + users — papel do usuário na conta)
- `notifications` (FK → account + user + conversation)
- `mentions` (FK → conversation + user)

**Decisão necessária**: Migrar essas tabelas? Se sim, em que posição da ordem FK?

---

### P2 — Sem Tratamento de `webhooks` e `integrations`

O Chatwoot permite webhooks e integrações por inbox/account. Esses registros em
`integrations_hooks` e tabelas afins **não são mencionados** na spec nem na constitution.

Migrar um inbox sem sua configuração de webhook pode tornar o canal inoperante no destino.

**Decisão necessária**: Migrar configurações de integrações? (in-scope ou out-of-scope explícito)

---

### P3 — Sem Plano para `schema_migrations` Divergentes

`chatwoot_dev1_db` tem 252 migrations (última: 20241217) e `chatwoot004_dev1_db` tem 255 migrations
(última: 20240820). O SHA do schema é idêntico, mas isso é uma coincidência que pode não persistir.

As 3 migrations extras do destino que não existem na última versão do banco origem são **gaps de
schema** não mapeados. Se alguma delas adicionou colunas NOT NULL sem default, inserções da
origem falharão silenciosamente.

**Ação recomendada**: Identificar as 3 migrations extras antes de implementar os migrators.

---

### P4 — Sem Definição de Janela de Tempo para Migração

`objetivo.yaml` → `constraints.timeline.target_date = "unknown"`.

Para um banco de 38k contacts, 41k conversations e 310k messages, a migração pode levar horas
dependendo da largura de banda de rede e do batch size de 500.

**Estimativa prévia** (batch=500, 310k messages, latência ~10ms/batch):
- messages: 310.000 / 500 = 620 batches × 10ms = ~6s a ~60s (depende de dedup lookup)
- Com dedup lookup por `additional_attributes->>'src_id'`: até **+300ms por batch** = ~3min somente para messages

**Recomendação**: Executar dry-run completo com --dry-run para estimar tempo real antes da migração.

---

## PARTE 4 — Resumo de Ações Requeridas

### Decisões do owner @yvesmarinho (bloqueantes):

| ID | Questão | Opções disponíveis |
|---|---|---|
| **D3-A** | O que significa "Cliente ativo" → manter ou remover R1? | Remover R1 (recomendado) ou definir critério |
| **D3-B** | R2: sobrepor tudo para inativo vs merge conservador (FR-005) — qual prevalece? | Opção A (FR-005) / Opção B (R2) / Opção C (por updated_at) |
| **D3-C** | Users sem match de email: what to do com conversations com esse assignee_id? | NULL (recomendado) / Skip / Placeholder |
| **D3-D** | Accounts: usar `name` como chave única ou mapeamento manual? | Automático por name / Manual config / Relatório + confirmação (recomendado) |
| **D3-E** | Tabelas pivot (`conversation_participants`, `team_memberships`, etc.): migrar? | Sim (+ ordem FK) / Não (out-of-scope) |
| **D3-F** | `webhooks`/`integrations`: migrar configurações de inbox? | Sim / Não (out-of-scope explícito) |

### Correções obrigatórias nos artefatos (independente das decisões):

| ID | Erro | Arquivo | Correção |
|---|---|---|---|
| **E1-FIX** | Fórmula offset: `max+1` → `max` | `spec.md` FR-002 | `offset = max(id_destino)` |
| **E2-FIX** | `contact_inboxes` ausente da ordem FK | `spec.md` FR-003 | Inserir após `contacts` |
| **E3-FIX** | `users` na ordem FK vs política "não criar" | `spec.md` FR-003 | Renomear step para "mapeamento de users" |
| **E4-FIX** | `display_id` global vs por account_id | `objetivo.yaml` + `constitution.md` | `MAX(display_id WHERE account_id = X)+1` |

### Investigações técnicas (antes de implementar):

| ID | Investigação | Responsável |
|---|---|---|
| **T1** | Verificar tipo real de `messages.content_attributes` em `chatwoot004_dev1_db` | Copilot (SQL direto no banco) |
| **T2** | Identificar as 3 migrations extras do destino (20240820 gap) | Copilot (consulta `schema_migrations`) |
| **T3** | Listar as 5 accounts da origem e verificar colisão de nomes com destino | Copilot (query cross-database) |
| **T4** | Estimar tempo de migração com dry-run estendido | Copilot (uv run python -m src.migrar --dry-run) |

---

## PARTE 5 — Decisões Já Tomadas (não reabrir)

| ID | Questão | Decisão | Sessão |
|---|---|---|---|
| D1 | Versão do schema | schema_sha1 idêntico (da6b4a366d...) — compatível | 2026-04-09 |
| D3-Q1 | Política de conflito por business key match | Merge (preencher NULLs + `dedup-merged`) | 2026-04-10 |
| — | Estratégia geral | Merge (não incremental) | 2026-04-10 |
| — | campos especiais: pubsub_token, source_id, uuid, content_attributes, display_id | Regras definidas na constitution v2.0.1 | 2026-04-10 |

---

## Próximos Passos

1. @yvesmarinho responde as decisões **D3-A a D3-F**
2. Copilot aplica correções **E1-FIX a E4-FIX** nos artefatos
3. Copilot executa investigações **T1 a T4** e documenta resultados
4. Retomar `/speckit.clarify` a partir da Q2 (users sem match)
5. Executar `/speckit.plan` para gerar `plan.md` e `tasks.md` atualizados para a estratégia merge
6. Comprometer e publicar alterações antes de iniciar implementação

---

*Gerado por GitHub Copilot em 2026-04-10 como parte do debate D3 aberto na constitution.md v2.0.1*
