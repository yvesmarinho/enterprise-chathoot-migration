# 📋 Daily Activities — 2026-05-21

**Branch**: `master`
**Modo**: PROGRAMMING
**Objetivo**: análise da migração DEV que ocorreu ontem

---

<!-- Atividades serão adicionadas incrementalmente abaixo -->

---

### Ritual de Início de Sessão (S22-START)

**Data/Hora da execução — ✅ COMPLETO (com ressalvas de estrutura)**

**Objetivo**: Executar o ritual de início de sessão conforme `.github/prompts/session-start.prompt.md`.
**Contexto**: Continuidade direta da Sessão 21 (2026-05-20), com foco em migração all-accounts e pendências D16.

**Passos executados**:
1. Verificado `.vscode/mcp.json`: `memory` e `sequential-thinking` configurados e ativos em arquivo.
2. Contexto recuperado de `docs/TODO.md`, `docs/INDEX.md`, `docs/SESSIONS/2026-05-20/FINAL_STATUS_2026-05-20.md` e `docs/SESSIONS/2026-05-20/DAILY_ACTIVITIES_2026-05-20.md`.
3. Regras carregadas de `.github/copilot-instructions.md` e dos arquivos `.copilot-rules-enterprise-*.md` (arquivo `.copilot-rules.md` não encontrado no workspace).
4. Scan de segurança executado por padrões de arquivos sensíveis; `.secrets/` confirmado no `.gitignore`.
5. Estado Git verificado: branch `master`, working tree limpo, últimos 5 commits revisados.
6. Criados documentos de sessão: `SESSION_RECOVERY_2026-05-21.md` e `DAILY_ACTIVITIES_2026-05-21.md`.
7. TODO atualizado com P0 da Sessão 22 (`S22-P0-1..3`).

**Resultado**: Ritual executado e sessão pronta para trabalho efetivo; pendente apenas declaração formal de modo/objetivo pelo usuário.

**Status**: ✅ Completo

---

### Execução da Coleta Produção — chat vs synchat (S22-05)

**Objetivo**: Executar coleta automática em produção da forma mais útil para investigação, com recorte global e recorte da Guaxupé.

**Passos executados**:
1. Executado coletor global (`.tmp/collect_chat_synchat_prod_data.py`) sem filtros.
2. Executado coletor focado em account_id=25 (Guaxupé) com amostra de 30 conversas.
3. Lidos os snapshots JSON gerados em `.tmp/`.

**Resultado**:
- Snapshot global e snapshot da Guaxupé gerados com sucesso.
- No ambiente de coleta atual, os snapshots retornaram `source.database=chatwoot_db` e `dest.database=chatwoot_db` com contagens idênticas (diff=0), indicando que as chaves de conexão usadas nesta execução apontaram para o mesmo banco físico.
- Recorte Guaxupé (account_id=25): 1 inbox, 1.513 contacts, 8.190 conversations, 46.010 messages, 1.932 attachments.

**Status**: ✅ Completo

---

### Fechamento da Investigação — Evidência front chat x synchat (S22-06)

**Objetivo**: Encerrar investigação com base nos dados de front fornecidos pelo usuário e corrigir conclusões ambíguas da análise anterior.

**Passos executados**:
1. Recarregadas regras `copilot-rules` solicitadas pelo usuário.
2. Lidas evidências HTTP completas de `.tmp/chat-vya-digital-header-get.txt` e `.tmp/synchat-vya-digital-header-get.txt`.
3. Consolidado relatório técnico formal com causa raiz, impacto, erro operacional da investigação e ações corretivas.

**Resultado**:
- Front confirma: origem `chat` account 25 com `all_count=8190`.
- Front confirma: destino `synchat` account 45 com `all_count=112`.
- Investigação formal concluída com explicação de divergência de contexto de banco/tenant entre runs e validação de UI.

**Artefato**:
- `docs/SESSIONS/2026-05-21/INVESTIGACAO_GUAXUPE_CHAT_SYNCHAT_2026-05-21.md`

**Status**: ✅ Completo

---

### Planejamento solicitado — Reset + Revisão Profunda + DEV-only (S22-07)

**Objetivo**: Gerar plano faseado e lista de tarefas executável para limpeza de dados no destino, revisão profunda do workflow e operação DEV-only até segunda ordem.

