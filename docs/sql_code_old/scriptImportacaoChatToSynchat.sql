-- psql chatwoot_tb_db < tbchat.sql
-- Contacts
DO $$ 
DECLARE
    var_account_id INT;
    var_additional_attributes jsonb;
    var_custom_attributes jsonb;
    var_company_name VARCHAR(255);
    var_contact_row RECORD;
BEGIN

    SELECT id INTO var_account_id
    FROM public.accounts
    WHERE "name" = 'Sol Copernico';
    RAISE NOTICE 'O account_id é: %', var_account_id;

    FOR var_contact_row IN SELECT * FROM public.contacts_tbchat limit 1
    LOOP
        -- Verificar se o contato já existe na nova tabela
        IF NOT EXISTS (SELECT 1 FROM public.contacts WHERE phone_number = TRIM(var_contact_row.phone)) THEN

            var_company_name:= var_contact_row.empresa;
            

            -- var_additional_attributes := jsonb_build_object(
            --     'city', '',
            --     'country', 'Brazil',
            --     'company_name', var_company_name,
            --     'description', '',
            --     'country_code', 'BR'
            -- );
            var_additional_attributes := var_contact_row.additional_attributes;

            var_custom_attributes := jsonb_build_object(
                'cpf', var_contact_row.cpf,
                'external_id', var_contact_row.id
            );

            RAISE NOTICE 'Nome é: %', var_contact_row.name_contact;

            -- Se não existir, inserir na nova tabela
            INSERT INTO public.contacts (
                name, 
                email, 
                phone_number, 
                account_id, 
                created_at, 
                updated_at, 
                additional_attributes, 
                identifier, 
                custom_attributes, 
                last_activity_at
                )
            VALUES (
                TRIM(var_contact_row.name_contact), 
                TRIM(var_contact_row.email), 
                TRIM(var_contact_row.phone),
                var_account_id,
                TO_TIMESTAMP(var_contact_row.created_at, 'YYYY-MM-DD HH24:MI:SS'),
                TO_TIMESTAMP(var_contact_row.updated_at, 'YYYY-MM-DD HH24:MI:SS'),
                var_additional_attributes,
                null,
                var_custom_attributes,
                TO_TIMESTAMP(var_contact_row.last_activity_at, 'YYYY-MM-DD HH24:MI:SS')
                );

            DELETE FROM public.contacts_tbchat WHERE id = var_contact_row.id;
        ELSE
			RAISE NOTICE 'Contato já existe: %', var_contact_row.name_contact;
		END IF;
		-- DELETE FROM public.contacts_tbchat WHERE id = var_contact_row.id;
    END LOOP;
END $$;


-- Conversations and Messages - select messages
DO $$ 
DECLARE
    var_account_id INT;
    var_user_id INT;
    var_contact_id INT;
    var_conversations_row RECORD;
    var_display_id INT;
    var_contact_inbox_id INT;
    var_inbox_id INT;
    var_conversation_id INT;
    var_message_type INT;
    var_messages_row RECORD;
    var_sender_type VARCHAR(255);
    var_contact_name VARCHAR(255);
    var_sender_id INT;
    var_content TEXT;
    var_id_empresa INT;
