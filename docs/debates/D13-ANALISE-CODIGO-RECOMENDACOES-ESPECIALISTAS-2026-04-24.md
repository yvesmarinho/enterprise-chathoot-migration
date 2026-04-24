# D13 — Análise do Código de Migração e Recomendações dos Especialistas

**Data**: 2026-04-24
**Status**: 🔴 REVISÃO OBRIGATÓRIA ANTES DA EXECUÇÃO
**Autores**: DBA & SQL Expert · Python Expert · Chatwoot Expert
**Referências**: D10, D11, D12, D7, D8, D9, D5, D6
**Escopo**: `src/migrators/` · `src/migrar.py` · `app/13_migrar_inbox_members.py`
**Prazo**: 2026-04-24 — migração de produção

---

## Sumário Executivo

Este documento consolida as análises de três especialistas sobre o código Python do pipeline de migração MERGE de `chatwoot_dev1_db` (SOURCE / chat.vya.digital) para `chatwoot004_dev1_db` (DEST / vya-chat-dev.vya.digital).

### Veredito Final

| Especialista | Veredito |
|---|---|
| DBA & SQL Expert | 🔴 **NÃO EXECUTAR** — 3 bugs críticos confirmados |
| Python Expert | 🔴 **NÃO EXECUTAR** — 4 gaps P0 (perda de dados sem erro) |
| Chatwoot Expert | 🔴 **NÃO EXECUTAR** — 5 condições bloqueadoras para produção |

**Decisão consolidada**: A migração possui riscos críticos que produzem corrupção de dados silenciosa. A execução sem as correções documentadas neste documento resultará em conversas vinculadas a inboxes errados, times sem membros, labels não associadas a conversas e possível conflito de credenciais de canais de produção.

### Itens Bloqueadores (devem ser corrigidos ANTES de executar)

| ID | Origem | Item | Componente | Impacto |
|---|---|---|---|---|
| **BUG-B** | DBA | InboxesMigrator sem dedup para contas merged | `inboxes_migrator.py` | 100% das conversas de Vya Digital vinculadas a inboxes duplicados |
| **BUG-C** | DBA | Dedup de Teams/Labels por `remap(id)==id` | `teams_migrator.py`, `labels_migrator.py` | Times e labels duplicados silenciosamente |
| **GAP-team_members** | Python | `team_members` ausente da pipeline | pipeline em `migrar.py` | Times existem mas sem membros — conversas sem responsável |
| **GAP-conv_labels** | Python | `conversation_labels` ausente da pipeline | pipeline em `migrar.py` | Histórico de classificação 100% perdido |
| **GAP-custom_attrs** | Python | `custom_attribute_definitions` ausente | pipeline em `migrar.py` | CPF, external_id e campos customizados inacessíveis na UI |
| **CRED-channels** | Chatwoot | Facebook/Telegram/WhatsApp credenciais verbatim com SOURCE ativo | `inboxes_migrator.py` | Conflito imediato de webhook — duplicação de mensagens em produção |

### Itens Não-Bloqueadores mas de Alta Prioridade

| ID | Origem | Item |
|---|---|---|
| **BUG-A** | DBA | Inbox com `channel_type` desconhecido → FK dangling → inbox invisível |
| **RISCO-auth-token** | Python/DBA | `users.authentication_token` verbatim — acesso cruzado SOURCE/DEST |
| **GAP-4** | Python/Chatwoot | `conversations.status` verbatim — conversas open contaminam filas |
| **RISCO-snoozed** | Chatwoot | `status=snoozed` com `snoozed_until` passado — Chatwoot reativa automaticamente |
| **GAP-webhooks** | Python | `webhooks` e `integration_hooks` ausentes — integrações perdidas |

---

## 1. Análise DBA: Integridade Referencial e Dados

> Análise completa em [D11 — Análise de Integridade do Pipeline](./D11-ANALISE-INTEGRIDADE-PIPELINE-MIGRACAO-2026-04-24.md)

### 1.1 Bugs Críticos Confirmados

#### BUG-A — InboxesMigrator: channel_type desconhecido → FK dangling (Severidade: CRÍTICO)

**Localização**: `src/migrators/inboxes_migrator.py` → `_migrate_channels()`

**Comportamento atual**: Se `channel_type` da inbox SOURCE não está em `_CHANNEL_CFG` (mapa interno), o método emite apenas `WARNING` e mantém o `channel_id` com o valor do SOURCE. Esse ID não existe na tabela de channel do DEST.

**Consequência**: A inbox é inserida no DEST com `channel_id` apontando para um registro inexistente. O Chatwoot usa associação polimórfica `belongs_to :channel`: se `channel` retornar `nil`, o Jbuilder omite o inbox do JSON da API. A inbox fica invisível para todos os usuários.

**Exemplos de channel_types suportados**: `Channel::WebWidget`, `Channel::Api`, `Channel::FacebookPage`, `Channel::Telegram`, `Channel::Email`, `Channel::TwilioSms`, `Channel::Whatsapp`, `Channel::Line`, `Channel::Sms`.

**Ação requerida**: Validar via SQL (PRE-03) que não existem `channel_type` no SOURCE fora desta lista antes da execução.

---

#### BUG-B — InboxesMigrator: ausência total de dedup para contas merged (Severidade: CRÍTICO)

