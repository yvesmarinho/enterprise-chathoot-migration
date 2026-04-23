# Q1 — Questionário de Informações Faltantes para Migração Completa

**Data**: 2026-04-23
**Contexto**: Migração enterprise `chatwoot_dev1_db` (SOURCE: chat.vya.digital)
→ `chatwoot004_dev1_db` (DEST: synchat / vya-chat-dev.vya.digital)

---

## Bloco A — Canais Migrados (Channel Credentials)

### Q-A1: Facebook Page (inbox "vya.digital", source inbox_id=13)

O SOURCE tem uma inbox do tipo `Channel::FacebookPage` com `page_id` e tokens de
autenticação que foram copiados para o DEST.

**Pergunta**: O token de acesso da página do Facebook (`page_access_token` e
`user_access_token`) que está no SOURCE ainda é válido?

- [ ] Sim — os tokens são válidos e a integração funcionará no DEST
- [ ] Não — o Facebook revogou os tokens (a inbox ficará em DEST mas sem funcionar)
- [ ] Não sei / Precisa verificar com o responsável

**Impacto se inválido**: O inbox aparecerá na API (visível), mas não receberá
mensagens do Facebook. Pode ser reconfigurado manualmente no painel Chatwoot.

---

### Q-A2: Telegram Bot (inbox "VyaDigitalBot Telegram", source inbox_id=53)

O SOURCE tem uma inbox do tipo `Channel::Telegram` com `bot_token`.

**Pergunta**: O bot token do Telegram copiado do SOURCE deve ser reutilizado
no DEST?

- [ ] Sim — usar o mesmo bot no DEST (o webhook deve ser reconfigurado para apontar para o novo domínio)
- [ ] Não — criar um novo bot separado para DEST
- [ ] Não sei / consultar responsável

**Observação crítica**: Dois Chatwoot ativos com o **mesmo bot token** causará
conflito de webhook (o Telegram só aceita um webhook por bot). Um dos dois
parará de receber mensagens.

**Ação necessária após migração** (se opção "Sim"):
```bash
# Atualizar webhook do Telegram para o DEST:
curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://vya-chat-dev.vya.digital/webhooks/telegram/bot<TOKEN>"
```

---

### Q-A3: Inboxes Channel::Api (4 inboxes)

Os 4 inboxes do tipo `Channel::Api` têm webhook URLs apontando para serviços
externos (ex: `wea001.vya.digital`, `wea004.vya.digital`).

**Pergunta**: Após a migração, esses webhooks externos devem ser atualizados para
enviar mensagens para o DEST (vya-chat-dev.vya.digital) em vez do SOURCE
(chat.vya.digital)?

| Inbox SOURCE | webhook_url atual |
|-------------|------------------|
| AtendimentoVYADIgital (id=32) | (verificar no SOURCE) |
| 551131357298 (id=85) | wea001.vya.digital |
| 5535988628436 (id=103) | wea001.vya.digital |
| wea004 (id=125) | wea004.vya.digital |

- [ ] Sim — atualizar webhooks para o DEST
- [ ] Não — SOURCE e DEST rodando em paralelo (ambos recebem mensagens)
- [ ] Não sei

---

## Bloco B — Estratégia de Deduplicação

### Q-B1: Inboxes com mesmo nome em SOURCE e DEST

O SOURCE tem 14 inboxes para account_id=1. O DEST tem 18 inboxes pré-existentes
para account_id=1.

**Pergunta**: Algum inbox do SOURCE deve ser **fundido** com um inbox
pré-existente do DEST (em vez de criar um novo)?

Exemplo: SOURCE tem "Atendimento Web" — existe um inbox com esse nome no DEST?

- [ ] Não — todos os 14 inboxes do SOURCE são inboxes distintos dos 18 do DEST
- [ ] Sim — especificar quais pares devem ser fundidos: ________________
- [ ] Verificar manualmente

**Impacto**: Se fundidos, as conversas do SOURCE serão associadas ao inbox
DEST existente. Se separados (padrão atual), um novo inbox é criado para cada
um do SOURCE.

---

### Q-B2: Contatos duplicados entre SOURCE e DEST

Contatos com mesmo phone_number ou email são automaticamente deduplicados pelo
`ContactsMigrator` (via merge rule). Porém, para contatos sem phone/email
(apenas `identifier`), a deduplicação depende do campo `identifier`.

