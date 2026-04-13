# Feature Specification: Enterprise Chatwoot Migration

**Feature Branch**: `001-enterprise-chatwoot-migration`
**Created**: 2026-04-09
**Status**: Draft
**Feature Directory**: `.specify/features/001-enterprise-chatwoot-migration/`

---

## Clarifications

### Session 2026-04-09

- Q: Mecanismo de rastreamento de IDs já migrados (Migration State Record) → A: Tabela `migration_state` no banco destino (`chatwoot004_dev1_db`)
- Q: Tamanho de lote (batch size) para inserção de registros → A: Lotes de 500 registros por batch
- Q: Destino do log de execução → A: Arquivo `.tmp/migration_YYYYMMDD_HHMMSS.log` + stdout simultâneo, ambos com mascaramento de dados sensíveis
- Q: Threshold mínimo de cobertura de testes unitários → A: 90% de cobertura de linhas nos módulos críticos (`pytest --cov --fail-under=90`)
- Q: Trigger e mecanismo de rollback em caso de falha catastrófica → A: Rollback manual — script registra falha no relatório e instrui o operador a restaurar o backup; sem rollback automático

### Session 2026-04-10

- Q: Política de resolução de conflito quando chave de negócio encontra match entre origem e destino → A: **Merge** — atualizar campos `NULL` no destino com valores da origem; registrar como `dedup-merged` em `migration_state`; mapear `id_origem → id_destino` para FK remapping nas entidades dependentes

- Q: Política para records com account_id inexistente na SOURCE (5.727 conversations + 70.716 messages de account_id=2 e 6 deletadas) → A: **Descartar e reportar** — SOURCE é read-only (nenhuma alteração); registros órfãos são pulados com `status='skipped-orphan-account'` em `migration_state`; FR-007 atualizado para incluir seção de registros descartados no relatório final
- Q: Tratamento de `messages.content_attributes` (23.530 registros não-nulos na SOURCE) → A: **Preservar + inspecionar** — copiar `content_attributes` exatamente como está; amostrar e documentar as estruturas únicas encontradas na seção "Amostras de content_attributes" do relatório final
- Q: Política para `contact_inboxes.source_id` (SOURCE já tem valores preenchidos; risco de colisão no DEST) → A: **Preservar com verificação prévia** — antes da migração checar colisões de `source_id` entre SOURCE e DEST; copiar apenas os sem colisão; para colisões, regenerar com `gen_random_uuid()` e registrar IDs no relatório
- Q: Tratamento de `attachments` com `external_url` ausente (26.888/26.889 na SOURCE sem URL) → A: **Copiar metadados como estão** — migrar todos os registros de `attachments` independentemente de `external_url`; documentar cobertura de URL no relatório; arquivos físicos não são movimentados
- Q: Política de remapping para accounts com IDs coincidentes entre SOURCE e DEST (id=1 "Vya Digital", id=17 "Unimed Poços PJ") → A: **Merge por nome** — accounts que já existem no DEST por `name` preservam o `id_destino` (sem offset); accounts novos recebem offset; toda a cadeia de FK downstream é remapeada usando o `id_destino` resolvido de cada account

### Insights dos SQL Scripts Legados (2026-04-10)

> Padrões extraídos de `docs/sql_code_old/` — migrações TBChat→Chatwoot pré-existentes.
> Confirmam e complementam as regras deste projeto.

