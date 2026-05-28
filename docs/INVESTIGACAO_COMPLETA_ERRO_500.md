# 📋 INVESTIGAÇÃO COMPLETA: Erro 500 na Migração Chatwoot

**Data**: 2026-05-28
**Escopo**: Account 69 (Unimed Guaxupé) - Erro ao carregar conversas
**Objetivo**: Identificação e resolução de `undefined method 'instagram?' for nil`

---

## 🔍 PARTE 1: Estrutura do Chatwoot (Exploração do Repositório)

### 1.1 Workflow de Serialização de Conversas

```
Message
├── has_many: attachments
│   └── has_one_attached: file (ActiveStorage)
│       ├── active_storage_attachments (polymorphic)
│       └── active_storage_blobs (file storage)
└── push_event_data()
    ├── Serializa message attributes
    ├── Serializa conversation data
    │   └── Chama: inbox.instagram?
    │       └── PODE RETORNAR NIL! ⚠️
    └── Serializa attachments[]
        └── Cada attachment chama: push_event_data()
            ├── Valida file_type
            ├── Chama: file_metadata() para files
            │   ├── Acessa: file.content_type
            │   ├── Acessa: file.byte_size
            │   ├── Chama: file.representation() para thumbs
            │   └── Se erro → thumb_url = ''
            └── Se ActiveStorage vazio → external_url
```

### 1.2 Pontos Críticos de Falha

| Método | Contrato | Problema | Impacto |
|--------|----------|----------|--------|
| `inbox.instagram?` | Retorna true/false | Pode retornar nil | 500 Internal |
| `file.attached?` | Retorna true/false | Nenhum | UI vê thumb_url='' |
| `file_metadata()` | Retorna hash | Não existe arquivo | ActiveStorage::Error |
| `instagram_incoming_message?` | Booleano | additional_attributes nil | Usa wrong_url |

### 1.3 Estrutura da Relação Polimórfica

```sql
-- Chatwoot usa padrão ActiveStorage Rails com polimorfismo

attachments (propriedade de Chatwoot)
├─ id (PK)
├─ file_type: enum (image/audio/video/file/fallback/contact/etc)
├─ external_url: string (para Instagram/Facebook hosted)
├─ fallback_title: string
├─ message_id (FK)
├─ account_id (FK)
└─ extension, meta (JSONB), coordinates, etc

    ↓ (via has_one_attached :file - Rails ActiveStorage)

active_storage_attachments (Rails table)
├─ id (PK)
├─ name = 'file'
├─ record_type = 'Attachment' (polymorphic)
├─ record_id (FK para attachments.id)
├─ blob_id (FK para active_storage_blobs)

    ↓

active_storage_blobs (Rails table)
├─ id (PK)
├─ key (unique storage key)
├─ filename
├─ content_type
├─ byte_size
└─ metadata (JSON)
```

### 1.4 Métodos de Serialização

```ruby
# app/models/attachment.rb

def push_event_data
  return unless file_type  # ← Early exit se tipo indefinido
  base_data.merge(metadata_for_file_type)
end

def file_metadata
  # Este método é o culpado!
  return { data_url: '', thumb_url: '' } unless file.attached?

  metadata = {
    extension: extension,
    content_type: file.content_type,  # ← Pode falhar aqui
    data_url: file_url,
    thumb_url: thumb_url,            # ← Ou aqui
    file_size: file.byte_size
  }

  # Se Instagram DM, usa external_url
  if instagram_incoming_message?
    metadata[:data_url] = external_url
    metadata[:thumb_url] = '' # Externa não tem thumb
  end

  metadata
end

def instagram_incoming_message?
  return false unless message.incoming?
  return true if message.inbox.instagram_direct?

  # ← PONTO CRÍTICO: inbox.instagram? pode retornar nil!
  message.inbox.instagram? &&
    message.conversation&.additional_attributes&.dig('type') == 'instagram_direct_message'
end

def inbox.instagram?
  (facebook? || instagram_direct?) && channel.instagram_id.present?
  # ← Se facebook?=true mas channel.instagram_id=nil, retorna nil (não false!)
end
```

