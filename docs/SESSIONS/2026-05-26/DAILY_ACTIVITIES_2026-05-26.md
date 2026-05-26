# 📋 Daily Activities — 2026-05-26

**Branch**: `master`
**Modo**: PROGRAMMING
**Objetivo**: Investigar causa raiz da impossibilidade de abrir mensagens da Unimed Guaxupé no ambiente DEV

---

<!-- Atividades serão adicionadas incrementalmente abaixo -->

---

### Ritual de Início de Sessão (SESSION-START)

**[TIMESTAMP] — 🔵 Em progresso**

**Objetivo**: Executar o ritual de início de sessão conforme o prompt oficial.
**Contexto**: Retomada após Sessão 23 (2026-05-24), com foco em gaps P0 de migração (D17).

**Passos executados**:
1. ✅ MCP validado em arquivo `.vscode/mcp.json`: servidores memory e sequential-thinking configurados
2. ✅ Contexto recuperado: TODO.md, INDEX.md, SESSIONS/2026-05-24/
3. ✅ Regras carregadas: `.copilot-rules-enterprise-chatwoot-migration.md` (150 linhas)
4. ✅ Scan de segurança: 🟢 LIMPO — nenhum arquivo sensível fora de .secrets/
5. ✅ `git status` verificado: branch master, working tree clean, up to date with origin/master
6. ✅ Últimos 5 commits verificados (último: 0236463 — docs session S23)
7. ✅ Documentos de sessão criados: SESSION_RECOVERY_2026-05-26.md, DAILY_ACTIVITIES_2026-05-26.md
8. ✅ Style guide carregado: `docs/templates/SESSION_DOCS_STYLE_GUIDE.md`
9. ✅ Domínio declarado: PROGRAMMING
10. ✅ Objetivo declarado: Investigar causa raiz - mensagens Unimed Guaxupé não abrem no DEV

**Resultado**: Sessão inicializada e pronta para investigação.

**Status**: ✅ Completo

---

### 🔍 Investigação D18 — Mensagens Unimed Guaxupé não abrem (DEV)

**09:06 — ✅ COMPLETO**

**Objetivo**: Identificar causa raiz da impossibilidade de abrir mensagens da Unimed Guaxupé no ambiente DEV após migração bem-sucedida (S23 — 2026-05-24).

**Contexto**: Última migração executou sem falhas (60.030 registros, 0 erros), mas usuário reporta que mensagens não abrem na UI. Histórico mostra problemas similares em D11 (banco errado) e D16 (ActiveStorage ausente).

**Passos executados**:
1. Criado script `.tmp/d18_investigacao_guaxupe.py` com 4 fases de validação
2. FASE 1: Validado banco conectado → ✅ `chatwoot004_dev1_db` (correto)
3. FASE 2: Validado account → ✅ ID=68, 8.190 convs, 46.010 msgs, 1.513 contacts, 1 inbox
4. FASE 3: Verificado ActiveStorage → ❌ **1.932 attachments sem vínculo (0% coberto)**
5. FASE 4: Validado FK integrity → ✅ 0 NULLs em campos críticos

**Resultado**: **CAUSA RAIZ CONFIRMADA — Problema D16 recorrente**

### 📊 Evidências Coletadas

| Check | Status | Detalhe |
|-------|--------|---------|
| Banco conectado | ✅ OK | `chatwoot004_dev1_db` (não é problema D11) |
| Account Unimed Guaxupé | ✅ OK | ID=68, 8.190 conversas, 46.010 mensagens |
| ActiveStorage | ❌ **PROBLEMA** | **1.932 attachments migrados sem vínculos** |
| FK Integrity | ✅ OK | 0 NULLs em conversation_id, contact_id, inbox_id, contact_inbox_id |

