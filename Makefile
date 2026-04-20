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

## Remove arquivos gerados
clean:
	@rm -rf dist/ build/ __pycache__/ .pytest_cache/ *.egg-info/ .coverage htmlcov/
## Carrega variáveis MCP do .secrets/.env e orienta a abrir o VS Code
mcp:
	@bash scripts/load-mcp.sh

# ---------------------------------------------------------------------------
# Validação pós-migração via API REST do Chatwoot
# ---------------------------------------------------------------------------
VALIDATE_TIMEOUT     ?= 300
VALIDATE_URL_TIMEOUT ?= 1800
SAMPLE               ?= 5
PHONE                ?=
EMAIL                ?=
CHECK_URLS           ?=

.PHONY: validate-api-counts validate-api-deep validate-api

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
	    $(if $(CHECK_URLS),--check-urls)
	@echo "Outputs em .tmp/"

## Executa Fase 1 + Fase 2 (PHONE=... ou EMAIL=... obrigatorio para Fase 2)
validate-api: validate-api-counts validate-api-deep
