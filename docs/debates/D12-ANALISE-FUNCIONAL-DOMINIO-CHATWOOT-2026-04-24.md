# D12 — Análise Funcional do Domínio Chatwoot: Impactos da Migração MERGE

**Data**: 2026-04-24
**Autor**: Chatwoot Expert (GitHub Copilot — Claude Sonnet 4.6)
**Versão**: 1.0
**Tipo**: Análise funcional de domínio — sem código; análise textual, tabelas e recomendações
**Status**: APROVADO PARA REFERÊNCIA — complementa D7, D8, D9, D10, D11
**Referências**: D7, D8, D9, D10, D11; `src/migrators/`; `app/13_migrar_inbox_members.py`

---

## Sumário Executivo

Este documento consolida a análise funcional de todos os impactos da migração MERGE de `chatwoot_dev1_db` (SOURCE / chat.vya.digital) para `chatwoot004_dev1_db` (DEST / vya-chat-dev.vya.digital) do ponto de vista do **comportamento do sistema Chatwoot** — não da integridade técnica do banco de dados (coberta em D11).

O objetivo é responder: *após a migração, o sistema Chatwoot DEST se comporta corretamente para os usuários finais?*

---

## 1. Análise de Visibilidade de Conversas — Cadeia Completa

### 1.1 Modelo de Permissões do Chatwoot (confirmado em D9)

O Chatwoot implementa um modelo de permissões em quatro camadas cumulativas. Uma conversa migrada só é visível quando **todas** as camadas aplicáveis estão satisfeitas:

| Camada | Tabela | Condição | Quebra visibilidade se ausente? |
|--------|--------|----------|--------------------------------|
| 1 — Associação à conta | `account_users` | `(account_id, user_id)` deve existir | Sim — usuário não existe na conta |
| 2 — Membro do inbox | `inbox_members` | `(inbox_id, user_id)` deve existir para `role=agent` | Sim — inbox invisível para agent |
| 3 — Inbox válido | `inboxes` → channel | `channel_id` deve ter registro na tabela de channel correspondente | Sim — inbox omitido do JSON pela API |
| 4 — FK de conversa | `conversations.inbox_id` | Deve apontar para inbox correto no DEST | Sim — conversa não aparece no inbox certo |

### 1.2 Visibilidade por Tipo de Usuário

#### `role = administrator`

Um administrator de uma conta no Chatwoot tem acesso irrestrito a **todas** as conversas da conta, sem filtragem por `inbox_members`. A lógica é implementada em `Conversations::PermissionFilterService`: se o token da API pertence a um administrator, o filtro de inboxes é bypassed.

**Campos migrados que afetam um administrator:**

| Campo | Comportamento pós-migração |
|-------|---------------------------|
| `conversations.inbox_id` | Deve apontar para inbox DEST correto. Se o inbox foi migrado com offset, conversas aparecem no inbox offset — não no inbox original do DEST |
| `conversations.assignee_id` | NULL-out se user não migrado. A conversa aparece em "Unassigned" em vez de "Mine" |
| `inboxes.channel_id` | Se NULL ou inválido (BUG-A do D11), o inbox não aparece no seletor lateral mas as conversas ainda estão no banco |
| `conversations.status` | Open = aparece em "Open", Resolved = não aparece por default |

#### `role = agent`

Um agent vê apenas conversas em inboxes onde está registrado em `inbox_members`. Esta é a restrição mais crítica para a migração.

**Campos migrados que afetam um agent:**

| Campo | Comportamento pós-migração |
|-------|---------------------------|
| `inbox_members.inbox_id` | Deve ser o ID do inbox no DEST (remapeado). Se `app/13` não foi executado, este registro não existe |
| `inbox_members.user_id` | Deve ser o ID do user no DEST (merged ou novo). Alias de UsersMigrator deve estar correto |
| `conversations.assignee_id` | NULL = conversa em "All" (se membro do inbox), não em "Mine" |
| `conversations.team_id` | Agentes em `team_members` veem conversas do time mesmo sem `inbox_members` explícito |

**Condição mínima para visibilidade completa de um agent:**
1. Registro em `account_users` com `account_id` e `user_id` corretos no DEST
2. Registros em `inbox_members` para cada inbox relevante (requer `app/13`)
3. Inboxes com `channel_id` válido no DEST (requer `_migrate_channels()`)
4. `conversations.inbox_id` remapeado para o inbox DEST correto

**Campos com NULL que afetam a visibilidade de um agent:**

| Campo NULL | Impacto |
|------------|---------|
| `assignee_id = NULL` | Conversa em "All" / "Unassigned", não em "Mine". Agent vê apenas se for membro do inbox |
| `contact_inbox_id = NULL` | Conversa "anônima" — sem link com canal. API pode retornar dados incompletos; UI não mostra o histórico do contato no canal |
| `contact_id = NULL` | Conversa sem contato. Nome do interlocutor não aparece; perfil lateral vazio |
| `team_id = NULL` | Conversa não associada ao time. Agentes que acessavam via time não verão |

#### `role = viewer` (agent readonly)

Mesmo modelo de permissão que `agent`. Pode ver conversas mas não pode responder. Todos os pontos do agent se aplicam.

---

## 2. Análise de Impacto por Status de Conversa