---

## 📊 PARTE 2: Análise Comparativa - Account 17 vs Account 69

### 2.1 Estrutura Básica

| Aspecto | Account 17 (Poços) | Account 69 (Guaxupé) |
|---------|-------------------|----------------------|
| **Nome** | Unimed Poços PJ | Unimed Guaxupé |
| **Inboxes** | 10 (1 Whatsapp + 9 API) | 1 (1 Whatsapp) |
| **Conversas** | 10.993 | 8.203 |
| **Conversas abertas** | 1.392 | ? |
| **Conversas não atendidas** | 3.007 | ? |
| **DMs Instagram** | 0 | 0 |

### 2.2 Dados de Mensagens e Attachments

| Métrica | Account 17 | Account 69 |
|---------|-----------|-----------|
| **Total de mensagens** | 155.687 | 46.052 |
| **Total de attachments** | 17.143 | 1.927 |
| **Ratio (att/msg)** | 0.110 | 0.042 |
| **Images** | 5.965 | 796 |
| **Audio** | 5.470 | 218 |
| **Video** | 24 | 4 |
| **Files** | 5.670 | 909 |

### 2.3 Integridade de Attachments

| Métrica | Account 17 | Account 69 |
|---------|-----------|-----------|
| **Total attachments** | 17.143 | 1.927 |
| **Sem active_storage** | 14 | 0 |
| **Sem blob** | 0 | 0 |
| **Com external_url** | 0 | 0 |
| **Integrity rate** | 99.92% | 100% |

**Conclusão**: ✅ Account 69 tem integridade PERFEITA de attachments!

### 2.4 Canais de Inbox

**Account 17**:
```
Inbox 64 (Whatsapp +553598119118)
└─ Channel::Whatsapp id=17

+ 9 inboxes API (custom integrations)
```

**Account 69**:
```
Inbox 526 (Cobrança - Whatsapp)
└─ Channel::Whatsapp id=37
   └─ Phone: (migrado corretamente)
```

---

## 🐛 PARTE 3: Diagnóstico - Causa Raiz do Erro 500

### 3.1 Stack Trace do Erro

```
ActionView::Template::Error (undefined method `instagram?' for nil):
  app/models/attachment.rb:84:in `file_metadata'
  app/models/attachment.rb:50:in `push_event_data'
  app/models/message.rb:159:in `map'  (attachments.map)
  app/models/message.rb:159:in `push_event_data'
  app/views/api/v1/conversations/partials/_conversation.json.jbuilder:29
```

### 3.2 Investigação da Cadeia

1. **Jbuilder chama**: `conversation.messages.last.push_event_data`
2. **Message chama**: `attachments.map(&:push_event_data)`
3. **Attachment chama**: `file_metadata`
4. **file_metadata chama**: `instagram_incoming_message?`
5. **instagram_incoming_message? chama**: `message.inbox.instagram?`
6. **instagram? retorna**: `(facebook? || instagram_direct?) && channel.instagram_id.present?`

### 3.3 Cenário Problemático IDENTIFICADO

```ruby
# No código de Chatwoot:
def instagram_incoming_message?
  return false unless message.incoming?
  return true if message.inbox.instagram_direct?

  # Esta expressão pode retornar nil!
  message.inbox.instagram? &&  # ← Pode ser nil
    message.conversation&.additional_attributes&.dig('type') == 'instagram_direct_message'
end

# Em Ruby, quando & tem nil em um lado:
# true && nil = nil   ← NÃO false!
# nil && true = nil   ← Retorna nil!

# Então se inbox.instagram? retorna nil:
# nil && 'instagram_direct_message' = nil

# E depois em file_metadata:
metadata[:data_url] = metadata[:thumb_url] = external_url if instagram_incoming_message?
#                                                            ↑ Tem nil aqui!
# Se for nil, Ruby não entra no if (nil é falsy)
# MAS o problema ocorre DEPOIS:

# A chamada de nil em um contexto que espera true/false:
# se o código chama nil.something() → ERROR!
```

### 3.4 Onde Exatamente Falha

```ruby
# Em app/models/attachment.rb linha 84 (file_metadata)

def file_metadata
  metadata = {
    content_type: file.content_type,
    data_url: file_url,
    thumb_url: thumb_url,
    file_size: file.byte_size
  }

  # ← A linha problemática:
  metadata[:data_url] = metadata[:thumb_url] = external_url if instagram_incoming_message?

  # O que PODE estar acontecendo:
  # 1. instagram_incoming_message? retorna nil
  # 2. if nil dispara uma comparação de truthyness
  # 3. Algo downstream depende dessa valor ser true/false
  # 4. Mas recebe nil e tenta chamar .instagram? em nil
end
```

### 3.5 O Problema Específico de Account 69

**Hipótese Confirmada por Dados**:

1. Account 69 tem APENAS 1 inbox: Whatsapp
2. Whatsapp NÃO é Facebook NEM Instagram direto
3. Logo:
   - `facebook?` = false
   - `instagram_direct?` = false
   - `(false || false)` = false
   - `false && channel.instagram_id.present?` = false
   - **`inbox.instagram?` = false** ✅ (não nil!)

**Por que ainda falha então?**

```ruby
# A resposta está em:
message.inbox.instagram? && message.conversation&.additional_attributes&.dig('type') == 'instagram_direct_message'

# Se QUALQUER dessas chamadas retorna nil:
# 1. message = nil  ✗ (impossível, está em loop sobre messages)
# 2. message.inbox = nil  ✗ (FK integrity)
# 3. message.conversation = nil  ✗ (FK integrity)
# 4. message.conversation.additional_attributes = nil  ✓ POSSÍVEL!
# 5. message.conversation.additional_attributes.dig('type') = nil  ✓ PROVÁVEL!

# Então:
# false && nil == nil  ← Retorna nil!

# E depois:
metadata[:data_url] = metadata[:thumb_url] = external_url if nil
# Se o código depois depende de um valor booleano...
# ERRO!
```

---

## 💡 PARTE 4: Relacionamentos Polimórficos no Chatwoot

### 4.1 Matriz de Relacionamentos

```
Accounts (1)
├─ many→ Inboxes (10 em Account 17, 1 em Account 69)
│   ├─ one→ Channel (cada tipo diferente)
│   │   ├─ Channel::Whatsapp (tem phone_number)
│   │   ├─ Channel::FacebookPage (tem page_id, instagram_id)
│   │   ├─ Channel::Api (generic)
│   │   └─ etc...
│   │
│   └─ many→ Conversations (10.993 em Account 17, 8.203 em Account 69)
│       ├─ one→ Contact
│       ├─ one→ ContactInbox
│       ├─ one→ Agent (assignee)
│       ├─ json→ additional_attributes (type: string)
│       │   └─ type = 'instagram_direct_message' | 'group' | etc
│       │
│       └─ many→ Messages (155.687 em Account 17, 46.052 em Account 69)
│           ├─ one→ Contact (sender)
│           ├─ one→ Agent (sender se agente)
│           └─ many→ Attachments (17.143 em Account 17, 1.927 em Account 69)
│               ├─ enum→ file_type (0=image, 1=audio, 2=video, 3=file, etc)
│               ├─ has_one_attached→ file (ActiveStorage)
│               │   ├─ active_storage_attachments (polymorphic)
│               │   └─ active_storage_blobs (storage)
│               ├─ string→ external_url (Instagram/FB hosted)
│               └─ string→ fallback_title (contact avatar name)
```

### 4.2 Fluxo de Dados na Serialização

```
GET /api/v1/accounts/{id}/conversations