**Localização**: `src/migrators/inboxes_migrator.py`

**Comportamento atual**: O `InboxesMigrator` não possui etapa de lookup de inboxes pré-existentes no DEST, ao contrário de `TeamsMigrator`, `LabelsMigrator` e `ContactsMigrator`.

**Cenário concreto**: A conta Vya Digital é merged (src_id=1 → dest_id=1 pelo nome). O DEST já possui 18 inboxes para `account_id=1` (provenientes da instalação original do synchat). O SOURCE possui as suas próprias inboxes para `account_id=1`. Com o comportamento atual:
1. Todos os inboxes SOURCE para `account_id=1` serão inseridos no DEST com `inbox_id = src_inbox_id + offset_inboxes`.
2. O DEST passa a ter `18 originais + N novos` — inboxes duplicados com o mesmo nome.
3. Todas as conversas migradas do SOURCE ficam associadas aos inboxes-offset (novos), não aos inboxes originais.
4. Agentes que monitoram os inboxes originais (IDs 1..18) não verão nenhuma conversa migrada.
5. `inbox_members` (app/13) também mapeia para os inboxes-offset, criando membros nos inboxes errados.

**Impacto estimado**: 100% das conversas migradas da Vya Digital (account_id=1) estarão vinculadas a inboxes duplicados.

**Ação requerida**: Implementar dedup de inboxes por tripla `(account_id, name, channel_type)` ou por `identifier` único antes da execução. Esta é a correção mais crítica do pipeline.

---

#### BUG-C — TeamsMigrator / LabelsMigrator: condição de dedup incorreta (Severidade: CRÍTICO)

**Localização**: `src/migrators/teams_migrator.py`, `src/migrators/labels_migrator.py`

**Comportamento atual**: A condição de dedup verifica `remap(src_id) == src_id`. Esta condição só é verdadeira quando o `src_id` não teve remapeamento — ou seja, quando `src_id == dest_id`.

**Problema**: Para contas merged onde `src_account_id != dest_account_id`, o remapeamento de `account_id` ocorre. Times e labels de uma conta com `src_account_id=2` (que foi merged para `dest_account_id=1`) têm `remap(2) = 1`. Mas `remap(team_id)` para o time em si pode ainda não ter ocorrido — a condição avalia o `team_id`, não o `account_id`. A lógica completa depende de como o IDRemapper resolve, mas o padrão de dedup documentado em `ContactsMigrator` usa `has_alias()`, que é semanticamente correto.

**Comparação com ContactsMigrator**: `contacts_migrator.py` usa `remapper.has_alias(table, src_id)` para verificar se o registro já existe via merge. Teams e Labels usam a verificação inversa `remap(src_id) == src_id`, que falha para qualquer registro já registrado com alias diferente.

**Consequência**: Times e labels com alias registrado (de contas merged) passam pelo dedup check incorretamente como "não mergeados" e são reinseridos → duplicação silenciosa.

**Ação requerida**: Alterar a condição de dedup em `teams_migrator.py` e `labels_migrator.py` para usar o mesmo padrão de `ContactsMigrator` com `has_alias()`.

---

### 1.2 Riscos de Dados Silenciosos (sem erro, dados errados)

#### RISCO-A — authentication_token copiado verbatim

O `UsersMigrator` NULLa `reset_password_token` e `confirmation_token`, mas não altera `authentication_token`. Este token é a credencial de autenticação da API REST do Chatwoot (`Authorization: Bearer <token>`). Enquanto o SOURCE estiver ativo com os mesmos usuários, o mesmo token funciona nos dois sistemas.

**Impacto**: Acesso cruzado SOURCE/DEST com as mesmas credenciais; auditoria impossível de distinguir qual sistema foi acessado.

---

#### RISCO-B — Dedup de contacts falha por ausência de normalização E.164

O `ContactsMigrator` faz dedup por `phone_number.strip().lower()`. Se o SOURCE tem `"5511999990000"` e o DEST tem `"+5511999990000"`, são strings diferentes — dedup não ocorre — e o mesmo contato é inserido duas vezes.

**Ação requerida**: Validar distribuição de formatos de phone_number em SOURCE e DEST (PRE-07) antes da execução.

---

#### RISCO-C — conversations.status verbatim: filas de agentes contaminadas

Conversas com `status=0` (open) do SOURCE são inseridas como abertas no DEST. Após a migração, os agentes encontrarão todas as conversas históricas abertas em suas filas, misturadas com as conversas ativas reais.

**Risco adicional — snoozed**: Conversas com `status=3` (snoozed) com `snoozed_until` no passado são reativadas automaticamente pelo Chatwoot via job background. Isso pode acontecer minutos após a migração.

**Ação requerida**: Confirmar com o cliente se conversas migradas devem ser forçadas para `status=resolved` (recomendação técnica) ou preservadas como estão (decisão de negócio).

---

#### RISCO-D — Mensagens com S3 URLs do legado TBChat

Mensagens do SOURCE com `content = "Image: https://tbchatuploads.s3..."` (produto da migração TBChat→Chatwoot original) não possuem registros em `attachments`. São copiadas verbatim como texto. No DEST, o Chatwoot renderiza como texto literal na UI, não como imagem. As imagens em si são acessíveis via URL (se o bucket S3 ainda estiver acessível) mas só via link manual.