**Passos executados**:
1. Consolidado plano por fases (A..E) com gates de segurança e critérios de aceite.
2. Gerada lista de tarefas priorizada (P0/P1) cobrindo limpeza seletiva, revisão de código e homologação em DEV.
3. Registradas dúvidas críticas para confirmação antes de execução destrutiva.

**Artefato**:
- `docs/SESSIONS/2026-05-21/PLANO_E_TAREFAS_RESET_E_MIGRACAO_DEV_ONLY_2026-05-21.md`

**Status**: ✅ Completo (aguarda confirmação das dúvidas de escopo)

---

### Análise Técnica — Unimed Guaxupé não aparece no app (S22-01)

**Objetivo**: Determinar se o problema atual da Unimed Guaxupé é ausência de migração de dados ou falha de visibilidade no Chatwoot.
**Contexto**: Usuário reportou que demais accounts estão acessíveis (incluindo conversas), mas Unimed Guaxupé não aparece corretamente.

**Passos executados**:
1. Revisão dos artefatos de sessão S19/S20/S21 para confirmar status real da migração DEV da Guaxupé.
2. Leitura do debate D16 (HTTP500 pós-migração) e final status S21.
3. Inspeção do pipeline atual `src/migrar.py` e migrators críticos (`users`, `inboxes`, `team_members`).
4. Inspeção do script legado `app/13_migrar_inbox_members.py` e verificação de cobertura de `inbox_members` no pipeline novo.

**Resultado**:
- Evidência documental confirma migração DEV da Guaxupé com contagens 100% (conversations/messages/contacts/attachments) em S19.
- D16 confirma causa raiz de HTTP500 para account_id=69/inbox_id=526: attachments sem vínculo em ActiveStorage (`active_storage_attachments`/`active_storage_blobs`).
- Pipeline novo `src/migrar.py` **não** contém etapa `inbox_members`; visibilidade para agentes pode falhar se membros de inbox não existirem no DEST.
- Script legado `app/13_migrar_inbox_members.py` ainda depende de `migration_state` e pode permanecer bloqueado em cenários sem esse estado.

**Conclusão técnica desta etapa**: forte evidência de que os dados foram migrados, e o sintoma atual é predominantemente de aplicação/permissão (HTTP500 e/ou ausência de inbox_members), não de ausência de dados na origem.

**Status**: ✅ Completo

---

### Diagnóstico Conclusivo — Estado atual do DEV DB (S22-02)

**Objetivo**: Validar, com evidência direta no banco atual, se a account da Unimed Guaxupé existe no DEST e se o problema é migração vs visibilidade.
**Contexto**: Havia divergência entre histórico de sessões anteriores (account 69 presente) e sintoma atual reportado pelo usuário.

**Passos executados**:
1. Script `.tmp/diagnostico_guaxupe_visibilidade_20260521.py` executado contra `chatwoot004_dev1_db`.
2. Script `.tmp/diagnostico_guaxupe_env_20260521.py` executado para confirmar chave/env resolvida e banco destino efetivo.
3. Script `.tmp/diagnostico_accounts_dev1_20260521.py` executado para snapshot completo de accounts e volumes no banco atual.

**Resultado**:
- Banco destino ativo confirmado: `chatwoot004_dev1_db`.
- Account alvo esperada (`account_id=69`, Guaxupé) **não existe** nesta base (contagens zeradas para account/inbox 69/526).
- A base contém 19 accounts com conversas (IDs 1..44 em uso), confirmando que o ambiente está funcional para outras contas.
- Conclusão operacional: no estado atual do `chatwoot004_dev1_db`, a Guaxupé **não foi migrada (ou foi removida por restore)**; portanto o sintoma atual é de ausência de dados dessa account nesta base específica.

**Status**: ✅ Completo

---

### Coleta de Evidência — Container parado no wfdb01 (S22-03)

**Objetivo**: Coletar logs e variáveis de execução do container `chatwoot-migrator-all` parado no wfdb01 para explicar divergência entre cenário atual e histórico.

