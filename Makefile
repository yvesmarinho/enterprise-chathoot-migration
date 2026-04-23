# Makefile — Enterprise Chathoot Migration
# Gerado por scaffold.py em 2026-04-09T11:37:54Z

.PHONY: help init dev build test lint format clean

## Mostra esta ajuda
help:
	@grep -E '^## ' Makefile | sed 's/## //'

## [DEPRECATED] — use: uv run scripts/scaffold.py
init:
	@echo ""
	@echo " ⚠️  Para criar/configurar o projeto, use diretamente:"
	@echo "      uv run scripts/scaffold.py"
	@echo "      python scripts/scaffold.py"
	@echo ""

## Instala dependências
install-deps:
	@echo "Instalando dependências..."

## Inicia servidor de desenvolvimento
dev:
	@echo "Iniciando desenvolvimento..."

## Build de produção
build:
	@echo "Buildando..."

## Executa testes
test:
	@echo "Executando testes..."

## Lint do código
lint:
	@echo "Linting..."

## Formata código
format:
	@echo "Formatando..."

## Remove arquivos gerados e limpa .tmp/
clean:
	@rm -rf dist/ build/ __pycache__/ .pytest_cache/ *.egg-info/ .coverage htmlcov/
	@bash scripts/cleanup-tmp.sh --verbose
## Carrega variáveis MCP do .secrets/.env e orienta a abrir o VS Code
mcp:
	@bash scripts/load-mcp.sh

# ---------------------------------------------------------------------------
# Validação pós-migração via API REST do Chatwoot
# ---------------------------------------------------------------------------
VALIDATE_TIMEOUT     ?= 600
VALIDATE_URL_TIMEOUT ?= 1800
SAMPLE               ?= 5
PHONE                ?=
EMAIL                ?=
CHECK_URLS           ?=
MAX_MSGS             ?= 50

.PHONY: validate-api-counts validate-api-deep validate-api validate-hash

## Fase 1 — contagens macro SOURCE vs DEST vs API (seguro para CI)
validate-api-counts:
	@test -f .secrets/generate_erd.json || \
	    { echo "ERRO: .secrets/generate_erd.json nao encontrado"; exit 1; }
	@timeout $(VALIDATE_TIMEOUT) \
	    python app/10_validar_api.py summary
	@echo "Outputs em .tmp/"

## Fase 2 — deep scan (auto-amostra padrão; ou PHONE='+55...' / EMAIL='foo@bar.com')
validate-api-deep:
	@test -f .secrets/generate_erd.json || \
	    { echo "ERRO: .secrets/generate_erd.json nao encontrado"; exit 1; }
	@timeout $(if $(CHECK_URLS),$(VALIDATE_URL_TIMEOUT),$(VALIDATE_TIMEOUT)) \
	    python app/10_validar_api.py deep \
	    $(if $(PHONE),--contact-phone "$(PHONE)") \
	    $(if $(EMAIL),--contact-email "$(EMAIL)") \
	    $(if $(SAMPLE),--sample-size "$(SAMPLE)") \
	    $(if $(MAX_MSGS),--max-msgs-per-conv "$(MAX_MSGS)") \
	    $(if $(CHECK_URLS),--check-urls)
	@echo "Outputs em .tmp/"

## Executa Fase 1 + Fase 2 (PHONE=... ou EMAIL=... obrigatorio para Fase 2)
validate-api: validate-api-counts validate-api-deep

## Validação de integridade por hash MD5 (contacts, conversations, messages, attachments)
validate-hash:
	@test -f .secrets/generate_erd.json || \
	    { echo "ERRO: .secrets/generate_erd.json nao encontrado"; exit 1; }
	@timeout $(VALIDATE_TIMEOUT) \
	    python app/11_validar_hash.py $(if $(TABLES),--tables $(TABLES)) \
	    $(if $(ACCOUNTS),--accounts $(ACCOUNTS)) \
	    $(if $(SAVE_PARQUET),--save-parquet)
	@echo "Outputs em .tmp/"

# ---------------------------------------------------------------------------
# Diagnóstico D7 — visibilidade pós-migração por agente
# ---------------------------------------------------------------------------
DIAGNOSE_EMAIL ?= marcos.andrade@vya.digital
DIAGNOSE_TIMEOUT ?= 120

.PHONY: diagnose-agent

## D7 — Diagnóstico de visibilidade de agente pós-migração (DIAGNOSE_EMAIL=user@domain)
diagnose-agent:
	@test -f .secrets/generate_erd.json || \
	    { echo "ERRO: .secrets/generate_erd.json nao encontrado"; exit 1; }
	@timeout $(DIAGNOSE_TIMEOUT) \
	    python app/12_diagnostico_marcos.py --email "$(DIAGNOSE_EMAIL)"
	@echo "Outputs em .tmp/"

# ---------------------------------------------------------------------------
# Verificação da conversa de 14/11/2025 — SOURCE vs DEST (D7 v2)
# ---------------------------------------------------------------------------
CONV_DATE     ?= 2025-11-14
CONV_USER_ID  ?= 88
CONV_WINDOW   ?= 3
CONV_TIMEOUT  ?= 15

.PHONY: verify-marcus-conv

## D7v2 — Verifica conversa de Marcos (CONV_DATE=YYYY-MM-DD) via SOURCE+DEST DB+API
verify-marcus-conv:
	@test -f .secrets/generate_erd.json || \
	    { echo "ERRO: .secrets/generate_erd.json nao encontrado"; exit 1; }
	@timeout 120 \
	    python app/14_verificar_conv_marcos.py \
	        --user-id  "$(CONV_USER_ID)" \
	        --date     "$(CONV_DATE)" \
	        --window-days "$(CONV_WINDOW)" \
	        --api-timeout "$(CONV_TIMEOUT)"
	@echo "Outputs em .tmp/"

# ---------------------------------------------------------------------------
# Diagnóstico D7 — inbox gap (inbox_id=125 não migrado)
# ---------------------------------------------------------------------------
DIAG_INBOX_ID ?= 125

.PHONY: diagnose-inbox-gap

## D7-G — Diagnóstico do gap: por que inbox SOURCE não foi migrado (DIAG_INBOX_ID=125)
diagnose-inbox-gap:
	@test -f .secrets/generate_erd.json || \
	    { echo "ERRO: .secrets/generate_erd.json nao encontrado"; exit 1; }
	@timeout 120 \
	    python app/15_diagnostico_inbox125.py --inbox-id "$(DIAG_INBOX_ID)"
	@echo "Outputs em .tmp/"

# ---------------------------------------------------------------------------
# Diagnóstico D7 — visibilidade Marcus nas conversas migradas
# ---------------------------------------------------------------------------
MARCUS_SRC_CONV_IDS ?= 62361,62362,62363
MARCUS_DEST_INBOX_ID ?= 521
MARCUS_DEST_USER_ID  ?= 88

.PHONY: diagnose-marcus-visibility

## D7-V — Diagnóstico de visibilidade: por que Marcus não vê as conversas migradas
diagnose-marcus-visibility:
	@test -f .secrets/generate_erd.json || \
	    { echo "ERRO: .secrets/generate_erd.json nao encontrado"; exit 1; }
	@timeout 120 \
	    python app/16_diagnostico_visibilidade_marcus.py \
	        --source-conv-ids "$(MARCUS_SRC_CONV_IDS)" \
	        --dest-inbox-id   "$(MARCUS_DEST_INBOX_ID)" \
	        --dest-user-id    "$(MARCUS_DEST_USER_ID)"
	@echo "Outputs em .tmp/"
