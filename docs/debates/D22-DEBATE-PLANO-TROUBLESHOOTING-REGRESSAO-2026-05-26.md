# D22 — Debate de Regressao e Plano Unico de Troubleshooting

Data: 2026-05-26
Status: Proposto para execucao imediata
Escopo: DEV, account Unimed Guaxupe, sem desenvolvimento de codigo novo

## 1. Problema Real (sem loop)

O time perdeu o patamar funcional que ja existiu. Em 2026-04-29 e 2026-05-24 havia migracao com dados de negocio acessiveis (conversations, messages e attachments). Hoje a execucao termina sem erro tecnico, mas com migrado=0 nas tabelas centrais.

Resumo do sintoma atual:
- Pipeline finaliza com exit 0
- Falhas tecnicas = 0
- Dados core migrados = 0
- Cobertura de anexos no DEST = 0%

Isso caracteriza regressao funcional mascarada por sucesso operacional.

## 2. Evidencias de Referencia

### 2.1 Patamar funcional historico (baseline)

Fonte: docs/SESSIONS/2026-04-29/RELATORIO_VALIDACAO_MIGRACAO.md
- Unimed Guaxupe (25 -> 46): 100% encontrado no DEST e 100% visivel via API na amostra de 100 conversations.

Fonte: docs/SESSIONS/2026-05-24/DAILY_ACTIVITIES_2026-05-24.md
- conversations: 8.190/8.190 (100%)
- messages: 46.010/46.010 (100%)
- attachments: 1.932/1.932 (100%)
- status declarado: sucesso com dados core 100%.

### 2.2 Estado atual (regredido)

Fonte: .tmp/migration_20260526_143559_report.txt
- conversations: origem 8.203, migrado 0
- messages: origem 46.048, migrado 0
- attachments: origem 1.938, migrado 0
- TOTAL: origem 143.493, migrado 0, falhas 0

Fonte: .tmp/d20_cobertura_final_20260526_143746.json
- SOURCE (account 25): cobertura ActiveStorage 99,43%
- DEST (account 69): cobertura ActiveStorage 0%

Conclusao objetiva: nao houve erro de banco; houve decisao de skip em massa por logica de deduplicacao/estado.

## 3. Diagnostico do Loop

O loop atual ocorre porque cada rodada valida a camada errada:
- Camada operacional: processo sobe, termina, sem excecao
- Camada funcional: dados de negocio nao entram

Sem gate funcional obrigatorio, o time interpreta progresso tecnico como progresso de entrega. Nao e.

## 4. Hipoteses Prioritarias (ordem de ataque)

H1 (Mais provavel): deduplicacao global sem escopo de account nas tabelas de negocio.
- Efeito: sistema entende que "ja existe" no DEST e pula quase tudo, mesmo para account destino vazio.

H2: contamination de migration_state de execucoes anteriores (mapeamentos herdados usados fora de escopo).
- Efeito: skips silenciosos por "already migrated" para IDs que deveriam entrar no account atual.

H3: divergencia de estrategia entre o que funcionava em 29/04 e o pipeline atual (mudanca de regras de merge).
- Efeito: antes inseria e hoje reaproveita excessivamente.

H4: criterio de validacao pos-migracao insuficiente (passa com exit 0, sem exigir minimo funcional).
- Efeito: regressao nao bloqueia execucao.

## 5. Debate Tecnico (decisao de abordagem)

Posicao A (continuar tentando patch por sintoma)
- Vantagem: resposta rapida local.
- Risco: perpetua loop e cria efeito colateral em outras tabelas.

Posicao B (voltar ao baseline funcional e comparar comportamento)
- Vantagem: identifica o primeiro ponto de divergencia real.
- Risco: exige disciplina de evidencia e mais tempo inicial.

Decisao recomendada: Posicao B.
Motivo: o problema e regressao sistemica, nao bug isolado.

## 6. Plano Unico de Troubleshooting (sem codigo novo)

### Fase 0 — Congelamento de referencia

Objetivo: parar o loop.

Acoes:
1. Declarar baseline oficial de comparacao:
- Baseline 1: 2026-04-29 (validacao API multi-account)
- Baseline 2: 2026-05-24 (core 100% no DEV)
2. Definir um unico account de prova: Unimed Guaxupe.
3. Proibir nova alteracao de logica ate fechar diagnostico diferencial.

Saida esperada:
- Documento de baseline aceito pela equipe.

### Fase 1 — Tabela de diferencas (config e regras)

Objetivo: responder "o que mudou" sem suposicao.

