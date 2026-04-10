<!--
SYNC IMPACT REPORT
==================
Version change: 1.0.0 → 2.0.0 (MAJOR — mudança de estratégia incremental → merge)
Version change: 2.0.0 → 2.0.1 (PATCH — clarificações técnicas: tabela de chaves de negócio, regras de campos especiais e convenção src_id derivadas de docs/sql_code_old/)
Added sections: N/A
Modified principles:
  ✅ Princípio II — adicionada cláusula de deduplicação por chave de negócio antes de remapear IDs
  ✅ Princípio II — tabela de chaves de negócio por entidade (10 entidades)
  ✅ Princípio II — tabela de regras de campos especiais (5 campos obrigatórios)
  ✅ Princípio II — convenção canônica de rastreio src_id
  ✅ Princípio IV — renomeado para "Idempotência & Execução por Merge"; regras reescritas
Modified sections:
  ✅ Fluxo de Desenvolvimento — passos 1/2 atualizados para mencionar merge
  ✅ Pendências — D3 adicionado
Templates updated:
  ⚠ .specify/templates/plan-template.md — atualizar após debate de estratégia de merge por entidade
  ⚠ .specify/templates/spec-template.md — atualizar user stories para refletir merge
  ⚠ .specify/templates/tasks-template.md — novos tipos de tarefa para resolução de conflito
Deferred TODOs:
  - D1: RESOLVIDO em 2026-04-09 — schema_sha1 idêntico (da6b4a366d...). chatwoot_dev1_db: migration=20241217041352, total=252. chatwoot004_dev1_db: migration=20240820191716, total=255.
  - D2: Destino final de chatwoot_dev1_db pós-migração — decisão do owner (yvesmarinho)
  - D3: ABERTO em 2026-04-10 — existem registros sobrepostos entre as duas instâncias. A estratégia de migração passa de incremental para merge. Debate necessário para definir: (a) chave de negócio de deduplicação por entidade, (b) política de resolução de conflito (origem vence / destino vence / fusão de campos), (c) tratamento de IDs órfãos após deduplicação.
-->

# Enterprise Chatwoot Migration Constitution

## Core Principles

### I. Fabric Design Pattern (NÃO-NEGOCIÁVEL)

Todo o código do projeto — da camada de conexão aos migrators, helpers e utilitários — DEVE
seguir o Fabric Design Pattern com organização em Factory + Repository. Nenhum script
procedural de nível top-level é permitido fora do ponto de entrada `src/migrar.py`.

Rationale: O projeto lida com múltiplas entidades interconectadas e dois bancos de dados
distintos. Sem uma arquitetura modular e consistente, qualquer mudança de schema ou adição
de entidade torna-se cirurgia de alto risco em código espaguete.

Regras obrigatórias:
- Cada entidade migrada DEVE ter um `Migrator` isolado e testável de forma independente
- Conexões com banco DEVEM ser criadas via `ConnectionFactory`, nunca hard-coded
- Dependências entre migrators DEVEM ser declaradas explicitamente (grafo de ordem de execução)
- Módulos internos DEVEM ser importáveis e testáveis sem execução do script principal

### II. Integridade dos Dados, Deduplicação e Remapeamento de IDs (NON-NEGOTIABLE)

Toda operação de migração DEVE preservar a integridade referencial entre todas as entidades.
Antes de remapear e inserir qualquer registro, o sistema DEVE verificar se aquele registro já
existe no destino por meio de uma **chave de negócio por entidade** (não apenas por ID primário).

**Estágio 1 — Deduplicação por chave de negócio (novo)**:
Cada entidade possui uma chave de negócio canônica que determina se um registro da origem
já existe no destino. Registros com match na chave de negócio DEVEM ser tratados pela política
de resolução de conflito definida para a entidade (skip / merge de campos / origem vence).
Registros sem match passam para o Estágio 2 como candidatos a inserção.