BEGIN

    SELECT id INTO var_account_id
    FROM public.accounts
    WHERE "name" = 'Dr. Thiago Bianco';
    RAISE NOTICE 'O account_id é: %', var_account_id;

    SELECT id INTO var_user_id
    FROM public.users
    WHERE "uid" = 'admin@vya.digital';
    RAISE NOTICE 'O user_id é: %', var_user_id;

    FOR var_conversations_row IN SELECT * FROM public.conversations_tbchat limit 42329
    LOOP
        SELECT id, inbox_id INTO var_conversation_id, var_id_empresa FROM public.conversations WHERE custom_attributes->>'external_id' = CAST(var_conversations_row.id AS text);
        -- Verificar se o contato já existe na nova tabela
        IF (var_conversation_id IS NULL) THEN

            RAISE NOTICE 'Conversations: %', var_conversations_row.id;

            SELECT MAX(display_id)+1 INTO var_display_id
            FROM public.conversations;

            SELECT id,name INTO var_contact_id,var_contact_name
            FROM public.contacts
            WHERE custom_attributes->>'external_id' = CAST(var_conversations_row.id_contact AS text);
            RAISE NOTICE 'O contact_id é: %', var_contact_id;
            RAISE NOTICE 'O var_contact_name é: %', var_contact_name;
            

            IF var_conversations_row.id_empresa = '2' THEN
                var_inbox_id:= 1;
                var_id_empresa:= 2;
                -- RAISE NOTICE 'Empresa Bellegarde';
            ELSE
                var_inbox_id:= 2;
                var_id_empresa:= 3;
                -- RAISE NOTICE 'Empresa SmartHair';
            END IF;

            -- inserir contact inbox id
            INSERT INTO public.contact_inboxes(
	        contact_id, 
            inbox_id, 
            source_id, 
            created_at, 
            updated_at, 
            hmac_verified, 
            pubsub_token)
	        VALUES (
                var_contact_id, 
                var_inbox_id, 
                gen_random_uuid(), 
                TO_TIMESTAMP(var_conversations_row.data_reg, 'YYYY-MM-DD HH24:MI:SS'), 
                TO_TIMESTAMP(var_conversations_row.data_reg, 'YYYY-MM-DD HH24:MI:SS'), 
                false, 
                null)
            RETURNING id INTO var_contact_inbox_id;
            RAISE NOTICE 'O contact_inbox_id é: %', var_contact_inbox_id;
            
            INSERT INTO public.conversations (account_id, inbox_id, status, assignee_id, created_at, updated_at, contact_id, display_id, contact_last_seen_at, agent_last_seen_at, additional_attributes, contact_inbox_id, uuid, identifier, last_activity_at, team_id, campaign_id, snoozed_until, custom_attributes, assignee_last_seen_at, first_reply_created_at, priority, sla_policy_id, waiting_since)
            SELECT 
                1 as "account_id",
                var_inbox_id as "inbox_id",
                1 as "status",
                var_user_id as "assignee_id",
                CASE 
                    WHEN var_conversations_row.data_ini IS null THEN TO_TIMESTAMP(var_conversations_row.data_reg, 'YYYY-MM-DD HH24:MI:SS')
                    ELSE var_conversations_row.data_ini
                END as "created_at",
                CASE 
                    WHEN var_conversations_row.data_ini IS null THEN TO_TIMESTAMP(var_conversations_row.data_reg, 'YYYY-MM-DD HH24:MI:SS')
                    ELSE var_conversations_row.data_ini
                END as "updated_at",
                var_contact_id as "contact_id", 
                var_display_id as "display_id",
                CASE 
                    WHEN var_conversations_row.data_ini IS null THEN TO_TIMESTAMP(var_conversations_row.data_reg, 'YYYY-MM-DD HH24:MI:SS')
                    ELSE var_conversations_row.data_ini
                END as "contact_last_seen_at",
                CASE 
                    WHEN var_conversations_row.data_ini IS null THEN TO_TIMESTAMP(var_conversations_row.data_reg, 'YYYY-MM-DD HH24:MI:SS')
                    ELSE var_conversations_row.data_ini
                END as "agent_last_seen_at",
                '{}'::jsonb as "additional_attributes",
                var_contact_inbox_id as "contact_inbox_id",
                gen_random_uuid() as "uuid",
                null as "identifier",
                CASE 
                    WHEN var_conversations_row.last_data_update IS null THEN TO_TIMESTAMP(var_conversations_row.data_reg, 'YYYY-MM-DD HH24:MI:SS')
                    ELSE TO_TIMESTAMP(var_conversations_row.last_data_update, 'YYYY-MM-DD HH24:MI:SS')
                END as "last_activity_at", 
                null as "team_id", 
                null as "campaign_id", 
                null as "snoozed_until", 
                jsonb_build_object(
                    'external_id', var_conversations_row.id
                ) as "custom_attributes", 
                var_conversations_row.data_ini as "assignee_last_seen_at", 
                null as "first_reply_created_at", 
                null as "priority", 
                null as "sla_policy_id", 
                var_conversations_row.data_ini as "waiting_since"
                RETURNING id INTO var_conversation_id;

                RAISE NOTICE 'Conversation criada: %', var_conversation_id;
        ELSE
			RAISE NOTICE 'Conversations já existe: %', var_conversations_row.id;
		END IF;

        RAISE NOTICE 'Conversations: %', var_conversation_id;
        RAISE NOTICE 'Conversations TBChat: %', var_conversations_row.id;
		RAISE NOTICE 'Empresa: %', var_id_empresa;
		RAISE NOTICE 'Empresa TBChat: %', var_conversations_row.id_empresa;

        INSERT INTO public.messages (content, account_id, inbox_id, conversation_id, message_type, created_at, updated_at, private, status, source_id, content_type, content_attributes, sender_type, sender_id, external_source_ids, additional_attributes, processed_message_content, sentiment)
        SELECT 
            CASE
                WHEN message_type = 'text' THEN "message"
                ELSE CONCAT(INITCAP(message_type),': https://tbchatuploads.s3.sa-east-1.amazonaws.com/',REPLACE(file_url, 'https://tbchatuploads.s3.sa-east-1.amazonaws.com/', ''))
            END AS "content",
            (SELECT id FROM public.accounts WHERE "name" = 'Dr. Thiago Bianco') AS "account_id",
            (SELECT inbox_id FROM public.conversations WHERE custom_attributes->>'external_id' = CAST(messages_tbchat.id_session AS text)) AS "inbox_id",
            (SELECT id FROM public.conversations WHERE custom_attributes->>'external_id' = CAST(messages_tbchat.id_session AS text)) AS "conversation_id",
            CASE
                WHEN type_in_message = 'RECEIVED' THEN 0
                ELSE 1
            END AS "message_type",
            moment as "created_at",
            moment as "updated_at",
            '0' as "private",
            0 as "status",
            null as "source_id",
            0 as "content_type", 
            null as "content_attributes",
            CASE
                WHEN type_in_message = 'RECEIVED' THEN 'Contact'
                ELSE 'User'
            END AS "sender_type",
            CASE
                WHEN type_in_message = 'RECEIVED' THEN (SELECT id FROM public.contacts WHERE custom_attributes->>'external_id' = CAST(id_contact AS text))
                ELSE (SELECT id FROM public.users WHERE "uid" = 'admin@vya.digital')
            END AS "sender_id",
            null as "external_source_ids",
            jsonb_build_object(
                'external_id', id
            ) as "additional_attributes",
            CASE
                WHEN message_type = 'text' THEN "message"
                ELSE CONCAT(INITCAP(message_type),': https://tbchatuploads.s3.sa-east-1.amazonaws.com/',REPLACE(file_url, 'https://tbchatuploads.s3.sa-east-1.amazonaws.com/', ''))
            END AS "processed_message_content",
            '{}'::jsonb as "sentiment"
        FROM 
        public.messages_tbchat
        WHERE 
        (id_session = var_conversations_row.id::varchar) 
        AND (id_empresa = var_conversations_row.id_empresa);

        RAISE NOTICE 'Excluindo messages';
        DELETE FROM public.messages_tbchat WHERE
        (id_session = var_conversations_row.id::varchar) 
        AND (id_empresa = var_conversations_row.id_empresa);

        RAISE NOTICE 'Termino messages';
        DELETE FROM public.conversations_tbchat WHERE id = var_conversations_row.id;
        COMMIT;

    END LOOP; -- conversations