O `status` em `conversations` é copiado verbatim pelo `ConversationsMigrator`. Os valores inteiros mapeiam para:

| Valor | Nome Rails | Descrição |
|-------|-----------|-----------|
| 0 | `open` | Conversa ativa, aguardando resposta |
| 1 | `resolved` | Encerrada |
| 2 | `pending` | Aguardando primeiro contato do agente (canal de entrada) |
| 3 | `snoozed` | Snoozada até uma data futura |

### 2.1 Status 0 — `open`

**O que acontece no DEST quando conversas open são importadas:**

Conversas `open` inseridas diretamente no banco (sem passar pelo ActiveRecord lifecycle do Rails) **não disparam callbacks nem WebSocket events** no momento da inserção. Porém, após o primeiro acesso da UI, o Chatwoot carrega essas conversas normalmente e elas aparecem em todas as filas de `open` de cada inbox.

**Impacto operacional:**
- Conversas históricas de 2024/2025 aparecem em "Open Conversations" junto com conversas ativas de hoje
- SLA timers (se configurados) iniciam contagem baseada em `created_at` (data original do SOURCE) — conversas antigas provavelmente já expiraram no SLA
- Relatórios de volume de conversas abertas ficam inflados com dados históricos
- Agentes verão um backlog artificial de conversas que não requerem ação
- Notificações não disparam no momento da inserção (pois não há evento Rails), mas se um agente carregar a página, as conversas aparecerão como não lidas

**Recomendação:** Conversas SOURCE com `updated_at` anterior à data de corte (e.g., 30 dias antes da migração) devem ser migradas como `status = 1 (resolved)`, preservando o histórico sem contaminar as filas ativas.

### 2.2 Status 1 — `resolved`

**O que acontece no DEST quando conversas resolved são importadas:**

Conversas `resolved` aparecem no histórico mas não nas filas ativas. Não afetam SLA timers nem filas de agentes. Este é o status mais seguro para migração de histórico.

**Impacto operacional:** Mínimo. Conversas visíveis apenas via busca ou filtro "Resolved". Sem side effects operacionais.

### 2.3 Status 2 — `pending`

**O que acontece no DEST quando conversas pending são importadas:**

Conversas `pending` ficam na fila de entrada do inbox aguardando que um agente as "aceite" (mova para open e assigne). No Chatwoot, a fila Pending é exibida separadamente da fila Open.

**Impacto operacional:**
- Conversas históricas pending aparecem como se fossem novas conversas aguardando ação
- Se o canal correspondente (inbox) não está mais ativo no DEST (canal migrado com credenciais do SOURCE), nenhuma resposta pode ser enviada mas a conversa fica visível
- Agentes verão backlog artificial de pending

**Recomendação:** Converter para `resolved` na migração, salvo se o inbox correspondente estará ativo no DEST e as conversas genuinamente precisam de ação.

### 2.4 Status 3 — `snoozed`

**O que acontece no DEST quando conversas snoozed são importadas:**

Conversas `snoozed` têm um timestamp de `snoozed_until` (campo em conversations). Quando esse timestamp passa, o Chatwoot tem um job agendado (`ConversationResolveWorker` / snooze job) que retorna a conversa para `open`.

**Impacto operacional:**
- Se `snoozed_until` está no passado (data do SOURCE era antes da migração) → o job do Chatwoot ativa essas conversas e elas se tornam `open` automaticamente, sem ação do usuário
- Efeito prático: conversas migradas como `snoozed` com timestamp expirado aparecerão como `open` após o primeiro ciclo do job (normalmente a cada 15 minutos)
- Contamina filas ativas com dados históricos silenciosamente

**Recomendação:** Converter snoozed → `resolved` na migração. O risco de ativação automática inesperada é inaceitável operacionalmente.

### 2.5 Tabela de Recomendação por Status

| Status SOURCE | Qtd estimada | Recomendação DEST | Justificativa |
|---------------|-------------|-------------------|---------------|
| `open` (0) — com `updated_at > 30 dias antes corte` | Minoria | Preservar como `open` | Conversas genuinamente ativas |
| `open` (0) — com `updated_at <= 30 dias antes corte` | Maioria | Converter para `resolved` (1) | Evita contaminação de filas |
| `resolved` (1) | Maioria | Preservar como `resolved` | Sem impacto operacional |
| `pending` (2) | Verificar | Converter para `resolved` (1) | Canais podem não estar ativos |
| `snoozed` (3) | Verificar | Converter para `resolved` (1) | Evita reativação automática |

---

## 3. Análise de Canais (Inboxes) Migrados

### 3.1 `Channel::WebWidget` — website_token regenerado

O `website_token` é o identificador público embutido no JavaScript instalado nos sites dos clientes. Ele determina para qual inbox as conversas iniciadas pelo widget são roteadas.

**O migrador regenera `website_token` via `secrets.token_urlsafe(18)`.**

**Impacto:**
- Sites que têm o script do Chatwoot instalado com o `website_token` do SOURCE (chat.vya.digital) continuarão enviando conversas para o SOURCE, não para o DEST
- O novo token do DEST é desconhecido pelos sites instalados
- Novas conversas do widget **não chegarão ao DEST** até que cada site tenha o script atualizado com o novo token
- **Ação necessária**: Após migração, coletar o novo `website_token` de cada Channel::WebWidget no DEST e comunicar às equipes responsáveis pelos sites para atualizar o script de instalação