**Não há risco de 500 (erro de servidor)** — apenas degradação visual.

---

### 1.3 Entidades Faltando na Pipeline

| Entidade | Impacto | Severidade |
|---|---|---|
| `team_members` | Times migrados sem membros — conversas com `team_id` sem responsável visível | 🔴 CRÍTICO |
| `conversation_labels` | Labels migradas mas não vinculadas a conversas — histórico de classificação perdido | 🔴 CRÍTICO |
| `custom_attribute_definitions` | Valores de CPF/external_id em `custom_attributes` JSONB existem no banco mas não são renderizáveis na UI | 🔴 CRÍTICO |
| `conversation_participants` | Assinaturas de conversas perdidas | 🟡 MÉDIO |
| `webhooks` | Integrações externas devem ser reconfiguradas manualmente | 🟠 ALTO (operacional) |
| `integration_hooks` | Idem | 🟠 ALTO (operacional) |
| `canned_responses` | Templates de resposta rápida perdidos | 🟡 MÉDIO |
| `reports` / `v2_reports` | Histórico de analytics perdido | 🟡 MÉDIO |

---

### 1.4 Checklist de Validações SQL Pré-migração (DBA)

Estas queries DEVEM ser executadas como pré-condição da migração. Resultados fora dos critérios de aceitação bloqueiam a execução.

| ID | O que verifica | Critério de aceitação |
|---|---|---|
| PRE-01 | Accounts: nomes que existem em SOURCE e DEST para verificar merge correto | Apenas "Vya Digital" deve colidir; outros devem ser únicos |
| PRE-02 | Inboxes de account_id=1: contagem no SOURCE e no DEST | DEST tem 18; SOURCE tem N — documentar antes de executar |
| PRE-03 | `channel_type` distintos em `inboxes` SOURCE | Todos devem estar em `_CHANNEL_CFG`; qualquer tipo extra bloqueia |
| PRE-04 | Emails de usuários duplicados entre SOURCE e DEST | Documentar todos os usuários que serão merged vs. inseridos |
| PRE-05 | Contatos com phone/email/identifier NULL em todos os três campos | Estes contatos não terão dedup — verificar se há duplicatas potenciais |
| PRE-06 | `conversations.status` distribuição no SOURCE | Quantas open, resolved, snoozed — informar cliente antes de executar |
| PRE-07 | `phone_number` — distribuição de formatos E.164 vs. sem prefixo | Se mix existe, normalizar ou aceitar dedup falho |
| PRE-08 | `messages.content` com padrão `tbchatuploads.s3` | Quantas mensagens afetadas — informar cliente |
| PRE-09 | `team_members` no SOURCE — contagem | Confirmar que esta tabela tem dados antes de implementar migrator |

---

### 1.5 Checklist de Validações SQL Pós-migração (DBA)

Estas queries devem ser executadas IMEDIATAMENTE após a migração para confirmar integridade antes de ligar o Chatwoot DEST.

| ID | O que verifica | Critério de aceitação |
|---|---|---|
| POS-01 | Inboxes no DEST com `channel_id` sem registro na tabela de channel correspondente | Zero registros — qualquer resultado indica BUG-A |
| POS-02 | Conversas com `inbox_id` sem inbox correspondente | Zero registros |
| POS-03 | Conversas com `contact_inbox_id` sem `contact_inboxes` correspondente | Documentar contagem; NULL é aceitável mas alta contagem indica problema |
| POS-04 | `inbox_members` — verificar que agentes têm membros nos inboxes corretos | Comparar com listagem de membros do SOURCE |
| POS-05 | Teams com zero `team_members` (se migrator de team_members for implementado) | Zero times sem membros |
| POS-06 | `conversation_labels` — verificar associações (se migrator for implementado) | Contagem ≥ contagem no SOURCE |
| POS-07 | `display_id` — verificar unicidade por account | Zero duplicatas |
| POS-08 | Contatos duplicados por phone_number exato | Documentar; alta contagem indica RISCO-B materializado |
| POS-09 | `migration_state` — comparar total de rows SOURCE com migrated+skipped+failed | Diferença aceitável: apenas registros explicitamente skipped por orphan FK |
| POS-10 | Conversas com `status=open` migradas (se decisão for preservar) | Documentar total para comunicar aos agentes |

---

## 2. Análise Python: Qualidade de Engenharia e Robustez

### 2.1 Falhas Silenciosas — Tabela Completa

| Ponto de falha | Migrator | Comportamento atual | Consequência |
|---|---|---|---|
| `remap_fn` retorna `None` | Todos | Conta como `skipped`, não como `failed_ids` | Exit code 0 com milhares de registros omitidos |
| Within-batch email collision | `UsersMigrator` | `return None` sem registro em `failed_ids` | Usuário descartado sem rastro auditável; `assignee_id` de conversas fica orfanado |
| `account_users` exception capturada | `UsersMigrator` | `except Exception` loga WARNING sem contagem em `MigrationResult` | Nenhuma contagem de falhas de `account_users` no relatório final |
| `channel_id` não encontrado | `InboxesMigrator` | WARNING logado, `channel_id` SOURCE mantido | Inbox com FK inválida — inbox invisível |
| `contact_inbox_id = NULL` após fallback | `ConversationsMigrator` | WARNING por row, sem contador total | Impossível saber quantas conversas têm `contact_inbox_id = NULL` após execução |
| Dedup por snapshot `_dest_ci_pairs` | `ConversationsMigrator` | Snapshot carregado ANTES dos batches; novas contact_inboxes inseridas durante migração não são detectadas | Falso NULL em `contact_inbox_id` |