END $$;


select
(SELECT count(1) FROM public.contacts_tbchat) contacts,
(SELECT count(1) FROM public.conversations_tbchat) conversations,
(SELECT count(1) FROM public.messages_tbchat) messages;


-- Conversations and Messages
DO $$ 
DECLARE
    var_account_id INT;
    var_user_id INT;
    var_contact_id INT;
    var_conversations_row RECORD;
    var_display_id INT;
    var_contact_inbox_id INT;
    var_inbox_id INT;
    var_conversation_id INT;
    var_message_type INT;
    var_messages_row RECORD;
    var_sender_type VARCHAR(255);
    var_contact_name VARCHAR(255);
    var_sender_id INT;
    var_content TEXT;
    var_id_empresa INT;
BEGIN

    SELECT id INTO var_account_id
    FROM public.accounts
    WHERE "name" = 'Dr. Thiago Bianco';
    RAISE NOTICE 'O account_id é: %', var_account_id;

    SELECT id INTO var_user_id
    FROM public.users
    WHERE "uid" = 'admin@vya.digital';
    RAISE NOTICE 'O user_id é: %', var_user_id;

    FOR var_conversations_row IN SELECT * FROM public.conversations_tbchat order by id asc limit 10
    LOOP
        SELECT id, inbox_id INTO var_conversation_id, var_id_empresa FROM public.conversations WHERE custom_attributes->>'external_id' = CAST(var_conversations_row.id AS text);
        -- Verificar se o contato já existe na nova tabela
        IF (var_conversation_id IS NULL) THEN

            RAISE NOTICE 'Conversations: %', var_conversations_row.id;

            SELECT MAX(display_id)+1 INTO var_display_id
            FROM public.conversations;

            SELECT id INTO var_contact_id
            FROM public.contacts
            WHERE custom_attributes->>'external_id' = CAST(var_conversations_row.id_contact AS text);
            RAISE NOTICE 'O contact_id é: %', var_contact_id;
            

            IF var_conversations_row.id_empresa = '2' THEN
                var_inbox_id:= 1;
                var_id_empresa:= 2;
                -- RAISE NOTICE 'Empresa Bellegarde';
            ELSE
                var_inbox_id:= 2;
                var_id_empresa:= 3;
                -- RAISE NOTICE 'Empresa SmartHair';
            END IF;

            -- inserir contact inbox id
            INSERT INTO public.contact_inboxes(
	        contact_id, 
            inbox_id, 
            source_id, 
            created_at, 
            updated_at, 
            hmac_verified, 
            pubsub_token)
	        VALUES (
                var_contact_id, 
                var_inbox_id, 
                gen_random_uuid(), 
                TO_TIMESTAMP(var_conversations_row.data_reg, 'YYYY-MM-DD HH24:MI:SS'), 
                TO_TIMESTAMP(var_conversations_row.data_reg, 'YYYY-MM-DD HH24:MI:SS'), 
                false, 
                null)
            RETURNING id INTO var_contact_inbox_id;
            RAISE NOTICE 'O contact_inbox_id é: %', var_contact_inbox_id;
            
            INSERT INTO public.conversations (account_id, inbox_id, status, assignee_id, created_at, updated_at, contact_id, display_id, contact_last_seen_at, agent_last_seen_at, additional_attributes, contact_inbox_id, uuid, identifier, last_activity_at, team_id, campaign_id, snoozed_until, custom_attributes, assignee_last_seen_at, first_reply_created_at, priority, sla_policy_id, waiting_since)
            SELECT 
                1 as "account_id",
                var_inbox_id as "inbox_id",
                1 as "status",
                var_user_id as "assignee_id",
                CASE 
                    WHEN var_conversations_row.data_ini IS null THEN TO_TIMESTAMP(var_conversations_row.data_reg, 'YYYY-MM-DD HH24:MI:SS')
                    ELSE var_conversations_row.data_ini
                END as "created_at",
                CASE 
                    WHEN var_conversations_row.data_ini IS null THEN TO_TIMESTAMP(var_conversations_row.data_reg, 'YYYY-MM-DD HH24:MI:SS')
                    ELSE var_conversations_row.data_ini
                END as "updated_at",
                var_contact_id as "contact_id", 
                var_display_id as "display_id",
                CASE 
                    WHEN var_conversations_row.data_ini IS null THEN TO_TIMESTAMP(var_conversations_row.data_reg, 'YYYY-MM-DD HH24:MI:SS')
                    ELSE var_conversations_row.data_ini
                END as "contact_last_seen_at",
                CASE 
                    WHEN var_conversations_row.data_ini IS null THEN TO_TIMESTAMP(var_conversations_row.data_reg, 'YYYY-MM-DD HH24:MI:SS')
                    ELSE var_conversations_row.data_ini
                END as "agent_last_seen_at",
                '{}'::jsonb as "additional_attributes",
                var_contact_inbox_id as "contact_inbox_id",
                gen_random_uuid() as "uuid",
                null as "identifier",
                CASE 
                    WHEN var_conversations_row.last_data_update IS null THEN TO_TIMESTAMP(var_conversations_row.data_reg, 'YYYY-MM-DD HH24:MI:SS')
                    ELSE TO_TIMESTAMP(var_conversations_row.last_data_update, 'YYYY-MM-DD HH24:MI:SS')
                END as "last_activity_at", 
                null as "team_id", 
                null as "campaign_id", 
                null as "snoozed_until", 
                jsonb_build_object(
                    'external_id', var_conversations_row.id
                ) as "custom_attributes", 
                var_conversations_row.data_ini as "assignee_last_seen_at", 
                null as "first_reply_created_at", 
                null as "priority", 
                null as "sla_policy_id", 
                var_conversations_row.data_ini as "waiting_since"
                RETURNING id INTO var_conversation_id;

                RAISE NOTICE 'Conversation criada: %', var_conversation_id;
        ELSE
			RAISE NOTICE 'Conversations já existe: %', var_conversations_row.id;
		END IF;

        RAISE NOTICE 'Conversations: %', var_conversation_id;
        RAISE NOTICE 'Conversations TBChat: %', var_conversations_row.id;
		RAISE NOTICE 'Empresa: %', var_id_empresa;
		RAISE NOTICE 'Empresa TBChat: %', var_conversations_row.id_empresa;

        -- tratamento das mensagens
        FOR var_messages_row IN SELECT * FROM public.messages_tbchat 
            WHERE 
                (id_session = var_conversations_row.id::varchar) 
                AND (id_empresa = var_conversations_row.id_empresa)
        LOOP
            RAISE NOTICE 'Processo messages iniciando: %',var_messages_row.id;

            SELECT id,"name" INTO var_contact_id,var_contact_name
                FROM public.contacts
                WHERE custom_attributes->>'external_id' = CAST(var_messages_row.id_contact AS text);
                RAISE NOTICE 'O contact_id é: %', var_contact_id;
                RAISE NOTICE 'O contact_name é: %', var_contact_name;

            IF NOT EXISTS (SELECT 1 FROM public.messages WHERE additional_attributes->>'external_id' = CAST(var_messages_row.id AS text)) THEN
                
                SELECT id,inbox_id INTO var_conversation_id,var_inbox_id
                    FROM public.conversations
                    WHERE custom_attributes->>'external_id' = CAST(var_messages_row.id_session AS text);
                    RAISE NOTICE 'Conversations: %', var_conversation_id;
                    RAISE NOTICE 'Inbox: %', var_inbox_id;

                IF (var_messages_row.message_type = 'text') THEN
                    RAISE NOTICE 'MESSAGE %', var_messages_row.message_type;
                    var_content:= var_messages_row.message;
                ELSE
                
                    RAISE NOTICE 'MESSAGE %', var_messages_row.message_type;
                    var_content:= REPLACE(var_messages_row.file_url, 'https://tbchatuploads.s3.sa-east-1.amazonaws.com/', '');
                    var_content:= CONCAT(INITCAP(var_messages_row.message_type),': https://tbchatuploads.s3.sa-east-1.amazonaws.com/', var_content);
                END IF;

                -- var_message_type:= 0; Received
                -- var_message_type:= 1; sent
                -- var_message_type:= 2; interno
                -- var_message_type:= 3; auto send   
                IF var_messages_row.type_in_message = 'RECEIVED' THEN
                    var_message_type:= 0;
                    var_sender_type:= 'Contact';
                    SELECT id,"name" INTO var_contact_id,var_contact_name
                    FROM public.contacts
                    WHERE custom_attributes->>'external_id' = CAST(var_messages_row.id_contact AS text);
                    RAISE NOTICE 'O contact_id é: %', var_contact_id;
                    RAISE NOTICE 'O contact_name é: %', var_contact_name;
                    var_sender_id:= var_contact_id;
                    
                ELSE
                    var_message_type:= 1;
                    var_sender_type:= 'User';
                    var_sender_id:= var_user_id;
    
                END IF;
                RAISE NOTICE 'Sender Type é: %', var_sender_type;

                RAISE NOTICE 'Inserindo messages';
                INSERT INTO public.messages (content, account_id, inbox_id, conversation_id, message_type, created_at, updated_at, private, status, source_id, content_type, content_attributes, sender_type,
                sender_id, external_source_ids, additional_attributes, processed_message_content, sentiment)
                SELECT
                    var_content as "content",
                    var_account_id as "account_id",
                    var_inbox_id as "inbox_id",
                    var_conversation_id as "conversation_id",
                    var_message_type as "message_type",
                    var_messages_row.moment as "created_at",
                    var_messages_row.moment as "updated_at",
                    '0' as "private",
                    0 as "status",
                    null as "source_id",
                    0 as "content_type", 
                    null as "content_attributes",
                    var_sender_type as "sender_type",
                    var_sender_id as "sender_id",
                    null as "external_source_ids",
                    jsonb_build_object(
                        'external_id', var_messages_row.id
                    ) as "additional_attributes",
                    var_content as "processed_message_content",
                    '{}'::jsonb as "sentiment";

            ELSE
                RAISE NOTICE 'Messages já existe: %', var_messages_row.id;
            END IF;
            RAISE NOTICE 'Excluindo messages';
            DELETE FROM public.messages_tbchat WHERE id = var_messages_row.id;

        END LOOP; -- messages
        RAISE NOTICE 'Termino messages';
        DELETE FROM public.conversations_tbchat WHERE id = var_conversations_row.id;
        COMMIT;

    END LOOP; -- conversations