- **pubsub_token = NULL**: Ambos os scripts SQL legados inserem `contact_inboxes` com `pubsub_token = null` explicitamente. Diagnóstico confirmou 4.360 colisões entre SOURCE e DEST. Regra formalizada em FR-013.
- **display_id por account**: SQL legado calcula `MAX(display_id)+1` globalmente (sem filtro por account), o que é um bug. Este projeto DEVE calcular por account, pois `display_id` é scoped por `account_id` no Chatwoot. Formalizado em FR-002 (atualizado).
- **conversations.uuid = PRESERVAR**: SQL legado gerava `gen_random_uuid()` porque a origem era um sistema externo (TBChat, sem UUID). Neste projeto a origem já é Chatwoot — UUIDs são globalmente únicos e devem ser PRESERVADOS para manter rastreabilidade. Formalizado em FR-003 (atualizado).
- **content_attributes ≠ NULL**: SQL legado inseria `content_attributes = null`. Diagnóstico confirmou 23.530 mensagens na SOURCE com conteúdo não-nulo real. Portanto `content_attributes` DEVE ser copiado tal como está — nunca zerado. Formalizado em FR-003 (atualizado).
- **sender_type/sender_id**: SQL legado mapeia `type_in_message = 'RECEIVED'` → `sender_type = 'Contact'`, caso contrário `sender_type = 'User'`. Na migração Chatwoot→Chatwoot, esses campos já estão corretamente preenchidos na SOURCE — o único tratamento necessário é o FK remapping de `sender_id` quando `sender_type IN ('Contact', 'User', 'AgentBot')`. Formalizado em FR-003 (atualizado).
- **custom_attributes com external_id**: SQL legado persiste `external_id` da origem em `custom_attributes` das conversations para idempotência e rastreabilidade. Este projeto usa `migration_state` como mecanismo primário, mas DEVE também escrever `id_origem` em `custom_attributes->>'_migration_src_id'` para consultas ad-hoc sem acesso à `migration_state`.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Executar Migração Completa de Dados (Priority: P1)

O DBA/Desenvolvedor executa `python src/migrar.py` e todos os registros de
`chatwoot_dev1_db` são inseridos em `chatwoot004_dev1_db` com IDs remapeados,
integridade referencial preservada e sem exposição de dados sensíveis em nenhum output.

**Why this priority**: É o entregável central do projeto. Sem isso, todo o demais não tem valor.

**Independent Test**: Executar o script em um ambiente de staging com cópias dos bancos;
verificar contagem pós-migração por tabela e ausência de FK violations.

**Acceptance Scenarios**:

1. **Given** chatwoot_dev1_db tem 38.868 contacts, **When** `python src/migrar.py` é executado,
   **Then** esses 38.868 contacts são inseridos em chatwoot004_dev1_db com `id >= max_id_destino + 1`,
   sem alteração nos 225.536 contacts pré-existentes.

2. **Given** contacts migrados existem no destino, **When** conversations são migradas,
   **Then** toda conversation possui `contact_id` válido no destino (zero FK violations em conversations).

3. **Given** conversations migradas existem no destino, **When** messages são migradas,
   **Then** toda message possui `conversation_id` válido no destino (zero FK violations em messages).

4. **Given** a migração completa terminou, **Then** o relatório exibe: total da origem por tabela,
   total migrado nesta execução, total acumulado no destino, lista de falhas (apenas IDs, sem conteúdo).

5. **Given** stdout é inspecionado ou logs são lidos, **Then** nenhum e-mail, nome, telefone,
   conteúdo de mensagem ou credential é visível em qualquer saída.

---

### User Story 2 — Re-execução Segura (Idempotência) (Priority: P2)

O DBA re-executa `python src/migrar.py` após uma execução parcial (falha de rede, FK violation
esporádica etc.) e apenas registros ainda não migrados são processados; registros já gravados no
destino não são duplicados.

**Why this priority**: Migrações grandes falham parcialmente. Idempotência elimina rollbacks manuais.

**Independent Test**: Executar o script até 50% da migração (interromper manualmente), re-executar;
verificar que registros da primeira execução não foram duplicados e a contagem final é idêntica à de
uma execução única sem interrupção.

**Acceptance Scenarios**:

1. **Given** o script foi executado e migrou 20.000 contacts, **When** é re-executado,
   **Then** apenas os contacts ainda não migrados são inseridos; os 20.000 anteriores não são duplicados.

2. **Given** uma FK violation interrompeu a migração de conversations no `id_origem = 99`,
   **When** o registro de estado indica esse ponto, **Then** a re-execução retoma a partir do registro
   seguinte, sem re-processar os já migrados.

3. **Given** o script é executado múltiplas vezes sem novos dados na origem, **Then** cada re-execução
   informa "0 registros novos a migrar" sem modificar o destino.

---

### User Story 3 — Consulta ao Relatório de Validação (Priority: P3)

Após a migração, o DBA lê o relatório de validação final e consegue confirmar, tabela por tabela,
se a migração foi bem-sucedida, quais registros falharam (por ID, sem conteúdo) e qual o delta total
de registros inseridos.

