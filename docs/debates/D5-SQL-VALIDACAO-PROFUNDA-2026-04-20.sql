-- =============================================================================
-- D5 — SQL de Validação Profunda de Dados Migrados
-- Projeto: enterprise-chatwoot-migration
-- Data:    2026-04-20
-- Autor:   @dba-sql-expert
--
-- Contexto:
--   SOURCE DB : chatwoot_dev1_db  (read-only) — verdade canônica
--   DEST DB   : chatwoot004_dev1_db (read-write)
--   migration_state reside EXCLUSIVAMENTE no DEST (tabela de controle de migração)
--
-- Convenção de parâmetros:
--   :param_name  → substituído pelo Python via psycopg2 (%s) ou SQLAlchemy (bindparam)
--
-- ATENÇÃO: queries de seções 1-4 rodam no SOURCE.
--          Queries de seções 5-7 rodam no DEST.
--          Comparação cross-DB é feita no Python (seção 8 explica o contrato).
-- =============================================================================


-- =============================================================================
-- SEÇÃO 1: BUSCA DO CONTATO NO SOURCE
-- =============================================================================

-- 1a. Busca por phone_number (normalização: strip não-dígitos, compara últimos 11)
--     Captura formatos: "+5511999990000", "5511999990000", "(11) 99999-0000" etc.
--
--     [SOURCE] Parâmetro: :phone_input (string bruta do usuário)
--              :src_account_id (int — filtra o account correto)
SELECT
    c.id,
    c.account_id,
    c.name,
    c.phone_number,
    c.email,
    c.identifier,
    c.pubsub_token,
    c.custom_attributes,
    c.created_at,
    c.updated_at
FROM contacts c
WHERE c.account_id = :src_account_id
  AND RIGHT(
          REGEXP_REPLACE(c.phone_number, '[^0-9]', '', 'g'),
          11
      ) = RIGHT(
              REGEXP_REPLACE(:phone_input, '[^0-9]', '', 'g'),
              11
          )
ORDER BY c.id;

-- 1b. Busca por e-mail (case-insensitive, trim)
--     [SOURCE] Parâmetro: :email_input, :src_account_id
SELECT
    c.id,
    c.account_id,
    c.name,
    c.phone_number,
    c.email,
    c.identifier,
    c.pubsub_token,
    c.custom_attributes,
    c.created_at,
    c.updated_at
FROM contacts c
WHERE c.account_id = :src_account_id
  AND LOWER(TRIM(c.email)) = LOWER(TRIM(:email_input))
ORDER BY c.id;

-- 1c. Busca por identifier (chave externa do sistema de origem, ex: CRM ID)
--     [SOURCE] Parâmetro: :identifier_input, :src_account_id
SELECT
    c.id,
    c.account_id,
    c.name,
    c.phone_number,
    c.email,
    c.identifier,
    c.pubsub_token,
    c.custom_attributes,
    c.created_at,
    c.updated_at
FROM contacts c
WHERE c.account_id = :src_account_id
  AND LOWER(TRIM(c.identifier)) = LOWER(TRIM(:identifier_input))
ORDER BY c.id;


-- =============================================================================
-- SEÇÃO 2: TODAS AS CONVERSAS DO CONTATO NO SOURCE
-- =============================================================================

-- [SOURCE] Parâmetros: :src_contact_id, :src_account_id
-- Retorna todas as conversas com campos completos para comparação.
-- Campos críticos de integridade: display_id, status, inbox_id, assignee_id.
-- Campos que diferirão no DEST: id, contact_id, inbox_id (remapeados).
SELECT
    cv.id                       AS src_conv_id,
    cv.account_id               AS src_account_id,
    cv.contact_id               AS src_contact_id,
    cv.inbox_id                 AS src_inbox_id,
    cv.display_id,
    cv.status,
    cv.assignee_id              AS src_assignee_id,
    cv.created_at,
    cv.updated_at,
    cv.additional_attributes,
    cv.custom_attributes,
    -- Contagem prévia de mensagens (evita N+1 no Python)
    (
        SELECT COUNT(*)
        FROM messages m
        WHERE m.conversation_id = cv.id
    )                           AS msg_count,
    -- Contagem de attachments na conversa
    (
        SELECT COUNT(*)
        FROM attachments a
        JOIN messages m ON m.id = a.message_id
        WHERE m.conversation_id = cv.id
    )                           AS att_count
FROM conversations cv
WHERE cv.contact_id  = :src_contact_id
  AND cv.account_id  = :src_account_id
ORDER BY cv.created_at, cv.id;


-- =============================================================================
-- SEÇÃO 3: TODAS AS MENSAGENS DE UMA CONVERSA NO SOURCE
-- =============================================================================