**Passos executados**:
1. Coleta de status e exit code via `docker ps -a` + `docker inspect` no wfdb01.
2. Coleta dos últimos logs via `docker logs --tail 250 chatwoot-migrator-all`.
3. Extração das variáveis de ambiente efetivas do container via `docker inspect`.

**Resultado**:
- Container parado com **exit=0** (execução concluída com sucesso).
- Log confirma execução da Guaxupé sem falha (`Conversations: 4.095 inseridas`, `Messages: 23.005 inseridas`, status OK).
- Config efetiva do container:
	- `MIGRATION_SOURCE_KEY=chat-vya-digital`
	- `MIGRATION_DEST_KEY=synchat-vya-digital`
	- `MIGRATION_ENV=prod`
	- `ALL_ACCOUNTS=true`
	- `PIPELINE=` (vazio; entrypoint resolve para legado em all-accounts)

**Conclusão técnica desta etapa**:
O run coletado no wfdb01 não escreveu no destino DEV (`chatwoot004_dev1_db`) usado no diagnóstico local; escreveu no destino de produção configurado por chave (`synchat-vya-digital`). Isso explica por que Guaxupé aparece processada no log remoto e, ao mesmo tempo, não existe na base DEV atual.

**Status**: ✅ Completo

---

### Ferramenta de Coleta — chat + synchat produção (S22-04)

**Objetivo**: Gerar script Python reutilizável para coletar dados comparativos entre `chat-vya-digital` (SOURCE) e `synchat-vya-digital` (DEST) usando credenciais de `.secrets/generate_erd.json`.

**Passos executados**:
1. Criado script `.tmp/collect_chat_synchat_prod_data.py` com parâmetros `--account-id`, `--account-name`, `--sample-size`.
2. Implementada coleta de:
	- `current_database()` de source/dest
	- contagens globais (`accounts/inboxes/contacts/conversations/messages/attachments`)
	- escopo de account (se filtro informado): contagens, distribuição por status/inbox, amostra de conversas
	- diff source→dest (global e por account)
3. Saída padronizada em JSON: `.tmp/chat_synchat_prod_snapshot_YYYYMMDD_HHMMSS.json`.
4. Validação de sintaxe executada com sucesso (`py_compile`).

**Status**: ✅ Completo

---

### Encerramento de Sessão — Ritual Session End (S22-END)

**Objetivo**: Executar encerramento completo da sessão com atualização documental, revisão de segurança e sincronização Git.

**Passos executados**:
1. Revisado e refinado o plano `PLANO_E_TAREFAS_RESET_E_MIGRACAO_DEV_ONLY_2026-05-21.md` com regra explícita `ID > nome` e auditoria obrigatória.
2. Atualizado `docs/TODO.md` com novo cabeçalho de status da sessão 22 e marcação de item concluído de planejamento (`S22-P0-3A`).
3. Atualizado `docs/INDEX.md` com referências da sessão 22 e novos artefatos.
4. Criado `FINAL_STATUS_2026-05-21.md` com estado consolidado, pendências e próximos passos P0.
5. Executado security review dos docs de sessão (scan por padrões de segredo/IP privado).
6. Executado `./scripts/cleanup-tmp.sh --dry-run` (43 itens candidatos à remoção) e registrada decisão de preservação de evidências da investigação.
7. Preparado commit de encerramento e sincronização com remoto.

**Decisões desta etapa**:
- Regra de reconciliação formalizada: em conflito `id` x `nome`, prevalece ID autoritativo (`source_id`/`dest_id`) com log estruturado.
- Execução destrutiva permanece bloqueada até confirmação explícita das dúvidas de escopo do plano.

**Resultado**:
- Session docs consolidados e prontos para retomada sem perda de contexto.
- Security review: sem evidência de credenciais, tokens ativos ou IPs privados nos docs da sessão.
- Pendência operacional principal: confirmação do usuário para base-alvo e escopo da limpeza antes da Fase A/B executável.

**Artefatos criados/modificados**:
- `docs/SESSIONS/2026-05-21/PLANO_E_TAREFAS_RESET_E_MIGRACAO_DEV_ONLY_2026-05-21.md`
- `docs/SESSIONS/2026-05-21/FINAL_STATUS_2026-05-21.md`
- `docs/TODO.md`
- `docs/INDEX.md`

**Status**: ✅ Completo