**Why this priority**: Auditabilidade e confirmação de sucesso sem acesso direto ao banco.

**Independent Test**: Executar o script e verificar que o relatório produzido contém todas as tabelas
migradas com contagens coerentes e sem exposição de dados de usuários.

**Acceptance Scenarios**:

1. **Given** a migração terminou, **Then** o relatório contém: `tabela | origem_total | migrado_nesta_exec | destino_total | falhas`.

2. **Given** 5 FK violations ocorreram em messages, **Then** o relatório lista os IDs que falharam
   sem exibir conteúdo das mensagens.

3. **Given** o relatório é salvo em arquivo, **Then** nenhuma linha contém e-mail, nome, telefone
   ou conteúdo de mensagem.

---

### User Story 4 — Executar POC Dry-Run de Validação (Priority: P0 — Pré-Migração)

O DBA executa `python src/migrar.py --dry-run --poc` e obtém um relatório completo de todas
as ocorrências previstas durante a migração real: quais registros seriam migrados, quais pulados
por FK órfã, quais colidiriam com dados existentes, quais já foram migrados — sem realizar
nenhuma escrita no banco destino.

**Why this priority**: Execução cega sobre 418k registros é arriscada. O POC mapeia todas as
ocorrências antecipadamente, permitindo identificar e corrigir problemas antes da migração de produção.

**Independent Test**: Executar `--dry-run --poc` com engines mockados; verificar que `POCResult`
contains classifications for each source record and the report is generated without any INSERT
or DDL in the destination database.

**Acceptance Scenarios**:

1. **Given** `chatwoot_dev1_db` tem 38.868 contacts, **When** `python src/migrar.py --dry-run --poc`
   é executado, **Then** cada contact é classificado como `WOULD_MIGRATE`, `WOULD_MIGRATE_MODIFIED`,
   `ORPHAN_FK_SKIP`, `ALREADY_MIGRATED` ou `COLLISION` — sem nenhum INSERT em `chatwoot004_dev1_db`.

2. **Given** o POC foi executado, **Then** o relatório em `.tmp/poc_YYYYMMDD_HHMMSS_report.txt`
   contém: por tabela, contagem por categoria de ocorrência e até 10 amostras de registros por
   categoria.

3. **Given** conversas com `contact_id` inválido existem na SOURCE, **Then** o POC as classifica
   como `ORPHAN_FK_SKIP` e inclui até 10 amostras, sem interromper a classificação das demais
   entidades.

4. **Given** o relatório POC é salvo em arquivo, **Then** nenhuma linha contém dado sensível
   (e-mail, nome, telefone, conteúdo de mensagem).

---

### Edge Cases

- O que acontece quando `chatwoot_dev1_db` está inacessível no momento da execução?
  → O script aborta com mensagem de erro indicando falha de conexão (sem imprimir credenciais)
  e registra o evento no log.

- O que acontece se `chatwoot004_dev1_db` tiver crescido entre duas execuções (novos registros
  chegaram após o cálculo do offset inicial)?
  → O offset é calculado uma única vez no início da sessão e mantido constante; registros novos no
  destino que cheguem durante a execução não afetam o offset de sessão, mas o estado de migração
  é atualizado para prevenir conflitos na próxima sessão.

- O que acontece com conversations/messages cujo `account_id` não existe na tabela `accounts`
  da SOURCE (account_id=2 e account_id=6, confirmados no diagnóstico)?
  → SOURCE é somente-leitura — nenhuma alteração é feita. O sistema pula esses registros,
  registra como `status='skipped-orphan-account'` em `migration_state` e inclui contagem e IDs
  na seção "Registros Descartados" do relatório final. Não é criada nenhuma account placeholder
  no destino para acomodar esses registros.

- O que acontece quando uma conversation de origem não possui `contact_id` válido (dado inconsistente
  conhecido em `chatwoot_dev1_db`)?
  → A inconsistência é registrada no relatório (apenas o ID da conversation) e o registro é pulado;
  a execução continua com os registros seguintes.