**Risco residual aceito:** Enquanto os sites não forem atualizados, eles criam conversas no SOURCE (que pode estar descomissionado). Há risco de perda de conversas novas nesse intervalo.

### 3.2 `Channel::Api` — identifier e hmac_token regenerados

O `identifier` é o endpoint público da API channel. O `hmac_token` é usado para verificar a autenticidade de mensagens enviadas via API externa.

**O migrador regenera ambos via `secrets.token_urlsafe(24)`.**

**Impacto:**
- Sistemas externos (CRMs, chatbots, integrações) que usam o `identifier` e `hmac_token` do SOURCE precisarão ser recadastrados no DEST com os novos valores
- Chamadas de API com o `identifier` antigo simplesmente não encontrarão o inbox (404 ou 422)
- **Ação necessária**: Mapear todos os sistemas integrados via Channel::Api, coletar novos `identifier` e `hmac_token` no DEST, e recadastrar nas integrações
- **Este é o canal mais crítico para integrações B2B** — uma integração não reconfigurada significa perda silenciosa de mensagens

### 3.3 `Channel::FacebookPage` — credenciais copiadas verbatim

O Facebook Messenger channel usa `page_access_token` para enviar/receber mensagens via webhook. Ao copiar verbatim, o DEST tem o mesmo token.

**O que acontece com mensagens novas do Facebook se SOURCE ainda está ativo:**

O Facebook Messenger envia webhooks para **uma única URL** cadastrada por página. Se o SOURCE continua com o webhook configurado apontando para `chat.vya.digital`, **todas as mensagens novas do Facebook chegam somente ao SOURCE**. O DEST não receberá nenhuma mensagem nova.

Se o webhook for alterado para apontar para o DEST (`vya-chat-dev.vya.digital`), o SOURCE para de receber — mas o SOURCE pode tentar reutilizar o mesmo `page_access_token` para respostas, causando conflito.

**Risco adicional:** O Facebook invalida `page_access_tokens` periodicamente ou quando a conexão é refeita. Se o token do SOURCE expirar ou for revogado, o channel no DEST também pára de funcionar imediatamente.

**Recomendação:** Reconectar o Facebook Channel no DEST via UI (não via migração), gerando um novo token dedicado ao DEST. Isso requer coordenação com o admin da página do Facebook.

### 3.4 `Channel::Telegram` — bot token copiado verbatim

O Telegram usa um `bot_token` único por bot. O Telegram **não permite dois sistemas recebendo atualizações do mesmo bot simultaneamente**. Ao copiar o `bot_token` verbatim:

- Se o DEST configurar o webhook para `vya-chat-dev.vya.digital`, o SOURCE pára de receber
- Se ambos tentarem usar `getUpdates` (polling), o Telegram alterna entre eles de forma imprevisível
- O Chatwoot usa webhook mode: quem configurar o webhook por último "ganha"

**Consequência direta:** Assim que o DEST sobe com o `bot_token` copiado e inicializa o canal, o webhook do SOURCE é sobrescrito automaticamente pelo Chatwoot DEST. O SOURCE para de receber mensagens Telegram **imediatamente**, mesmo sem descomissionamento planejado.

**Recomendação:** Este canal exige análise caso a caso: ou criar um novo bot Telegram para o DEST, ou aceitar o cutover imediato do bot para o DEST no momento da migração.

### 3.5 `Channel::Whatsapp` — credenciais verbatim

Semelhante ao Telegram, mas com complexidade maior: o WhatsApp Business API (via Twilio, Meta Cloud API, ou WABA direto) tem restrições mais severas.

**Se utilizado via Twilio:** O número de telefone Twilio tem um webhook configurado no painel Twilio. Copiar as credenciais verbatim não causa conflito imediato no banco, mas quando o DEST inicializar o canal, ele tentará reconfigurar o webhook Twilio — podendo falhar se as credenciais não forem válidas no novo contexto, ou sobrescrever o webhook SOURCE.

**Se utilizado via Meta Cloud API:** O token de acesso é vinculado ao número WABA. Não pode haver dois sistemas com o mesmo número ativo simultaneamente. O cutover é imediato e requer coordenação com o Meta Business Suite.

**Consequência:** Em qualquer variante, copiar verbatim significa que SOURCE e DEST competem pelo mesmo número/webhook. O comportamento é indeterminado e pode resultar em mensagens perdidas.

**Recomendação:** Planejar cutover explícito: desativar o canal no SOURCE antes de ativar no DEST.

### 3.6 `Channel::Email` — configurações SMTP/IMAP verbatim

Ao copiar SMTP/IMAP credentials verbatim, tanto SOURCE quanto DEST têm credenciais para a mesma caixa de email.

**Risco crítico:** O IMAP polling (se habilitado) do Chatwoot busca emails não lidos e os cria como conversas. Se ambos SOURCE e DEST estão ativos com o mesmo IMAP:
- O SOURCE "consome" o email (marca como lido) → o DEST não cria a conversa
- Ou ambos criam a conversa duplicada (corrida entre os dois processos)
- Emails enviados pelo DEST chegam ao destinatário com o endereço da caixa SOURCE (se o endereço não mudar)