-- [SOURCE] Parâmetro: :src_conversation_id
-- message_type: 0=incoming, 1=outgoing, 2=activity, 3=template
-- sender_type: 'Contact', 'User', 'AgentBot', NULL
SELECT
    m.id                        AS src_msg_id,
    m.conversation_id           AS src_conv_id,
    m.account_id                AS src_account_id,
    m.message_type,
    m.content,
    m.content_type,
    m.created_at,
    m.updated_at,
    m.sender_type,
    m.sender_id                 AS src_sender_id,
    m.private,
    m.status,
    m.additional_attributes,
    -- Flag de presença de attachment (evita sub-query por mensagem no Python)
    EXISTS (
        SELECT 1 FROM attachments a WHERE a.message_id = m.id
    )                           AS has_attachment
FROM messages m
WHERE m.conversation_id = :src_conversation_id
ORDER BY m.created_at, m.id;


-- =============================================================================
-- SEÇÃO 4: TODOS OS ANEXOS DE UMA MENSAGEM NO SOURCE
-- =============================================================================

-- [SOURCE] Parâmetro: :src_message_id
-- external_url: referência S3 — deve ser copiada verbatim para o DEST.
-- Coluna file_url NÃO existe em attachments; o campo S3 é external_url.
SELECT
    a.id                        AS src_att_id,
    a.message_id                AS src_message_id,
    a.account_id                AS src_account_id,
    a.file_type,
    a.external_url,
    a.content_type,
    a.created_at
FROM attachments a
WHERE a.message_id = :src_message_id
ORDER BY a.id;

-- 4b. Batch: todos os attachments de uma lista de message_ids (eficiente para N msgs)
--     [SOURCE] Parâmetro: :src_message_ids (array de ints — ANY(:src_message_ids))
SELECT
    a.id                        AS src_att_id,
    a.message_id                AS src_message_id,
    a.account_id                AS src_account_id,
    a.file_type,
    a.external_url,
    a.content_type,
    a.created_at
FROM attachments a
WHERE a.message_id = ANY(:src_message_ids)
ORDER BY a.message_id, a.id;


-- =============================================================================
-- SEÇÃO 5: MAPEAMENTO SOURCE → DEST via migration_state
-- =============================================================================
-- Todas as queries desta seção rodam NO DEST DB.
-- migration_state.tabela usa os nomes literais: 'contacts', 'conversations',
-- 'messages', 'attachments', 'inboxes', 'accounts', 'users'.

-- 5a. Mapeamento de um contato
--     [DEST] Parâmetro: :src_contact_id
SELECT
    ms.id_origem   AS src_contact_id,
    ms.id_destino  AS dest_contact_id,
    ms.status,
    ms.migrated_at
FROM migration_state ms
WHERE ms.tabela    = 'contacts'
  AND ms.id_origem = :src_contact_id
  AND ms.status    = 'ok';

-- 5b. Mapeamento de uma conversa
--     [DEST] Parâmetro: :src_conversation_id
SELECT
    ms.id_origem   AS src_conv_id,
    ms.id_destino  AS dest_conv_id,
    ms.status,
    ms.migrated_at
FROM migration_state ms
WHERE ms.tabela    = 'conversations'
  AND ms.id_origem = :src_conversation_id
  AND ms.status    = 'ok';

-- 5c. Mapeamento batch de mensagens (ANY para IN-list eficiente)
--     [DEST] Parâmetro: :src_msg_ids (array de ints)
--     Retorna apenas as mensagens que foram migradas com sucesso.
SELECT
    ms.id_origem   AS src_msg_id,
    ms.id_destino  AS dest_msg_id,
    ms.migrated_at
FROM migration_state ms
WHERE ms.tabela    = 'messages'
  AND ms.id_origem = ANY(:src_msg_ids)
  AND ms.status    = 'ok'
ORDER BY ms.id_origem;

-- 5d. Mapeamento batch de attachments
--     [DEST] Parâmetro: :src_att_ids (array de ints)
SELECT
    ms.id_origem   AS src_att_id,
    ms.id_destino  AS dest_att_id,
    ms.migrated_at
FROM migration_state ms
WHERE ms.tabela    = 'attachments'
  AND ms.id_origem = ANY(:src_att_ids)
  AND ms.status    = 'ok'
ORDER BY ms.id_origem;

-- 5e. Diagnóstico: mensagens sem mapeamento (skipped/falha)
--     Útil para identificar o que não foi migrado.
--     [DEST] Parâmetro: :src_conv_id_list (array de ints — ids das convs do contato)
SELECT
    ms.id_origem,
    ms.status,
    ms.migrated_at