- O que acontece se o backup de `chatwoot004_dev1_db` não existir?
  → O script verifica a existência de um checkpoint de backup antes da primeira escrita e emite
  aviso ao operador; a execução pode prosseguir somente mediante confirmação explícita do operador.

- O que acontece em caso de falha catastrófica (ex: FK violation generalizada em `accounts`)?
  → O script **não executa rollback automático**. Registra a falha no relatório com IDs afetados,
  exibe mensagem clara instruindo o operador a restaurar o backup de `chatwoot004_dev1_db` antes
  de re-executar. A tabela `migration_state` preserva o estado para diagnóstico. Após restauração,
  re-execução é segura (idempotência garante isso).

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: O sistema DEVE conectar-se a `chatwoot_dev1_db` em modo somente leitura e a
  `chatwoot004_dev1_db` em modo leitura/escrita, carregando credenciais exclusivamente de
  `.secrets/generate_erd.json`.

- **FR-002**: O sistema DEVE calcular, uma única vez por sessão, o offset de ID para cada tabela
  com chave primária (`offset = max(id_destino) + 1`) e aplicá-lo a todos os registros da origem
  antes da inserção. Para `conversations.display_id`, o offset DEVE ser calculado **por account_id**
  (i.e., `MAX(display_id) + 1` filtrado por `account_id`), pois `display_id` é scoped por account
  no Chatwoot — um cálculo global causaria colisões dentro de cada account.
  **Exceção para `accounts`**: o offset não é aplicado uniformemente. O sistema resolve o
  `id_destino` de cada account por merge por `name`:
  - Account com match por `name` no DEST: usar `id_destino` existente (sem offset).
    Confirmado: `name='Vya Digital'` → id=1 em ambos; `name='Unimed Poços PJ'` → id=17 em ambos.
  - Account sem match (novo): atribuir `max(id_destino_accounts) + 1` em sequência.
    Confirmado novos: id=4 (Sol Copernico), id=18 (Unimed Poços PF), id=25 (Unimed Guaxupé).
  Toda a cadeia de FK downstream (inboxes, users, contacts, conversations, messages, attachments)
  é remapeada usando o `id_destino` resolvido de cada account, não o `id_origem`.

- **FR-003**: O sistema DEVE migrar as seguintes entidades na ordem de dependência de FK:
  `accounts` → `inboxes` → `users` → `teams` → `labels` → `contacts` →
  `conversations` → `messages` → `attachments`, com todas as FKs internas remapeadas no
  mesmo lote de inserção. Inserção realizada em batches de **500 registros**, dentro de uma
  transação por batch; falha em um batch registra os IDs afetados e continua com o próximo.
  Regras adicionais de mapeamento de campos extraídas dos scripts SQL legados:
  - `conversations.uuid`: PRESERVAR o UUID original da SOURCE (não regenerar). UUIDs Chatwoot
    são globalmente únicos — preservar mantém rastreabilidade sem risco de colisão.
  - `messages.content_attributes`: COPIAR tal como está da SOURCE (não forçar NULL).
    Diagnóstico confirmou 23.530 mensagens com conteúdo real neste campo. Durante a migração,
    o sistema DEVE coletar uma amostra das estruturas únicas encontradas (chaves de topo,
    tipos de valores) e incluí-las na seção **"Amostras de content_attributes"** do relatório
    de validação final (mascarando valores que sejam dados pessoais).
  - `messages.sender_id`: FK remap obrigatório quando `sender_type IN ('Contact', 'User', 'AgentBot')`.
    Para `sender_type = 'Contact'`: usar `contact_id` remapeado. Para `sender_type = 'User'`:
    usar `user_id` remapeado. Para outros tipos (`ApiChannel`, etc.): copiar `sender_id` sem remap.
  - `contact_inboxes.pubsub_token`: SEMPRE `NULL` na inserção (ver FR-013).
  - `contact_inboxes.source_id`: verificar colisões com o DEST **antes** da migração
    (query `SELECT source_id FROM contact_inboxes` em ambos os bancos). Registros sem
    colisão: copiar `source_id` original. Registros com colisão: regenerar com
    `gen_random_uuid()` e registrar IDs afetados na seção **"source_id Regenerados"**
    do relatório de validação.
  - Adicionar `custom_attributes->>'_migration_src_id'` com o `id` original da SOURCE em cada
    registro migrado das tabelas `contacts`, `conversations` e `messages`, para rastreabilidade
    ad-hoc sem acesso à tabela `migration_state`.

