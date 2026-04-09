# Relatório de Análise de Redundância do Banco de Dados

**Gerado em:** 2026-04-09 16:04:26  
**Total de tabelas analisadas:** 70

---

## 1. Redundância de Colunas

> ⚠️ **43 colunas duplicadas encontradas entre tabelas.**

### `account_id`

| Tabela | Tipo |
|--------|------|
| `account_users` | `BIGINT` |
| `agent_bots` | `BIGINT` |
| `agent_bot_inboxes` | `INTEGER` |
| `attachments` | `INTEGER` |
| `automation_rules` | `BIGINT` |
| `articles` | `INTEGER` |
| `canned_responses` | `INTEGER` |
| `categories` | `INTEGER` |
| `channel_api` | `INTEGER` |
| `channel_email` | `INTEGER` |
| `channel_facebook_pages` | `INTEGER` |
| `channel_line` | `INTEGER` |
| `channel_telegram` | `INTEGER` |
| `channel_twilio_sms` | `INTEGER` |
| `channel_twitter_profiles` | `INTEGER` |
| `channel_web_widgets` | `INTEGER` |
| `channel_whatsapp` | `INTEGER` |
| `channel_sms` | `INTEGER` |
| `conversation_participants` | `BIGINT` |
| `conversations` | `INTEGER` |
| `custom_attribute_definitions` | `BIGINT` |
| `custom_roles` | `BIGINT` |
| `data_imports` | `BIGINT` |
| `folders` | `INTEGER` |
| `inboxes` | `INTEGER` |
| `macros` | `BIGINT` |
| `messages` | `INTEGER` |
| `notes` | `BIGINT` |
| `notification_settings` | `INTEGER` |
| `notifications` | `BIGINT` |
| `reporting_events` | `INTEGER` |
| `sla_policies` | `BIGINT` |
| `telegram_bots` | `INTEGER` |
| `portals` | `INTEGER` |
| `applied_slas` | `BIGINT` |
| `campaigns` | `BIGINT` |
| `contacts` | `INTEGER` |
| `csat_survey_responses` | `BIGINT` |
| `custom_filters` | `BIGINT` |
| `dashboard_apps` | `BIGINT` |
| `email_templates` | `INTEGER` |
| `integrations_hooks` | `INTEGER` |
| `labels` | `BIGINT` |
| `mentions` | `BIGINT` |
| `sla_events` | `BIGINT` |
| `teams` | `BIGINT` |
| `webhooks` | `INTEGER` |
| `working_hours` | `BIGINT` |

### `actions`

| Tabela | Tipo |
|--------|------|
| `automation_rules` | `JSONB` |
| `macros` | `JSONB` |

### `additional_attributes`

| Tabela | Tipo |
|--------|------|
| `channel_api` | `JSONB` |
| `conversations` | `JSONB` |
| `messages` | `JSONB` |
| `contacts` | `JSONB` |

### `availability`

| Tabela | Tipo |
|--------|------|
| `account_users` | `INTEGER` |
| `users` | `INTEGER` |

### `blob_id`

| Tabela | Tipo |
|--------|------|
| `active_storage_attachments` | `BIGINT` |
| `active_storage_variant_records` | `BIGINT` |

### `category_id`

| Tabela | Tipo |
|--------|------|
| `articles` | `INTEGER` |
| `folders` | `INTEGER` |
| `related_categories` | `BIGINT` |

### `color`

| Tabela | Tipo |
|--------|------|
| `portals` | `VARCHAR` |
| `labels` | `VARCHAR` |

### `contact_id`

| Tabela | Tipo |
|--------|------|
| `contact_inboxes` | `BIGINT` |
| `conversations` | `BIGINT` |
| `notes` | `BIGINT` |
| `csat_survey_responses` | `BIGINT` |

### `content`

| Tabela | Tipo |
|--------|------|
| `articles` | `TEXT` |
| `canned_responses` | `TEXT` |
| `messages` | `TEXT` |
| `notes` | `TEXT` |
| `dashboard_apps` | `JSONB` |

### `content_type`

| Tabela | Tipo |
|--------|------|
| `messages` | `INTEGER` |
| `active_storage_blobs` | `VARCHAR` |

### `conversation_id`

| Tabela | Tipo |
|--------|------|
| `conversation_participants` | `BIGINT` |
| `messages` | `INTEGER` |
| `reporting_events` | `INTEGER` |
| `applied_slas` | `BIGINT` |
| `csat_survey_responses` | `BIGINT` |
| `mentions` | `BIGINT` |
| `sla_events` | `BIGINT` |

### `custom_attributes`