**Estágio 2 — Remapeamento de IDs (candidatos à inserção apenas)**:
IDs da origem (chatwoot_dev1_db) SAÓ remapeados para valores posteriores ao maior ID existente
no destino (chatwoot004_dev1_db) apenas para registros que NÃO encontraram match no Estágio 1.

Fórmula obrigatória para inserções novas: `novo_id = id_origem + offset`, onde
`offset = max(id_destino)` calculado uma única vez por sessão. Se a tabela destino estiver
vazia, `offset = 0`.

Regras obrigatórias:
- A chave de negócio por entidade DEVE ser definida antes da implementação (debate D3)
- O offset DEVE ser calculado uma única vez no início da sessão e mantido constante
- TODA FK referenciando uma ID remapeada DEVE ser atualizada no mesmo lote (batch)
- A ordem de inserção DEVE respeitar o grafo de dependências de FK
  (ex: `accounts` → `inboxes` → `contacts` → `conversations` → `messages`)
- Violações de FK durante a migração DEVEM ser registradas por ID (sem conteúdo) e incluídas
  no relatório final, sem abortar a execução completa

**Tabela de chaves de negócio por entidade** (fonte: `docs/sql_code_old/` + `app/01_migrar_account.py`):

| Entidade | Chave de negócio (prioridade decrescente) | Política de conflito |
|---|---|---|
| `accounts` | `name` | reutilizar id destino |
| `inboxes` | `name + account_id` | reutilizar id destino |
| `users` | `email` (`uid`) | mapear — NÃO criar |
| `teams` | `name + account_id` | reutilizar id destino |
| `labels` | `title + account_id` | reutilizar id destino |
| `contacts` | `src_id` → `identifier+account` → `phone+account` → `email+account` → `name+account` | skip / merge (D3) |
| `conversations` | `custom_attributes->>'src_id'` | skip / merge (D3) |
| `messages` | `additional_attributes->>'src_id'` | skip (D3) |
| `attachments` | `message_id + external_url` | orphan check por FK |
| `contact_inboxes` | `contact_id + inbox_id` | regenerar campos únicos |

**Regras de campos especiais — OBRIGATÓRIAS em toda inserção** (fonte: `docs/sql_code_old/`):

| Campo | Regra | Motivo |
|---|---|---|
| `contact_inboxes.pubsub_token` | SEMPRE `NULL` | UUID único global; fork compartilha tokens com origem → UNIQUE violation |
| `contact_inboxes.source_id` | SEMPRE `gen_random_uuid()` | Não copiar da origem — risco de colisão |
| `conversations.uuid` | SEMPRE `gen_random_uuid()` | Campo UNIQUE global; copiar da origem causa conflito |
| `messages.content_attributes` | SEMPRE `NULL` | Tipo `json` (não `jsonb`); Rails retorna String em vez de Hash quebrando `push_event_data` |
| `conversations.display_id` | `MAX(display_id)+1` calculado no destino | Sequencial por account; copiar da origem colide com ids existentes |

**Coluna de rastreio de origem** (convenção canônica do projeto):
- `contacts`, `conversations`, `inboxes`: `custom_attributes->>'src_id'` = id de origem (como texto)
- `messages`: `additional_attributes->>'src_id'` = id de origem (convenção Chatwoot para mensagens)
- Nota: scripts legados em `docs/sql_code_old/` usam `external_id` — padrão deste projeto é `src_id`

### III. Segurança e Privacidade por Padrão (NÃO-NEGOCIÁVEL)

Nenhum dado sensível DEVE aparecer em qualquer output do sistema em nenhuma circunstância.

Dados sensíveis incluem sem limitação: e-mails, nomes, números de telefone, conteúdo de
mensagens, tokens, senhas, UUIDs de sessão e qualquer coluna que identifique uma pessoa.

Regras obrigatórias:
- Credenciais DEVEM ser carregadas exclusivamente de `.secrets/generate_erd.json`
- Credenciais NUNCA DEVEM ser impressas, logadas, serializadas em arquivos ou
  incluídas em mensagens de erro
