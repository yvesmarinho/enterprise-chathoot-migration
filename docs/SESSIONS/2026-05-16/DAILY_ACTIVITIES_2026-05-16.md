# 📋 Daily Activities — 2026-05-16 (Sessão 16)

**Branch**: `001-enterprise-chatwoot-migration`
**Session Start**: 2026-05-16 14:10
**Focus**: Execução de migração em produção (14:00-20:00 BRT)

---

## Atividades

<!-- Blocos de atividade serão adicionados incrementalmente durante a sessão -->
<!-- Formato obrigatório: template canônico com separador --- e campos estruturados -->

---

### Session Initialization

**14:10 — ✅ Completo**

**Objetivo**: Inicializar sessão de trabalho para 2026-05-16, executar ritual completo de início de sessão

**Contexto**: Dia da migração em produção (14:00 BRT). Runbook e checklist completos preparados na Sessão 15.

**Passos executados**:
1. ✅ **Passo 1** — Verificação MCP Config (.vscode/mcp.json)
   - memory ✅ | sequential-thinking ✅ | filesystem ✅ | github ✅

2. ✅ **Passo 2** — Recuperação de contexto
   - docs/TODO.md (status: 🟢 PRONTO PARA PRODUÇÃO)
   - docs/INDEX.md (última sessão: 2026-05-15)
   - docs/SESSIONS/2026-05-15/DAILY_ACTIVITIES_2026-05-15.md
   - docs/SESSIONS/2026-05-15/SESSION_RECOVERY_2026-05-15.md
   - docs/SESSIONS/2026-05-13/FINAL_STATUS_2026-05-13.md

3. ✅ **Passo 3** — Carregamento de regras
   - .github/copilot-instructions.md (100 linhas, P0: ferramentas obrigatórias)
   - .copilot-rules-enterprise-chatwoot-migration.md (200 linhas, regras específicas)

4. ✅ **Passo 4** — Security scan
   - 🟢 **LIMPO** — nenhum arquivo sensível fora de .secrets/
   - .secrets/ está no .gitignore ✅
   - Nenhum .env*, *.key, *.pem versionado ✅
   - Pre-commit hook de segurança presente ✅

5. ✅ **Passo 5** — Git status
   - Branch: 001-enterprise-chatwoot-migration (ahead of origin by 1 commit)
   - Working tree: **clean**
   - Last commit: cda13d5 (docs(session15): Preparação completa para migração em produção 16/05/2026)
   - ⚠️ Sugestão: `git push` antes de iniciar trabalho

6. ✅ **Passo 6** — Documentos de sessão criados
   - SESSION_RECOVERY_2026-05-16.md
   - DAILY_ACTIVITIES_2026-05-16.md (este arquivo)

**Resultado**:
- ✅ Contexto recuperado: Sessão 15 focada em preparação para produção
- ✅ MCP configurado corretamente (4 servidores ativos)
- ✅ Regras P0 carregadas e ativas
- 🟢 Security: LIMPO
- ✅ Git: working tree clean (1 commit ahead)

---

### ✅ [PROD-1] — Refactoring env vars conexão DB (`app/db.py`)

**Horário**: ~14:30 | **Status**: ✅ Concluído

**Contexto**: Credenciais de conexão estavam hardcodadas. Necessário parametrizar via env vars para suportar execução em diferentes ambientes (dev/prod) e via container Docker.

**Artefatos modificados**:
| Arquivo | O que mudou |
|---------|-------------|
| `app/db.py` | Refatorado para exigir `MIGRATION_SOURCE_KEY` e `MIGRATION_DEST_KEY` como env vars; lança `KeyError` descritivo com chaves disponíveis se não definidas |

**Destaques**:
- Todas as chaves disponíveis: `chatwoot_dev`, `chatwoot004_dev`, `vya-chat-dev`, `chat-vya-digital` (SOURCE prod), `synchat-vya-digital` (DEST prod)
- Scripts em `app/` herdam automaticamente (importam `db.py`)
- Exporta: `_DB_SOURCE`, `_DB_DEST`, `get_conn()`, `src()`, `dst()`, `cur()`

---

### ✅ [PROD-2] — Validação SOURCE prod + criação de 4 usuários ausentes no DEST

**Horário**: ~15:00 | **Status**: ✅ Concluído