| Tabela | Tipo |
|--------|------|
| `accounts` | `JSONB` |
| `conversations` | `JSONB` |
| `contacts` | `JSONB` |
| `users` | `JSONB` |

### `description`

| Tabela | Tipo |
|--------|------|
| `agent_bots` | `VARCHAR` |
| `automation_rules` | `TEXT` |
| `articles` | `TEXT` |
| `categories` | `TEXT` |
| `custom_roles` | `VARCHAR` |
| `sla_policies` | `VARCHAR` |
| `campaigns` | `TEXT` |
| `labels` | `TEXT` |
| `teams` | `TEXT` |

### `display_id`

| Tabela | Tipo |
|--------|------|
| `conversations` | `INTEGER` |
| `campaigns` | `INTEGER` |

### `email`

| Tabela | Tipo |
|--------|------|
| `channel_email` | `VARCHAR` |
| `contacts` | `VARCHAR` |
| `users` | `VARCHAR` |

### `feature_flags`

| Tabela | Tipo |
|--------|------|
| `accounts` | `BIGINT` |
| `channel_web_widgets` | `INTEGER` |

### `hmac_mandatory`

| Tabela | Tipo |
|--------|------|
| `channel_api` | `BOOLEAN` |
| `channel_web_widgets` | `BOOLEAN` |

### `hmac_token`

| Tabela | Tipo |
|--------|------|
| `channel_api` | `VARCHAR` |
| `channel_web_widgets` | `VARCHAR` |

### `identifier`

| Tabela | Tipo |
|--------|------|
| `channel_api` | `VARCHAR` |
| `conversations` | `VARCHAR` |
| `contacts` | `VARCHAR` |
| `notification_subscriptions` | `TEXT` |

### `inbox_id`

| Tabela | Tipo |
|--------|------|
| `agent_bot_inboxes` | `INTEGER` |
| `contact_inboxes` | `BIGINT` |
| `conversations` | `INTEGER` |
| `messages` | `INTEGER` |
| `reporting_events` | `INTEGER` |
| `campaigns` | `BIGINT` |
| `inbox_members` | `INTEGER` |
| `integrations_hooks` | `INTEGER` |
| `sla_events` | `BIGINT` |
| `webhooks` | `INTEGER` |
| `working_hours` | `BIGINT` |

### `key`

| Tabela | Tipo |
|--------|------|
| `ar_internal_metadata` | `VARCHAR` |
| `active_storage_blobs` | `VARCHAR` |

### `last_activity_at`

| Tabela | Tipo |
|--------|------|
| `conversations` | `TIMESTAMP` |
| `notifications` | `TIMESTAMP` |
| `contacts` | `TIMESTAMP` |

### `locale`

| Tabela | Tipo |
|--------|------|
| `accounts` | `INTEGER` |
| `articles` | `VARCHAR` |
| `categories` | `VARCHAR` |
| `email_templates` | `INTEGER` |

### `message_id`

| Tabela | Tipo |
|--------|------|
| `attachments` | `INTEGER` |
| `action_mailbox_inbound_emails` | `VARCHAR` |
| `csat_survey_responses` | `BIGINT` |

### `meta`

| Tabela | Tipo |
|--------|------|
| `articles` | `JSONB` |
| `notifications` | `JSONB` |
| `sla_events` | `JSONB` |

### `name`

| Tabela | Tipo |
|--------|------|
| `active_storage_attachments` | `VARCHAR` |
| `accounts` | `VARCHAR` |
| `agent_bots` | `VARCHAR` |
| `automation_rules` | `VARCHAR` |
| `categories` | `VARCHAR` |
| `custom_roles` | `VARCHAR` |
| `folders` | `VARCHAR` |
| `inboxes` | `VARCHAR` |
| `macros` | `VARCHAR` |
| `platform_apps` | `VARCHAR` |
| `reporting_events` | `VARCHAR` |
| `sla_policies` | `VARCHAR` |
| `telegram_bots` | `VARCHAR` |
| `portals` | `VARCHAR` |
| `contacts` | `VARCHAR` |
| `custom_filters` | `VARCHAR` |
| `email_templates` | `VARCHAR` |
| `installation_configs` | `VARCHAR` |
| `tags` | `VARCHAR` |
| `teams` | `VARCHAR` |
| `users` | `VARCHAR` |

### `phone_number`

| Tabela | Tipo |
|--------|------|
| `channel_twilio_sms` | `VARCHAR` |
| `channel_whatsapp` | `VARCHAR` |
| `channel_sms` | `VARCHAR` |
| `contacts` | `VARCHAR` |

### `portal_id`

| Tabela | Tipo |
|--------|------|
| `articles` | `INTEGER` |
| `categories` | `INTEGER` |
| `inboxes` | `BIGINT` |
| `portals_members` | `BIGINT` |
| `portal_members` | `BIGINT` |

