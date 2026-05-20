# 📋 Daily Activities — 2026-05-20

**Branch**: `master`
**Modo**: PROGRAMMING
**Objetivo**: Preparação para migração em produção

---

<!-- Atividades serão adicionadas incrementalmente abaixo -->

---

### Debate D16 — Investigação HTTP 500 Conversações Pós-Migração DEV (D16)

**Horário não especificado — ✅ FASE 1 CONCLUÍDA**

**Objetivo**: Investigar HTTP 500 ao carregar conversações em `vya-chat-dev.vya.digital` após migração DEV bem-sucedida (S20). Gerar debate, documentar hipóteses e plano de investigação.
**Contexto**: Usuário reportou `GET /api/v1/accounts/69/conversations?inbox_id=526&...` retornando 500. A migração DEV (S20) completou com FK integrity 100%, mas aplicação apresenta erro ao renderizar conversações.

**Passos executados**:
1. Analisado `logs/messages_error.log` — 2 evidências: HTTP 500 autenticado + erro auth ao acessar URL diretamente (esperado)
2. Lidos migrators `conversations_migrator.py`, `messages_migrator.py`, `base_migrator.py` e `migrar.py`
3. Identificado que campos JSONB (`meta`, `additional_attributes`) são copiados literalmente sem reprocessamento de IDs internos
4. Mapeadas 7 hipóteses de causa raiz (H1-H7) com ranking de probabilidade
5. Criados 7 diagnósticos read-only específicos para cada hipótese
6. Gerado plano de investigação faseado (4 fases: diagnóstico → análise → correção → validação)

**Resultado**: Fase 1 executada com causa raiz confirmada.
- Stack trace Rails: `ActionView::Template::Error (undefined method [] for nil)` em `app/models/attachment.rb:80`
- Diagnóstico DB: 1932/1932 attachments da account 69 sem vínculo em `active_storage_attachments` e `active_storage_blobs`
- Sequências OK e sem mismatch de `contact_inbox_id`

**Arquivos criados**:
- `docs/debates/D16-DEBATE-HTTP500-CONVERSACOES-POS-MIGRACAO-2026-05-20.md`
- `docs/debates/D16-PLANO-INVESTIGACAO-HTTP500-2026-05-20.md`
- `.tmp/d16_stacktrace_20260520_1204.txt`
- `.tmp/d16_diagnostico_http500.py`
- `.tmp/d16_diagnostico_http500_20260520_120230.json`

**Status**: ✅ Fase 1 concluída — pronto para Fase 2/3 (script de correção, sob autorização)

---

---

### Ritual de Início de Sessão (S21-00)

**Horário não especificado — ✅ COMPLETO**

**Objetivo**: Executar ritual de início de sessão conforme `.github/prompts/session-start.prompt.md`
**Contexto**: Sessão 21 iniciada após Sessão 20 (2026-05-19) que completou refatoração de scripts e migração DEV validada
**Passos executados**:
1. **Passo 1 — MCP Config**: Verificado `.vscode/mcp.json` — ✅ memory, sequential-thinking, filesystem, github
2. **Passo 2 — Contexto Recuperado**:
   - `docs/TODO.md` lido — última sessão: 2026-05-19
   - `docs/INDEX.md` lido — projeto indexado e organizado
   - `docs/SESSIONS/2026-05-18/FINAL_STATUS_2026-05-18.md` lido — última sessão finalizada documentada
   - `docs/SESSIONS/2026-05-18/DAILY_ACTIVITIES_2026-05-18.md` lido — atividades detalhadas
   - `docs/SESSIONS/2026-05-19/DAILY_ACTIVITIES_2026-05-19.md` lido — Sessão 20 (scripts refactor + migração DEV)
3. **Passo 3 — Regras Copilot**:
   - `.copilot-rules-enterprise-chatwoot-migration.md` lido (200 linhas)
   - `.github/copilot-instructions.md` carregado (resumo P0/P1)
   - P0: Nunca heredoc/echo para criar arquivos ✅
   - P0: Nunca cat/grep/find/ls via terminal ✅
   - P0: Mover/copiar/excluir → Python stdlib ✅