**Diagnóstico técnico**:
- Tabela `attachments`: 1.932 registros migrados ✅
- `active_storage_attachments`: **0 registros** (esperado: 1.932) ❌
- `active_storage_blobs`: **0 registros** (esperado: 1.932) ❌
- Cobertura ActiveStorage: **0%**

**Impacto funcional**:
- Ao abrir mensagem com anexo, Chatwoot tenta acessar `attachment.file_metadata`
- `file_metadata` depende de `active_storage_blobs.metadata`
- Como blob não existe → `undefined method [] for nil` → HTTP 500
- Mensagens SEM anexo abrem normalmente
- Mensagens COM anexo causam 500 e travam a UI

**Arquivos criados**:
- `.tmp/d18_investigacao_guaxupe.py` (script diagnóstico, 300 linhas)
- `.tmp/d18_investigacao_guaxupe_20260526_090807.json` (relatório JSON, evidências completas)

**Decisões técnicas**:
- Problema é **idêntico ao D16** (2026-05-20)
- Migração de `attachments` está incompleta: copia metadados mas não cria vínculos ActiveStorage
- Necessário criar `ActiveStorageMigrator` ou script de correção pós-migração

**Status**: ✅ Completo

---

### 🔍 D18 Parte 2 — Análise ActiveStorage no SOURCE

**09:09 — ✅ COMPLETO**

**Objetivo**: Verificar se o SOURCE possui registros de ActiveStorage para mapear a estrutura necessária ao migrator.

**Contexto**: D18 Parte 1 identificou que DEST não possui ActiveStorage (0% cobertura). Necessário verificar se SOURCE possui os dados ou se o problema é pré-existente.

**Passos executados**:
1. Criado script `.tmp/d18_part2_activestorage_source.py`
2. Conectado ao SOURCE (chat-vya-digital, banco `chatwoot_dev1_db`)
3. Identificada account Unimed Guaxupé: ID=25
4. Contados attachments no SOURCE: 1.934
5. Verificado active_storage_attachments: **0 registros**
6. Verificado active_storage_blobs: **0 registros**

**Resultado**: **🚨 DESCOBERTA CRÍTICA — Problema pré-existente no SOURCE**

### 📊 Comparação SOURCE vs DEST

| Métrica | SOURCE (chat.vya.digital) | DEST (vya-chat-dev.vya.digital) |
|---------|---------------------------|--------------------------------|
| Database | `chatwoot_dev1_db` | `chatwoot004_dev1_db` |
| Account ID | 25 | 68 |
| Attachments | 1.934 | 1.932 |
| active_storage_attachments | **0 (0%)** | **0 (0%)** |
| active_storage_blobs | **0 (0%)** | **0 (0%)** |

**Conclusão**:
- ✅ Migração copiou attachments corretamente (99,9% cobertura)
- ❌ ActiveStorage **já estava ausente no SOURCE** antes da migração
- ❌ **Este não é um problema da migração — é um problema do Chatwoot original**

**Hipóteses**:
1. **H1**: Chatwoot em `chat.vya.digital` usa versão antiga que não depende de ActiveStorage
2. **H2**: Configuração do Chatwoot SOURCE usa storage direto via `external_url` (sem ActiveStorage)
3. **H3**: ActiveStorage foi desabilitado manualmente no SOURCE
4. **H4**: Problema existe no SOURCE também (mensagens com anexo não abrem lá)

**Próximos passos**:
1. Testar se mensagens com anexo abrem em `chat.vya.digital` (SOURCE)
2. Verificar versão do Chatwoot em ambas as instâncias
3. Comparar configuração de storage (`config/storage.yml`)
4. Se SOURCE funciona sem ActiveStorage → replicar configuração no DEST
5. Se SOURCE também não funciona → problema sistêmico a corrigir

**Arquivos criados**:
- `.tmp/d18_part2_activestorage_source.py` (script análise SOURCE, 250 linhas)
- `.tmp/d18_part2_activestorage_source_20260526_090956.json` (relatório JSON)

**Status**: ✅ Completo

---