### 2.2 Cadeia de Falhas em Cascata

O pipeline não tem mecanismo de abort parcial exceto para `accounts`. O grafo de cascata é:

```
inboxes.failed_ids
  └─► conversations skipped (orphan inbox_id)
        └─► messages skipped (orphan conversation_id)
              └─► attachments skipped (orphan message_id)

contacts.failed_ids
  └─► contact_inboxes skipped (orphan contact_id)
        └─► conversations com contact_inbox_id = NULL
```

Uma falha de batch em `inboxes` pode silenciosamente fazer desaparecer dezenas de conversas do relatório final, sem que o exit code reflita esse problema.

### 2.3 Análise de Comportamento por Tipo de Entidade — Parar ou Continuar?

| Tabela | Parar na falha? | Justificativa |
|---|---|---|
| `accounts` | **Sim — sys.exit(3)** ✅ | Correto. Sem accounts, todo o resto é inútil. |
| `inboxes` | **Deveria parar** ⚠️ | Batch failure silencia conversas em cascata sem exit code |
| `users` | Continuar — aceitável | FKs são nullable; perda tolerável |
| `teams` | Continuar — aceitável | `team_id` é nullable em conversations |
| `labels` | Continuar — aceitável | Não é FK obrigatória |
| `contacts` | **Deveria registrar melhor** ⚠️ | Perda causa `contact_id=NULL` em conversas |
| `conversations` | **Deveria parar** ⚠️ | Batch failure silencia mensagens e anexos inteiros |
| `messages` | Continuar — aceitável | Perda parcial indesejável mas não fatal |
| `attachments` | Continuar — aceitável | Arquivos em S3 permanecem acessíveis |

### 2.4 Segurança de Tokens — Inventário Completo

| Token | Tabela | Tratamento atual | Risco |
|---|---|---|---|
| `authentication_token` | `users` | Verbatim ⚠️ | Acesso cruzado SOURCE/DEST |
| `access_token` | `users` | Verbatim ⚠️ | Idem |
| `pubsub_token` (users) | `users` | Regenerado ✅ | Sem risco |
| `reset_password_token` | `users` | NULL ✅ | Sem risco |
| `confirmation_token` | `users` | NULL ✅ | Sem risco |
| `website_token` | `channel_web_widgets` | Regenerado ✅ | Sem risco |
| `identifier` / `hmac_token` | `channel_api` | Regenerados ✅ | Sem risco |
| `pubsub_token` (contact_inboxes) | `contact_inboxes` | NULL ⚠️ | Push WebSocket ausente até 1ª interação |
| `page_access_token` | `channel_facebook_pages` | Verbatim ⚠️ | Conflito de webhook com SOURCE ativo |
| `bot_token` | `channel_telegram` | Verbatim ⚠️ | Conflito imediato com SOURCE |
| `phone_number` / `provider_config` | `channel_whatsapp` | Verbatim ⚠️ | Conflito com SOURCE |

### 2.5 Entidades Ausentes — Impacto por Prioridade

| Prioridade | Entidade | Impacto |
|---|---|---|
| 🔴 P0 | `team_members` | Times existem mas sem membros — conversas com `team_id` sem responsável |
| 🔴 P0 | `conversation_labels` | Histórico de classificação 100% perdido |
| 🔴 P0 | `custom_attribute_definitions` | Campos customizados (CPF, external_id) não renderizáveis na UI |
| 🟠 P1 | `webhooks` | Integrações externas precisam reconfigurações manuais |
| 🟠 P1 | `integration_hooks` | Idem |
| 🟡 P2 | `conversation_participants` | Assinaturas de conversas perdidas |
| 🟡 P2 | `canned_responses` | Templates de resposta rápida perdidos |
| 🟡 P2 | `reports` / `v2_reports` | Analytics histórico perdido |

### 2.6 Rastreabilidade SOURCE → DEST

| Cenário | Rastreável? | Via |
|---|---|---|
| Registro inserido (offset ID) | ✅ Sim | `migration_state WHERE id_destino=Y → id_origem` |
| Registro merged (alias) | ✅ Sim | `migration_state WHERE id_destino=Y` |
| Registro com contact_inbox_id nullado | ⚠️ Parcial | Log contém o aviso por row mas sem contador |
| Contato com todos os campos identidade NULL | ⚠️ Parcial | `id_destino = id_origem + offset` |
| `account_users` falhados | ❌ Não | Não registrado em `migration_state` |
| Registros skipped por remap_fn → None | ⚠️ Parcial | Nos logs de DEBUG por batch |

---

## 3. Análise Chatwoot: Impacto Funcional e Operacional

> Análise completa em [D12 — Análise Funcional do Domínio Chatwoot](./D12-ANALISE-FUNCIONAL-DOMINIO-CHATWOOT-2026-04-24.md)

### 3.1 Condições para Visibilidade de Conversas Migradas