FROM migration_state ms
WHERE ms.tabela  = 'messages'
  AND ms.status <> 'ok'
  -- filtra por IDs de msgs desta conversa (passado como subquery ou lista)
  AND ms.id_origem = ANY(:src_msg_ids_all)
ORDER BY ms.id_origem;


-- =============================================================================
-- SEÇÃO 6: VERIFICAÇÃO DE DADOS NO DEST
-- =============================================================================
-- Todas as queries rodam NO DEST DB.

-- 6a. Busca contato no DEST pelo dest_id (obtido do migration_state)
--     Parâmetro: :dest_contact_id
SELECT
    c.id                        AS dest_contact_id,
    c.account_id                AS dest_account_id,
    c.name,
    c.phone_number,
    c.email,
    c.identifier,
    c.pubsub_token,             -- ESPERADO: diferente do SOURCE (regenerado pelo Chatwoot)
    c.custom_attributes,
    c.created_at,
    c.updated_at
FROM contacts c
WHERE c.id = :dest_contact_id;

-- 6b. Conversas do contato no DEST
--     Parâmetros: :dest_contact_id, :dest_account_id
SELECT
    cv.id                       AS dest_conv_id,
    cv.account_id               AS dest_account_id,
    cv.contact_id               AS dest_contact_id,
    cv.inbox_id                 AS dest_inbox_id,
    cv.display_id,
    cv.status,
    cv.assignee_id              AS dest_assignee_id,
    cv.created_at,
    cv.updated_at,
    cv.additional_attributes,
    cv.custom_attributes,
    (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = cv.id) AS msg_count
FROM conversations cv
WHERE cv.contact_id = :dest_contact_id
  AND cv.account_id = :dest_account_id
ORDER BY cv.created_at, cv.id;

-- 6c. Mensagens de uma conversa no DEST
--     Parâmetro: :dest_conversation_id
SELECT
    m.id                        AS dest_msg_id,
    m.conversation_id           AS dest_conv_id,
    m.message_type,
    m.content,
    m.content_type,
    m.created_at,
    m.sender_type,
    m.additional_attributes,
    m.private,
    m.status,
    EXISTS (SELECT 1 FROM attachments a WHERE a.message_id = m.id) AS has_attachment
FROM messages m
WHERE m.conversation_id = :dest_conversation_id
ORDER BY m.created_at, m.id;

-- 6d. Attachments de uma mensagem no DEST
--     Parâmetro: :dest_message_id
SELECT
    a.id            AS dest_att_id,
    a.message_id    AS dest_message_id,
    a.file_type,
    a.external_url,
    a.content_type
FROM attachments a
WHERE a.message_id = :dest_message_id
ORDER BY a.id;


-- =============================================================================
-- SEÇÃO 7: QUERIES DE AUDITORIA INTRA-DEST
-- =============================================================================
-- Estas queries rodam APENAS no DEST e verificam consistência interna.
-- Não dependem do SOURCE. Devem retornar 0 linhas se a migração foi perfeita.

-- 7a. CTE: Saúde completa de um contato migrado
--     Parâmetros: :dest_contact_id, :dest_account_id
WITH contact_health AS (
    SELECT
        c.id                                                                AS contact_id,
        c.name                                                              AS contact_name,
        c.phone_number,
        c.email,
        -- Total de conversas do contato
        COUNT(DISTINCT cv.id)                                               AS total_conversations,
        -- Conversas com display_id nulo ou zero (anomalia)
        COUNT(DISTINCT cv.id) FILTER (
            WHERE cv.display_id IS NULL OR cv.display_id = 0
        )                                                                   AS conv_display_id_invalido,
        -- Total de mensagens
        COUNT(DISTINCT m.id)                                                AS total_messages,
        -- Mensagens sem conteúdo e sem attachment (suspeito)
        COUNT(DISTINCT m.id) FILTER (
            WHERE (m.content IS NULL OR m.content = '')
              AND NOT EXISTS (SELECT 1 FROM attachments a WHERE a.message_id = m.id)
        )                                                                   AS msg_sem_conteudo_sem_att,
        -- Total de attachments
        COUNT(DISTINCT att.id)                                              AS total_attachments,
        -- Attachments sem external_url (quebrado)
        COUNT(DISTINCT att.id) FILTER (
            WHERE att.external_url IS NULL OR att.external_url = ''
        )                                                                   AS att_sem_url
    FROM contacts c
    LEFT JOIN conversations cv
           ON cv.contact_id = c.id
          AND cv.account_id = :dest_account_id
    LEFT JOIN messages m
           ON m.conversation_id = cv.id
    LEFT JOIN attachments att
           ON att.message_id = m.id
    WHERE c.id          = :dest_contact_id
      AND c.account_id  = :dest_account_id
    GROUP BY c.id, c.name, c.phone_number, c.email
)
SELECT
    contact_id,
    contact_name,
    phone_number,
    email,
    total_conversations,
    conv_display_id_invalido,
    total_messages,
    msg_sem_conteudo_sem_att,
    total_attachments,
    att_sem_url,
    -- Flag global de saúde
    CASE
        WHEN conv_display_id_invalido > 0  THEN 'WARN: display_id inválido'
        WHEN att_sem_url              > 0  THEN 'WARN: attachment sem URL'
        WHEN msg_sem_conteudo_sem_att > 0  THEN 'WARN: mensagem vazia sem att'
        ELSE 'OK'
    END                                                                     AS health_status