Acoes:
1. Comparar configuracoes de execucao entre baseline e hoje:
- ambiente
- estrategia merge
- deduplicacao
- uso de migration_state
- ordenacao do pipeline
2. Comparar apenas fatos documentados (logs, reports, debates, daily activities).

Saida esperada:
- Matriz "Antes funcionava assim" vs "Hoje roda assim" por etapa.

### Fase 2 — Gate funcional obrigatorio

Objetivo: impedir falso positivo operacional.

Gate de aceite minimo por rodada:
1. conversations migrado > 0
2. messages migrado > 0
3. attachments migrado > 0
4. cobertura DEST de anexos >= 95% para account alvo
5. FK orphans = 0 (ou dentro da tolerancia formalizada)

Regra:
- Se qualquer gate falhar, rodada = falhou, mesmo com exit 0.

### Fase 3 — Isolamento da causa raiz

Objetivo: provar uma unica causa primaria antes de qualquer mudanca.

Acoes:
1. Verificar se skip em massa vem de deduplicacao global (por tabela).
2. Verificar se skip em massa vem de migration_state herdado.
3. Verificar se a estrategia de merge atual diverge do baseline.

Saida esperada:
- Causa raiz primaria assinada com evidencia objetiva.

### Fase 4 — Plano de correcao unico (depois do diagnostico)

Objetivo: executar uma unica onda de correcao, nao micro-ajustes.

Acoes:
1. Definir pacote de correcao com escopo fechado (P0/P1).
2. Validar pacote em dry-run funcional e depois rodada real.
3. Publicar checklist de regressao para evitar retorno do problema.

## 7. Regras Anti-Loop (obrigatorias)

1. Nao aceitar "sem erro" como sucesso.
2. Nao abrir nova frente antes de fechar causa raiz primaria.
3. Nao alterar varias tabelas ao mesmo tempo sem criterio de impacto.
4. Nao trocar account de teste no meio da investigacao.
5. Cada rodada deve terminar com veredito binario: passou nos gates ou nao.
6. Nao deve haver codigo de remendo; toda correcao deve ser implementada no codigo do workflow oficial.

## 8. Criterio de Saida do Incidente

Incidente encerrado somente quando:
1. Uma rodada completa atingir os 5 gates funcionais.
2. Resultado replicado em segunda rodada de confirmacao.
3. Diferenca para baseline 29/04 explicada e documentada.
4. Plano de prevencao anexado (checklist de regressao).

## 9. Recomendacao Final para a Equipe

O caminho correto agora nao e continuar ajustando por sintoma. E executar troubleshooting diferencial orientado por baseline, com gate funcional obrigatorio. Isso resolve o problema de uma vez porque elimina falso progresso e forca evidencia da causa raiz antes de qualquer nova alteracao.

## 10. Atualizacao de Execucao (2026-05-26 16:02)

Rodada executada apos restauracao da base (workflow oficial):
- Log: .tmp/migration_20260526_155511.log
- Report: .tmp/migration_20260526_160248_report.txt
- Cobertura: .tmp/d20_cobertura_final_20260526_160356.json

Resultado da rodada:
1. Exit code 0.
2. FK validator: 0 orphans.
3. Gates funcionais de banco aprovados:
- conversations migrado: 8203 (>0)
- messages migrado: 46048 (>0)
- attachments migrado: 1938 (>0)
- cobertura DEST anexos: 99,43% (>=95%)

Pendencia operacional para encerramento completo no app:
1. Validacao API da account destino (69) depende de token valido com escopo dessa account.
2. Probe de API geral responde (app acessivel), mas token atualmente disponivel no ambiente retornou account_id diferente e 401 no endpoint de conversations da account 69.
3. Proximo passo: gerar/fornecer token valido da account 69 e rodar validacao API final (summary + deep) para fechar o incidente com segunda confirmacao funcional.

---

Referencias usadas neste debate:
- docs/SESSIONS/2026-04-29/RELATORIO_VALIDACAO_MIGRACAO.md
- docs/SESSIONS/2026-05-24/DAILY_ACTIVITIES_2026-05-24.md
- docs/debates/D18-DEBATE-MENSAGENS-NAO-ABREM-DEV-2026-05-26.md
- docs/debates/D21-BUG-CRITICO-IDEMPOTENCIA-DEDUPLICACAO-GLOBAL-2026-05-26.md
- .tmp/migration_20260526_143559_report.txt
- .tmp/d20_cobertura_final_20260526_143746.json