Para que um agente veja uma conversa migrada, **todas** as condições abaixo devem ser satisfeitas simultaneamente:

| # | Condição | Tabela | Status pós-migração |
|---|---|---|---|
| 1 | Usuário associado à conta | `account_users` | ✅ Migrado por UsersMigrator |
| 2 | Usuário membro do inbox | `inbox_members` | ⚠️ Requer execução manual de `app/13` |
| 3 | Inbox com canal válido | `inboxes.channel_id` → channel table | ⚠️ BUG-A se channel_type desconhecido |
| 4 | Conversa com `inbox_id` correto no DEST | `conversations.inbox_id` | ⚠️ BUG-B se inbox foi duplicado |
| 5 | Conversa com status visível | `conversations.status` | ⚠️ Open/Pending visíveis; Resolved requer filtro |

**Se BUG-B ocorrer** (inboxes duplicados): o agente vê as conversas apenas nos inboxes-duplicata (com offset IDs), não nos inboxes originais onde já trabalhava. Do ponto de vista operacional, parece que as conversas "desapareceram" dos inboxes existentes.

### 3.2 Impacto por Status de Conversa

| Status | Valor | Comportamento no DEST | Recomendação |
|---|---|---|---|
| `open` | 0 | Aparece em filas ativas de todos os agentes membros do inbox | Converter para `resolved` — confirmar com cliente |
| `resolved` | 1 | Não aparece por default; acessível via filtro | Preservar — comportamento correto |
| `pending` | 2 | Aparece em "Pending" — aguarda triagem de agente | Converter para `resolved` — salvo se intencionalmente pendente |
| `snoozed` | 3 | **CRÍTICO**: Chatwoot job background reativa conversas com `snoozed_until < NOW()` | Converter para `resolved` **imediatamente** |

**Recomendação do Chatwoot Expert**: Migrar TODAS as conversas com `status ≠ resolved` como `status = resolved`. Manter o status original do SOURCE como metadado em `additional_attributes` para rastreabilidade.

### 3.3 Impacto por Tipo de Canal

| Canal | Tokens/Credenciais | Risco com SOURCE ativo | Ação recomendada |
|---|---|---|---|
| `Channel::WebWidget` | `website_token` regenerado | Baixo — scripts dos sites precisam atualizar o token | Notificar equipe de frontend |
| `Channel::Api` | `identifier` e `hmac_token` regenerados | Baixo — sistemas integrados precisam atualizar | Notificar integrações externas |
| `Channel::Telegram` | `bot_token` verbatim | **CRÍTICO** — Telegram permite apenas um webhook por bot; DEST "rouba" o webhook do SOURCE | Trocar credenciais do bot OU desligar SOURCE antes de migrar |
| `Channel::FacebookPage` | `page_access_token` verbatim | **ALTO** — dois webhooks recebem os mesmos eventos → duplicação de mensagens | Desligar SOURCE antes de migrar |
| `Channel::Whatsapp` | `phone_number` e `provider_config` verbatim | **ALTO** — depende do BSP mas há risco de split | Confirmar com provedor |
| `Channel::TwilioSms` | `account_sid` e `auth_token` verbatim | **ALTO** — dois webhooks → duplicação de mensagens | Desligar SOURCE ou reconfigurar Twilio antes |
| `Channel::Email` | Configurações SMTP/IMAP verbatim | **ALTO** — dois sistemas recebendo os mesmos emails | Desligar SOURCE antes de migrar |

### 3.4 Impacto no Sistema de Notificações

O Chatwoot dispara notificações ActionCable e emails em tempo real quando:
- Uma nova conversa `open` é criada (notifica agentes do inbox)
- Uma conversa `pending` é criada (notifica supervisores)
- Uma conversa é atribuída a um agente (`assignee_id` definido)

**Se conversas com `status=open` forem migradas verbatim**: no momento do INSERT, o sistema pode disparar notificações para os agentes do DEST — **notificações em massa para conversas históricas**. A magnitude depende de como o Chatwoot processa `after_create` hooks para INSERTs diretos no banco (bypass da API REST).

**Nota**: A migração faz INSERT direto via SQLAlchemy, sem passar pela API REST do Chatwoot. Os hooks ActiveRecord ainda podem ser disparados se o PostgreSQL triggers existirem, mas `after_create` Rails callbacks não são executados para INSERTs externos ao Rails. **Risco de notificações em massa é BAIXO** para INSERTs via SQL direto — mas confirmar na documentação da versão do Chatwoot em uso.

### 3.5 Análise de display_id e URLs de Conversas

**Situação atual**:
- DEST (account_id=1): 378 conversas com `display_id` 1..378
- SOURCE (account_id=1): 309 conversas com `display_id` 1..N (números próprios)
- Após migração: conversas SOURCE receberão `display_id` 379..687 (ou range equivalente)

**Consequência**: Qualquer URL compartilhada externamente que aponte para conversas do SOURCE pelo `display_id` **não mais corresponderá** à mesma conversa no DEST — o display_id muda. Links em emails, sistemas externos, tickets de suporte serão inválidos.

**Não há forma de evitar essa mudança** sem um mapeamento de URL redirect no servidor web.

### 3.6 pubsub_token NULL em contact_inboxes