FROM contact_health;

-- 7b. CTE: Auditoria de migration_state para o contato
--     Verifica se TODOS os registros do contato têm mapeamento no migration_state.
--     Parâmetros: :dest_contact_id, :dest_account_id
WITH
dest_convs AS (
    SELECT id AS dest_conv_id
    FROM conversations
    WHERE contact_id = :dest_contact_id
      AND account_id = :dest_account_id
),
dest_msgs AS (
    SELECT m.id AS dest_msg_id
    FROM messages m
    JOIN dest_convs dc ON dc.dest_conv_id = m.conversation_id
),
dest_atts AS (
    SELECT a.id AS dest_att_id
    FROM attachments a
    JOIN dest_msgs dm ON dm.dest_msg_id = a.message_id
),
-- Verifica cobertura do migration_state
conv_coverage AS (
    SELECT
        dc.dest_conv_id,
        ms.id_origem AS src_conv_id,
        ms.status
    FROM dest_convs dc
    LEFT JOIN migration_state ms
           ON ms.tabela     = 'conversations'
          AND ms.id_destino = dc.dest_conv_id
),
msg_coverage AS (
    SELECT
        dm.dest_msg_id,
        ms.id_origem AS src_msg_id,
        ms.status
    FROM dest_msgs dm
    LEFT JOIN migration_state ms
           ON ms.tabela     = 'messages'
          AND ms.id_destino = dm.dest_msg_id
),
att_coverage AS (
    SELECT
        da.dest_att_id,
        ms.id_origem AS src_att_id,
        ms.status
    FROM dest_atts da
    LEFT JOIN migration_state ms
           ON ms.tabela     = 'attachments'
          AND ms.id_destino = da.dest_att_id
)
SELECT
    'conversations' AS entidade,
    COUNT(*)                                                         AS total_dest,
    COUNT(*) FILTER (WHERE src_conv_id IS NOT NULL)                  AS com_mapeamento,
    COUNT(*) FILTER (WHERE src_conv_id IS NULL)                      AS sem_mapeamento,
    COUNT(*) FILTER (WHERE status <> 'ok' AND status IS NOT NULL)    AS status_nao_ok
FROM conv_coverage
UNION ALL
SELECT
    'messages',
    COUNT(*),
    COUNT(*) FILTER (WHERE src_msg_id IS NOT NULL),
    COUNT(*) FILTER (WHERE src_msg_id IS NULL),
    COUNT(*) FILTER (WHERE status <> 'ok' AND status IS NOT NULL)
FROM msg_coverage
UNION ALL
SELECT
    'attachments',
    COUNT(*),
    COUNT(*) FILTER (WHERE src_att_id IS NOT NULL),
    COUNT(*) FILTER (WHERE src_att_id IS NULL),
    COUNT(*) FILTER (WHERE status <> 'ok' AND status IS NOT NULL)
FROM att_coverage;

-- 7c. CTE: Comparação campo a campo entre SOURCE e DEST para um contato
--     ⚠️  Esta query deve ser montada NO PYTHON: executa em cada banco separado
--         e o Python faz o diff. O template abaixo ilustra o contrato de campos.
--
--     Campos IDÊNTICOS esperados (divergência = bug de migração):
--       name, phone_number, email, identifier, custom_attributes (JSONB)
--
--     Campos com diferença ESPERADA (não indicam bug):
--       id              → remapeado
--       account_id      → remapeado (offset aplicado pelo migrator)
--       pubsub_token    → regenerado pelo Chatwoot pós-importação
--       created_at      → timestamp de inserção no DEST (diferente do SOURCE)
--       updated_at      → idem
--
-- Template de SELECT para rodar em SOURCE:
SELECT
    id             AS entity_id,
    'contacts'     AS tabela,
    name,
    phone_number,
    email,
    identifier,
    custom_attributes::text AS custom_attributes_json
FROM contacts
WHERE id = :src_contact_id;