### `position`

| Tabela | Tipo |
|--------|------|
| `articles` | `INTEGER` |
| `categories` | `INTEGER` |

### `provider`

| Tabela | Tipo |
|--------|------|
| `channel_email` | `VARCHAR` |
| `channel_whatsapp` | `VARCHAR` |
| `channel_sms` | `VARCHAR` |
| `users` | `VARCHAR` |

### `provider_config`

| Tabela | Tipo |
|--------|------|
| `channel_email` | `JSONB` |
| `channel_whatsapp` | `JSONB` |
| `channel_sms` | `JSONB` |

### `pubsub_token`

| Tabela | Tipo |
|--------|------|
| `contact_inboxes` | `VARCHAR` |
| `users` | `VARCHAR` |

### `sender_id`

| Tabela | Tipo |
|--------|------|
| `messages` | `BIGINT` |
| `campaigns` | `INTEGER` |

### `sla_policy_id`

| Tabela | Tipo |
|--------|------|
| `conversations` | `BIGINT` |
| `applied_slas` | `BIGINT` |
| `sla_events` | `BIGINT` |

### `slug`

| Tabela | Tipo |
|--------|------|
| `articles` | `VARCHAR` |
| `categories` | `VARCHAR` |
| `portals` | `VARCHAR` |

### `snoozed_until`

| Tabela | Tipo |
|--------|------|
| `conversations` | `TIMESTAMP` |
| `notifications` | `TIMESTAMP` |

### `source_id`

| Tabela | Tipo |
|--------|------|
| `contact_inboxes` | `VARCHAR` |
| `messages` | `VARCHAR` |

### `status`

| Tabela | Tipo |
|--------|------|
| `accounts` | `INTEGER` |
| `agent_bot_inboxes` | `INTEGER` |
| `articles` | `INTEGER` |
| `conversations` | `INTEGER` |
| `data_imports` | `INTEGER` |
| `messages` | `INTEGER` |
| `action_mailbox_inbound_emails` | `INTEGER` |
| `integrations_hooks` | `INTEGER` |

### `team_id`

| Tabela | Tipo |
|--------|------|
| `conversations` | `BIGINT` |
| `team_members` | `BIGINT` |

### `title`

| Tabela | Tipo |
|--------|------|
| `articles` | `VARCHAR` |
| `campaigns` | `VARCHAR` |
| `dashboard_apps` | `VARCHAR` |
| `labels` | `VARCHAR` |

### `user_id`

| Tabela | Tipo |
|--------|------|
| `account_users` | `BIGINT` |
| `conversation_participants` | `BIGINT` |
| `notes` | `BIGINT` |
| `notification_settings` | `INTEGER` |
| `notifications` | `BIGINT` |
| `portals_members` | `BIGINT` |
| `reporting_events` | `INTEGER` |
| `team_members` | `BIGINT` |
| `audits` | `BIGINT` |
| `custom_filters` | `BIGINT` |
| `dashboard_apps` | `BIGINT` |
| `inbox_members` | `INTEGER` |
| `mentions` | `BIGINT` |
| `notification_subscriptions` | `BIGINT` |
| `portal_members` | `BIGINT` |

### `value`

| Tabela | Tipo |
|--------|------|
| `ar_internal_metadata` | `VARCHAR` |
| `reporting_events` | `DOUBLE PRECISION` |

### `version`

| Tabela | Tipo |
|--------|------|
| `audits` | `INTEGER` |
| `schema_migrations` | `VARCHAR` |

---

## 2. Foreign Keys — Tabelas Mais Referenciadas

**Total de tabelas referenciadas:** 2

| Tabela Referenciada | Qtd. Referências |
|---------------------|------------------|
| `active_storage_blobs` | 2 |
| `portals` | 1 |

### `active_storage_blobs`

| Tabela Origem | FK | Coluna Referenciada |
|---------------|----|---------------------|
| `active_storage_attachments` | `blob_id` | `id` |
| `active_storage_variant_records` | `blob_id` | `id` |

### `portals`

| Tabela Origem | FK | Coluna Referenciada |
|---------------|----|---------------------|
| `inboxes` | `portal_id` | `id` |

---

## 3. Dependências Circulares

> ✅ Nenhuma dependência circular detectada.

---

## 4. Tabelas sem Primary Key

> ⚠️ **1 tabelas sem primary key.**

- `portals_members`

---

## 5. Candidatos à Desnormalização

> ✅ Nenhum candidato crítico à desnormalização encontrado.

---

*Relatório gerado automaticamente por db-erd-analysis v2.0.0.*
