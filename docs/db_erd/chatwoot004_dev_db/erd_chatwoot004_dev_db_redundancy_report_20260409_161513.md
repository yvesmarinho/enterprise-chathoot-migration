# Relatório de Análise de Redundância do Banco de Dados

**Gerado em:** 2026-04-09 16:09:51  
**Total de tabelas analisadas:** 70

---

## 1. Redundância de Colunas

> ⚠️ **43 colunas duplicadas encontradas entre tabelas.**

### `account_id`

| Tabela | Tipo |
|--------|------|
| `articles` | `INTEGER` |
| `channel_web_widgets` | `INTEGER` |
| `dashboard_apps` | `BIGINT` |
| `account_users` | `BIGINT` |
| `agent_bot_inboxes` | `INTEGER` |
| `agent_bots` | `BIGINT` |
| `applied_slas` | `BIGINT` |
| `attachments` | `INTEGER` |
| `automation_rules` | `BIGINT` |
| `campaigns` | `BIGINT` |
| `canned_responses` | `INTEGER` |
| `categories` | `INTEGER` |
| `channel_api` | `INTEGER` |
| `channel_email` | `INTEGER` |
| `channel_facebook_pages` | `INTEGER` |
| `channel_line` | `INTEGER` |
| `channel_sms` | `INTEGER` |
| `channel_telegram` | `INTEGER` |
| `channel_twilio_sms` | `INTEGER` |
| `channel_twitter_profiles` | `INTEGER` |
| `channel_whatsapp` | `INTEGER` |
| `contacts` | `INTEGER` |
| `conversation_participants` | `BIGINT` |
| `conversations` | `INTEGER` |
| `csat_survey_responses` | `BIGINT` |
| `custom_attribute_definitions` | `BIGINT` |
| `custom_filters` | `BIGINT` |
| `custom_roles` | `BIGINT` |
| `data_imports` | `BIGINT` |
| `email_templates` | `INTEGER` |
| `folders` | `INTEGER` |
| `inboxes` | `INTEGER` |
| `integrations_hooks` | `INTEGER` |
| `labels` | `BIGINT` |
| `macros` | `BIGINT` |
| `mentions` | `BIGINT` |
| `messages` | `INTEGER` |
| `notes` | `BIGINT` |
| `notification_settings` | `INTEGER` |
| `notifications` | `BIGINT` |
| `portals` | `INTEGER` |
| `reporting_events` | `INTEGER` |
| `sla_events` | `BIGINT` |
| `sla_policies` | `BIGINT` |
| `teams` | `BIGINT` |
| `telegram_bots` | `INTEGER` |
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
| `contacts` | `JSONB` |
| `conversations` | `JSONB` |
| `messages` | `JSONB` |

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
| `labels` | `VARCHAR` |
| `portals` | `VARCHAR` |

### `contact_id`

| Tabela | Tipo |
|--------|------|
| `contact_inboxes` | `BIGINT` |
| `conversations` | `BIGINT` |
| `csat_survey_responses` | `BIGINT` |
| `notes` | `BIGINT` |

### `content`

| Tabela | Tipo |
|--------|------|
| `articles` | `TEXT` |
| `dashboard_apps` | `JSONB` |
| `canned_responses` | `TEXT` |
| `messages` | `TEXT` |
| `notes` | `TEXT` |

### `content_type`

| Tabela | Tipo |
|--------|------|
| `active_storage_blobs` | `VARCHAR` |
| `messages` | `INTEGER` |

### `conversation_id`

| Tabela | Tipo |
|--------|------|
| `applied_slas` | `BIGINT` |
| `conversation_participants` | `BIGINT` |
| `csat_survey_responses` | `BIGINT` |
| `mentions` | `BIGINT` |
| `messages` | `INTEGER` |
| `reporting_events` | `INTEGER` |
| `sla_events` | `BIGINT` |

### `custom_attributes`

| Tabela | Tipo |
|--------|------|
| `accounts` | `JSONB` |
| `contacts` | `JSONB` |
| `conversations` | `JSONB` |
| `users` | `JSONB` |

### `description`

| Tabela | Tipo |
|--------|------|
| `articles` | `TEXT` |
| `agent_bots` | `VARCHAR` |
| `automation_rules` | `TEXT` |
| `campaigns` | `TEXT` |
| `categories` | `TEXT` |
| `custom_roles` | `VARCHAR` |
| `labels` | `TEXT` |
| `sla_policies` | `VARCHAR` |
| `teams` | `TEXT` |

### `display_id`

| Tabela | Tipo |
|--------|------|
| `campaigns` | `INTEGER` |
| `conversations` | `INTEGER` |

### `email`

| Tabela | Tipo |
|--------|------|
| `channel_email` | `VARCHAR` |
| `contacts` | `VARCHAR` |
| `users` | `VARCHAR` |

### `feature_flags`

| Tabela | Tipo |
|--------|------|
| `channel_web_widgets` | `INTEGER` |
| `accounts` | `BIGINT` |

### `hmac_mandatory`

| Tabela | Tipo |
|--------|------|
| `channel_web_widgets` | `BOOLEAN` |
| `channel_api` | `BOOLEAN` |

### `hmac_token`

| Tabela | Tipo |
|--------|------|
| `channel_web_widgets` | `VARCHAR` |
| `channel_api` | `VARCHAR` |

### `identifier`