-- Template de SELECT equivalente para rodar em DEST:
SELECT
    id             AS entity_id,
    'contacts'     AS tabela,
    name,
    phone_number,
    email,
    identifier,
    custom_attributes::text AS custom_attributes_json
FROM contacts
WHERE id = :dest_contact_id;

-- 7d. Template de comparação campo a campo para conversations
--     (mesma lógica de dois SELECTs idênticos, um por banco)
--
--     Campos IDÊNTICOS: display_id, status, additional_attributes, custom_attributes
--     Campos com diferença ESPERADA: id, contact_id, inbox_id, assignee_id, account_id, created_at
--
-- SOURCE:
SELECT
    cv.id              AS entity_id,
    cv.display_id,
    cv.status,
    cv.additional_attributes::text,
    cv.custom_attributes::text
FROM conversations cv
WHERE cv.id = :src_conversation_id;

-- DEST:
SELECT
    cv.id              AS entity_id,
    cv.display_id,
    cv.status,
    cv.additional_attributes::text,
    cv.custom_attributes::text
FROM conversations cv
WHERE cv.id = :dest_conversation_id;

-- 7e. Template de comparação para messages
--     Campos IDÊNTICOS: message_type, content, content_type, sender_type, additional_attributes
--     Campos com diferença ESPERADA: id, conversation_id, account_id, sender_id, created_at
--
-- SOURCE:
SELECT
    m.id              AS entity_id,
    m.message_type,
    m.content,
    m.content_type,
    m.sender_type,
    m.private,
    m.status,
    m.additional_attributes::text
FROM messages m
WHERE m.id = :src_message_id;

-- DEST:
SELECT
    m.id              AS entity_id,
    m.message_type,
    m.content,
    m.content_type,
    m.sender_type,
    m.private,
    m.status,
    m.additional_attributes::text
FROM messages m
WHERE m.id = :dest_message_id;

-- 7f. Template de comparação para attachments
--     Campos IDÊNTICOS: file_type, external_url, content_type
--     Campos com diferença ESPERADA: id, message_id, account_id, created_at
--
-- SOURCE:
SELECT
    a.id              AS entity_id,
    a.file_type,
    a.external_url,
    a.content_type
FROM attachments a
WHERE a.id = :src_att_id;

-- DEST:
SELECT
    a.id              AS entity_id,
    a.file_type,
    a.external_url,
    a.content_type
FROM attachments a
WHERE a.id = :dest_att_id;


-- =============================================================================
-- SEÇÃO 8: CONTRATO PYTHON PARA COMPARAÇÃO CROSS-DB
-- =============================================================================
--
-- Como a comparação é cross-DB, o Python é responsável por:
--
--   1. Executar as queries de SOURCE (conn_src) → dict src_row
--   2. Executar as queries de DEST   (conn_dst) → dict dst_row
--   3. Para cada campo em CAMPOS_IDENTICOS, comparar src_row[campo] == dst_row[campo]
--   4. Montar estrutura de resultado:
--
--   {
--     "tabela": "contacts",
--     "src_id": 123,
--     "dest_id": 456,
--     "campos": [
--       {"campo": "name",         "src": "João",  "dest": "João",  "igual": True},
--       {"campo": "phone_number", "src": "+55...", "dest": "+55...", "igual": True},
--       {"campo": "email",        "src": "a@b.c", "dest": "a@b.c", "igual": True},
--     ],
--     "divergencias": []
--   }
--
-- CAMPOS_IDENTICOS por tabela:
--
--   contacts:      ["name", "phone_number", "email", "identifier"]
--   conversations: ["display_id", "status"]
--   messages:      ["message_type", "content", "content_type", "sender_type", "private"]
--   attachments:   ["file_type", "external_url", "content_type"]
--
-- CAMPOS_ESPERADO_DIFERIR por tabela:
--
--   contacts:      ["id", "account_id", "pubsub_token", "created_at", "updated_at"]
--   conversations: ["id", "contact_id", "inbox_id", "assignee_id", "account_id",
--                   "created_at", "updated_at"]
--   messages:      ["id", "conversation_id", "account_id", "sender_id",
--                   "created_at", "updated_at"]
--   attachments:   ["id", "message_id", "account_id", "created_at", "updated_at"]
--
-- NOTA JSONB: custom_attributes e additional_attributes devem ser comparados com
-- json.loads() + sorted keys, não como string direta (ordem de chaves pode variar).
-- =============================================================================