**Recomendação:** Desativar o polling IMAP no SOURCE antes de ativar no DEST. Configurar um endereço de email separado para o DEST em ambiente de desenvolvimento.

### 3.7 `Channel::TwilioSms` — número Twilio verbatim

O Twilio roteia SMS para uma única URL de webhook por número. Copiar o número verbatim e ambos os sistemas configurados no Twilio causará conflito de webhook — apenas o sistema que configurou o webhook por último recebe os SMS.

**Recomendação:** Configurar o webhook Twilio explicitamente para apontar para o DEST após a migração. Descomissionar o SOURCE antes de receber novos SMS.

### 3.8 Tabela Resumo de Canais

| Tipo de Canal | Token regenerado? | Risco de conflito com SOURCE ativo | Ação necessária pós-migração |
|---------------|------------------|------------------------------------|------------------------------|
| `Channel::WebWidget` | ✅ Sim (website_token) | Baixo (SOURCE e DEST independentes) | Atualizar script em todos os sites |
| `Channel::Api` | ✅ Sim (identifier, hmac_token) | Baixo | Recadastrar integrações externas |
| `Channel::FacebookPage` | ❌ Não | **ALTO** — webhook conflict | Reconectar via UI, não via migração |
| `Channel::Telegram` | ❌ Não | **CRÍTICO** — webhook sobrescrito | Coordenar cutover ou criar novo bot |
| `Channel::Whatsapp` | ❌ Não | **CRÍTICO** — número compartilhado | Planejar cutover explícito |
| `Channel::Email` | ❌ Não | **ALTO** — IMAP race condition | Desativar IMAP SOURCE antes de ativar DEST |
| `Channel::TwilioSms` | ❌ Não | **ALTO** — webhook Twilio | Configurar webhook explicitamente |

---

## 4. Análise do Fluxo de Criação de Contatos e contact_inboxes

### 4.1 Duplicação por criação automática do Chatwoot

O Chatwoot cria `contact_inboxes` automaticamente quando:
1. Um contato existente inicia uma nova conversa em um inbox
2. O módulo de contato do inbox detecta que não há `contact_inbox` para o par `(contact_id, inbox_id)`
3. Via callback `before_create :set_contact_inbox` no modelo `Conversation`

O `ContactInboxesMigrator` **antecipa** esses registros inserindo-os explicitamente. O dedup por par `(contact_id, inbox_id)` no DEST evita duplicação para pares já existentes. Entretanto:

**Cenário de duplicação residual:** Se um contato migrado do SOURCE entra em contato via um inbox que já existia no DEST antes da migração (inbox pré-existente, não migrado do SOURCE), o Chatwoot cria um novo `contact_inbox` com os IDs nativos do DEST — e o migrador teria criado um com IDs offset. O par `(dest_contact_id, dest_inbox_id)` seria idêntico → a constraint UNIQUE impediria a criação, e o Rails retornaria erro.

**Conclusão:** Para inboxes pré-existentes no DEST (não migrados do SOURCE), não haverá duplicação — a constraint protege. Para inboxes migrados (com ID offset), os contact_inboxes migrados têm IDs diferentes dos que o Rails criaria naturalmente. Não há duplicação técnica, mas há inconsistência de IDs.

### 4.2 `pubsub_token = NULL` — comportamento do Chatwoot

O `pubsub_token` em `contact_inboxes` é gerado pelo Rails via `before_create :generate_pubsub_token`. **Como os registros são inseridos diretamente no banco (não via ActiveRecord), esse callback nunca executa.**

**Consequência funcional:**

O `pubsub_token` é usado pelo Chatwoot para subscriptions WebSocket em tempo real — especificamente, é o token que o frontend usa para se inscrever em notificações de novas mensagens de um contato específico em um inbox. Com `pubsub_token = NULL`:

- O frontend **não pode** estabelecer subscription WebSocket para contact_inboxes migrados
- Mensagens em conversas migradas aparecem apenas via polling/refresh, não em tempo real
- Notificações push de novas mensagens em conversas migradas podem não funcionar

**O Chatwoot gera automaticamente após inserção?** Não. O token é gerado apenas no `before_create` callback, que não roda para INSERTs diretos. Um `UPDATE contact_inboxes SET pubsub_token = gen_random_uuid()::text WHERE pubsub_token IS NULL` é necessário após a migração para restaurar essa funcionalidade.

### 4.3 `source_id` regenerado — impacto na deduplicação

O `source_id` em `contact_inboxes` é o identificador externo do contato no canal específico. No Chatwoot, ele é usado para:
- Identificar um contato existente quando uma nova mensagem chega de um canal (e.g., `phone_number` no WhatsApp, `page_scoped_id` no Facebook)
- Deduplicação: se uma mensagem chega com `source_id` conhecido → conversa roteada para o contact_inbox existente

**Ao regenerar `source_id` com um UUID aleatório**, o Chatwoot DEST perde a capacidade de reconhecer o contato migrado quando ele entrar em contato novamente via canal. O sistema criará um **novo** `contact_inbox` com o `source_id` real do canal, resultando em dois contact_inboxes para o mesmo contato no mesmo inbox — um histórico (com UUID fake) e um novo (com source_id real).

