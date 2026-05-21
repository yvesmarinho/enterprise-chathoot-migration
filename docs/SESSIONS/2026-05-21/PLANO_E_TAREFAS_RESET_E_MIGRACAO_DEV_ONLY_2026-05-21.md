# Plano e Lista de Tarefas — Reset de Destino + Revisão Profunda da Migração (DEV-only)

**Data**: 2026-05-21
**Solicitante**: usuário
**Contexto**: Remover do destino (`chatwoot004_db`) os dados oriundos da origem (`chatwoot_db`), revisar profundamente o workflow de migração e operar somente em ambiente DEV até segunda ordem.

---

## 1. Objetivo do Plano

1. Limpar do banco destino os dados importados da origem com segurança e rastreabilidade.
2. Revisar end-to-end todo o pipeline de migração (código, ordem, idempotência, validações, observabilidade).
3. Bloquear execução em produção e padronizar operação exclusivamente em DEV até autorização explícita.
4. Garantir próxima execução com cobertura total dos dados e validação funcional no front/API/DB.

---

## 2. Premissas e Restrições

1. Operações destrutivas exigem backup e plano de rollback validado.
2. O banco origem tem mais dados (uso contínuo em `chat.vya.digital`), portanto não usar comparação ingênua por volume absoluto no destino.
3. A limpeza deve ser seletiva para dados migrados (evitar remoção indevida de dados nativos do destino).
4. Até segunda ordem, qualquer execução deve usar chaves DEV (`chatwoot_dev` -> `chatwoot004_dev`) e não pode apontar para produção.
5. Para identificação de entidades (account/inbox/contact/conversation), usar ID como chave canônica; nome é apenas validação auxiliar e não critério único de decisão.

---

## 3. Estratégia de Execução (Fases)

### Fase A — Segurança Operacional e Congelamento de Ambiente

1. Ativar modo DEV-only no workflow:
- Falhar execução se `MIGRATION_DEST_KEY` for diferente de `chatwoot004_dev`.
- Falhar execução se `MIGRATION_SOURCE_KEY` for diferente de `chatwoot_dev`.
- Falhar execução se `MIGRATION_ENV=prod`.

2. Preparar guardrails de execução:
- Banner explícito de ambiente efetivo (host, database, source_key, dest_key).
- Confirmação obrigatória para operações de limpeza.

3. Capturar baseline antes da limpeza:
- Snapshot de contagens por tabela/account no destino.
- Snapshot de integridade FK e cobertura de `src_id`.

### Fase B — Modelagem de Limpeza Seletiva

1. Identificar critérios robustos de “dado importado”:
- `custom_attributes->>'src_id'` (quando existir).
- Mapeamentos no `migration_state` (quando existir e estiver consistente).
- Chaves de negócio por entidade (account/inbox/contact/conversation/message/attachment).

2. Definir política de limpeza por entidade:
- Ordem reversa de dependência FK (filhos -> pais).
- Soft-delete lógico quando aplicável; hard-delete somente com regra documentada.
- Exclusão restrita ao escopo migrado, nunca por truncates globais sem critério.

3. Executar dry-run da limpeza:
- Relatório com quantidades previstas para remoção por tabela.
- Lista de riscos (colisões, órfãos, lacunas de rastreabilidade).

### Fase C — Execução da Limpeza

1. Backup obrigatório do destino antes da remoção.
2. Execução em lotes transacionais com checkpoints.
3. Geração de relatório final de limpeza (before/after por tabela/account).
4. Validação pós-limpeza:
- Integridade referencial.
- Ausência de resíduos migrados no escopo alvo.

### Fase D — Revisão Profunda do Código de Migração

1. Revisão estática do workflow completo (entrada -> remap -> persistência -> validação):
- `docker/entrypoint.sh`
- `docker/docker-compose.yml`
- `docker/deploy-to-wfdb01.sh`
- `app/migrate_all_accounts.py`
- `app/01_migrar_account.py`
- `src/migrar.py`
- migrators em `src/migrators/`
- validações em `src/utils/` e `src/reports/`