-- =============================================================================
-- SEÇÃO 9: QUERIES DE VALIDAÇÃO PROFUNDA POR CONTATO
-- Adicionado em 2026-04-20 — resposta ao debate D5
--
-- Índice:
--   9a. Seleção de amostra (SOURCE) — N contatos mais ricos para validação
--   9b. Cross-reference contato     (DEST) — src_contact_id → dest_contact_id
--       [já coberto pela Seção 5a; referência cruzada aqui]
--   9c. Conversas do contato SOURCE (SOURCE)
--       [já coberto pela Seção 2; referência cruzada aqui]
--   9d. Cross-reference batch de conversas (DEST)
--       — quais src_conv_ids têm dest_conv_id em migration_state
--   9e. Contagem comparativa de mensagens por conversa (SOURCE + DEST)
--       — dois SELECTs separados a executar em cada banco
--   9f. Attachments por conversa: mapa src→dest + status de external_url (DEST)
--       — inclui diagnóstico de URL ausente/vazia
--   9g. Query de divergência (DEST + Python)
--       — contatos migrados cujas conversas NÃO foram totalmente migradas
--
-- NOTA sobre file_path: o schema Chatwoot NÃO possui coluna file_path em
-- attachments. O campo equivalente é external_url (referência S3 copiada verbatim).
-- =============================================================================


-- =============================================================================
-- SEÇÃO 9a: SELEÇÃO DE AMOSTRA — N CONTATOS MAIS RICOS NO SOURCE
-- =============================================================================
-- Seleciona os N contatos com maior cobertura de dados (conversas + mensagens
-- + attachments). Estes são os melhores candidatos para validação profunda.
--
-- [SOURCE] Parâmetros: :src_account_id (int), :n (int — limite de linhas)
--
-- Estratégia: INNER JOINs garantem que só retornam contatos que têm pelo menos
-- 1 conversa, 1 mensagem E 1 attachment — os "mais completos".
-- Para incluir contatos sem attachment, substituir JOIN por LEFT JOIN e
-- remover o HAVING.
WITH contact_richness AS (
    SELECT
        c.id                    AS src_contact_id,
        c.name                  AS contact_name,
        c.phone_number,
        c.email,
        COUNT(DISTINCT cv.id)   AS conv_count,
        COUNT(DISTINCT m.id)    AS msg_count,
        COUNT(DISTINCT a.id)    AS att_count
    FROM contacts c
    JOIN conversations cv
           ON cv.contact_id = c.id
          AND cv.account_id = :src_account_id
    JOIN messages m
           ON m.conversation_id = cv.id
    JOIN attachments a
           ON a.message_id = m.id
    WHERE c.account_id = :src_account_id
    GROUP BY c.id, c.name, c.phone_number, c.email
    -- Garante pelo menos 1 attachment (remove para relaxar critério)
    HAVING COUNT(DISTINCT a.id) > 0
)
SELECT
    src_contact_id,
    contact_name,
    phone_number,
    email,
    conv_count,
    msg_count,
    att_count,
    -- Score composto para ordenação: peso maior para attachments
    (att_count * 10 + msg_count + conv_count * 5) AS richness_score
FROM contact_richness
ORDER BY richness_score DESC, conv_count DESC
LIMIT :n;


-- =============================================================================
-- SEÇÃO 9b: CROSS-REFERENCE CONTATO (REFERÊNCIA → SEÇÃO 5a)
-- =============================================================================
-- Reutilizar diretamente a query da Seção 5a:
--
--   SELECT ms.id_origem AS src_contact_id, ms.id_destino AS dest_contact_id,
--          ms.status, ms.migrated_at
--   FROM migration_state ms
--   WHERE ms.tabela = 'contacts'
--     AND ms.id_origem = :src_contact_id
--     AND ms.status    = 'ok';
--
-- [DEST] Parâmetro: :src_contact_id (int)
-- Retorna 0 linhas → contato NÃO migrado.
-- Retorna 1 linha  → contato migrado com sucesso (caso normal).
-- Retorna >1 linha → anomalia — contato migrado em duplicata.


-- =============================================================================
-- SEÇÃO 9c: CONVERSAS DO CONTATO NO SOURCE (REFERÊNCIA → SEÇÃO 2)
-- =============================================================================
-- Reutilizar diretamente a query da Seção 2.
--
-- Campos-chave para comparação: display_id (deve ser idêntico no DEST),
-- status, msg_count, att_count.
-- [SOURCE] Parâmetros: :src_contact_id, :src_account_id