**Impacto prático:** Histórico de conversas do contato migrado não será automaticamente vinculado ao novo contact_inbox. O agente verá o contato como "novo" quando ele voltar a entrar em contato.

**Mitigação possível (sem código):** Para channels que têm `source_id` definido e identificável (e.g., número de telefone no WhatsApp), seria possível copiar o `source_id` original em vez de regenerar — mas isso só é seguro se o DEST não tiver registros pré-existentes com o mesmo `source_id` para o mesmo inbox.

---

## 5. Análise de Mensagens com URLs S3 Legadas

### 5.1 Contexto

O SOURCE (`chatwoot_dev1_db`) contém mensagens onde `messages.content` é um texto como `"Image: https://tbchatuploads.s3.amazonaws.com/..."`. Essas mensagens foram criadas pelo script SQL legado (TBChat → Chatwoot) e não têm registro correspondente em `attachments`. O arquivo físico está em um bucket S3 do sistema TBChat original.

### 5.2 Como o Chatwoot DEST renderiza esse conteúdo na UI

O Chatwoot renderiza `messages.content` como texto simples ou Markdown, dependendo de `content_type`. Para `content_type = 0` (text), o conteúdo é exibido como texto. A string `"Image: https://..."` aparecerá literalmente como texto, sem pré-visualização de imagem.

Se o frontend do Chatwoot detectar uma URL no texto (linkificação automática), a URL será clicável — mas ao clicar, o browser tentará acessar o S3 bucket do TBChat. Se o bucket for privado (presigned URL expirada) ou o objeto tiver sido deletado, o browser retornará 403 ou 404.

**Experiência do usuário:** A mensagem é visível como texto. Nenhum erro na UI do Chatwoot — apenas um link quebrado se o usuário tentar acessar a imagem.

### 5.3 Como o Chatwoot DEST responde via API para essas mensagens

A API retorna o campo `content` verbatim. Não há processamento do conteúdo pela API. A resposta JSON conterá `"content": "Image: https://tbchatuploads.s3..."` normalmente. Nenhum erro de API é gerado.

### 5.4 Risco de erro 500 ao abrir conversas na UI

**Não há risco de HTTP 500 diretamente por causa do content.** O Rails não processa nem valida o campo `content` ao renderizar. O Jbuilder serializa verbatim.

O campo `content_attributes` (tipo `json`) é diferente: se preenchido incorretamente (não-JSON), Rails pode lançar erro de parse. O `MessagesMigrator` copia `content_attributes` verbatim do SOURCE, que já é JSON válido (ou NULL).

**Risco identificado:** O migrador copiou `content_attributes` verbatim do SOURCE (conforme o código em `messages_migrator.py`). A nota no schema diz que este campo deve ser `NULL` — se preenchido com dados do TBChat legado, pode causar comportamento inesperado no Rails. Verificar se `content_attributes` foi normalizado para NULL durante a migração.

### 5.5 Experiência do usuário final

| Cenário | Experiência |
|---------|-------------|
| Mensagem `"Image: https://tbchatuploads.s3..."` | Texto visível com URL clicável. Imagem não pré-visualizada |
| URL S3 acessível publicamente | Link funciona; imagem abre em nova aba |
| URL S3 privada ou expirada | Link abre página de erro S3 (403/404) |
| SOURCE descomissionado, bucket deletado | Link permanentemente quebrado |
| Mensagem com `content = NULL` | Chatwoot exibe mensagem vazia (comportamento esperado para attachments-only) |

**Conclusão:** A experiência é degradada mas não causa erro no sistema. O histórico é preservado como texto, mas sem visualização de imagem inline.

---

## 6. Análise de Impacto no Sistema de Notificações

### 6.1 Notificações ao inserir conversas com status=open

**O Chatwoot NÃO dispara notificações de conversa nova ao fazer INSERT direto no banco.** O sistema de notificações é acionado via ActiveRecord callbacks (`after_create_commit`, `after_update_commit`) e eventos do ActionCable. Um INSERT direto via SQLAlchemy bypassa completamente o Rails, portanto:

- Nenhum email de "nova conversa" é enviado
- Nenhuma notificação push é enviada
- Nenhum evento WebSocket é emitido
- Os contadores de badge da UI (e.g., "5 conversas abertas") serão atualizados apenas quando o agente recarregar a página (consulta direta ao banco)

**Conclusão:** A migração em si não causará "dilúvio" de notificações nos agentes. Porém, após a migração, quando os agentes acessarem a UI pela primeira vez, verão o backlog completo de conversas open sem ter sido notificados de sua chegada — o que pode ser confuso operacionalmente.

### 6.2 Notificações para assignee_id

Pelo mesmo motivo acima, a atribuição de `assignee_id` feita pelo migrador (INSERT com `assignee_id` já preenchido) não aciona o callback `notify_assignee` do Rails. Nenhum email "conversa atribuída a você" é enviado.

**Risco residual:** Se após a migração, um agente editar e salvar qualquer conversa que tenha `assignee_id` preenchido (mesmo sem mudar o assignee), o Rails pode acionar o callback de notificação — potencialmente enviando um email antigo de "nova atribuição" para o agente.