`pubsub_token` em `contact_inboxes` é usado pelo ActionCable (WebSocket) para push de notificações em tempo real. Com `NULL` após a migração:
- Conversas migradas não recebem push WebSocket de novas mensagens.
- O Chatwoot regenera o token automaticamente na **próxima interação** do contato.
- O impacto é **temporário** mas afeta 100% das conversas migradas imediatamente após a migração.

---

## 4. Matriz de Riscos Consolidada

### 4.1 Riscos Críticos (Bloqueiadores)

| ID | Descrição | Origem | Probabilidade | Impacto | Componente |
|---|---|---|---|---|---|
| BUG-B | Inboxes duplicados para conta Vya Digital | DBA + Chatwoot | **Certa** (100%) | Máximo — 100% conversas no inbox errado | `inboxes_migrator.py` |
| BUG-C | Dedup incorreto em Teams/Labels | DBA + Python | **Alta** (para contas merged) | Alto — duplicação silenciosa | `teams_migrator.py`, `labels_migrator.py` |
| GAP-team-members | `team_members` ausente | Python | **Certa** | Alto — times vazios | Pipeline `migrar.py` |
| GAP-conv-labels | `conversation_labels` ausente | Python + DBA | **Certa** | Alto — classificação perdida | Pipeline `migrar.py` |
| GAP-custom-attrs | `custom_attribute_definitions` ausente | Python | **Certa** | Alto — campos customizados inacessíveis | Pipeline `migrar.py` |
| CRED-channels | Credenciais de produção verbatim | Chatwoot | **Alta** | Máximo — conflito de webhook | `_migrate_channels()` |

### 4.2 Riscos Altos (Corrigir antes ou aceitar com documentação)

| ID | Descrição | Origem | Probabilidade | Impacto | Mitigação disponível |
|---|---|---|---|---|---|
| BUG-A | Inbox invisível por channel_type desconhecido | DBA | Baixa (verificar PRE-03) | Alto | Validação PRE-03 antes de executar |
| RISCO-auth | `authentication_token` verbatim | Python + DBA | Alta | Médio-Alto | Forçar re-login de todos os usuários pós-migração |
| GAP-4 | `status=open` contamina filas | DBA + Chatwoot | **Certa** | Alto | Confirmar com cliente; converter para resolved |
| RISCO-snoozed | `snoozed_until` passado → reativação automática | Chatwoot | Alta | Médio-Alto | Converter snoozed para resolved |
| GAP-webhooks | Webhooks não migrados | Python | **Certa** | Alto (operacional) | Aceitar + plano de reconfiguração manual |
| RISCO-phone | Dedup contatos falha sem E.164 | DBA | Média | Médio | Validação PRE-07 antes de executar |

### 4.3 Riscos Médios (Aceitar com documentação)

| ID | Descrição | Origem | Mitigação |
|---|---|---|---|
| RISCO-S3 | S3 URLs legadas em messages.content | DBA | Comunicar ao cliente; UX degradada mas funcional |
| RISCO-pubsub | pubsub_token NULL em contact_inboxes | Python + Chatwoot | Temporário; resolvido na 1ª interação |
| GAP-participants | `conversation_participants` ausente | Python + Chatwoot | Aceitar; impacto menor |
| GAP-canned | `canned_responses` ausente | Python | Reconfigurar manualmente; documentar |
| RISCO-display-id | display_id muda para conversas SOURCE | Chatwoot | Comunicar; criar redirect se necessário |
| RISCO-timestamps | `snoozed` + JobWorker pode reativar imediatamente | Chatwoot | Parar JobWorker antes de ligar o DEST |
| RISCO-window | Janela inconsistente conversations/messages | Python | Executar durante período de baixo uso |

---

## 5. Checklist de Pré-migração (Ordenado por Criticidade)

> Este checklist deve ser executado integralmente antes de rodar `python -m src.migrar` em produção.

### Fase 0 — Preparação do Ambiente

- [ ] **0.1** Verificar que o DEST está em modo manutenção (página de manutenção ativa, usuários não conseguem acessar)
- [ ] **0.2** Desligar os JobWorkers do DEST (Sidekiq/DelayedJob) para evitar processamento de jobs durante migração
- [ ] **0.3** Fazer backup completo do DEST antes de qualquer execução: `pg_dump chatwoot004_dev1_db > backup_pre_migration_YYYYMMDD.sql`
- [ ] **0.4** Verificar conectividade com SOURCE (read-only) e DEST (read-write): `psql` ambas as strings de conexão
- [ ] **0.5** Verificar versão do Chatwoot SOURCE vs. DEST (schema compatibility)

### Fase 1 — Validações SQL Obrigatórias (Executar todas; bloquear se critério não for atendido)

- [ ] **PRE-01** Verificar nomes de accounts colidentes SOURCE vs. DEST — documentar
- [ ] **PRE-02** Contar inboxes por account_id no SOURCE e DEST — documentar antes e depois
- [ ] **PRE-03** ⛔ **BLOQUEADOR**: Verificar channel_types distintos no SOURCE — nenhum deve estar fora da lista suportada
- [ ] **PRE-04** Listar usuários com email duplicado SOURCE vs. DEST — documentar
- [ ] **PRE-05** Identificar contatos com phone/email/identifier todos NULL — documentar contagem
- [ ] **PRE-06** Distribuição de `conversations.status` no SOURCE — apresentar ao cliente para decisão
- [ ] **PRE-07** Distribuição de formatos de `phone_number` (com/sem `+`) — documentar
- [ ] **PRE-08** Contagem de mensagens com `tbchatuploads.s3` em `content` — informar cliente
- [ ] **PRE-09** Contar registros em `team_members` no SOURCE — confirmar existência antes de criar migrator

