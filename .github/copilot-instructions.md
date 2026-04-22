---
applyTo: "**"
---

# GitHub Copilot — Instruções do Projeto

**Projeto**: `enterprise-chathoot-migration` — Enterprise Chathoot Migration
**Domínio**: programming | **Linguagem**: python
**Regras completas**: `.copilot-rules-enterprise-chathoot-migration.md`
**Rituais de sessão**: `.github/prompts/session-start.prompt.md` | `session-end.prompt.md`
**Domain Profile ativo**: `.github/prompts/domain/devops-programming.prompt.md`

---

## 🚨 Regras P0 — CRÍTICO (nunca violar)

### 1. Criar/editar arquivos — NUNCA via terminal

| Operação | ✅ Ferramenta obrigatória |
|----------|--------------------------|
| Criar arquivo novo | `create_file` |
| Editar arquivo existente | `replace_string_in_file` (mín. 3 linhas de contexto) |
| Múltiplas edições | `multi_replace_string_in_file` |

❌ **PROIBIDO**: `cat > heredoc`, `echo >> arquivo`, `echo | tee arquivo`

---

### 2. Ler/buscar/listar arquivos — NUNCA via terminal

| Operação | ✅ Ferramenta obrigatória |
|----------|--------------------------|
| Ler conteúdo | `read_file` |
| Buscar texto | `grep_search` |
| Encontrar arquivos | `file_search` |
| Listar diretório | `list_dir` |
| Busca semântica | `semantic_search` |
| Verificar erros | `get_errors` |

❌ **PROIBIDO via terminal**: `cat`, `grep`, `find`, `ls`
✅ **`run_in_terminal` apenas para**: `git`, `make`, `pytest`, `pip install`, `docker`, `systemctl`

---

### 3. Mover/copiar/excluir arquivos — SEMPRE Python stdlib

```python
import shutil, logging
from pathlib import Path

log = logging.getLogger(__name__)
src, dst = Path("origem/arq.md"), Path("destino/arq.md")
dst.parent.mkdir(parents=True, exist_ok=True)
if src.exists():
    shutil.move(str(src), str(dst))
    log.info("✅ %s → %s", src, dst)
```

❌ **PROIBIDO**: `mv`, `cp`, `rm`, `mkdir` via terminal

---

### 4. Git commits — SEMPRE via arquivo de mensagem

```bash
echo "feat(escopo): descrição" > /tmp/commit.txt
./scripts/git-commit-with-file.sh /tmp/commit.txt
```

❌ **PROIBIDO**: `git commit -m "..."` direto

---

## 📋 Regras P1 — Organização

### 5. Pastas corretas

| Tipo | Localização |
|------|-------------|
| Docs de sessão | `docs/SESSIONS/YYYY-MM-DD/` |
| Docs de chat | `docs/SESSIONS/YYYY-MM-DD/CHAT-HH-MM.md/` |
| Docs técnicos | `docs/` |
| Python source | `src/` |
| Scripts | `scripts/` |
| Temporary files | `.tmp/` |

❌ **NUNCA** arquivos de sessão/doc na raiz

---

### 6. Documentos incrementais — nunca sobrescrever

`README.md`, `docs/INDEX.md`, `docs/TODO.md`, `docs/SESSIONS/*/DAILY_ACTIVITIES_*.md`,
`docs/SESSIONS/*/SESSION_REPORT_*.md`, `docs/SESSIONS/*/FINAL_STATUS_*.md` →
sempre **acrescentar**, nunca reescrever do zero.

---

### 7. Nomenclatura

| Tipo | Padrão |
|------|--------|
| Python | `snake_case.py` |
| Markdown | `SCREAMING_SNAKE.md` |
| JSON | `kebab-case.json` |
| Shell | `kebab-case.sh` |

---

## 🔒 Segurança

- Credenciais/tokens: NUNCA em arquivos versionados
- `mcp.json`: usar `${env:VAR_NAME}` ou `.secrets/.env`
- `.secrets/` está no `.gitignore` ✅

---

## ⚠️ Enforcement

```
❌ REGRA [N] violada: [nome]
Motivo: [explicação]
Correto: [alternativa válida]
```

*Gerado por scaffold.py em 2026-04-09T11:37:54Z — Projeto: enterprise-chathoot-migration*

## Active Technologies
- Python 3.12+ + SQLAlchemy 2.0.49 (Core + ORM), psycopg2-binary 2.9.11, alembic 1.18.4 (referência), ruff 0.15.10, black 26.3.1, pytest 9.0.3, pytest-cov (001-enterprise-chatwoot-migration)
- PostgreSQL 16.10 — `wfdb02.vya.digital:5432`, sem SSL (`sslmode=disable`). Dois bancos: `chatwoot_dev1_db` (read-only) e `chatwoot004_dev1_db` (read-write). (001-enterprise-chatwoot-migration)
- **Estratégia de migração**: MERGE (não incremental). Existem registros sobrepostos entre os dois bancos. Deduplicação por chave de negócio obrigatória antes de remapear IDs. Ver D3 na constitution. (2026-04-10)

## Recent Changes
- 001-enterprise-chatwoot-migration: Added Python 3.12+ + SQLAlchemy 2.0.49 (Core + ORM), psycopg2-binary 2.9.11, alembic 1.18.4 (referência), ruff 0.15.10, black 26.3.1, pytest 9.0.3, pytest-cov
- 001-enterprise-chatwoot-migration (2026-04-10): Estratégia alterada de incremental para merge. Registros sobrepostos identificados. Constitution v2.0.0 publicada. Debate D3 necessário antes de spec/plan/tasks revisados.
- 001-enterprise-chatwoot-migration (2026-04-22): ARQUITETURA CORRIGIDA: chatwoot_dev1_db=export chat.vya.digital (SOURCE); chatwoot004_dev1_db=export synchat.vya.digital (DEST). API SOURCE=chat.vya.digital; API DEST=vya-chat-dev.vya.digital (NÃO synchat). D7 debate revisado com migration gap confirmado: conversa src_conv_id=62363/display_id=1093 (inbox_id=125, account=1/Vya Digital, 14/11/2025) NÃO foi migrada. Scripts: app/12_diagnostico_marcos.py, app/14_verificar_conv_marcos.py. Make targets: diagnose-agent, verify-marcus-conv.