### 6.3 Como prevenir notificações em massa durante a migração

Como a migração é via INSERT direto (não via Rails), notificações em massa **não ocorrem durante a migração** por design. O risco está no **pós-migração**:

| Cenário pós-migração | Risco de notificação | Mitigação |
|----------------------|---------------------|-----------|
| Agente abre a UI pela primeira vez | Vê badge de conversas mas sem notificação push | Informar os agentes antes do cutover |
| Admin edita uma conversa migrada e salva | Rails aciona callbacks → pode notificar assignee | Monitorar as primeiras horas pós-migração |
| Webhook externo envia nova mensagem para conversa migrada | Rails cria a mensagem via ActiveRecord → notifica normalmente | Comportamento esperado, não é problema |
| Bot/integração processa conversas open antigas | Pode acionar automações (labels, respostas automáticas) configuradas no DEST | Verificar automações do DEST antes da migração |

**Automações (CSAT, resolution bots):** O Chatwoot DEST pode ter automações configuradas que são acionadas para conversas com `status=open`. Ao importar conversas abertas, essas automações podem disparar retroativamente (e.g., enviar pesquisa CSAT para conversas de 2024). **Verificar e desativar temporariamente as automações no DEST antes de executar a migração.**

---

## 7. Análise do Impacto no display_id e URLs de Conversas

### 7.1 Mecanismo de display_id (confirmado em D9)

O Chatwoot usa um **trigger PostgreSQL** (não uma sequence global) para gerar `display_id`:

```
trigger BEFORE INSERT em conversations:
  NEW.display_id := nextval('conv_dpid_seq_' || NEW.account_id)
```

O `ConversationsMigrator` calcula `MAX(display_id)` por account antes do loop e incrementa em memória. **Isso serve para pré-calcular o valor — mas o trigger SUBSTITUI o valor calculado pelo Python com o nextval da sequence.**

**Consequência:** O `display_id` efetivamente salvo no banco é determinado pelo trigger, não pelo Python. Como o `ConversationsMigrator` incrementa o contador de forma consistente com a sequence, o resultado final deve ser equivalente — desde que a sequence não seja avançada por operações concorrentes.

### 7.2 URLs compartilhadas anteriormente

Para a conta Vya Digital (account_id=1), o SOURCE tinha conversas com display_id até ~1093. O DEST tinha 378 conversas pré-existentes. Após a migração, as conversas SOURCE recebem display_ids começando em 379.

**Exemplo concreto:**
- URL SOURCE: `chat.vya.digital/app/accounts/1/conversations/1093` → display_id=1093 no SOURCE
- No DEST, esta conversa receberá display_id=379+N (onde N é a posição relativa no lote)
- URL DEST: `vya-chat-dev.vya.digital/app/accounts/1/conversations/379+N` (diferente)

**Impacto:**
- Links compartilhados anteriormente (emails, tickets de suporte, documentos) com URLs do SOURCE **não funcionam** no DEST para as conversas migradas
- A busca por `display_id` antigo (e.g., "conversa 1093") não encontrará nada no DEST — existe no DEST com outro display_id
- O campo `custom_attributes` de conversas tem `src_id` (ID interno do SOURCE), não o `display_id`. A busca por `src_id` exige acesso ao banco ou à API com filtros específicos

**Rastreabilidade pós-migração:** Para localizar uma conversa do SOURCE no DEST, a busca deve ser feita via:
- `conversations.additional_attributes->>'src_id' = '<id_origem>'` — disponível se o migrador popula esse campo
- Verificar se `ConversationsMigrator` popula `additional_attributes['src_id']` (não está explícito no código lido, mas é uma prática documentada no projeto)

### 7.3 Accounts com IDs remapeados

Para `account_id=18 → 61` e `account_id=25 → 68`, as URLs mudam de formato também: `conversations/N` dentro do account_id=61 terá display_ids completamente diferentes dos do SOURCE. Usuários desses accounts precisam ser notificados de que os URLs antigos são inválidos.

---

## 8. Análise de Compatibilidade de Versão Chatwoot

### 8.1 Verificação de versão

O projeto não documenta explicitamente as versões dos dois servidores. A análise D9 referencia `chatwoot/chatwoot` branch `develop` (v3.9+). As diferenças de schema entre versões do Chatwoot são relevantes para a migração via `autoload_with`.

**Risco com SQLAlchemy autoload:** O `autoload_with` carrega o schema real do banco em runtime. Se SOURCE e DEST têm schemas diferentes (colunas adicionadas/removidas em versões diferentes do Chatwoot):

| Cenário | Comportamento |
|---------|--------------|
| Coluna existe no SOURCE mas não no DEST | O `dict(row)` do SOURCE inclui a coluna → INSERT no DEST falha com "column does not exist" |
| Coluna existe no DEST mas não no SOURCE | O INSERT omite a coluna → DEST usa o valor default definido no schema; geralmente OK |
| Tipo de dado diferente (e.g., varchar → jsonb) | INSERT pode falhar com type error |

**Mitigação do autoload:** O `_run_batches` usa o schema do DEST (`dest_table`) para o INSERT. Se o `remap_fn` retorna um campo que não existe em `dest_table`, o SQLAlchemy ignora esse campo (pois o INSERT é construído com as colunas de `dest_table`). Isso protege parcialmente contra colunas extras no SOURCE.