- **FR-004**: O sistema DEVE migrar os registros da tabela `attachments` como estão, incluindo
  o campo `external_url` (mesmo que vazio). Arquivos físicos no S3 NÃO devem ser
  movimentados. Diagnóstico confirmou que 26.888 de 26.889 attachments não têm `external_url`
  preenchida — isso é esperado (Chatwoot usa ActiveStorage internamente). O relatório
  DEVE incluir a cobertura de `external_url` (quantos com/sem URL).

- **FR-005**: O sistema DEVE ser idempotente e operar por estratégia de **merge**: antes de inserir
  qualquer registro, o sistema verifica se ele já existe no destino pela chave de negócio da entidade
  (ver tabela em Architecture Constraints). Há dois caminhos possíveis:
  - **Registro sem match** (novo): inserido com ID remapeado (`id_origem + offset`); registrado como
    `status='ok'` em `migration_state`.
  - **Registro com match** (deduplicado): campos `NULL` no destino são preenchidos com valores
    não-nulos da origem (_merge_); o `id_destino` existente é preservado; registrado como
    `status='dedup-merged'` em `migration_state` com o mapeamento `id_origem → id_destino` para
    uso no FK remapping das entidades dependentes.
  **Chaves de negócio por entidade (para dedução e merge-by-name):**
  | Entidade | Chave de negócio |
  |---|---|
  | accounts | `name` |
  | users | `email` |
  | inboxes | `name` + `account_id` |
  | teams | `name` + `account_id` |
  | labels | `title` + `account_id` |
  | contacts | `phone_number` (preferêncial) ou `email` |
  | conversations | `uuid` |
  | messages | `source_id` (quando não-nulo) |
  | contact_inboxes | `contact_id` + `inbox_id` |
  A tabela `migration_state` em `chatwoot004_dev1_db` rastreia todos os registros processados com
  colunas: `tabela`, `id_origem`, `id_destino`, `status` (VARCHAR: `ok` | `dedup-merged` | `failed`),
  `migrated_at`. Índice único em `(tabela, id_origem)` garante que re-execuções não reprocessem
  registros já tratados. Essa tabela é criada automaticamente na primeira execução.

- **FR-006**: Toda saída do sistema DEVE ter mascaramento automático de dados sensíveis:
  e-mails, nomes, números de telefone, conteúdo de mensagens, tokens e quaisquer valores de
  colunas identificadoras de pessoas. O log é gravado simultaneamente em stdout e em arquivo
  `.tmp/migration_YYYYMMDD_HHMMSS.log` (criado automaticamente; diretório `.tmp/` não
  versionado). Ambas as saídas passam pelo mesmo pipeline de mascaramento antes da escrita.

- **FR-007**: O sistema DEVE gerar um relatório de validação final contendo, por tabela:
  total de registros na origem, total migrado na execução atual, total acumulado no destino e
  lista de IDs com falha (sem conteúdo dos registros). O relatório DEVE incluir também:
  - Seção **"Registros Descartados"**: contagem e IDs por motivo de descarte
    (`skipped-orphan-account`, etc.). SOURCE não é modificada em nenhuma hipótese.
  - Seção **"Amostras de content_attributes"**: após migração das messages, listar as chaves
    de topo únicas encontradas e seus tipos; valores que sejam dados pessoais devem ser
    mascarados. Esta seção serve como auditoria de integridade do campo.
  - Seção **"source_id Regenerados"**: listar IDs de `contact_inboxes` cujo `source_id`
    colidiu com o DEST e foi regenerado com `gen_random_uuid()`.
  - Seção **"Cobertura de external_url em attachments"**: total com URL preenchida vs total
    sem URL, confirmando que o campo foi copiado fielmente da SOURCE.

- **FR-008**: Violações de FK durante a migração DEVEM ser registradas por ID (sem conteúdo),
  incluídas no relatório final e não devem abortar a execução completa das demais entidades.
  **Exceção**: Falha irrecuperável em `accounts` (entidade raiz de todas as FKs) DEVE abortar
  a execução com exit code 3, pois nenhuma outra entidade pode ser inserida sem um `account_id`
  válido no destino. O operador deve restaurar o backup antes de re-executar.