-- =============================================================================
-- SEÇÃO 9d: CROSS-REFERENCE BATCH DE CONVERSAS (DEST)
-- =============================================================================
-- Para a lista de src_conv_ids (obtida da Seção 9c/2), verifica quais têm
-- mapeamento em migration_state.
--
-- [DEST] Parâmetro: :src_conv_ids (array de ints — e.g. ARRAY[1,2,3])
--
-- Uso Python:
--   src_conv_ids = [row["src_conv_id"] for row in source_conversations]
--   result = conn_dest.execute(text(query), {"src_conv_ids": src_conv_ids})
SELECT
    input_ids.src_conv_id,
    ms.id_destino                       AS dest_conv_id,
    ms.status                           AS migration_status,
    ms.migrated_at,
    CASE
        WHEN ms.id_destino IS NULL THEN 'NAO_MIGRADA'
        WHEN ms.status     = 'ok'  THEN 'MIGRADA_OK'
        ELSE 'MIGRADA_COM_FALHA'
    END                                 AS resultado
FROM UNNEST(:src_conv_ids::int[]) AS input_ids(src_conv_id)
LEFT JOIN migration_state ms
       ON ms.tabela    = 'conversations'
      AND ms.id_origem = input_ids.src_conv_id
ORDER BY input_ids.src_conv_id;


-- =============================================================================
-- SEÇÃO 9e: CONTAGEM COMPARATIVA DE MENSAGENS POR CONVERSA
-- =============================================================================
-- Executa um SELECT em SOURCE e outro no DEST para a mesma conversa.
-- O Python recebe dois números e calcula a diferença.
--
-- [SOURCE] Parâmetro: :src_conv_id
--   Retorna: msg_count_source (int)
SELECT
    :src_conv_id           AS src_conv_id,
    COUNT(*)               AS msg_count_source,
    COUNT(*) FILTER (WHERE message_type = 0) AS incoming,
    COUNT(*) FILTER (WHERE message_type = 1) AS outgoing,
    COUNT(*) FILTER (WHERE message_type = 2) AS activity,
    COUNT(*) FILTER (WHERE message_type = 3) AS template,
    COUNT(*) FILTER (
        WHERE EXISTS (SELECT 1 FROM attachments a WHERE a.message_id = m.id)
    )                      AS with_attachment
FROM messages m
WHERE m.conversation_id = :src_conv_id;

-- [DEST] Parâmetro: :dest_conv_id
--   Retorna: msg_count_dest (int) — deve ser igual a msg_count_source para
--   conversas migradas sem skips.
SELECT
    :dest_conv_id          AS dest_conv_id,
    COUNT(*)               AS msg_count_dest,
    COUNT(*) FILTER (WHERE message_type = 0) AS incoming,
    COUNT(*) FILTER (WHERE message_type = 1) AS outgoing,
    COUNT(*) FILTER (WHERE message_type = 2) AS activity,
    COUNT(*) FILTER (WHERE message_type = 3) AS template,
    COUNT(*) FILTER (
        WHERE EXISTS (SELECT 1 FROM attachments a WHERE a.message_id = m.id)
    )                      AS with_attachment
FROM messages m
WHERE m.conversation_id = :dest_conv_id;


-- =============================================================================
-- SEÇÃO 9f: ATTACHMENTS POR CONVERSA — src_att_id → dest_att_id + STATUS URL
-- =============================================================================
-- Pipeline em duas etapas (cross-DB).
--
-- Etapa 1 — [SOURCE] Todos os attachments de todas as mensagens da conversa.
-- Parâmetro: :src_conv_id
WITH src_conv_messages AS (
    SELECT id AS src_msg_id
    FROM messages
    WHERE conversation_id = :src_conv_id
)
SELECT
    a.id            AS src_att_id,
    a.message_id    AS src_msg_id,
    a.file_type,
    a.external_url  AS src_external_url,   -- referência S3 original
    a.content_type,
    a.created_at
FROM attachments a
JOIN src_conv_messages cm ON cm.src_msg_id = a.message_id
ORDER BY a.message_id, a.id;

-- Etapa 2 — [DEST] Para a lista de src_att_ids (resultado da Etapa 1),
-- busca dest_att_ids via migration_state e verifica external_url no DEST.
--
-- Parâmetro: :src_att_ids (array de ints retornados pela Etapa 1)
--
-- Colunas de diagnóstico:
--   migration_status : 'ok' | NULL (não migrado)
--   att_status       : 'OK' | 'NAO_MIGRADO' | 'SEM_URL' | 'URL_VAZIA'
WITH att_map AS (
    SELECT
        ms.id_origem   AS src_att_id,
        ms.id_destino  AS dest_att_id,
        ms.status      AS migration_status,
        ms.migrated_at
    FROM migration_state ms
    WHERE ms.tabela    = 'attachments'
      AND ms.id_origem = ANY(:src_att_ids::int[])
)
SELECT
    am.src_att_id,
    am.dest_att_id,
    am.migration_status,
    am.migrated_at,
    a.file_type,
    a.external_url          AS dest_external_url,  -- deve ser idêntico ao src
    a.content_type,
    CASE
        WHEN am.dest_att_id IS NULL               THEN 'NAO_MIGRADO'
        WHEN a.external_url IS NULL               THEN 'SEM_URL'
        WHEN TRIM(a.external_url) = ''            THEN 'URL_VAZIA'
        ELSE                                           'OK'
    END                     AS att_status