### Fase 2 — Decisões de Negócio (Obter confirmação explícita do cliente antes de executar)

- [ ] **DEC-01** ⛔ **DECISÃO OBRIGATÓRIA**: `conversations.status` — preservar ou converter para `resolved`?
- [ ] **DEC-02** ⛔ **DECISÃO OBRIGATÓRIA**: Canais Facebook/Telegram/WhatsApp — desligar SOURCE primeiro ou aceitar possível duplicação de mensagens durante cutover?
- [ ] **DEC-03** Usuários — forçar re-login de todos após migração (invalidar `authentication_token`)?
- [ ] **DEC-04** Inboxes — criar dedup por nome/channel_type para account merged ou aceitar duplicação?
- [ ] **DEC-05** WebWidget — notificar equipes de frontend sobre regeneração de `website_token`?

### Fase 3 — Correções de Código Obrigatórias (Antes de executar em produção)

- [ ] **FIX-01** ⛔ **BLOQUEADOR**: Implementar dedup de inboxes por `(account_id, name, channel_type)` em `InboxesMigrator` para contas merged
- [ ] **FIX-02** ⛔ **BLOQUEADOR**: Corrigir condição de dedup em `TeamsMigrator` e `LabelsMigrator` para usar `has_alias()` em vez de `remap(id) == id`
- [ ] **FIX-03** ⛔ **BLOQUEADOR**: Implementar `TeamMembersMigrator` (tabela `team_members`)
- [ ] **FIX-04** ⛔ **BLOQUEADOR**: Implementar `ConversationLabelsMigrator` (tabela `conversation_labels`)
- [ ] **FIX-05** ⛔ **BLOQUEADOR**: Implementar `CustomAttributeDefinitionsMigrator` (tabela `custom_attribute_definitions`)
- [ ] **FIX-06** Aplicar decisão DEC-01: converter `conversations.status` conforme solicitação do cliente
- [ ] **FIX-07** Aplicar decisão DEC-03: NULL `authentication_token` em `UsersMigrator` se cliente solicitar

### Fase 4 — Execução da Migração

- [ ] **4.1** Executar `python -m src.migrar --dry-run` e revisar saída completa
- [ ] **4.2** Verificar `migration_state` — se houver execução anterior, limpar ou verificar idempotência
- [ ] **4.3** Executar `python -m src.migrar` com logging em nível INFO (saída para arquivo)
- [ ] **4.4** Monitorar exit code: 0 = sucesso, 1 = falhas parciais, 3 = catastrófico
- [ ] **4.5** Após pipeline principal, executar `app/13_migrar_inbox_members.py` (separado)
- [ ] **4.6** Verificar logs por `WARNING` com "orphan" ou "fallback" — documentar contagens

### Fase 5 — Validações Pós-migração (Antes de ligar o Chatwoot DEST)

- [ ] **POS-01** ⛔ Zero inboxes com `channel_id` FK inválida
- [ ] **POS-02** ⛔ Zero conversas com `inbox_id` FK inválida
- [ ] **POS-03** Contar conversas com `contact_inbox_id = NULL` — documentar
- [ ] **POS-04** Verificar `inbox_members` por inbox e por agente
- [ ] **POS-05** Verificar `team_members` por time (se FIX-03 implementado)
- [ ] **POS-06** Verificar `conversation_labels` por amostragem (se FIX-04 implementado)
- [ ] **POS-07** Verificar unicidade de `display_id` por account
- [ ] **POS-08** Contar contatos duplicados por phone_number exato
- [ ] **POS-09** Comparar totais: `migration_state` vs. tabelas destino
- [ ] **POS-10** Verificar distribuição de `status` em conversas migradas

### Fase 6 — Ativação do DEST

- [ ] **6.1** Reativar JobWorkers do DEST (Sidekiq/DelayedJob)
- [ ] **6.2** Remover página de manutenção
- [ ] **6.3** Notificar agentes sobre período de observação pós-migração
- [ ] **6.4** Monitorar logs do Chatwoot DEST por 30 minutos (erros 500, timeouts)

---

## 6. Registro de Decisões Pendentes (DDL)

Estas decisões precisam de confirmação explícita do cliente/responsável técnico **antes** da execução da migração.