- **FR-009**: O sistema DEVE ser executável via `python src/migrar.py`, sem argumentos
  obrigatórios na fase inicial, em ambiente Linux com Python 3.12+.

- **FR-010**: Toda função pública DEVE ter docstring reStructuredText (`:param:`, `:type:`,
  `:returns:`, `:rtype:`, `:raises:`) e funções críticas DEVEM ter doctest executável.

- **FR-011**: Todo código DEVE passar em `ruff check` (linting) e `black --check` (formatação) antes
  de qualquer commit, com tipagem estrita em todos os parâmetros e retornos de funções públicas.

- **FR-012**: Testes unitários DEVEM cobrir no mínimo: `id_remapper`, `log_masker`,
  `fk_validator`, `connection_factory` e cada `Migrator` individualmente, com cobertura
  mínima de **90% de linhas** nesses módulos (`pytest --cov --fail-under=90`).

- **FR-013**: Durante a inserção de registros em `contact_inboxes`, o campo `pubsub_token`
  DEVE ser definido como `NULL` (nunca copiar o valor da SOURCE). Diagnóstico confirmou
  4.360 colisões de `pubsub_token` entre SOURCE e DEST — copiar causaria violação de
  constraint UNIQUE. O Chatwoot regenera o token automaticamente quando necessário.
  Scripts SQL legados (`docs/sql_code_old/`) confirmam este padrão com `pubsub_token = null`
  explícito em todos os INSERTs.
- **FR-014**: O sistema DEVE suportar o flag `--poc` (em conjunto com `--dry-run`) que ativa o
  modo de classificação sem escrita. Neste modo, cada migrator lê TODOS os registros da origem
  e classifica cada um em uma das cinco categorias definidas em `src/reports/poc_reporter.py`:
  `WOULD_MIGRATE` (inserção limpa com IDs remapeados), `WOULD_MIGRATE_MODIFIED` (FK nulável
  ausente → inserido com NULL), `ORPHAN_FK_SKIP` (FK obrigatória ausente → descartado),
  `ALREADY_MIGRATED` (já em `migration_state` → pulado), `COLLISION` (constraint única →
  violação esperada). Nenhum INSERT, UPDATE ou DDL é executado durante `--poc`.

- **FR-015**: No modo `--dry-run --poc`, o sistema DEVE coletar até 10 amostras de registros
  por categoria de ocorrência por tabela. Cada amostra contém: `id_origem`, `outcome`, `reason`
  e `masked_preview` (campos não-sensíveis; campos sensíveis mascarados conforme FR-006).

- **FR-016**: O sistema DEVE gerar o relatório POC em `.tmp/poc_YYYYMMDD_HHMMSS_report.txt`
  com: (a) tabela-resumo de contagens por categoria × tabela; (b) seção de amostras por tabela
  e categoria; (c) duração total da classificação. O relatório obedece as mesmas regras de
  mascaramento de FR-006. Nenhuma escrita no banco destino é realizada antes ou após a geração
  do relatório POC.
---

### Key Entities

- **Account**: Representa uma empresa/tenant no Chatwoot. Entidade raiz; todas as demais
  dependem dela. Possui `id` (PK), `name`, configurações de inbox.
  _Volumes_: origem = 5 / destino = 20.

- **Inbox**: Canal de atendimento associado a um Account. FK → Account.
  _Volumes_: origem = 21 / destino = 151.

- **User**: Agente ou administrador associado a um Account. FK → Account.
  _Volumes_: origem = 112 / destino = 294.

- **Team**: Grupo de usuários dentro de um Account. FK → Account.
  _Volumes_: origem = 3 / destino = 22.

- **Label**: Tag categorizadora de conversas, pertencente a um Account. FK → Account.
  _Volumes_: origem = 32 / destino = 184.

- **Contact**: Cliente/usuário final. FK → Account. Contém dados sensíveis (nome, e-mail, telefone).
  _Volumes_: origem = 38.868 / destino = 225.536.