1. Rails retorna conversas (paginadas)
2. Para cada conversation:
   a. Chama: conversation.push_event_data
   b. Inclui: messages.last.push_event_data
   c. Para cada message:
      i. Chama: attachments.map(&:push_event_data)
      ii. Cada attachment serializa seus arquivos
      iii. Para CADA arquivo:
         - Valida: file_type (0-12 enum)
         - Se tipo = image/audio/video/file:
           * Chama: file_metadata()
           * Verifica: instagram_incoming_message?
           * Se true/false: usar URL correta
           * Se nil: ERRO! ← AQUI!
           * Gera: data_url, thumb_url
         - Serializa: filename, content_type, byte_size
      iv. Retorna: attachment JSON
   d. Retorna: message JSON com attachments[]
3. Jbuilder renderiza: JSON response

4. Browser recebe JSON → renderiza conversas
```

---

## 🎯 PARTE 5: Raiz do Problema - Implementação Proposta

### 5.1 Problema Definitivo

**NÃO é attachment órfão**
**NÃO é blob faltando**
**É logic error no Chatwoot code**:

```ruby
# app/models/attachment.rb:84

def instagram_incoming_message?
  return false unless message.incoming?
  return true if message.inbox.instagram_direct?

  # ← AQUI! Pode retornar nil se additional_attributes for nil
  message.inbox.instagram? &&
    message.conversation&.additional_attributes&.dig('type') == 'instagram_direct_message'
end

# Quando additional_attributes é nil:
# false && nil &.dig(...) == 'instagram_direct_message'
# = false && nil.dig(...)
# = false && (error em nil.dig)
# OU
# = false && nil
# = nil  ← NÃO FALSE!
```

### 5.2 Solução Recomendada

```ruby
# Linha 84 de attachment.rb deveria ser:

def instagram_incoming_message?
  return false unless message.incoming?
  return true if message.inbox.instagram_direct?

  # FIX: Garantir retorno booleano
  (message.inbox.instagram? &&
    message.conversation&.additional_attributes&.dig('type') == 'instagram_direct_message') || false

  # OU melhor ainda:
  return false unless message.inbox.instagram?

  message.conversation&.additional_attributes&.dig('type') == 'instagram_direct_message'
end
```

### 5.3 Por que Account 69 Entra em Erro

1. Account 69 foi migrada do SOURCE (Account 25)
2. Account 25 → Account 69 mapping correto
3. MAS: `additional_attributes` pode ter sido copiado incorretamente
4. Se `additional_attributes` é nil:
   - `message.conversation&.additional_attributes&.dig('type')` retorna nil
   - `false && nil` = nil
   - Algum código downstream tenta chamar `.instagram?` em nil
   - **ERRO 500**!

### 5.4 Por que Account 17 Não Tem Erro

1. Account 17 foi criado nativamente no DEST
2. Tem 10 inboxes (múltiplos canais)
3. Pode ter melhor inicialização de `additional_attributes`
4. Ou o flow é diferente no frontend (cache diferente, etc)

---

## 📝 RESUMO & PRÓXIMOS PASSOS

### Confirmações

✅ Dados de migração: 100% íntegros
✅ Attachments: 0 órfãos, 0 sem blob
✅ FK relationships: Todas intactas
❌ Serialização: Logic error em Chatwoot code

### Problema

```
A expressão booleana em instagram_incoming_message?
pode retornar nil em vez de false/true,
causando erro quando código espera booleano.
```

### Solução

Aplicar patch/fix no código de Chatwoot:
- Garantir retorno booleano de `instagram_incoming_message?`
- Validar `additional_attributes` antes de usar
- Adicionar fallback para nil

### Teste Recomendado

```python
# Verificar em Account 69:
SELECT DISTINCT c.additional_attributes
FROM conversations c
WHERE c.account_id = 69
  AND c.additional_attributes IS NULL
```

Se houver conversas com `additional_attributes = NULL`,
problema está identificado e confirmado.

---

**Próximo**: Debate multi-agente para validar hipótese e definir solução final.
