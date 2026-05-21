# Investigacao Tecnica — Guaxupe chat x synchat (2026-05-21)

## Objetivo
Determinar por que a Guaxupe apresenta 8190 conversas no chat (origem) e 112 conversas no synchat (destino), e explicar os erros cometidos durante a investigacao anterior.

## Escopo da evidencia analisada
- Capturas HTTP do front enviadas em:
  - .tmp/chat-vya-digital-header-get.txt
  - .tmp/synchat-vya-digital-header-get.txt
- Log do container parado no wfdb01 (chatwoot-migrator-all), com status exited 0.
- Coletas SQL automatizadas executadas na sessao atual.
- Regras carregadas de:
  - .copilot-rules-enterprise-chatwoot-migration.md
  - .copilot-rules-enterprise-chathoot-migration.md

## Evidencia primaria (front/API)
### Origem (chat.vya.digital)
Endpoint: /api/v1/accounts/25/conversations?status=all&assignee_type=me&page=1&sort_by=last_activity_at_desc
Resposta meta:
- assigned_count = 4933
- unassigned_count = 3257
- all_count = 8190

Conclusao: a account 25 (Unimed Guaxupe) na origem possui 8190 conversas.

### Destino (synchat.vya.digital)
Endpoint: /api/v1/accounts/45/conversations?status=all&assignee_type=me&page=1&sort_by=last_activity_at_desc
Resposta meta:
- assigned_count = 112
- unassigned_count = 0
- all_count = 112

Conclusao: a account 45 no synchat exibe 112 conversas neste contexto de UI/API.

## Correlacao com o migrator no wfdb01
Do log coletado no container parado:
- run completo finalizado com exit code 0
- Guaxupe processada com:
  - SOURCE account_id=25
  - Account ja existe no DEST: id=25
  - Conversations inseridas: 4095
  - Messages inseridas: 23005

Interpretacao:
- Esse run atuou sobre uma base de destino onde Guaxupe estava em account_id=25.
- O front do synchat analisado usa account_id=45.
- Portanto, houve divergencia de contexto de banco/tenant entre o run coletado e o front validado.

## O que ocorreu na investigacao anterior (erro meu)
1. Eu executei coletas SQL com chaves de conexao que resolveram source e dest para o mesmo banco fisico em parte dos testes.
2. Isso gerou snapshots com diff zero e conclusoes parciais incoerentes com o front.
3. A evidencia de front enviada agora elimina essa ambiguidade e confirma o comportamento real da UI.

## Causa raiz tecnica consolidada
Causa raiz principal: divergencia de alvo entre ambientes usados na migracao e ambiente realmente observado no front.

Em termos praticos:
- O migrator investigado no wfdb01 gravou em um contexto onde Guaxupe era account_id=25.
- A interface synchat validada no navegador consulta account_id=45 e retorna 112 conversas.
- Logo, o run analisado nao prova cobertura completa da account que o front esta exibindo.

## Por que os demais accounts parecem funcionar
Porque os demais accounts consultados no front atual estao coerentes com o banco/tenant da UI. O problema ficou evidente na Guaxupe por ser justamente onde houve mudanca de mapeamento de account_id entre contextos (25 na origem vs 45 no destino observado).

## Parte problematica do codigo/configuracao
Nao foi identificado bug de loop de insercao no trecho analisado do migrator all-accounts.
O problema esta na camada de configuracao/roteamento de destino e operacao:
- defaults de execucao e aliases de destino permitiram run em contexto diferente do esperado para validacao da UI.
- o entrypoint em ALL_ACCOUNTS com PIPELINE vazio forca fluxo legado, aumentando risco de executar com semantica historica em ambiente errado.

## Impacto
- investigacoes SQL anteriores ficaram contaminadas por alvo de banco incorreto para o caso de uso da tela do synchat.
- risco de falsa conclusao sobre migracao completa de Guaxupe no destino observado pelo usuario.

## Acoes corretivas objetivas
1. Fixar rastreabilidade do alvo em toda execucao:
   - registrar host, database, key logica source/dest no inicio e fim de cada run.
2. Bloquear execucao sem confirmacao explicita de alvo:
   - abortar quando o destino nao corresponder ao tenant esperado de validacao.
3. Para este incidente:
   - usar a propria API do front do synchat (account 45) como fonte de verdade de contagem funcional.
   - reconciliar account 45 no destino com account 25 da origem por chave de negocio e src_id.
4. Seguranca operacional:
   - rotacionar imediatamente os tokens expostos nas capturas de header/cookie.

## Conclusao final
Com base nas evidencias de front fornecidas, a afirmacao correta para o ambiente validado e:
- chat (origem): 8190 conversas na account 25
- synchat (destino observado): 112 conversas na account 45

Portanto, o caso Guaxupe esta parcialmente refletido no destino observado pelo front, e a investigacao anterior que indicava paridade total nao representa o mesmo contexto de banco/tenant da UI.