| ID | Questão | Opção A | Opção B | Recomendação Técnica |
|---|---|---|---|---|
| DEC-01 | `conversations.status` nas conversas migradas | Preservar verbatim (open, snoozed, pending) | Converter tudo para `resolved` | **Opção B** — preservar `status=open` contamina filas de agentes com histórico irrelevante |
| DEC-02 | Canais Facebook/Telegram/WhatsApp | Desligar SOURCE antes de migrar (sem risco) | Migrar com SOURCE ativo (risco de duplicação) | **Opção A** — desligar SOURCE primeiro; janela de indisponibilidade aceitável |
| DEC-03 | Autenticação de usuários após migração | Manter `authentication_token` verbatim | Forçar re-login de todos os usuários | **Opção B** — segurança; usuários fazem login uma vez |
| DEC-04 | Inboxes de conta Vya Digital (account_id=1) | Dedup por nome (mapear SOURCE inbox para DEST inbox existente) | Inserir com offset (inboxes duplicados, conversas no inbox novo) | **Opção A** — dedup correto; requer FIX-01 |
| DEC-05 | Notificação ao cliente sobre display_id | Comunicar que display_ids de conversas SOURCE mudaram | Criar regra de redirect no servidor | **Opção A** — redirect é complexo para o ganho |
| DEC-06 | `canned_responses` | Aceitar perda e recriar manualmente | Implementar `CannedResponsesMigrator` | **Depende da quantidade** — verificar PRE count |
| DEC-07 | `webhooks` e `integration_hooks` | Aceitar perda e reconfigurar manualmente | Implementar migrators correspondentes | **Opção A para dev env** — reconfiguração manual mais segura |

---

## 7. Sumário de Recomendações por Especialista

### 7.1 Recomendações DBA

1. **Execute PRE-03 imediatamente**: um único `channel_type` desconhecido no SOURCE pode fazer inboxes inteiros ficarem invisíveis pós-migração.
2. **Não execute sem FIX-01**: o BUG-B (inboxes sem dedup) é o bug com maior impacto — 100% das conversas da principal conta (Vya Digital) ficarão no inbox errado.
3. **Execute PRE-06 antes de qualquer coisa**: mostre ao cliente quantas conversas são `open`, `pending`, `snoozed` e obtenha DEC-01 por escrito.
4. **Faça backup do DEST antes de executar**: a migração faz INSERTs diretos no banco; rollback requer restauração completa do backup.
5. **Pare os JobWorkers do DEST antes de ligar o Chatwoot**: `snoozed_until` no passado → reativação imediata por Sidekiq.

### 7.2 Recomendações Python Expert

1. **Implemente team_members, conversation_labels e custom_attribute_definitions HOJE**: são P0 — sem eles, a migração está incompleta do ponto de vista funcional.
2. **Adicione contadores explícitos para NULL-outs e fallbacks**: o relatório final deve mostrar quantas conversas tiveram `contact_inbox_id = NULL`, não apenas "skipped".
3. **Considere abort em batch failure de inboxes e conversations**: o comportamento atual de "continuar" mascara perdas de dados no exit code.
4. **Documente a ordem correta de execução**: `migrar.py` → `app/13_migrar_inbox_members.py`. Esta dependência não está documentada no README atual.
5. **Trate `authentication_token`**: NULL-out ou regenerar. A segurança de tokens verbatim é um risco desnecessário.

### 7.3 Recomendações Chatwoot Expert

1. **Converta `snoozed` para `resolved` incondicionalmente**: é o único status que causa comportamento automático (reativação pelo Chatwoot job) que não pode ser facilmente desfeito depois.
2. **Desconecte os webhooks dos canais de produção NO SOURCE antes de migrar**: Facebook, Telegram, WhatsApp, Twilio. Isso é mais importante do que o timing de desligar o SOURCE em si.
3. **Execute `app/13` ANTES de liberar o acesso ao DEST**: sem `inbox_members`, agentes com `role=agent` não conseguem ver nenhuma conversa.
4. **Verifique `pubsub_token` em `contact_inboxes` após migração**: um UPDATE para regenerar os tokens eliminará o impacto de push WebSocket ausente nas conversas migradas.
5. **Comunique aos agentes sobre o período de observação**: display_ids mudaram, filas podem ter conversas históricas (se DEC-01 for Opção A), e integrações externas precisam ser reconfiguradas.

---

## 8. Conclusão

O código de migração está bem estruturado, com boas práticas de idempotência via `migration_state`, tratamento de orphan FKs, dedup em múltiplas entidades e regeneração correta de tokens sensíveis para a maioria dos casos.

**Os problemas identificados são corrigíveis** — nenhum requer reescrita do pipeline. Mas a migração **não deve ser executada em produção com os bugs atuais** (BUG-B, BUG-C, entidades faltando), pois produzirá dados tecnicamente válidos mas semanticamente incorretos — conversas em inboxes errados, times sem membros, labels sem associação — sem nenhuma mensagem de erro para indicar o problema.

**Caminho para execução hoje**:
1. Obter DEC-01 (status das conversas) do cliente — 15 minutos
2. Obter DEC-02 (canais de produção) — 15 minutos
3. Implementar FIX-01 (dedup de inboxes) — 2-4 horas
4. Implementar FIX-02 (dedup de teams/labels) — 30 minutos
5. Implementar FIX-03, FIX-04, FIX-05 (entidades faltando) — 2-3 horas
6. Executar PRE-01 a PRE-09 — 30 minutos
7. Executar migração com monitoramento — 1-2 horas
8. Executar POS-01 a POS-10 — 30 minutos

**Estimativa total**: 6-10 horas de trabalho contínuo para migração segura.

---

*Documento gerado em 2026-04-24 a partir das análises individuais de DBA & SQL Expert (D11), Python Expert e Chatwoot Expert (D12) no projeto enterprise-chathoot-migration.*