4. **Passo 4 — Scan de Segurança**:
   - `file_search` para `**/*.env`, `**/*.key`, `**/*.pem` — 0 resultados
   - 🟢 LIMPO — nenhum arquivo sensível fora de `.secrets/`
   - `.secrets/` está no `.gitignore` ✅
5. **Passo 5 — Git Status**:
   - Branch: `master` (up to date with origin/master)
   - Working tree: clean
   - Last 5 commits visualizados — último: `0072293` (scripts refactor + BUG-SENDER fix)
6. **Passo 6 — Documentos de Sessão**:
   - ✅ Criado: `docs/SESSIONS/2026-05-20/SESSION_RECOVERY_2026-05-20.md`
   - ✅ Criado: `docs/SESSIONS/2026-05-20/DAILY_ACTIVITIES_2026-05-20.md` (este arquivo)
7. **Passo 7 — Domínio Declarado**:
   - Modo: PROGRAMMING
   - Projeto: enterprise-chatwoot-migration
   - Domain Profile: `.github/prompts/domain/devops-programming.prompt.md` carregado

**Resultado**: Sessão iniciada com sucesso. Contexto completo recuperado. Pronto para trabalho.

**Status**: ✅ Completo

---

### Migração All-Accounts Legado + Deploy wfdb01 (S21-01)

**Horário não especificado — ✅ CONCLUÍDO**

**Objetivo**: Forçar migração de todas as accounts pelo fluxo legado por default e atualizar remoto wfdb01.

**Artefatos criados/modificados**:
| Arquivo | O que mudou |
|---------|-------------|
| `docker/entrypoint.sh` | `PIPELINE` passou a ser resolvido dinamicamente: `legacy` quando `ALL_ACCOUNTS=true` e `full` caso contrário |
| `docker/docker-compose.yml` | `PIPELINE` default alterado para vazio (`${PIPELINE:-}`) para não sobrescrever decisão do entrypoint |
| `app/migrate_all_accounts.py` | removida whitelist fixa de Guaxupé; default agora migra todas as accounts; whitelist opcional via `ACCOUNTS_WHITELIST` |
| `docker/Dockerfile` | adicionado `PYTHONPATH=/app` para corrigir import `from src...` no container |
| `app/migrate_all_accounts.py` | adicionado `import os` (correção de `NameError`) |

**Passos executados**:
1. Diagnóstico do erro em produção do migrador: `PIPELINE=full` indevido e `ModuleNotFoundError: No module named 'src'`.
2. Correção da resolução de pipeline no `entrypoint` + `docker-compose`.
3. Correção do ambiente Python no container (`PYTHONPATH=/app`).
4. Correção do `NameError` no runner legado (`import os`).
5. Deploy remoto via `./docker/deploy-to-wfdb01.sh --build` com confirmação no host.
6. Execução validada em daemon com `ALL_ACCOUNTS=true` exibindo `PIPELINE: legacy` e listando as 6 accounts do SOURCE.

**Resultado**:
- Fluxo `ALL_ACCOUNTS=true` funcionando no caminho legado em wfdb01.
- Migração em daemon iniciada e processando accounts do SOURCE no runner legado.

**Destaques**: O campo `ACCOUNT` no cabeçalho permanece cosmético em modo all-accounts; a execução real está correta e orientada pela lista de accounts do SOURCE.

---

### Encerramento de Sessão (S21-END)

**Horário não especificado — ✅ CONCLUÍDO**

**Validações de qualidade**:
- `make test` ✅
- `make lint` ✅
- `python -m py_compile app/migrate_all_accounts.py` ✅

**Security review (session docs)**:
- Scan em `docs/SESSIONS/2026-05-20/*.md` sem credenciais, tokens reais, chaves privadas ou IPs privados.

**Limpeza de temporários**:
- Executado `./scripts/cleanup-tmp.sh --dry-run`.
- Limpeza real **não executada** para preservar artefatos de diagnóstico D16 e logs recentes necessários para continuidade.

---
