# D18 — DEBATE: Mensagens Unimed Guaxupé Não Abrem no DEV

**Data**: 2026-05-26
**Sessão**: 26 (S26)
**Ambiente**: DEV — `vya-chat-dev.vya.digital` → banco `chatwoot004_dev1_db`
**Account afetada**: Unimed Guaxupé — `account_id=68` (SOURCE: `id=25`)
**Última migração**: 2026-05-24 (S23) — 60.030 registros, 0 falhas

---

## 📋 Manifestação do Problema

**Sintoma reportado pelo usuário**:
> "Última migração não ocorreu com falhas, não é possível abrir as mensagens da Unimed Guaxupé. Ambiente DEV."

**Contexto**:
- Migração S23 executada com sucesso (8.190 conversas, 46.010 mensagens, 1.513 contacts)
- Validações FK: 100% clean (0 orphans no escopo migrado)
- Dados core migrados corretamente (100% cobertura)
- **MAS**: Mensagens não abrem na UI do vya-chat-dev.vya.digital

---

## 🔍 Investigação Executada

### Fase 1 — Validação Básica (D18 Parte 1)

**Script**: `.tmp/d18_investigacao_guaxupe.py`
**Objetivo**: Verificar banco conectado, account, ActiveStorage e FK integrity

**Resultados**:

| Check | Status | Detalhe |
|-------|--------|---------|
| Banco conectado | ✅ OK | `chatwoot004_dev1_db` (banco correto — não é problema D11) |
| Account Unimed Guaxupé | ✅ OK | ID=68, 8.190 conversas, 46.010 mensagens, 1.513 contacts, 1 inbox |
| **ActiveStorage** | ❌ **PROBLEMA** | **1.932 attachments migrados, 0 vínculos ActiveStorage (0% coberto)** |
| FK Integrity | ✅ OK | 0 NULLs em conversation_id, contact_id, inbox_id, contact_inbox_id |

**Diagnóstico inicial**:
- Tabela `attachments`: 1.932 registros migrados ✅
- `active_storage_attachments`: **0 registros** (esperado: 1.932) ❌
- `active_storage_blobs`: **0 registros** (esperado: 1.932) ❌

**Conclusão Parte 1**: Problema idêntico ao **D16** (2026-05-20) — ActiveStorage ausente no DEST.

---

### Fase 2 — Análise do SOURCE (D18 Parte 2)

**Script**: `.tmp/d18_part2_activestorage_source.py`
**Objetivo**: Verificar se SOURCE possui ActiveStorage (para mapear estrutura do migrator)

**Resultados**:

| Métrica | SOURCE (chat.vya.digital) | DEST (vya-chat-dev.vya.digital) |
|---------|---------------------------|--------------------------------|
| Database | `chatwoot_dev1_db` | `chatwoot004_dev1_db` |
| Account ID | 25 | 68 |
| Attachments | 1.934 | 1.932 (99,9% migrado) ✅ |
| active_storage_attachments | **0 (0%)** ❌ | **0 (0%)** ❌ |
| active_storage_blobs | **0 (0%)** ❌ | **0 (0%)** ❌ |

**🚨 DESCOBERTA CRÍTICA**:
- ActiveStorage **já estava ausente no SOURCE** antes da migração
- **Este não é um problema da migração — é um problema do Chatwoot original**
- Migração copiou attachments corretamente (99,9% cobertura)

---

## 🧩 Hipóteses de Causa Raiz

### H1 — Versão do Chatwoot SOURCE não usa ActiveStorage ★★★★★

**Descrição**: O Chatwoot em `chat.vya.digital` pode usar uma versão mais antiga que armazena anexos diretamente via `external_url` (S3 direto), sem a camada de ActiveStorage do Rails.

**Evidência a favor**:
- SOURCE tem 0% ActiveStorage mas funciona (supostamente)
- Campo `external_url` em `attachments` contém URL completa do S3
- Chatwoot tem histórico de usar storage direto antes de migrar para ActiveStorage

**Evidência contra**: Precisaria confirmar:
1. Se mensagens com anexo realmente funcionam em `chat.vya.digital`
2. Qual versão do Chatwoot está em cada instância

**Veredicto**: **HIPÓTESE PRIMÁRIA** — requer teste funcional no SOURCE.

---

### H2 — Configuração de storage diferente entre SOURCE e DEST ★★★★☆

**Descrição**: O Chatwoot DEST (`vya-chat-dev.vya.digital`) pode estar configurado para usar ActiveStorage (via `config/storage.yml`), enquanto o SOURCE usa storage direto.

**Evidência a favor**:
- DEST é instância mais recente (Chatwoot 3.x ou 4.x provavelmente usa ActiveStorage)
- SOURCE é instância legada (pode usar storage direto)

**Evidência contra**:
- Ambos são PostgreSQL 16.10 no mesmo host (wfdb02.vya.digital)
- Migrações de schema devem ser compatíveis

**Veredicto**: Requer comparação de:
- `rails db:migrate:status` em ambas as instâncias
- `config/storage.yml` em ambas as instâncias
- Versão do Chatwoot em ambas as instâncias

---

### H3 — Problema existe no SOURCE também (mas nunca foi reportado) ★★★☆☆

**Descrição**: É possível que o SOURCE **também tenha o problema** (mensagens com anexo não abrem), mas nunca foi reportado porque:
- Usuários não tentam abrir mensagens antigas com anexo
- O problema é intermitente
- O problema afeta apenas alguns tipos de anexo