### 8.2 Campo `meta` em conversations

O campo `meta` em `conversations` (presente no Chatwoot como campo JSON denormalizado com dados do sender) é gerado pelo Chatwoot em memória via o método `meta_details` — não é armazenado persistentemente no banco no schema padrão do Chatwoot. Se alguma versão adicionar um campo `meta` persistido, o valor do SOURCE seria copiado com IDs do SOURCE não remapeados.

**Verificação necessária:** `SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'conversations' AND table_schema = 'public'` em SOURCE e DEST para comparar schemas antes da migração.

---

## 9. Recomendações de Execução Operacional

### 9.1 Sequência de Passos Recomendada

A sequência a seguir garante mínimo impacto operacional e máxima rastreabilidade:

**FASE 1 — Preparação (antes do cutover)**

1. Executar `python -m src.migrar --dry-run --poc` no ambiente de staging para classificar todos os registros SOURCE e identificar orphans
2. Verificar e desativar temporariamente todas as **automações** configuradas no Chatwoot DEST (campanhas, CSAT automático, bots de resposta)
3. Verificar se SOURCE e DEST compartilham o mesmo `secret_key_base` do Rails (risco RISCO-A do D11)
4. Documentar todos os sistemas integrados via `Channel::Api` (identifier + hmac_token) para recadastramento posterior
5. Comunicar aos usuários: "O sistema estará em manutenção de [horário] a [horário]. Conversas históricas estarão disponíveis após a manutenção."
6. Definir a política de status: quais conversas migrar como `open` (recentes) vs `resolved` (históricas)

**FASE 2 — Janela de migração (sistema SOURCE pausado)**

7. Pausar o Chatwoot SOURCE (impedir novas conversas; ou colocar em manutenção)
8. Para `Channel::Telegram` e `Channel::Whatsapp`: coordenar cutover com os responsáveis pelos canais
9. Executar o pipeline principal: `python -m src.migrar --verbose`
10. Verificar saída do pipeline: zero erros críticos, migrated counts esperados
11. Executar `app/13_migrar_inbox_members.py` para migrar membros de inboxes

**FASE 3 — Pós-migração imediata (antes de liberar para usuários)**

12. Executar `UPDATE contact_inboxes SET pubsub_token = gen_random_uuid()::text WHERE pubsub_token IS NULL` para restaurar notificações WebSocket em tempo real
13. Validar via API DEST com administrator: contagens de conversas, contatos, inboxes batem com o SOURCE
14. Validar visibilidade para um agente de teste (role=agent) — verificar que inbox_members foram criados
15. Verificar que nenhuma automação disparou retroativamente durante a migração
16. Atualizar scripts de WebWidget em todos os sites com os novos `website_token`
17. Reconfigurar integrações `Channel::Api` com os novos `identifier` e `hmac_token`
18. Reativar automações no DEST

**FASE 4 — Cutover (liberação para usuários)**

19. Comunicar aos usuários: "Migração concluída. Acesse o novo sistema em [URL DEST]."
20. Monitorar durante as primeiras 2 horas: logs do Chatwoot DEST para erros, filas de agentes
21. Manter o SOURCE em modo somente-leitura (não descomissionar imediatamente) por pelo menos 7 dias

### 9.2 Quando desligar o SOURCE

**Não desligar o SOURCE imediatamente.** Manter por 7-30 dias em modo somente-leitura para:
- Resolução de dúvidas de usuários sobre dados históricos
- Referência para rastreabilidade (busca por display_id antigo)
- Fallback se algum dado crítico não foi migrado

Descomissionar o SOURCE antes de resolver os `Channel::WebWidget` (scripts dos sites) e `Channel::Api` (integrações) causará perda de dados de novos contatos durante o período de transição.

### 9.3 Validação de sucesso do ponto de vista do negócio

A migração é considerada bem-sucedida quando:

| Critério de negócio | Como verificar (não técnico) |
|--------------------|-----------------------------|
| Histórico de conversas visível | Um supervisor acessa o DEST e encontra conversas antigas de clientes conhecidos |
| Agentes conseguem operar normalmente | Um agente faz login no DEST e vê suas conversas abertas nos inboxes corretos |
| Canais de entrada funcionando | Um cliente envia mensagem via WhatsApp/Telegram/Widget e o agente recebe no DEST |
| Sem explosão de notificações | Agentes não recebem emails de "nova conversa" para itens históricos |
| Contatos preservados | Busca por nome/telefone/email de clientes conhecidos retorna resultados corretos |

### 9.4 Rollback

Se algo der errado **antes de descomissionar o SOURCE**:

- O rollback do DEST é possível restaurando o backup do banco `chatwoot004_dev1_db` feito antes da migração (snapshot pré-migração obrigatório)
- Redirecionar o DNS ou configuração de proxy para o SOURCE
- As conversas criadas no DEST **durante a janela de migração** (se houver) serão perdidas no rollback — por isso é crítico pausar o SOURCE

**Limite de rollback:** Após descomissionar o SOURCE e os canais serem reconfigurados para o DEST, o rollback é inviável sem perda de dados (novas conversas no DEST seriam perdidas ao restaurar o backup). O ponto de no-return é o descomissionamento do SOURCE.