| Tabela | Tipo |
|--------|------|
| `channel_api` | `VARCHAR` |
| `contacts` | `VARCHAR` |
| `conversations` | `VARCHAR` |
| `notification_subscriptions` | `TEXT` |

### `inbox_id`

| Tabela | Tipo |
|--------|------|
| `agent_bot_inboxes` | `INTEGER` |
| `campaigns` | `BIGINT` |
| `contact_inboxes` | `BIGINT` |
| `conversations` | `INTEGER` |
| `inbox_members` | `INTEGER` |
| `integrations_hooks` | `INTEGER` |
| `messages` | `INTEGER` |
| `reporting_events` | `INTEGER` |
| `sla_events` | `BIGINT` |
| `webhooks` | `INTEGER` |
| `working_hours` | `BIGINT` |

### `key`

| Tabela | Tipo |
|--------|------|
| `active_storage_blobs` | `VARCHAR` |
| `ar_internal_metadata` | `VARCHAR` |

### `last_activity_at`

| Tabela | Tipo |
|--------|------|
| `contacts` | `TIMESTAMP` |
| `conversations` | `TIMESTAMP` |
| `notifications` | `TIMESTAMP` |

### `locale`

| Tabela | Tipo |
|--------|------|
| `accounts` | `INTEGER` |
| `categories` | `VARCHAR` |
| `email_templates` | `INTEGER` |

### `message_id`

| Tabela | Tipo |
|--------|------|
| `action_mailbox_inbound_emails` | `VARCHAR` |
| `attachments` | `INTEGER` |
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
| `accounts` | `VARCHAR` |
| `active_storage_attachments` | `VARCHAR` |
| `agent_bots` | `VARCHAR` |
| `automation_rules` | `VARCHAR` |
| `categories` | `VARCHAR` |
| `contacts` | `VARCHAR` |
| `custom_filters` | `VARCHAR` |
| `custom_roles` | `VARCHAR` |
| `email_templates` | `VARCHAR` |
| `folders` | `VARCHAR` |
| `inboxes` | `VARCHAR` |
| `installation_configs` | `VARCHAR` |
| `macros` | `VARCHAR` |
| `platform_apps` | `VARCHAR` |
| `portals` | `VARCHAR` |
| `reporting_events` | `VARCHAR` |
| `sla_policies` | `VARCHAR` |
| `tags` | `VARCHAR` |
| `teams` | `VARCHAR` |
| `telegram_bots` | `VARCHAR` |
| `users` | `VARCHAR` |

### `phone_number`

| Tabela | Tipo |
|--------|------|
| `channel_sms` | `VARCHAR` |
| `channel_twilio_sms` | `VARCHAR` |
| `channel_whatsapp` | `VARCHAR` |
| `contacts` | `VARCHAR` |

### `portal_id`

| Tabela | Tipo |
|--------|------|
| `articles` | `INTEGER` |
| `categories` | `INTEGER` |
| `inboxes` | `BIGINT` |
| `portal_members` | `BIGINT` |
| `portals_members` | `BIGINT` |

### `position`

| Tabela | Tipo |
|--------|------|
| `articles` | `INTEGER` |
| `categories` | `INTEGER` |

### `provider`

| Tabela | Tipo |
|--------|------|
| `channel_email` | `VARCHAR` |
| `channel_sms` | `VARCHAR` |
| `channel_whatsapp` | `VARCHAR` |
| `users` | `VARCHAR` |

### `provider_config`

| Tabela | Tipo |
|--------|------|
| `channel_email` | `JSONB` |
| `channel_sms` | `JSONB` |
| `channel_whatsapp` | `JSONB` |

### `pubsub_token`

| Tabela | Tipo |
|--------|------|
| `contact_inboxes` | `VARCHAR` |
| `users` | `VARCHAR` |

### `sender_id`

| Tabela | Tipo |
|--------|------|
| `campaigns` | `INTEGER` |
| `messages` | `BIGINT` |

### `sla_policy_id`

| Tabela | Tipo |
|--------|------|
| `applied_slas` | `BIGINT` |
| `conversations` | `BIGINT` |
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
| `articles` | `INTEGER` |
| `accounts` | `INTEGER` |
| `action_mailbox_inbound_emails` | `INTEGER` |
| `agent_bot_inboxes` | `INTEGER` |
| `conversations` | `INTEGER` |
| `data_imports` | `INTEGER` |
| `integrations_hooks` | `INTEGER` |
| `messages` | `INTEGER` |

### `team_id`

| Tabela | Tipo |
|--------|------|
| `conversations` | `BIGINT` |
| `team_members` | `BIGINT` |

### `title`

| Tabela | Tipo |
|--------|------|
| `articles` | `VARCHAR` |
| `dashboard_apps` | `VARCHAR` |
| `campaigns` | `VARCHAR` |
| `labels` | `VARCHAR` |

### `user_id`

| Tabela | Tipo |
|--------|------|
| `dashboard_apps` | `BIGINT` |
| `account_users` | `BIGINT` |
| `audits` | `BIGINT` |
| `conversation_participants` | `BIGINT` |
| `custom_filters` | `BIGINT` |
| `inbox_members` | `INTEGER` |
| `mentions` | `BIGINT` |
| `notes` | `BIGINT` |
| `notification_settings` | `INTEGER` |
| `notification_subscriptions` | `BIGINT` |
| `notifications` | `BIGINT` |
| `portal_members` | `BIGINT` |
| `portals_members` | `BIGINT` |
| `reporting_events` | `INTEGER` |
| `team_members` | `BIGINT` |

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