**Evidência a favor**:
- SOURCE tem 0% ActiveStorage (idêntico ao DEST)
- Sem ActiveStorage, o serializer deveria falhar da mesma forma

**Evidência contra**:
- Usuário não mencionou problema no SOURCE
- Se problema existisse, seria reportado

**Veredicto**: Requer teste funcional no SOURCE (abrir mensagens com anexo da Unimed Guaxupé em `chat.vya.digital`).

---

### H4 — ActiveStorage foi desabilitado manualmente no SOURCE ★★☆☆☆

**Descrição**: Alguém pode ter desabilitado ActiveStorage manualmente no SOURCE para contornar bugs ou problemas de performance.

**Evidência a favor**: Desconhecida.

**Evidência contra**:
- Nenhuma evidência em configuração
- Improvável em produção

**Veredicto**: Improvável, mas pode ser verificado via git history do repo do Chatwoot no SOURCE.

---

## ✅ Conclusões

### Fatos Confirmados

1. ✅ Banco conectado correto: `chatwoot004_dev1_db`
2. ✅ Account Unimed Guaxupé existe e está ativa (ID=68)
3. ✅ Dados migrados corretamente: 8.190 conversas, 46.010 mensagens, 1.513 contacts
4. ✅ FK integrity 100% clean (0 NULLs, 0 orphans no escopo migrado)
5. ❌ ActiveStorage **ausente em SOURCE e DEST** (0% cobertura)
6. ✅ Migração copiou attachments corretamente (99,9% cobertura)

### Causa Raiz Provável

**O problema NÃO é da migração. O problema é pré-existente no SOURCE.**

O `AttachmentsMigrator` copia corretamente os registros da tabela `attachments`, mas **não pode criar vínculos ActiveStorage que nunca existiram no SOURCE**.

### Caminho Crítico — Próximas Ações

#### A1 — Testar funcionalidade no SOURCE (URGENTE)

**Ação**: Acessar `chat.vya.digital`, logar com um usuário da Unimed Guaxupé, tentar abrir mensagens com anexo.

**Resultado esperado**:
- **Se funciona**: H1 confirmada → SOURCE usa storage direto, DEST precisa ser reconfigurado
- **Se não funciona**: H3 confirmada → problema sistêmico a corrigir em ambas as instâncias

#### A2 — Verificar versões do Chatwoot

**Ação**:
```bash
# No SOURCE
ssh chat.vya.digital
cd /path/to/chatwoot
cat VERSION  # ou grep VERSION Gemfile.lock

# No DEST
ssh vya-chat-dev.vya.digital
cd /path/to/chatwoot
cat VERSION
```

**Resultado esperado**: Confirmar se há diferença de versão major/minor.

#### A3 — Comparar configuração de storage

**Ação**:
```bash
# SOURCE
cat /path/to/chatwoot/config/storage.yml

# DEST
cat /path/to/chatwoot/config/storage.yml
```

**Resultado esperado**: Identificar diferenças em `active_storage` config.

#### A4 — Se SOURCE funciona sem ActiveStorage

**Ação**: Replicar configuração do SOURCE no DEST:
1. Copiar `config/storage.yml` do SOURCE para DEST
2. Atualizar variáveis de ambiente (se necessário)
3. Reiniciar container/processo Chatwoot no DEST
4. Testar se mensagens com anexo abrem

#### A5 — Se SOURCE também não funciona

**Ação**: Criar `ActiveStorageMigrator` para ambas as instâncias:
1. Gerar `active_storage_blobs` a partir de `attachments.external_url`
2. Gerar `active_storage_attachments` vinculando `Message` → `Blob`
3. Executar no SOURCE primeiro (validação)
4. Executar no DEST

**Complexidade**: ALTA — requer parsing de `external_url`, geração de `checksum`, cálculo de `byte_size`, etc.

---

## 📄 Evidências Geradas

| Arquivo | Descrição |
|---------|-----------|
| `.tmp/d18_investigacao_guaxupe.py` | Script diagnóstico DEST (4 fases: banco, account, ActiveStorage, FK) |
| `.tmp/d18_investigacao_guaxupe_20260526_090807.json` | Relatório JSON DEST (evidências completas) |
| `.tmp/d18_part2_activestorage_source.py` | Script análise SOURCE (ActiveStorage) |
| `.tmp/d18_part2_activestorage_source_20260526_090956.json` | Relatório JSON SOURCE |

---

## 🎯 Recomendações

### Imediatas (Bloqueante para DEV)

1. **Executar A1** (teste funcional no SOURCE) — **URGENTE**
2. **Executar A2** (verificar versões do Chatwoot) — 5 min
3. **Executar A3** (comparar config storage) — 5 min

### Curto Prazo (Resolução)

- **Se SOURCE funciona**: Executar A4 (replicar config) — 30 min
- **Se SOURCE não funciona**: Executar A5 (criar ActiveStorageMigrator) — 4-8 horas

### Longo Prazo (Prevenção)

- Documentar diferenças de versão/config entre instâncias
- Criar testes de integração que verifiquem funcionalidade de anexos pós-migração
- Adicionar validação de ActiveStorage ao pipeline de migração (alerta se ausente)

---

*Gerado em 2026-05-26 — Sessão 26 — D18: Mensagens Unimed Guaxupé não abrem*