**Pergunta**: Existem contatos no SOURCE que devem ser tratados como o mesmo
contato no DEST mas têm informações diferentes (ex: mesmo número mas um tem
email e o outro não)?

- [ ] Não — a deduplicação automática por phone/email é suficiente
- [ ] Sim — existem casos especiais: ________________
- [ ] Não sei

---

## Bloco C — S3 / Attachments

### Q-C1: Acesso aos buckets S3 do SOURCE a partir do DEST

O `AttachmentsMigrator` copia os registros de `attachments` com
`external_url` verbatim (URL do S3). Os **arquivos físicos** não são movidos.

**Pergunta**: O bucket S3 onde os attachments do SOURCE estão armazenados
é acessível publicamente (ou com as mesmas credenciais) a partir da aplicação
DEST?

- [ ] Sim — os arquivos S3 são acessíveis via URL (públicos ou CDN compartilhado)
- [ ] Não — o S3 é privado e requer credenciais diferentes no DEST
- [ ] Não se aplica — não usamos S3 (attachments locais/disco)

**Se "Não"**: Os attachments aparecerão na UI do Chatwoot mas os links de
download retornarão 403/404. Será necessário um processo separado de
transferência dos arquivos S3.

---

## Bloco D — Operacionalização Pós-Migração

### Q-D1: Período de operação paralela SOURCE + DEST

**Pergunta**: SOURCE (chat.vya.digital) e DEST (synchat/vya-chat-dev.vya.digital)
operarão em **paralelo** (recebendo novas conversas simultaneamente) após a
migração?

- [ ] Não — SOURCE será desativado após migração (big-bang cutover)
- [ ] Sim — operar em paralelo por N dias: ______
- [ ] Não decidido ainda

**Impacto crítico se paralelo**: Novas conversas surgirão no SOURCE após a
migração. Para incluí-las no DEST será necessária uma **re-execução incremental**
da migração (ou operação de delta sync). O design atual do migrador suporta
re-execuções idempotentes via `migration_state`.

---

### Q-D2: Inboxes de Telegram e Facebook — ação pós-migração

**Pergunta**: Após a migração, qual é o plano para os inboxes do Telegram e
Facebook no SOURCE?

- [ ] Desativar os inboxes no SOURCE para evitar duplicação
- [ ] Manter ativo no SOURCE e criar novo bot/página separada no DEST
- [ ] Pausar integração temporariamente durante a transição

---

## Bloco E — Validação

### Q-E1: Critério de sucesso da migração

**Pergunta**: Qual é o critério mínimo de sucesso para declarar a migração
concluída?

- [ ] 100% das conversas visíveis na API do DEST
- [ ] 100% das conversas + mensagens verificadas
- [ ] X% das conversas + amostragem de mensagens (X = ____)
- [ ] Validação manual por usuário-chave (ex: Marcos / admin)

---

### Q-E2: Conversas com contato_id=NULL aceitáveis?

O `ConversationsMigrator` pode NULL-out `contact_id` para conversas cujo
contato SOURCE não foi migrado (ex: contato sem phone/email que não pôde ser
deduplicado).

**Pergunta**: Conversas sem contact_id associado são aceitáveis no DEST?

- [ ] Sim — podem ser re-vinculadas manualmente depois
- [ ] Não — todas as conversas DEVEM ter contact_id; investigar antes de migrar
- [ ] Depende da quantidade (informar threshold: ____)

---

## Resumo de Ações Bloqueantes

| Código | Questão | Urgência |
|--------|---------|---------|
| Q-A2 | Estratégia bot Telegram (conflito webhook) | 🔴 CRÍTICO antes de migrar |
| Q-D1 | Operação paralela ou big-bang? | 🔴 CRÍTICO antes de migrar |
| Q-A1 | Validade tokens Facebook | 🟡 Alta (funcionalidade) |
| Q-A3 | Atualizar webhooks Channel::Api | 🟡 Alta (funcionalidade) |
| Q-C1 | Acesso S3 attachments | 🟡 Alta (dados) |
| Q-B1 | Deduplicação inboxes | 🟢 Médio |
| Q-E1 | Critério de sucesso | 🟢 Médio |
| Q-B2 | Contatos especiais | 🟢 Baixo |
| Q-D2 | Plano Facebook/Telegram pós-migração | 🟢 Baixo |
| Q-E2 | Conversas sem contact_id | 🟢 Baixo |