**Contexto**: Executadas validações SOURCE (`chat-vya-digital`) para account Unimed Guaxupé (account_id=25). Descobertos 4 usuários presentes no SOURCE mas ausentes no DEST prod (`synchat-vya-digital`).

**Artefatos criados**:
| Arquivo | O que mudou |
|---------|-------------|
| `.tmp/create_missing_users.py` | Script criado e executado para copiar 4 usuários do SOURCE → DEST |

**Usuários criados no DEST**:
- `gabriel.sa@vya.digital` → dest_id=358 (role=1)
- `juliana.ferreira@unimedguaxupe.coop.br` → dest_id=359 (role=1)
- `emoonlit@gmail.com` → dest_id=360 (role=1)
- `vya@vya.digital` → dest_id=361 (role=1)

**Destaques**: Senha copiada via bcrypt (funciona cross-DB), `pubsub_token` gerado único, vinculados a `account_id=45` (DEST prod).

---

### ✅ [PROD-3] — Adaptação infraestrutura Docker para produção + daemon mode

**Horário**: ~15:30 | **Status**: ✅ Concluído

**Contexto**: Container Docker existia para dev mas RUNBOOK não o utilizava (identificado em `docs/avaliação_do_processo.md`). Adaptado para produção com modo daemon (`docker compose run -d`).

**Artefatos modificados**:
| Arquivo | O que mudou |
|---------|-------------|
| `docker/docker-compose.yml` | Adicionado `MIGRATION_SOURCE_KEY`/`MIGRATION_DEST_KEY` com defaults de prod; `ACCOUNT_NAME` default → "Unimed Guaxupé" |
| `docker/entrypoint.sh` | Bloco de validação das env vars; banner de produção; default ACCOUNT_NAME = "Unimed Guaxupé" |
| `docker/deploy-to-wfdb01.sh` | `--run` agora usa `docker compose run -d` (daemon); nome de container auto-gerado; propagação das env vars; defaults de prod |
| `docs/RUNBOOK_MIGRACAO_PRODUCAO_2026-05-16.md` | Atualizado para usar container como método primário (FASE 1.1 Opção A); `--account-id 45` corrigido; env vars de prod documentadas |

**Destaques**:
- Container name: `chatwoot-migrator-unimed_guaxup`
- DEST prod account_id = **45** (não 46 — confirmado via API)
- Migration é idempotente: re-execução segura

---

### ✅ [PROD-4] — Deploy e execução em wfdb01 (container daemon)

**Horário**: ~16:00 | **Status**: ✅ Concluído

**Contexto**: Executado `./docker/deploy-to-wfdb01.sh --build --run` — rsync código + .secrets → build imagem Docker → container iniciado em modo daemon no wfdb01.

**Resultado**:
- ✅ rsync: 216 arquivos enviados (181 KB → 9.6 MB repo)
- ✅ .secrets sincronizado (chmod 600)
- ✅ Docker build: `chatwoot-migration:latest` (sha256:`6310957726e5`) — 10 steps, ~45s
- ✅ Container `chatwoot-migrator-unimed_guaxup` (ID: `9f13b2337b26`) iniciado em background

**Comandos para acompanhar**:
```bash
fwknop --rc-file ~/.fwknoprc -n wfdb01 && sleep 3
ssh -p 5010 archaris@wfdb01.vya.digital 'docker logs -f chatwoot-migrator-unimed_guaxup'
```

---

### ⏳ [PROD-5] — Validações pós-migração (pendente)

**Horário**: TBD | **Status**: ⏳ Pendente

**Pendentes para próxima sessão** (ou após container concluir):
- `uv run python app/02_verificar.py "Unimed Guaxupé"`
- `uv run python app/06_verificar_erros.py "Unimed Guaxupé"`
- `uv run python scripts/check_s3_attachments.py --instance synchat-vya-digital --account-id 45 --limit 100`
- Validação API (FASE 3 do RUNBOOK)
- Migração dos demais accounts (Sol Copernico, Unimed Poços PF/PJ, Vya Digital)
- 🔄 Aguardando declaração de domínio e objetivo pelo usuário (Passo 7)

**Status**: ✅ Completo — Aguardando Passo 7 (Declarar Domínio e Objetivo)

---
