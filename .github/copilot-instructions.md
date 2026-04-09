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
| Docs técnicos | `docs/` |
| Python source | `src/` |
| Scripts | `scripts/` |

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