2. Pontos obrigatórios de revisão:
- Ler o arquivo `migration_state` e separar estado por ambiente (`DEV`/`PROD`) e por par `source_key`->`dest_key`, mantendo IDs como chaves primárias de rastreio.
- Validar inconsistências entre ID e nome com regra explícita: prevalece o ID autoritativo (`source_id` para rastreio de origem e `dest_id` para persistência local), e toda divergência deve ser registrada em log estruturado/relatório de auditoria (entidade, source_key, dest_key, source_id, dest_id, nome_origem, nome_destino, decisão aplicada).
- Resolução de ambiente e destino efetivo.
- Ordem de migração e dependências FK.
- Cobertura de entidades críticas (incluindo visibilidade em front: account_users, inbox_members, etc.).
- Idempotência real em re-runs.
- Deduplicação e remapeamento de IDs/chaves de negócio.
- Logs auditáveis e diagnósticos reproduzíveis.

3. Revisão dinâmica (execução controlada em DEV):
- Dry-run completo.
- Run real em conta piloto.
- Validação DB + API + front com critérios de aceite.

### Fase E — Reexecução da Migração em DEV e Homologação

1. Rodar pipeline revisado apenas em DEV.
2. Validar totalidade dos dados no escopo definido por account.
3. Validar funcionalidade no front (contadores, filtros, visibilidade por perfil).
4. Publicar relatório de homologação com GO/NO-GO.

---

## 4. Lista de Tarefas (Executável)

## P0 — Bloqueadores de Segurança

- [ ] T1 — Implementar bloqueio DEV-only no entrypoint e scripts de execução.
- [ ] T2 — Adicionar validação obrigatória de destino efetivo (host/database/keys) em runtime.
- [ ] T3 — Criar checklist de pré-execução destrutiva (backup, janela, rollback).

## P0 — Limpeza Seletiva

- [ ] T4 — Definir SQL de identificação de dados migrados por tabela.
- [ ] T5 — Implementar script de dry-run de limpeza com relatório JSON.
- [ ] T6 — Revisar resultado do dry-run e aprovar escopo final de remoção.
- [ ] T7 — Executar limpeza real com transações e checkpoints.
- [ ] T8 — Validar pós-limpeza (FK, contagens, resíduos).

## P0 — Revisão Profunda de Código

- [ ] T9 — Revisar fluxo operacional docker (compose/deploy/entrypoint) e defaults perigosos.
- [ ] T10 — Revisar fluxo legado (`app/01` e `app/migrate_all_accounts.py`) ponta a ponta.
- [ ] T11 — Revisar fluxo novo (`src/migrar.py` + migrators) ponta a ponta.
- [ ] T12 — Revisar consistência de validações (DB/API/front), política `ID > nome` e gaps de observabilidade.
- [ ] T13 — Emitir relatório técnico de revisão com falhas, severidade e correções.

## P1 — Correções e Endurecimento

- [ ] T14 — Corrigir itens críticos identificados na revisão.
- [ ] T15 — Adicionar testes de regressão para mapeamento, dedup e idempotência.
- [ ] T16 — Padronizar saída de relatórios (JSON) com metadados de ambiente.

## P1 — Homologação em DEV

- [ ] T17 — Executar migração piloto em DEV com conta alvo.
- [ ] T18 — Validar totalidade: origem x destino por entidade e por account.
- [ ] T19 — Validar funcionalidade no front por perfil (admin/agent) e filtros de inbox.
- [ ] T20 — Publicar relatório final de homologação DEV-only.

---

## 5. Critérios de Aceite

1. Nenhuma execução em produção durante o ciclo (hard gate DEV-only ativo).
2. Limpeza seletiva concluída com relatório before/after e sem quebra de integridade.
3. Revisão de código concluída com evidência por arquivo e plano de correção aplicado.
4. Migração em DEV homologada com cobertura total no escopo definido.
5. Relatório final publicado com riscos residuais e decisão GO/NO-GO.

---

## 6. Dúvidas/Confirmações Necessárias

1. **Escopo exato da limpeza**: remover somente dados migrados anteriormente da origem, preservando dados nativos do destino?
2. **Base alvo da limpeza**: confirmar se a limpeza solicitada é no `chatwoot004_db` (prod) agora, ou se devemos executar o mesmo procedimento somente no `chatwoot004_dev1_db` dado o modo DEV-only.
3. **Modelo de remoção**: preferir hard-delete físico ou estratégia híbrida (soft-delete quando disponível + hard-delete seletivo)?
4. **Janela operacional**: há janela de manutenção definida para operação destrutiva e validação posterior?
5. **Escopo funcional de homologação**: validar somente Guaxupé primeiro ou todas as contas do plano em DEV?

---

## 7. Próxima Ação Recomendada

Após sua confirmação das dúvidas acima, iniciar imediatamente pela **Fase A (guardrails DEV-only)** e pela **Fase B (dry-run de limpeza seletiva)** antes de qualquer remoção real.