- O banco `chatwoot_dev1_db` é SOMENTE LEITURA — nenhuma transação de escrita
  ou DDL é permitida contra ele em nenhum módulo
- Logs de execução DEVEM usar mascaramento automático para qualquer valor de coluna
  proveniente de tabelas de dados (contacts, messages, conversations, users)
- Classificação dos dados: `confidential` — LGPD se aplica ao processo de migração

### IV. Idempotência & Execução por Merge

O sistema de migração DEVE ser seguro para re-execução: múltiplas execuções do script
sobre o mesmo banco destino NÃO DEVEM produzir registros duplicados nem sobrescrever
registros com dados idênticos sem necessidade.

Rationale: As duas instâncias possuem registros sobrepostos (mesmas entidades em ambos os
bancos). A estratégia incremental pura (offset de IDs) não é suficiente — é necessário
identificar e resolver sobreposições antes de inserir. A re-execução segura elimina a
necessidade de rollback manual e torna o processo auditável.

Regras obrigatórias:
- O sistema DEVE identificar registros já presentes no destino pela chave de negócio
  (não pelo ID primário) antes de qualquer inserção
- Registros com match na chave de negócio DEVEM ser tratados pela política de resolução
  de conflito da entidade: skip (sem alteração), merge (fusão de campos) ou update
  (origem vence). A política DEVE ser definida por entidade antes da implementação (D3)
- Registros sem match DEVEM ser inseridos como novos com ID remapeado (Princípio II)
- O sistema DEVE manter tabela de controle de migração registrando o resultado de cada
  registro: novo-inserido / dedup-skip / dedup-merged / falha
- O relatório de validação final DEVE exibir por tabela: total na origem, novos inseridos,
  deduplicados (skip), deduplicados (merged), falhas, total acumulado no destino

### V. Qualidade por Contrato

Qualidade de código é um pré-requisito de entrega, não um pós-processamento opcional.

Regras obrigatórias:
- TODA função pública DEVE ter docstring reStructuredText com `:param:`, `:type:`,
  `:returns:`, `:rtype:` e `:raises:` quando aplicáveis
- Funções críticas (remapeamento de IDs, mascaramento de log, validação de FK) DEVEM
  ter doctest executável
- Testes unitários DEVEM cobrir: `id_remapper`, `log_masker`, `fk_validator`,
  `connection_factory` e cada `Migrator` individualmente
- Todo código DEVE passar em `ruff check` (linting) e `black --check` (formatação)
  antes de qualquer commit
- Tipagem estrita (`strict_typing: true`) DEVE ser aplicada — todos os parâmetros e
  retornos de funções públicas DEVEM ter type hints

## Arquitetura e Stack Tecnológico

**Linguagem**: Python 3.12+
**ORM / Acesso a dados**: SQLAlchemy (Core + ORM) — obrigatório, sem queries SQL raw
**Driver PostgreSQL**: psycopg2-binary
**Controle de versão de schema**: Alembic (como referência, não como mecanismo do Chatwoot)
**Linting**: ruff
**Formatação**: black
**Testes**: pytest com doctest integrado
**Bancos**: PostgreSQL 16 — servidor único `wfdb02.vya.digital` porta 5432
**Origem**: `chatwoot_dev1_db` — somente leitura
**Destino**: `chatwoot004_dev1_db` — leitura e escrita controlada
**Entrypoint**: `python src/migrar.py`
**Credenciais**: `.secrets/generate_erd.json` — jamais versionado

Estrutura de referência de código-fonte:

```text
src/
├── migrar.py                   # Entrypoint único
├── factory/
│   └── connection_factory.py   # Cria conexões SQLAlchemy
├── repository/
│   ├── base_repository.py      # CRUD genérico
│   └── chatwoot_repository.py  # Queries específicas do Chatwoot
├── migrators/
│   ├── base_migrator.py        # Contrato Fabric
│   ├── accounts_migrator.py
│   ├── contacts_migrator.py
│   ├── conversations_migrator.py
│   ├── messages_migrator.py
│   └── ...
├── utils/
│   ├── id_remapper.py          # Cálculo de offset e remapeamento
│   ├── log_masker.py           # Mascaramento de dados sensíveis
│   └── fk_validator.py
└── reports/
    └── validation_reporter.py  # Relatório final por tabela

test/
├── unit/
│   ├── test_id_remapper.py
│   ├── test_log_masker.py
│   ├── test_fk_validator.py
│   └── test_*_migrator.py
└── integration/
    └── test_migration_flow.py
```

## Fluxo de Desenvolvimento

1. **Pré-implementação**: D1 RESOLVIDO (2026-04-09) — schema_sha1 idêntico confirmado.
   chatwoot_dev1_db: migration=20241217041352 (252 total) | chatwoot004_dev1_db: migration=20240820191716 (255 total).
   Schemas plenamente compatíveis.
   D3 ABERTO (2026-04-10) — existem registros sobrepostos. Estratégia alterada para merge.
   Debate necessário antes de spec/plan revisados. Ver `docs/debates/` para registro.
2. **Ordem do speckit chain**: `speckit.constitution` → `speckit.clarify` →
   `speckit.plan` → `speckit.checklist` → `speckit.tasks` → `speckit.analyze` →
   `speckit.implement`
3. **Commits**: sempre via arquivo de mensagem, nunca `git commit -m` direto
4. **Arquivos**: criados/editados via ferramentas do Copilot — proibido `cat > heredoc`
5. **Verificação pós-edição**: Todo arquivo Python editado DEVE ser validado com
   `ruff check` e `black --check` antes de commit
6. **Constitution Check em todo PR/revisão**: verificar aderência aos 5 princípios
   antes de qualquer merge ou push

**Pendências antes do speckit.plan**:

| ID | Tarefa | Responsável |
|----|--------|-------------|
| D1 | ✅ RESOLVIDO — schema_sha1 idêntico (da6b4a366d...). Contagens: origem 38.868 contacts/41.743 convs/310.155 msgs. Destino 225.536 contacts/153.582 convs/1.302.949 msgs. | Copilot |
| D2 | Definir destino final de chatwoot_dev1_db após migração | yvesmarinho |
| D3 | 🔴 ABERTO — Existem registros sobrepostos entre as instâncias. Definir: (a) chave de negócio por entidade, (b) política de resolução de conflito por entidade, (c) coluna de rastreio de origem (ex: `custom_attributes->>src_id`). Debate obrigatório antes de spec/plan revisados. | yvesmarinho + Copilot |

## Governance

Esta constitution é o artefato de maior autoridade do projeto e supersede qualquer
outra prática, convenção ou instrução conflitante.

**Processo de emenda**:
- Mudanças MINOR ou MAJOR requerem justificativa documentada em
  `docs/SESSIONS/YYYY-MM-DD/` antes da alteração
- Qualquer remoção ou redefinição de princípio é uma versão MAJOR
- Adição de seção ou expansão material é uma versão MINOR
- Clarificações, correções tipográficas e refinamentos não-semânticos são PATCH

**Política de versioning**: MAJOR.MINOR.PATCH (SemVer)

**Compliance**: Todo código gerado no projeto DEVE passar pela Constitution Check
dos 5 princípios. Violações DEVEM ser sinalizadas no relatório de `speckit.analyze`
antes de `speckit.implement`.

**Referências**:
- Especificação do projeto: `objetivo.yaml`, `objetivo-template.yaml`
- Credenciais: `.secrets/generate_erd.json`
- Script de verificação de versão: `scripts/check_chatwoot_versions.py`
- Relatório de análise pré-spec: `docs/SESSIONS/2026-04-09/PRE_SPEC_ANALYSIS_REPORT.md`

**Version**: 2.0.1 | **Ratified**: 2026-04-09 | **Last Amended**: 2026-04-10
<!-- Example: Version: 2.1.1 | Ratified: 2025-06-13 | Last Amended: 2025-07-16 -->