- **Conversation**: Sessão de atendimento. FK → Contact, Inbox, Account.
  Inconsistência conhecida na origem: nem todas têm `contact_id` válido.
  _Volumes_: origem = 41.743 / destino = 153.582.

- **Message**: Mensagem individual dentro de uma Conversation. FK → Conversation, Account.
  Contém dados sensíveis (conteúdo da mensagem). Inconsistência conhecida: nem todas têm
  `conversation_id` válido na origem.
  _Volumes_: origem = 310.155 / destino = 1.302.949.

- **Attachment**: Referência a arquivo anexado, associada a uma Message.
  Apenas URLs S3 são migradas; arquivos físicos não são movimentados. FK → Message.
  _Volumes_: origem = 26.889 / destino = 73.435.

- **Migration State Record**: Tabela `migration_state` criada em `chatwoot004_dev1_db` na
  primeira execução do script. Colunas: `tabela` (VARCHAR), `id_origem` (BIGINT), `id_destino`
  (BIGINT), `status` (VARCHAR: 'ok'|'failed'), `migrated_at` (TIMESTAMP). Índice único em
  `(tabela, id_origem)` garante idempotência. Consultável via SQL para diagnóstico.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% dos registros de `chatwoot_dev1_db` com `account_id` válido inseridos em
  `chatwoot004_dev1_db` ao final da execução. Registros com `account_id` inexistente na tabela
  `accounts` da SOURCE (account_id=2: 5.727 conversations + 70.716 messages; account_id=6 incluso)
  são descartados e documentados no relatório — não constituem falha de migração.
  Volumes esperados após exclusão de órfãos: conversations=36.016, messages=239.439.

- **SC-002**: Zero violações de FK verificadas por consulta direta ao banco destino após a
  migração completa (todo `contact_id` em conversations e todo `conversation_id` em messages
  existem no destino).

- **SC-003**: Contagem de registros pré-existentes em `chatwoot004_dev1_db` permanece inalterada
  após a migração (nem um registro existente foi modificado ou removido).

- **SC-004**: O script completa a migração dos ~690.000 registros totais em menos de 2 horas
  em execução local com conexão à VPS `wfdb02.vya.digital`.

- **SC-005**: Re-execução do script sobre o mesmo destino produz "0 novos registros" sem erros,
  confirmando idempotência completa.

- **SC-006**: Nenhuma linha de log, stdout ou relatório contém dado sensível (verificável por
  grep de padrões de e-mail, telefone português/brasileiro ou palavras de conteúdo de mensagens).

- **SC-007**: O relatório de validação final exibe contagens coerentes em ≤ 30 segundos após o
  término da migração, com todas as tabelas incluídas.

- **SC-008**: Todo o código-fonte passa em `ruff check` e `black --check` sem erros e atinge
  cobertura mínima de **90% de linhas** nos módulos críticos listados em FR-012
  (`pytest --cov --fail-under=90`).

---

## Architecture Constraints *(from Constitution)*

> As restrições abaixo são **NÃO-NEGOCIÁVEIS** conforme definidas na
> [Constitution](.specify/memory/constitution.md).

- **Fabric Design Pattern**: Todo código DEVE usar Factory + Repository. Nenhum script
  procedural top-level fora de `src/migrar.py`.

- **ConnectionFactory**: Conexões com banco criadas exclusivamente via `factory/connection_factory.py`.

- **Migrator isolados**: Cada entidade tem seu próprio `Migrator` testável de forma independente.

- **Somente leitura**: `chatwoot_dev1_db` — nenhuma escrita ou DDL é permitida.

- **Credenciais**: Carregadas de `.secrets/generate_erd.json` — nunca impressas, logadas
  ou versionadas.

- **Mascaramento automático**: `utils/log_masker.py` DEVE interceptar qualquer valor de coluna
  de dados antes de qualquer output.

- **Offset constante por sessão**: Calculado uma única vez no início; mantido constante durante
  toda a execução.

---

## Assumptions

- Os schemas de `chatwoot_dev1_db` e `chatwoot004_dev1_db` são estruturalmente idênticos
  (schema_sha1 = `da6b4a366d550dc7794f55f5e1536342ce50845f`, confirmado em 2026-04-09).
  As 3 migrations extras em `chatwoot004_dev1_db` (total 255 vs 252) não introduzem colunas
  ou tabelas incompatíveis com `chatwoot_dev1_db`.