---

## 10. Riscos Residuais Aceitos

Os riscos a seguir não podem ser completamente eliminados e devem ser **documentados, comunicados ao time de negócio, e explicitamente aceitos** antes da migração de produção.

### 10.1 Tabela de Riscos

| ID | Descrição | Probabilidade | Impacto | Mitigação possível | Aceito? |
|----|-----------|--------------|---------|-------------------|---------|
| R01 | `source_id` regenerado em `contact_inboxes`: contatos retornando via canal não são reconhecidos automaticamente; histórico não vinculado ao novo contact | Alta (100% dos contact_inboxes migrados) | Médio — UX degradada; agente vê "novo contato" em vez de histórico | Copiar source_id original onde não há conflito | Aceitar com comunicação aos agentes |
| R02 | `pubsub_token = NULL` após migração: notificações WebSocket em tempo real não funcionam para contact_inboxes migrados até UPDATE | Alta (100% sem o UPDATE pós-migração) | Médio — sem notificações em tempo real | Executar UPDATE imediatamente pós-migração (item 12 da fase 3) | Mitigável — não aceitar sem mitigação |
| R03 | URLs de conversas antigas (display_id do SOURCE) não são válidas no DEST | Alta (100% das conversas migradas) | Baixo — apenas links históricos quebrados | Documentar e comunicar; manter SOURCE para consulta | Aceitar com comunicação |
| R04 | Mensagens com S3 URLs do TBChat têm imagens quebradas quando SOURCE/TBChat for descomissionado | Alta (todas as mensagens legadas) | Baixo — conteúdo de texto preservado, apenas imagem inacessível | Migrar arquivos S3 (fora do escopo atual) | Aceitar com documentação |
| R05 | Conversas `open` antigas contaminam filas de agentes | Média (depende da política de status) | Alto — impacto operacional imediato | Converter para `resolved` na política de migração | Mitigável — implementar política de status |
| R06 | `Channel::FacebookPage`, `Telegram`, `Whatsapp` com credenciais verbatim: conflito com SOURCE ativo | Depende de quantos canais ativos existem | Crítico — perda de mensagens em produção | Coordenar cutover explícito por canal | Não aceitar sem plano de cutover |
| R07 | `authentication_token` de users copiado verbatim: risco de acesso cruzado SOURCE/DEST | Baixa (apenas se `secret_key_base` compartilhado) | Alto — risco de segurança | Verificar `secret_key_base`; gerar novo token se necessário | Não aceitar sem verificação |
| R08 | Duplicação de inboxes para contas merged (BUG-B D11): 100% das conversas de contas merged vinculadas a inboxes-duplicata | Alta (afeta account_id=1 Vya Digital) | Crítico — todas as conversas no inbox errado; agentes nos inboxes originais não veem | Implementar dedup no `InboxesMigrator` antes de executar em produção | Não aceitar — requer correção |
| R09 | Race condition em `display_id` se Chatwoot DEST não for pausado durante migração | Média (se sistema ativo durante migração) | Médio — falha de batch de conversas | Pausar o sistema durante a migração (janela de manutenção) | Mitigável — planejar janela de manutenção |
| R10 | Contatos sem phone/email/identifier não sofrem dedup: duplicatas silenciosas | Média (depende da qualidade dos dados SOURCE) | Baixo — contatos duplicados, visíveis via busca | Limpeza manual pós-migração; aceitar duplicatas de contatos anônimos | Aceitar com documentação |
| R11 | Automações do DEST disparando retroativamente para conversas open importadas | Baixa se automações forem desativadas previamente | Alto — spam de CSAT, respostas automáticas para clientes históricos | Desativar automações antes da migração (item 2 da fase 1) | Mitigável — não aceitar sem mitigação |
| R12 | `inbox_members` executado para inboxes-duplicata (cascade do BUG-B): agentes membros dos inboxes errados | Alta se BUG-B não corrigido | Crítico — agrupa R08 | Corrigir BUG-B primeiro | Não aceitar — bloqueia R08 |

### 10.2 Bloqueadores para Produção

Os riscos que **bloqueiam a execução em produção** (não podem ser aceitos):

| ID | Descrição | O que resolve |
|----|-----------|--------------|
| **R08** | Duplicação de inboxes para contas merged — 100% das conversas de Vya Digital no inbox errado | Implementar dedup em `InboxesMigrator` (ver D11 BUG-B) |
| **R06** | Canais de produção (Facebook, Telegram, WhatsApp) com credenciais conflitantes | Plano de cutover por canal antes da migração |
| **R07** | `authentication_token` — risco de segurança | Verificar `secret_key_base`; regenerar token se necessário |
| **R02** | `pubsub_token = NULL` sem UPDATE pós-migração | Garantir execução do UPDATE na fase 3 |
| **R11** | Automações disparando retroativamente | Desativar automações antes da migração |

---

*Documento gerado por: GitHub Copilot (Chatwoot Expert Agent) — 2026-04-24*
*Baseado em: D7, D8, D9, D10, D11; src/migrators/; app/13_migrar_inbox_members.py*
*Próximo debate sugerido: D13 — Plano de Correção do BUG-B (InboxesMigrator dedup para contas merged)*
