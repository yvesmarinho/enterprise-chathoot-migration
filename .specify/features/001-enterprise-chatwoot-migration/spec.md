# Feature Specification: Enterprise Chatwoot Migration

**Feature Branch**: `001-enterprise-chatwoot-migration`
**Created**: 2026-04-09
**Status**: Draft
**Feature Directory**: `.specify/features/001-enterprise-chatwoot-migration/`

---

## Clarifications

### Session 2026-04-09

- Q: Mecanismo de rastreamento de IDs já migrados (Migration State Record) → A: Tabela `migration_state` no banco destino (`chatwoot004_dev_db`)
- Q: Tamanho de lote (batch size) para inserção de registros → A: Lotes de 500 registros por batch
- Q: Destino do log de execução → A: Arquivo `.tmp/migration_YYYYMMDD_HHMMSS.log` + stdout simultâneo, ambos com mascaramento de dados sensíveis
- Q: Threshold mínimo de cobertura de testes unitários → A: 90% de cobertura de linhas nos módulos críticos (`pytest --cov --fail-under=90`)
- Q: Trigger e mecanismo de rollback em caso de falha catastrófica → A: Rollback manual — script registra falha no relatório e instrui o operador a restaurar o backup; sem rollback automático

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Executar Migração Completa de Dados (Priority: P1)

O DBA/Desenvolvedor executa `python src/migrar.py` e todos os registros de
`chatwoot_dev_db` são inseridos em `chatwoot004_dev_db` com IDs remapeados,
integridade referencial preservada e sem exposição de dados sensíveis em nenhum output.

**Why this priority**: É o entregável central do projeto. Sem isso, todo o demais não tem valor.

**Independent Test**: Executar o script em um ambiente de staging com cópias dos bancos;
verificar contagem pós-migração por tabela e ausência de FK violations.

**Acceptance Scenarios**:

1. **Given** chatwoot_dev_db tem 38.868 contacts, **When** `python src/migrar.py` é executado,
   **Then** esses 38.868 contacts são inseridos em chatwoot004_dev_db com `id >= max_id_destino + 1`,
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

### Edge Cases

- O que acontece quando `chatwoot_dev_db` está inacessível no momento da execução?
  → O script aborta com mensagem de erro indicando falha de conexão (sem imprimir credenciais)
  e registra o evento no log.

- O que acontece se `chatwoot004_dev_db` tiver crescido entre duas execuções (novos registros
  chegaram após o cálculo do offset inicial)?
  → O offset é calculado uma única vez no início da sessão e mantido constante; registros novos no
  destino que cheguem durante a execução não afetam o offset de sessão, mas o estado de migração
  é atualizado para prevenir conflitos na próxima sessão.

- O que acontece quando uma conversation de origem não possui `contact_id` válido (dado inconsistente
  conhecido em `chatwoot_dev_db`)?
  → A inconsistência é registrada no relatório (apenas o ID da conversation) e o registro é pulado;
  a execução continua com os registros seguintes.

- O que acontece se o backup de `chatwoot004_dev_db` não existir?
  → O script verifica a existência de um checkpoint de backup antes da primeira escrita e emite
  aviso ao operador; a execução pode prosseguir somente mediante confirmação explícita do operador.

- O que acontece em caso de falha catastrófica (ex: FK violation generalizada em `accounts`)?
  → O script **não executa rollback automático**. Registra a falha no relatório com IDs afetados,
  exibe mensagem clara instruindo o operador a restaurar o backup de `chatwoot004_dev_db` antes
  de re-executar. A tabela `migration_state` preserva o estado para diagnóstico. Após restauração,
  re-execução é segura (idempotência garante isso).

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: O sistema DEVE conectar-se a `chatwoot_dev_db` em modo somente leitura e a
  `chatwoot004_dev_db` em modo leitura/escrita, carregando credenciais exclusivamente de
  `.secrets/generate_erd.json`.

- **FR-002**: O sistema DEVE calcular, uma única vez por sessão, o offset de ID para cada tabela
  com chave primária (`offset = max(id_destino) + 1`) e aplicá-lo a todos os registros da origem
  antes da inserção.

- **FR-003**: O sistema DEVE migrar as seguintes entidades na ordem de dependência de FK:
  `accounts` → `inboxes` → `users` → `teams` → `labels` → `contacts` →
  `conversations` → `messages` → `attachments`, com todas as FKs internas remapeadas no
  mesmo lote de inserção. Inserção realizada em batches de **500 registros**, dentro de uma
  transação por batch; falha em um batch registra os IDs afetados e continua com o próximo.

- **FR-004**: O sistema DEVE migrar apenas as referências (URLs) de attachments S3; arquivos
  físicos no S3 NÃO devem ser movimentados.

- **FR-005**: O sistema DEVE ser idempotente: re-execução sobre o mesmo destino não deve
  produzir registros duplicados. A tabela `migration_state` em `chatwoot004_dev_db` rastreia
  quais IDs da origem já foram inseridos no destino, com colunas: `tabela`, `id_origem`,
  `id_destino`, `status`, `migrated_at`. Essa tabela é criada automaticamente na primeira execução.

- **FR-006**: Toda saída do sistema DEVE ter mascaramento automático de dados sensíveis:
  e-mails, nomes, números de telefone, conteúdo de mensagens, tokens e quaisquer valores de
  colunas identificadoras de pessoas. O log é gravado simultaneamente em stdout e em arquivo
  `.tmp/migration_YYYYMMDD_HHMMSS.log` (criado automaticamente; diretório `.tmp/` não
  versionado). Ambas as saídas passam pelo mesmo pipeline de mascaramento antes da escrita.