END $$;

-- Conversations
DO $$ 
DECLARE
    var_account_id INT;
    var_user_id INT;
    var_contact_id INT;
    var_conversations_row RECORD;
    var_display_id INT;
    var_contact_inbox_id INT;
    var_inbox_id INT;
BEGIN

    SELECT id INTO var_account_id
    FROM public.accounts
    WHERE "name" = 'Dr. Thiago Bianco';
    RAISE NOTICE 'O account_id é: %', var_account_id;

    SELECT id INTO var_user_id
    FROM public.users
    WHERE "uid" = 'admin@vya.digital';
    RAISE NOTICE 'O user_id é: %', var_user_id;

    FOR var_conversations_row IN SELECT * FROM public.conversations_tbchat where id_contact = '1001'
    LOOP
        -- Verificar se o contato já existe na nova tabela
        IF NOT EXISTS (SELECT 1 FROM public.conversations WHERE custom_attributes ->> 'external_id' = CAST(var_conversations_row.id AS text)) THEN

            SELECT MAX(display_id)+1 INTO var_display_id
            FROM public.conversations;
            -- WHERE account_id = var_account_id;

            SELECT id INTO var_contact_id
            FROM public.contacts
            WHERE custom_attributes ->> 'external_id' = CAST(var_conversations_row.id_contact AS text);
            RAISE NOTICE 'O contact_id é: %', var_contact_id;

            RAISE NOTICE 'Conversations: %', var_conversations_row.id;

            IF var_conversations_row.id_empresa = '2' THEN
                var_inbox_id:= 1;
                -- RAISE NOTICE 'Empresa Bellegarde';
            ELSE
                var_inbox_id:= 2;
                -- RAISE NOTICE 'Empresa SmartHair';
            END IF;

            -- inserir contact inbox id
            INSERT INTO public.contact_inboxes(
	        contact_id, 
            inbox_id, 
            source_id, 
            created_at, 
            updated_at, 
            hmac_verified, 
            pubsub_token)
	        VALUES (
                var_contact_id, 
                var_inbox_id, 
                gen_random_uuid(), 
                TO_TIMESTAMP(var_conversations_row.data_reg, 'YYYY-MM-DD HH24:MI:SS'), 
                TO_TIMESTAMP(var_conversations_row.data_reg, 'YYYY-MM-DD HH24:MI:SS'), 
                false, 
                null)
            RETURNING id INTO var_contact_inbox_id;
            RAISE NOTICE 'O contact_inbox_id é: %', var_contact_inbox_id;
            
            INSERT INTO public.conversations (account_id, inbox_id, status, assignee_id, created_at, updated_at, contact_id, display_id, contact_last_seen_at, agent_last_seen_at, additional_attributes, contact_inbox_id, uuid, identifier, last_activity_at, team_id, campaign_id, snoozed_until, custom_attributes, assignee_last_seen_at, first_reply_created_at, priority, sla_policy_id, waiting_since)
            SELECT 
                1 as "account_id",
                var_inbox_id as "inbox_id",
                1 as "status",
                var_user_id as "assignee_id",
                CASE 
                    WHEN var_conversations_row.data_ini IS null THEN TO_TIMESTAMP(var_conversations_row.data_reg, 'YYYY-MM-DD HH24:MI:SS')
                    ELSE var_conversations_row.data_ini
                END as "created_at",
                CASE 
                    WHEN var_conversations_row.data_ini IS null THEN TO_TIMESTAMP(var_conversations_row.data_reg, 'YYYY-MM-DD HH24:MI:SS')
                    ELSE var_conversations_row.data_ini
                END as "updated_at",
                var_contact_id as "contact_id", 
                var_display_id as "display_id",
                CASE 
                    WHEN var_conversations_row.data_ini IS null THEN TO_TIMESTAMP(var_conversations_row.data_reg, 'YYYY-MM-DD HH24:MI:SS')
                    ELSE var_conversations_row.data_ini
                END as "contact_last_seen_at",
                CASE 
                    WHEN var_conversations_row.data_ini IS null THEN TO_TIMESTAMP(var_conversations_row.data_reg, 'YYYY-MM-DD HH24:MI:SS')
                    ELSE var_conversations_row.data_ini
                END as "agent_last_seen_at",
                '{}'::jsonb as "additional_attributes",
                var_contact_inbox_id as "contact_inbox_id",
                gen_random_uuid() as "uuid",
                null as "identifier",
                CASE 
                    WHEN var_conversations_row.last_data_update IS null THEN TO_TIMESTAMP(var_conversations_row.data_reg, 'YYYY-MM-DD HH24:MI:SS')
                    ELSE TO_TIMESTAMP(var_conversations_row.last_data_update, 'YYYY-MM-DD HH24:MI:SS')
                END as "last_activity_at", 
                null as "team_id", 
                null as "campaign_id", 
                null as "snoozed_until", 
                jsonb_build_object(
                    'external_id', var_conversations_row.id
                ) as "custom_attributes", 
                var_conversations_row.data_ini as "assignee_last_seen_at", 
                null as "first_reply_created_at", 
                null as "priority", 
                null as "sla_policy_id", 
                var_conversations_row.data_ini as "waiting_since";
        ELSE
			RAISE NOTICE 'Conversations já existe: %', var_conversations_row.id;
		END IF;
        DELETE FROM public.conversations_tbchat WHERE id = var_conversations_row.id;
		
    END LOOP;
   
