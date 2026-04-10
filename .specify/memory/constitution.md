<!--
SYNC IMPACT REPORT
==================
Version change: (unset) → 1.0.0
Added sections: Core Principles (5), Architecture & Technology Stack, Development Workflow, Governance
Modified principles: N/A — first full population from template
Templates updated:
  ✅ .specify/memory/constitution.md — this file
  ⚠ .specify/templates/plan-template.md — "Constitution Check" section references generic gates; update after speckit.plan
  ⚠ .specify/templates/spec-template.md — no constitution-specific constraints to update yet
  ⚠ .specify/templates/tasks-template.md — no constitution-specific task types to add yet
Deferred TODOs:
  - D1: RESOLVIDO em 2026-04-09 — schema_sha1 idêntico (da6b4a366d...). chatwoot_dev_db: migration=20241217041352, total=252. chatwoot004_dev_db: migration=20240820191716, total=255.
  - D2: Destino final de chatwoot_dev_db pós-migração — decisão do owner (yvesmarinho)
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

### II. Integridade dos Dados & Remapeamento de IDs (NON-NEGOTIABLE)

Toda operação de migração DEVE preservar a integridade referencial entre todas as entidades.
IDs da origem (chatwoot_dev_db) DEVEM ser remapeados para valores posteriores ao maior ID
existente no destino (chatwoot004_dev_db) no momento da execução.

Fórmula obrigatória: `novo_id = id_origem + offset`, onde `offset = max(id_destino)` (i.e., `SELECT MAX(id)`) calculado uma única vez por sessão para cada tabela com chave primária própria. Se a tabela destino estiver vazia, `offset = 0` e os IDs da origem são preservados (comportamento seguro — nenhuma colisão possível com tabela vazia).

Regras obrigatórias:
- O offset DEVE ser calculado uma única vez no início da sessão de migração e mantido constante
- TODA FK referenciando a ID remapeada DEVE ser atualizada no mesmo lote (batch)
- A ordem de inserção DEVE respeitar o grafo de dependências de FK
  (ex: `accounts` → `inboxes` → `contacts` → `conversations` → `messages`)
- Violações de FK durante a migração DEVEM ser registradas por ID (sem conteúdo) e incluídas
  no relatório final, sem abortar a execução completa

### III. Segurança e Privacidade por Padrão (NÃO-NEGOCIÁVEL)

Nenhum dado sensível DEVE aparecer em qualquer output do sistema em nenhuma circunstância.

Dados sensíveis incluem sem limitação: e-mails, nomes, números de telefone, conteúdo de
mensagens, tokens, senhas, UUIDs de sessão e qualquer coluna que identifique uma pessoa.

Regras obrigatórias:
- Credenciais DEVEM ser carregadas exclusivamente de `.secrets/generate_erd.json`
- Credenciais NUNCA DEVEM ser impressas, logadas, serializadas em arquivos ou
  incluídas em mensagens de erro
- O banco `chatwoot_dev_db` é SOMENTE LEITURA — nenhuma transação de escrita
  ou DDL é permitida contra ele em nenhum módulo
- Logs de execução DEVEM usar mascaramento automático para qualquer valor de coluna
  proveniente de tabelas de dados (contacts, messages, conversations, users)
- Classificação dos dados: `confidential` — LGPD se aplica ao processo de migração

### IV. Idempotência & Execução Incremental

O sistema de migração DEVE ser seguro para re-execução: múltiplas execuções do script
sobre o mesmo banco destino NÃO DEVEM produzir registros duplicados.

Rationale: Migrações falham parcialmente. A capacidade de re-executar sem efeitos colaterais
elimina a necessidade de rollback manual e torna o processo auditável.

Regras obrigatórias:
- O sistema DEVE manter um registro de estado de migração (tabela de controle ou arquivo)
  indicando quais registros da origem já foram inseridos no destino
- Antes de inserir qualquer registro, o sistema DEVE verificar se ele já foi migrado
- Re-execução DEVE processar apenas registros ainda não migrados (incremental)
- O relatório de validação final DEVE exibir: total da origem, total migrado nesta execução,
  total acumulado no destino, registro de falhas por tabela

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
**Origem**: `chatwoot_dev_db` — somente leitura
**Destino**: `chatwoot004_dev_db` — leitura e escrita controlada
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
   chatwoot_dev_db: migration=20241217041352 (252 total) | chatwoot004_dev_db: migration=20240820191716 (255 total).
   Schemas plenamente compatíveis. Prosseguir diretamente para `speckit.clarify`.
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
| D2 | Definir destino final de chatwoot_dev_db após migração | yvesmarinho |

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

**Version**: 1.0.0 | **Ratified**: 2026-04-09 | **Last Amended**: 2026-04-09
<!-- Example: Version: 2.1.1 | Ratified: 2025-06-13 | Last Amended: 2025-07-16 -->