FROM att_map am
LEFT JOIN attachments a ON a.id = am.dest_att_id
ORDER BY am.src_att_id;


-- =============================================================================
-- SEÇÃO 9g: QUERY DE DIVERGÊNCIA — CONTATOS COM CONVERSAS NÃO MIGRADAS
-- =============================================================================
-- Identifica contatos que foram migrados (existem em migration_state['contacts'])
-- mas cujas conversas foram parcialmente ou totalmente não migradas.
--
-- Estratégia cross-DB (Python orquestra):
--   Passo A [SOURCE]  → lista de src_contact_id + src_conv_count
--   Passo B [DEST]    → para cada src_contact_id, conta dest_conv_count migrado
--   Passo C [Python]  → join por src_contact_id; divergência = src > dest
--
-- ─── PASSO A — [SOURCE] ──────────────────────────────────────────────────────
-- Todos os contatos do account que possuem pelo menos 1 conversa.
-- Parâmetro: :src_account_id
SELECT
    c.id                    AS src_contact_id,
    c.name                  AS contact_name,
    c.phone_number,
    c.email,
    COUNT(DISTINCT cv.id)   AS src_conv_count
FROM contacts c
JOIN conversations cv
       ON cv.contact_id = c.id
      AND cv.account_id = :src_account_id
WHERE c.account_id = :src_account_id
GROUP BY c.id, c.name, c.phone_number, c.email
HAVING COUNT(DISTINCT cv.id) > 0
ORDER BY src_conv_count DESC, c.id;

-- ─── PASSO B — [DEST] ────────────────────────────────────────────────────────
-- Para a lista de src_contact_ids do Passo A, conta conversas migradas com
-- sucesso em migration_state.
--
-- Parâmetros:
--   :src_contact_ids  (array de ints — Passo A)
--   :dest_account_id  (int)
WITH contact_map AS (
    -- Resolve src_contact_id → dest_contact_id
    SELECT
        ms.id_origem   AS src_contact_id,
        ms.id_destino  AS dest_contact_id
    FROM migration_state ms
    WHERE ms.tabela    = 'contacts'
      AND ms.status    = 'ok'
      AND ms.id_origem = ANY(:src_contact_ids::int[])
),
dest_conv_migrated AS (
    -- Para cada dest_contact_id, conta conversas em migration_state['conversations']
    SELECT
        cv.contact_id                       AS dest_contact_id,
        COUNT(DISTINCT ms_cv.id_origem)     AS dest_conv_count
    FROM conversations cv
    JOIN migration_state ms_cv
           ON ms_cv.tabela     = 'conversations'
          AND ms_cv.id_destino = cv.id
          AND ms_cv.status     = 'ok'
    WHERE cv.account_id = :dest_account_id
      AND cv.contact_id = ANY(
              SELECT dest_contact_id FROM contact_map
          )
    GROUP BY cv.contact_id
)
SELECT
    cm.src_contact_id,
    cm.dest_contact_id,
    COALESCE(dcm.dest_conv_count, 0)    AS dest_migrated_conv_count
    -- O Python junta com o Passo A via src_contact_id e calcula:
    --   faltando = src_conv_count - dest_migrated_conv_count
FROM contact_map cm
LEFT JOIN dest_conv_migrated dcm
       ON dcm.dest_contact_id = cm.dest_contact_id
ORDER BY dest_migrated_conv_count ASC, cm.src_contact_id;

-- ─── PASSO C — [Python] ──────────────────────────────────────────────────────
-- Pseudocódigo de join:
--
--   rows_a = {r["src_contact_id"]: r for r in result_passo_a}
--   rows_b = {r["src_contact_id"]: r for r in result_passo_b}
--
--   divergencias = []
--   for src_id, a in rows_a.items():
--       b = rows_b.get(src_id)
--       dest_count = b["dest_migrated_conv_count"] if b else 0
--       if a["src_conv_count"] > dest_count:
--           divergencias.append({
--               "src_contact_id":    src_id,
--               "contact_name":      a["contact_name"],
--               "src_conv_count":    a["src_conv_count"],
--               "dest_conv_count":   dest_count,
--               "faltando":          a["src_conv_count"] - dest_count,
--           })
--   divergencias.sort(key=lambda x: -x["faltando"])
-- =============================================================================