END $$;


-- Messages
DO $$ 
DECLARE
    var_account_id INT;
    var_user_id INT;
    var_contact_id INT;
    var_inbox_id INT;
    var_display_id INT;
    var_conversation_id INT;
    var_message_type INT;
    var_messages_row RECORD;
    var_sender_type VARCHAR(255);
    var_contact_name VARCHAR(255);
    var_sender_id INT;
    var_content TEXT;
BEGIN

    SELECT id INTO var_account_id
    FROM public.accounts
    WHERE "name" = 'Dr. Thiago Bianco';
    RAISE NOTICE 'O account_id é: %', var_account_id;

    SELECT id INTO var_user_id
    FROM public.users
    WHERE "uid" = 'admin@vya.digital';
    RAISE NOTICE 'O user_id é: %', var_user_id;

    FOR var_messages_row IN SELECT * FROM public.messages_tbchat where id_contact = '1001'
    LOOP

        SELECT id,"name" INTO var_contact_id,var_contact_name
            FROM public.contacts
            WHERE custom_attributes ->> 'external_id' = CAST(var_messages_row.id_contact AS text);
            RAISE NOTICE 'O contact_id é: %', var_contact_id;
            RAISE NOTICE 'O contact_name é: %', var_contact_name;

        IF NOT EXISTS (SELECT 1 FROM public.messages WHERE additional_attributes ->> 'external_id' = CAST(var_messages_row.id AS text)) THEN
            
            SELECT id,inbox_id INTO var_conversation_id,var_inbox_id
            FROM public.conversations
            WHERE custom_attributes ->> 'external_id' = CAST(var_messages_row.id_session AS text);
            RAISE NOTICE 'Conversations: %', var_conversation_id;
            RAISE NOTICE 'Inbox: %', var_inbox_id;

            IF (var_messages_row.message_type = 'text') THEN
                RAISE NOTICE 'MESSAGE %', var_messages_row.message_type;
                var_content:= var_messages_row.message;
            ELSE
            
                RAISE NOTICE 'MESSAGE %', var_messages_row.message_type;
                var_content:= REPLACE(var_messages_row.file_url, 'https://tbchatuploads.s3.sa-east-1.amazonaws.com/', '');
                var_content:= CONCAT(INITCAP(var_messages_row.message_type),': https://tbchatuploads.s3.sa-east-1.amazonaws.com/', var_content);
            END IF;

            -- var_message_type:= 0; Received
            -- var_message_type:= 1; sent
            -- var_message_type:= 2; interno
            -- var_message_type:= 3; auto send   
            IF var_messages_row.type_in_message = 'RECEIVED' THEN
                var_message_type:= 0;
                var_sender_type:= 'Contact';
                SELECT id,"name" INTO var_contact_id,var_contact_name
                FROM public.contacts
                WHERE custom_attributes ->> 'external_id' = CAST(var_messages_row.id_contact AS text);
                RAISE NOTICE 'O contact_id é: %', var_contact_id;
                RAISE NOTICE 'O contact_name é: %', var_contact_name;
                var_sender_id:= var_contact_id;
                
            ELSE
                var_message_type:= 1;
                var_sender_type:= 'User';
                var_sender_id:= var_user_id;
 
            END IF;

            INSERT INTO public.messages (content, account_id, inbox_id, conversation_id, message_type, created_at, updated_at, private, status, source_id, content_type, content_attributes, sender_type,
             sender_id, external_source_ids, additional_attributes, processed_message_content, sentiment)
            SELECT
                var_content as "content",
                var_account_id as "account_id",
                var_inbox_id as "inbox_id",
                var_conversation_id as "conversation_id",
                var_message_type as "message_type",
                var_messages_row.moment as "created_at",
                var_messages_row.moment as "updated_at",
                '0' as "private",
                0 as "status",
                null as "source_id",
                0 as "content_type", 
                null as "content_attributes",
                var_sender_type as "sender_type",
                var_sender_id as "sender_id",
                null as "external_source_ids",
                jsonb_build_object(
                    'external_id', var_messages_row.id
                ) as "additional_attributes",
                var_content as "processed_message_content",
                '{}'::jsonb as "sentiment";
        ELSE
			RAISE NOTICE 'Messages já existe: %', var_messages_row.id;
		END IF;
        DELETE FROM public.messages_tbchat WHERE id = var_messages_row.id;

    END LOOP;
   
END $$;

-- DELETE FROM public.contacts WHERE ((custom_attributes->>'external_id')::int >= 105 and (custom_attributes->>'external_id')::int <= 1000);
-- DELETE FROM public.messages;
-- DELETE FROM public.contact_inboxes;
-- DELETE FROM public.conversations;
-- DELETE FROM public.messages_tbchat;
-- DELETE FROM public.conversations_tbchat;