- **FR-007**: O sistema DEVE gerar um relatório de validação final contendo, por tabela:
  total de registros na origem, total migrado na execução atual, total acumulado no destino e
  lista de IDs com falha (sem conteúdo dos registros).

- **FR-008**: Violações de FK durante a migração DEVEM ser registradas por ID (sem conteúdo),
  incluídas no relatório final e não devem abortar a execução completa das demais entidades.

- **FR-009**: O sistema DEVE ser executável via `python src/migrar.py`, sem argumentos
  obrigatórios na fase inicial, em ambiente Linux com Python 3.12+.

- **FR-010**: Toda função pública DEVE ter docstring reStructuredText (`:param:`, `:type:`,
  `:returns:`, `:rtype:`, `:raises:`) e funções críticas DEVEM ter doctest executável.

- **FR-011**: Todo código DEVE passar em `ruff check` (linting) e `black --check` (formatação) antes
  de qualquer commit, com tipagem estrita em todos os parâmetros e retornos de funções públicas.

- **FR-012**: Testes unitários DEVEM cobrir no mínimo: `id_remapper`, `log_masker`,
  `fk_validator`, `connection_factory` e cada `Migrator` individualmente, com cobertura
  mínima de **90% de linhas** nesses módulos (`pytest --cov --fail-under=90`).

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

- **Migration State Record**: Tabela `migration_state` criada em `chatwoot004_dev_db` na
  primeira execução do script. Colunas: `tabela` (VARCHAR), `id_origem` (BIGINT), `id_destino`
  (BIGINT), `status` (VARCHAR: 'ok'|'failed'), `migrated_at` (TIMESTAMP). Índice único em
  `(tabela, id_origem)` garante idempotência. Consultável via SQL para diagnóstico.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% dos registros de `chatwoot_dev_db` (accounts=5, contacts=38.868,
  conversations=41.743, messages=310.155, inboxes=21, users=112, teams=3, labels=32,
  attachments=26.889) inseridos em `chatwoot004_dev_db` ao final da execução.

- **SC-002**: Zero violações de FK verificadas por consulta direta ao banco destino após a
  migração completa (todo `contact_id` em conversations e todo `conversation_id` em messages
  existem no destino).

- **SC-003**: Contagem de registros pré-existentes em `chatwoot004_dev_db` permanece inalterada
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

- **Somente leitura**: `chatwoot_dev_db` — nenhuma escrita ou DDL é permitida.

- **Credenciais**: Carregadas de `.secrets/generate_erd.json` — nunca impressas, logadas
  ou versionadas.

- **Mascaramento automático**: `utils/log_masker.py` DEVE interceptar qualquer valor de coluna
  de dados antes de qualquer output.

- **Offset constante por sessão**: Calculado uma única vez no início; mantido constante durante
  toda a execução.

---

## Assumptions

- Os schemas de `chatwoot_dev_db` e `chatwoot004_dev_db` são estruturalmente idênticos
  (schema_sha1 = `da6b4a366d550dc7794f55f5e1536342ce50845f`, confirmado em 2026-04-09).
  As 3 migrations extras em `chatwoot004_dev_db` (total 255 vs 252) não introduzem colunas
  ou tabelas incompatíveis com `chatwoot_dev_db`.

- Os dados das duas instâncias pertencem a empresas/clientes completamente distintos — não há
  sobreposição de registros entre as bases que exija deduplicação lógica.

- O backup de `chatwoot004_dev_db` está disponível e válido para rollback, conforme confirmado
  pelo owner antes do início da migração.

- No ambiente DEV, as URLs de S3 presentes nas referências de attachments são suficientes para
  uso futuro; os arquivos físicos no S3 não precisam ser movimentados.

- O operador executa o script a partir de uma máquina com Python 3.12+, acesso de rede à porta
  5432 de `wfdb02.vya.digital` e o arquivo `.secrets/generate_erd.json` presente localmente.

- As inconsistências conhecidas em `chatwoot_dev_db` (conversations sem `contact_id`, messages
  sem `conversation_id`) são migradas no estado atual, sem correção, registradas no relatório.

- Downtime parcial do ambiente DEV é aceitável durante a execução da migração.

---

## Dependencies & Prerequisites

| Prerequisite | Status | Evidence |
|---|---|---|
| Credenciais `.secrets/generate_erd.json` | ✅ Pronto | Confirmado pelo owner |
| Python 3.12 + `pyproject.toml` / `uv` | ✅ Pronto | `pyproject.toml` na raiz |
| Backup de `chatwoot004_dev_db` | ✅ Pronto | Confirmado pelo owner |
| Schema SHA1 idêntico (D1) | ✅ Resolvido | `scripts/check_chatwoot_versions.py` — 2026-04-09 |
| Acesso de rede a `wfdb02.vya.digital:5432` | ✅ Pronto | Testado via scripts ERD |
| Decisão sobre destino final de `chatwoot_dev_db` (D2) | ⏳ Pendente | Aguardando owner |

---

## Out of Scope

- Modificação de qualquer código da aplicação Chatwoot
- Movimentação física de arquivos no S3
- Criação de interface web ou API para a ferramenta de migração
- Alteração do banco `chatwoot_dev_db` (somente leitura em toda esta fase)
- Migração de configurações da aplicação (env vars, settings, secrets do Chatwoot)
- Migração de ambiente de produção nesta fase (somente DEV)
- Correção de inconsistências de dados em `chatwoot_dev_db` (migrar no estado atual)

---

## Data Volumes Summary

| Entidade | Origem (`chatwoot_dev_db`) | Destino (`chatwoot004_dev_db`) |
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