- Os dados das duas instâncias pertencem a empresas/clientes completamente distintos — não há
  sobreposição de registros entre as bases que exija deduplicação lógica.

- O backup de `chatwoot004_dev1_db` está disponível e válido para rollback, conforme confirmado
  pelo owner antes do início da migração.

- No ambiente DEV, as URLs de S3 presentes nas referências de attachments são suficientes para
  uso futuro; os arquivos físicos no S3 não precisam ser movimentados.

- O operador executa o script a partir de uma máquina com Python 3.12+, acesso de rede à porta
  5432 de `wfdb02.vya.digital` e o arquivo `.secrets/generate_erd.json` presente localmente.

- As inconsistências conhecidas em `chatwoot_dev1_db` (conversations sem `contact_id`, messages
  sem `conversation_id`) são migradas no estado atual, sem correção, registradas no relatório.

- Downtime parcial do ambiente DEV é aceitável durante a execução da migração.

---

## Dependencies & Prerequisites

| Prerequisite | Status | Evidence |
|---|---|---|
| Credenciais `.secrets/generate_erd.json` | ✅ Pronto | Confirmado pelo owner |
| Python 3.12 + `pyproject.toml` / `uv` | ✅ Pronto | `pyproject.toml` na raiz |
| Backup de `chatwoot004_dev1_db` | ✅ Pronto | Confirmado pelo owner |
| Schema SHA1 idêntico (D1) | ✅ Resolvido | `scripts/check_chatwoot_versions.py` — 2026-04-09 |
| Acesso de rede a `wfdb02.vya.digital:5432` | ✅ Pronto | Testado via scripts ERD |
| Decisão sobre destino final de `chatwoot_dev1_db` (D2) | ⏳ Pendente | Aguardando owner |

---

## Out of Scope

- Modificação de qualquer código da aplicação Chatwoot
- Movimentação física de arquivos no S3
- Criação de interface web ou API para a ferramenta de migração
- Alteração do banco `chatwoot_dev1_db` (somente leitura em toda esta fase)
- Migração de configurações da aplicação (env vars, settings, secrets do Chatwoot)
- Migração de ambiente de produção nesta fase (somente DEV)
- Correção de inconsistências de dados em `chatwoot_dev1_db` (migrar no estado atual)

---

## Data Volumes Summary

| Entidade | Origem (`chatwoot_dev1_db`) | Destino (`chatwoot004_dev1_db`) |
|---|---|---|
| accounts | 5 | 20 |
| inboxes | 21 | 151 |
| users | 112 | 294 |
| teams | 3 | 22 |
| labels | 32 | 184 |
| contacts | 38.868 | 225.536 |
| conversations | 41.743 | 153.582 |
| messages | 310.155 | 1.302.949 |
| attachments | 26.889 | 73.435 |
| **TOTAL** | **~418.828** | **~1.756.173** |

---

## Security & Compliance

- **Classificação**: Confidencial — LGPD se aplica ao processo de migração.
- **Dados sensíveis**: e-mails, nomes, telefones, conteúdo de mensagens, tokens.
- **Mascaramento**: Obrigatório em stdout, logs de arquivo e relatório de validação.
- **Credenciais**: Exclusivamente via `.secrets/generate_erd.json` (não versionado).
- **Auditoria**: Log de execução em `.tmp/migration_YYYYMMDD_HHMMSS.log` + stdout simultâneo.
  Inclui: tabela processada, contagem de registros por lote, IDs com falha (sem conteúdo),
  timestamp de início/fim de cada entidade. Nenhuma linha contém dado sensível.

---

## Next Steps

1. `/speckit.plan` — Decompor em tarefas técnicas ordenadas por dependência de FK
2. Implementar `connection_factory.py` + testes
3. Implementar `id_remapper.py` + testes + doctest
4. Implementar `log_masker.py` + testes
5. Implementar Migrators por entidade (ordem: accounts → inboxes → users → teams → labels → contacts → conversations → messages → attachments)
6. Implementar `validation_reporter.py`
7. Integração: `src/migrar.py` como entrypoint
8. Execução em staging → validação → execução em DEV
