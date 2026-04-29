# D5 — DEBATE: Especificação de `app/10_validar_api.py`

**Data**: 2026-04-20
**Revisado em**: 2026-04-20 (v2 — validação profunda)
**Participantes**: @system-engineer, @dba-sql-expert, @python-expert, @devops-expert, @chatwoot-expert
**Contexto**: O pipeline principal (`python -m src.migrar`) concluiu com exit code 0 em 2026-04-20, migrando 313.539 rows com 0 falhas. Precisamos validar via API REST do Chatwoot (synchat.vya.digital) — não apenas contagens, mas a **integridade profunda dos dados** importados, incluindo conversas, mensagens e links de anexos.

---

## Questão Central (v2 — revisada)

Como deve ser o script `app/10_validar_api.py` que:

1. **Valida contagens macro** por account — SOURCE DB vs API DEST (conversations, contacts)
2. **Valida dados profundamente** — busca dados reais de uma amostra de contatos e verifica:
   - Todas as conversas do contato no SOURCE estão presentes no DEST via API
   - Cada conversa contém as mensagens correspondentes (contagem + campos críticos)
   - Cada mensagem com anexo tem o link (`data_url`) acessível via HTTP
3. **Gera o máximo de informação em logs** para avaliação futura dos códigos de exportação

Seguindo os padrões do projeto: Python 3.12+, `logging` estruturado (nunca `print`), saídas CSV+JSON em `.tmp/`, credenciais **exclusivamente** via `.secrets/generate_erd.json` — **nunca hardcoded, nunca em logs**.

---

## Contexto Técnico

| Item | Valor |
|------|-------|
| SOURCE DB | `chatwoot_dev1_db` @ `wfdb02.vya.digital:5432` (read-only) |
| DEST DB | `chatwoot004_dev1_db` @ `wfdb02.vya.digital:5432` (read-write) |
| API Chatwoot | `https://synchat.vya.digital` |
| Token API | em `.secrets/generate_erd.json` → chave `synchat.api_key` — SuperAdmin, HTTP 200 |
| Mapeamento src→dest | `migration_state` table no DEST (colunas: `tabela`, `id_origem`, `id_destino`, `status`, `migrated_at`) |

### Resultados do pipeline (referência)

| Tabela | Migrated | Skipped |
|--------|----------|---------|
| accounts | 3 | 2 |
| inboxes | 21 | 0 |
| users | 8 | 104 |
| contacts | 5.966 | 32.902 |
| contact_inboxes | 7.228 | 1.295 |
| conversations | 36.016 | 5.727 |
| messages | 239.439 | 70.716 |
| attachments | 22.841 | 4.048 |

---

## Perspectiva 1 — @system-engineer: Arquitetura (v2)

### Duas Fases, não um script monolítico de contagens

O script evolui para **dois modos de execução** (`summary` e `deep`) — sem criar subcomandos artificiais:

| Modo | Descrição | Tempo estimado |
|------|-----------|---------------|
| `summary` | Contagens macro SOURCE DB vs DEST DB vs API por account | < 30s |
| `deep` | Validação profunda por amostra de contatos — conversas + mensagens + links | 1-30min (depende de `--check-urls`) |

O separador entre modos é o `argparse subcommand`:
```
python app/10_validar_api.py summary
python app/10_validar_api.py deep --sample-size 5 [--check-urls]
```

### Fronteiras de dados (ampliadas)

| Fronteira | Modo | Responsabilidade |
|-----------|------|-----------------|
| SOURCE DB | summary + deep | Verdade canônica — contagens e dados de origem |
| DEST DB | summary + deep | Dados pós-migração para cross-check DB-a-DB |
| DEST API | summary + deep | Acessibilidade real via Chatwoot |
| HTTP (links) | deep (opcional) | Verificação de `data_url` de attachments |
| Persistência | ambos | JSON + CSV + LOG em `.tmp/` |

### Funções por responsabilidade (ampliadas)

```
# COMPARTILHADAS
_load_api_config()             → ApiConfig          # .secrets/generate_erd.json["synchat"]
_probe_api()                   → None               # GET /profile, fail fast
_api_get()                     → dict               # thin wrapper, header api_access_token
_fetch_account_map()           → dict[int,int]      # migration_state src→dest accounts
_setup_logging()               → None               # duplo stdout+arquivo, nivel por --verbose

# MODO summary
_fetch_source_counts()         → dict[int, Counts]  # SOURCE DB por src_account_id
_fetch_dest_db_counts()        → dict[int, Counts]  # DEST DB por dest_account_id
_fetch_api_counts()            → dict[int, Counts]  # API DEST /conversations/meta + /contacts
_build_summary_report()        → SummaryReport      # PURA: sem I/O
_write_summary_outputs()       → tuple[Path, Path]  # JSON + CSV

# MODO deep
_select_sample_contacts()      → list[SampleContact]  # N contatos com conversas+msgs+anexos
_deep_scan_db()                → ContactDeepResult    # SOURCE vs DEST DB por contato
_deep_scan_api_contact()       → ContactApiCheck      # GET /contacts/{id}
_deep_scan_api_conversations() → list[ConvApiCheck]   # GET /contacts/{id}/conversations
_check_url()                   → AttachmentUrlCheck   # HEAD data_url — sem token na URL
_build_deep_report()           → DeepReport           # PURA: sem I/O
_write_deep_outputs()          → tuple[Path, Path]    # JSON + CSV expandido
```

**Invariante crítica**: `_build_summary_report()` e `_build_deep_report()` são **funções puras** — recebem dados já coletados, retornam dataclass. Zero I/O. Isso isola lógica de cálculo de falhas de rede/banco.

### Seleção da Amostra para modo `deep`

**Critério**: máximo signal com mínimo de execução. Contatos com conversas + mensagens + anexos no SOURCE:

```sql
-- [SOURCE] Top-N contatos ricos por account, ordenados por richness_score
WITH contact_richness AS (
    SELECT
        c.id              AS src_contact_id,
        c.account_id,
        COUNT(DISTINCT cv.id)  AS conv_count,
        COUNT(DISTINCT m.id)   AS msg_count,
        COUNT(DISTINCT a.id)   AS att_count,
        COUNT(DISTINCT cv.id) * 5 + COUNT(DISTINCT a.id) * 10 + COUNT(DISTINCT m.id)
                               AS richness_score
    FROM contacts c
    INNER JOIN conversations cv ON cv.contact_id = c.id AND cv.account_id = c.account_id
    INNER JOIN messages      m  ON m.conversation_id = cv.id
    INNER JOIN attachments   a  ON a.message_id = m.id
    WHERE c.account_id IN :src_account_ids
      AND (c.phone_number IS NOT NULL OR c.email IS NOT NULL)
    GROUP BY c.id, c.account_id
    HAVING COUNT(DISTINCT cv.id) >= 2
)
SELECT src_contact_id, account_id, conv_count, msg_count, att_count
FROM contact_richness
ORDER BY account_id, richness_score DESC
LIMIT :n;
```

**N recomendado**: 10 total (2 por account). Justificativa:
- 10 contatos × 5 conversas × 5 msgs × 3 anexos = 375 HEAD requests no pior caso
- Sem `--check-urls`: < 60s. Com `--check-urls`: < 30min na prática (S3/CDN responde em <500ms)
- N máximo prático: 20 sem links, 10 com links

### Fluxo de execução — modo `deep`

```
1. _load_api_config()
2. _probe_api()                      ← fail-fast se 401/403
3. _fetch_account_map(dest_conn)
4. _select_sample_contacts(src, N)   ← critério richness_score
5. Para cada contato da amostra:
   a. _deep_scan_db(src, dest, contact)         ← SOURCE vs DEST DB
   b. _deep_scan_api_contact(cfg, dest_acc, contact)
   c. Para cada conversa do contato:
      - _deep_scan_api_conversations(cfg, dest_acc, contact_id)
      - Para cada mensagem com attachment:
        - _check_url(data_url) se --check-urls
6. _build_deep_report(all_results)   ← PURO
7. _write_deep_outputs(report)
8. log SUMMARY + sys.exit(code)
```

### Pontos de Falha e Resiliência (ampliados)

| Ponto | Falha | Estratégia |
|-------|-------|-----------|
| Token inválido | 401 no probe | `sys.exit(1)` imediato — sem sentido continuar |
| Account não existe na API | 404 | `api_status="not_found"`, continua próxima account |
| Contact não encontrado | 404 | `found_in_api=False`, continua |
| Conversas do contact > 20 | Limite hardcoded da API | Logar `WARNING`, comparar os 20 retornados |
| Timeout por request | `URLError` | per-item try/except, `error="timeout"`, continua |
| Link de attachment 403 | Token S3 expirado | `verdict="forbidden"` — dado existe, link expirou |
| Link de attachment 404 | Arquivo deletado | `verdict="not_found"` — possível perda de dado |
| Rate limit API (429) | Improvável (<80 calls) | 1 retry após `sleep(5)`, exit code 3 se persistir |

---

## Perspectiva 2 — @dba-sql-expert: Queries SQL (v2)

### Query de mapeamento src→dest (âncora principal)

```sql
-- [DEST] Roda uma vez — obtém todos os account_id mapeados
SELECT
    ms.id_origem   AS src_account_id,
    ms.id_destino  AS dest_account_id,
    a.name         AS account_name,
    ms.status,
    ms.migrated_at
FROM migration_state ms
JOIN accounts a ON a.id = ms.id_destino
WHERE ms.tabela = 'accounts'
  AND ms.status = 'ok'
ORDER BY ms.id_origem;
```

> ⚠️ **Schema real**: colunas `id_origem` e `id_destino` (não `src_id`/`dest_id`).

### Contagens no SOURCE (modo summary)

```sql
-- Rodar 1x por tabela: contacts | conversations | messages | attachments
SELECT account_id, COUNT(*) AS total
FROM {table}
GROUP BY account_id
ORDER BY account_id;

-- Attachments sem account_id direto — via messages
SELECT m.account_id, COUNT(a.id) AS total
FROM attachments a
JOIN messages m ON m.id = a.message_id
GROUP BY m.account_id
ORDER BY m.account_id;
```

### Snapshot por account no DEST (modo summary)

```sql
-- [DEST] Snapshot completo com sanidade embutida
WITH account_snapshot AS (
    SELECT
        :dest_account_id AS account_id,
        (SELECT COUNT(*) FROM contacts      WHERE account_id = :dest_account_id) AS contacts,
        (SELECT COUNT(*) FROM conversations WHERE account_id = :dest_account_id) AS conversations,
        (SELECT COUNT(*) FROM messages      WHERE account_id = :dest_account_id) AS messages,
        (SELECT COUNT(*) FROM attachments   WHERE account_id = :dest_account_id) AS attachments,
        (SELECT COUNT(*) FROM conversations
         WHERE account_id = :dest_account_id
           AND (display_id IS NULL OR display_id = 0))    AS conv_display_id_invalido,
        (SELECT COUNT(*) FROM messages m
         WHERE m.account_id = :dest_account_id
           AND NOT EXISTS (
               SELECT 1 FROM conversations c WHERE c.id = m.conversation_id
           ))                                              AS messages_orphans
)
SELECT * FROM account_snapshot;
```

### Queries para modo `deep` — Validação por Contato

#### Cross-reference de um contato

```sql
-- [DEST] Busca dest_id dado src_contact_id
SELECT id_destino AS dest_contact_id, status, migrated_at
FROM migration_state
WHERE tabela = 'contacts'
  AND id_origem = :src_contact_id
  AND status = 'ok';
```

#### Conversas do contato no SOURCE

```sql
-- [SOURCE] Conversas com contagens de msgs e anexos
SELECT
    cv.id                                           AS src_conv_id,
    cv.display_id,
    cv.status,
    cv.inbox_id,
    cv.assignee_id,
    cv.created_at,
    COUNT(DISTINCT m.id)                            AS msg_count,
    COUNT(DISTINCT a.id)                            AS att_count
FROM conversations cv
LEFT JOIN messages   m ON m.conversation_id = cv.id
LEFT JOIN attachments a ON a.message_id = m.id
WHERE cv.contact_id  = :src_contact_id
  AND cv.account_id  = :src_account_id
GROUP BY cv.id, cv.display_id, cv.status, cv.inbox_id, cv.assignee_id, cv.created_at
ORDER BY cv.created_at DESC;
```

#### Cross-reference em lote de conversas

```sql
-- [DEST] Verifica quais src_conv_ids foram migrados
SELECT
    orig.id_source,
    ms.id_destino  AS dest_conv_id,
    ms.status,
    CASE
        WHEN ms.id_destino IS NULL        THEN 'NAO_MIGRADA'
        WHEN ms.status = 'ok'             THEN 'MIGRADA_OK'
        ELSE 'MIGRADA_COM_FALHA'
    END AS resultado
FROM UNNEST(:src_conv_ids::int[]) AS orig(id_source)
LEFT JOIN migration_state ms
       ON ms.id_origem = orig.id_source
      AND ms.tabela    = 'conversations';
```

#### Attachments de uma conversa — src→dest com status

```sql
-- [SOURCE] Etapa 1: listar attachments da conversa
SELECT
    a.id           AS src_att_id,
    a.message_id   AS src_msg_id,
    a.file_type,
    a.external_url AS url_source
FROM attachments a
JOIN messages m ON m.id = a.message_id
WHERE m.conversation_id = :src_conv_id;

-- [DEST] Etapa 2: cross-reference dos src_att_ids
SELECT
    orig.id_source             AS src_att_id,
    ms.id_destino              AS dest_att_id,
    att.external_url           AS url_dest,
    CASE
        WHEN ms.id_destino IS NULL           THEN 'NAO_MIGRADO'
        WHEN att.external_url IS NULL        THEN 'SEM_URL'
        WHEN TRIM(att.external_url) = ''     THEN 'URL_VAZIA'
        ELSE 'OK'
    END AS att_status
FROM UNNEST(:src_att_ids::int[]) AS orig(id_source)
LEFT JOIN migration_state ms
       ON ms.id_origem = orig.id_source
      AND ms.tabela    = 'attachments'
LEFT JOIN attachments att ON att.id = ms.id_destino;
```

> ⚠️ **Campo correto**: `external_url` (não `file_path` — não existe no schema Chatwoot).

#### Queries de sanidade (modo summary)

```sql
-- [DEST] display_id duplicado (deve retornar 0 linhas)
SELECT account_id, display_id, COUNT(*) AS n
FROM conversations
GROUP BY account_id, display_id
HAVING COUNT(*) > 1;

-- [DEST] pubsub_token duplicado em contacts (deve retornar 0 linhas)
WITH dups AS (
    SELECT pubsub_token, COUNT(*) AS n
    FROM contacts
    WHERE pubsub_token IS NOT NULL AND pubsub_token <> ''
    GROUP BY pubsub_token
    HAVING COUNT(*) > 1
)
SELECT COUNT(*) AS tokens_duplicados FROM dups;

-- [DEST] Orphan messages
SELECT COUNT(*) AS orphan_messages
FROM messages m
WHERE NOT EXISTS (
    SELECT 1 FROM conversations c WHERE c.id = m.conversation_id
);

-- [DEST] Distribuição de status por account
SELECT status, COUNT(*) AS total
FROM conversations
WHERE account_id = :dest_account_id
GROUP BY status ORDER BY status;
```

---

## Perspectiva 3 — @python-expert: Implementação Python (v2)

### Dataclasses — camada API aditiva sobre camada DB

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

@dataclass(frozen=True)
class ApiConfig:
    base_url: str
    api_key: str          # nunca exposto em log INFO
    timeout_s: int = 10

@dataclass
class ContactApiCheck:
    """Validação do contato via GET /contacts/{id}."""
    dest_account_id: int
    dest_contact_id: int
    api_found: bool
    api_name: str = ""
    name_match: bool = False
    email_match: bool = False
    phone_match: bool = False
    api_status: int = 0
    api_error: str = ""

@dataclass
class ConversationApiCheck:
    """Validação da conversa via API."""
    src_conv_id: int
    dest_conv_id: int | None
    display_id: int | None
    api_found: bool
    status_src: str = ""
    status_dest: str = ""
    status_match: bool = False
    messages_api_count: int = -1
    messages_db_count: int = -1
    api_error: str = ""

@dataclass
class AttachmentUrlCheck:
    """Verificação HTTP HEAD do link do anexo."""
    src_att_id: int
    dest_att_id: int | None
    url_preview: str = ""     # primeiros 80 chars — nunca URL completa em INFO
    url_accessible: bool = False
    http_status: int = 0
    http_content_type: str = ""
    verdict: str = "not_checked"  # ok | not_found | forbidden | timeout | no_url
    error: str = ""

@dataclass
class SampleContactResult:
    """Resultado completo de um contato na fase deep."""
    src_id: int
    dest_id: int | None
    dest_account_id: int
    api_check: ContactApiCheck | None = None
    conversation_checks: list[ConversationApiCheck] = field(default_factory=list)
    attachment_checks: list[AttachmentUrlCheck] = field(default_factory=list)
```

### Cliente HTTP — `urllib.request` (sem nova dependência)

```python
import urllib.request
import urllib.error
import json

class ApiError(Exception):
    def __init__(self, status: int, url: str) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status

def _api_get(url: str, cfg: ApiConfig) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={"api_access_token": cfg.api_key},
    )
    try:
        with urllib.request.urlopen(req, timeout=cfg.timeout_s) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        raise ApiError(exc.code, url) from exc
    except urllib.error.URLError as exc:
        raise ApiError(0, url) from exc
```

### Verificação de link de attachment

```python
import re

_TOKEN_PARAMS = re.compile(
    r"(X-Amz-Credential|X-Amz-Signature|X-Amz-Security-Token"
    r"|token|access_token|sig|signature)=[^&]+",
    re.IGNORECASE,
)

def _redact_url(url: str) -> str:
    """Remove query params com tokens de URLs para log seguro."""
    return _TOKEN_PARAMS.sub(r"\1=***", url)

def _check_url(url: str, timeout_s: int = 8) -> AttachmentUrlCheck:
    safe_preview = _redact_url(url)[:80]
    req = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return AttachmentUrlCheck(
                src_att_id=0,   # preenchido pelo chamador
                dest_att_id=None,
                url_preview=safe_preview,
                url_accessible=True,
                http_status=resp.status,
                http_content_type=resp.headers.get("Content-Type", ""),
                verdict="ok",
            )
    except urllib.error.HTTPError as exc:
        verdicts = {403: "forbidden", 404: "not_found", 410: "gone", 429: "rate_limited"}
        return AttachmentUrlCheck(
            src_att_id=0, dest_att_id=None,
            url_preview=safe_preview,
            http_status=exc.code,
            verdict=verdicts.get(exc.code, f"http_{exc.code}"),
            error=f"HTTPError:{exc.code}",
        )
    except urllib.error.URLError as exc:
        return AttachmentUrlCheck(
            src_att_id=0, dest_att_id=None,
            url_preview=safe_preview,
            verdict="timeout" if "timed out" in str(exc) else "network_error",
            error=str(exc)[:120],
        )
```

### Estrutura de log — níveis e o que expor

| Nível | Evento | O que logar |
|-------|--------|-------------|
| `INFO` | Contato | `src_id=%d dest_id=%s name_match=%s email_match=%s phone_match=%s` |
| `INFO` | Conversa | `src_id=%d dest_id=%s status_match=%s msgs_src=%d msgs_dest=%d` |
| `INFO` | Attachment | `src_id=%d dest_id=%s verdict=%s http=%d url_preview=%.80s` |
| `WARNING` | Campo divergente | `FIELD contact.name src=%r dest=%r` |
| `WARNING` | Contact não encontrado | `API contact not found dest_id=%d account_id=%d` |
| `DEBUG` | Row completa do DB | `CONTACT src_full={...}` — apenas no `.log`, nunca stdout |
| `DEBUG` | Resposta API completa | JSON da resposta — apenas no `.log` |
| `ERROR` | Exceção inesperada | `msg=%s` sem stack trace completo no INFO |

**Nunca logar**: `api_key`, `api_access_token`, query strings com `token=`, `X-Amz-Signature`.

### Parâmetros CLI (argparse expandido)

```
summary                    Fase 1 — contagens macro por account
deep                       Fase 2 — validação profunda por amostra
  --sample-size N          Número de contatos para amostra (default: 5)
  --check-urls             Ativa verificação HTTP dos links de attachment
  --contact-phone PHONE    Valida contato específico por phone (alternativo ao sample)
  --contact-email EMAIL    Valida contato específico por email
  --verbose                Nível de log DEBUG
  --timeout S              Timeout HTTP em segundos (default: 10)
```

### JSON de saída — modo `deep`

```json
{
  "timestamp": "20260420_173000",
  "mode": "deep",
  "sample_size": 5,
  "check_links": true,
  "summary": {
    "contacts_sampled": 5,
    "contacts_found_in_api": 5,
    "conversations_sampled": 23,
    "conversations_found": 23,
    "messages_sampled": 147,
    "messages_found": 145,
    "attachments_checked": 38,
    "attachments_ok": 35,
    "attachments_not_found": 2,
    "attachments_forbidden": 1,
    "attachments_timeout": 0
  },
  "contacts": [
    {
      "src_id": 1234,
      "dest_id": 5678,
      "dest_account_id": 47,
      "found_in_api": true,
      "api_status": 200,
      "name_match": true,
      "email_match": true,
      "phone_match": true,
      "conversations": [
        {
          "src_id": 111,
          "dest_id": 222,
          "display_id_src": 15,
          "display_id_dest": 15,
          "status_match": true,
          "messages_src_count": 12,
          "messages_dest_count": 12,
          "attachments": [
            {
              "src_id": 501,
              "dest_id": 1002,
              "verdict": "ok",
              "http_status": 200,
              "url_preview": "https://synchat.vya.digital/rails/active_storage/..."
            }
          ]
        }
      ]
    }
  ]
}
```

---

## Perspectiva 4 — @devops-expert: Operacionalização (v2)

### Dois targets Makefile separados

```makefile
VALIDATE_TIMEOUT     ?= 300
VALIDATE_URL_TIMEOUT ?= 1800
PHONE                ?=
EMAIL                ?=
SAMPLE               ?= 5
CHECK_URLS           ?=

.PHONY: validate-api-counts validate-api-deep validate-api

validate-api-counts: ## Fase 1 — contagens macro por account (seguro para CI)
	@test -f .secrets/generate_erd.json || \
	    { echo "ERRO: .secrets/generate_erd.json nao encontrado"; exit 1; }
	@python app/10_validar_api.py summary
	@echo "Outputs em .tmp/"

validate-api-deep: ## Fase 2 — deep scan por amostra (PHONE=... ou EMAIL=... ou --sample-size)
	@test -f .secrets/generate_erd.json || \
	    { echo "ERRO: .secrets/generate_erd.json nao encontrado"; exit 1; }
	@timeout $(if $(CHECK_URLS),$(VALIDATE_URL_TIMEOUT),$(VALIDATE_TIMEOUT)) \
	    python app/10_validar_api.py deep \
	    --sample-size "$(SAMPLE)" \
	    $(if $(PHONE),--contact-phone "$(PHONE)") \
	    $(if $(EMAIL),--contact-email "$(EMAIL)") \
	    $(if $(CHECK_URLS),--check-urls)
	@echo "Outputs em .tmp/"

validate-api: validate-api-counts validate-api-deep ## Executa as duas fases
```

### Exit codes revisados (3 dimensões)

| Código | Significado |
|--------|-------------|
| `0` | Tudo ok — contagens e links conferem |
| `1` | Erro fatal — DB inacessível, token inválido, exceção Python |
| `2` | Contagens divergem — delta ≠ 0 em algum account/contato |
| `3` | Links quebrados — `verdict=not_found` em algum attachment verificado |
| `4` | Contagens divergem E links quebrados |

### Segurança — URLs de attachment com tokens S3

URLs de Active Storage / S3 pre-signed contêm parâmetros como `X-Amz-Signature`. Proteções:

1. **`_redact_url()`** — obrigatório antes de qualquer `log.*` com URL
2. **JSON de saída** — usar `url_preview` (80 chars redactados), nunca `url_completa`
3. **Flag `--redact-urls`** (opcional) — omite completamente a URL do JSON

### Observabilidade — métricas para avaliação futura

| Métrica | Por quê importa |
|---------|----------------|
| `delta_messages` por account | Principal indicador de perda de dados |
| `messages_content_match %` | Detecta truncamento ou encoding corrompido |
| `attachments_ok / attachments_checked` | Taxa de links válidos |
| `attachments_not_found` | Possível perda de arquivo na migração |
| `conversations_found / conversations_total` | Taxa de mapeamento src→dest |
| `duration_s` por fase | Tendência de degradação com crescimento do banco |

---

## Perspectiva 5 — @chatwoot-expert: API Chatwoot (v2)

### Endpoints completos para Fase 2

| Objetivo | Endpoint | Nota crítica |
|----------|----------|-------------|
| Autenticar | `GET /api/v1/profile` | Valida token — sempre o primeiro call |
| Contagem conversations | `GET /api/v1/accounts/{id}/conversations/meta?status=all` | `data.all_count` |
| Contagem contacts | `GET /api/v1/accounts/{id}/contacts?page=1` | `meta.count` |
| Buscar contact por ID | `GET /api/v1/accounts/{id}/contacts/{contact_id}` | `id` = interno da tabela |
| Buscar contact por phone | `GET /api/v1/accounts/{id}/contacts/search?q={phone}` | `+` → `%2B` na URL |
| Conversas do contato | `GET /api/v1/accounts/{id}/contacts/{contact_id}/conversations` | **LIMITE 20, sem paginação** |
| Detalhes da conversa | `GET /api/v1/accounts/{id}/conversations/{display_id}` | usa `display_id`, não id interno |
| Messages da conversa | `GET /api/v1/accounts/{id}/conversations/{display_id}/messages` | `payload[]` |
| Attachments da conversa | `GET /api/v1/accounts/{id}/conversations/{display_id}/attachments` | até 100/página |
| Verificar URL de attachment | `HEAD {data_url}` | sem token; Active Storage redirect |

### Autenticação — header correto

```bash
# CORRETO — header api_access_token (valor via .secrets/generate_erd.json)
curl -H "api_access_token: <ver .secrets/generate_erd.json>" \
     "https://synchat.vya.digital/api/v1/accounts/3/contacts/123/conversations"

# INCORRETO — não funciona na Application API
# Authorization: Bearer <token>
```

### Estrutura da resposta — campos críticos por endpoint

**Conversas do contato** (`/contacts/{id}/conversations`):
```json
{
  "payload": [{
    "id": 9871,
    "additional_attributes": { "src_id": "8810" },
    "status": "resolved",
    "meta": { "assignee": { "id": 7 }, "sender": { "id": 123 } }
  }]
}
```
> ⚠️ **LIMITE CRÍTICO**: este endpoint retorna apenas as **20 conversas mais recentes** — hardcoded no Rails. Para contatos com >20 conversas, a validação é parcial. Logar `WARNING` quando `len(payload) == 20`.

**Messages de uma conversa** (`/conversations/{display_id}/messages`):
```json
{
  "payload": [{
    "id": 55001,
    "content": "Olá",
    "message_type": 0,
    "additional_attributes": { "src_id": "7654" },
    "attachments": [{
      "message_id": 55001,
      "data_url": "https://synchat.vya.digital/rails/active_storage/blobs/redirect/{id}/file.pdf",
      "file_type": 3,
      "extension": "pdf"
    }]
  }]
}
```

**Links de attachment**: `data_url` usa Rails Active Storage redirect (302 → URL temporária S3). Não requer `api_access_token` para verificar. HTTP HEAD funciona corretamente.

### Cross-reference via `src_id`

| Entidade | Campo na API | Como verificar |
|----------|-------------|----------------|
| `conversations` | `additional_attributes.src_id` | `str(src_id) == str(expected_src_id)` |
| `messages` | `additional_attributes.src_id` | idem |
| `contacts` | `custom_attributes.src_id` | idem |

### Rate limit para Fase 2

Para 10 contatos × 5 conversas × 5 msgs = ~100 requests: **completamente seguro** (Rack::Attack padrão = 300 req/min). Delay de 150ms entre requests como cortesia:

```python
import time
time.sleep(0.15)  # entre cada chamada — previne pico de carga no servidor
```

---

## Síntese — Decisões Atualizadas do Debate

| Tópico | Decisão | Agente | Motivo |
|--------|---------|--------|--------|
| Estrutura | Dois modos: `summary` + `deep` via argparse subcommand | @system-engineer | Separação clara de responsabilidades e timeouts |
| Seleção de amostra | `richness_score` = conversas × 5 + anexos × 10 + mensagens | @system-engineer + @dba-sql-expert | Máximo signal de validação |
| HTTP client | `urllib.request` (stdlib) | @python-expert | Sem nova dependência |
| Autenticação | Header `api_access_token` (valor de `.secrets/`) | @chatwoot-expert | Padrão Application API |
| Endpoint conversations | `/conversations/meta?status=all` | @chatwoot-expert | 1 request vs 1.441 páginas |
| Endpoint contacts | `/contacts?page=1` → `meta.count` | @chatwoot-expert | Total global sem paginação |
| Conversas do contato | `/contacts/{id}/conversations` + aviso se len==20 | @chatwoot-expert | Limite 20 hardcoded no Rails |
| Messages e Attachments | DB DEST + amostragem API | @chatwoot-expert + @system-engineer | API inviável para 239k+ rows |
| Verificação de links | HTTP HEAD + `_redact_url()` + `url_preview[:80]` | @python-expert + @devops-expert | Sem expor tokens S3 nos logs |
| Campo attachment URL | `external_url` (não `file_path`) | @dba-sql-expert | Nome real no schema Chatwoot |
| Cross-reference | `additional_attributes.src_id` / `custom_attributes.src_id` | @chatwoot-expert | Rastreio migração via API |
| Exit codes | 0=ok, 1=fatal, 2=delta, 3=links, 4=ambos | @devops-expert | 4 dimensões de resultado |
| Makefile | `validate-api-counts` + `validate-api-deep` separados | @devops-expert | CI usa só counts; deep é manual |
| Log seguro | `_redact_url()`, dados sensíveis só em DEBUG, nunca tokens | @python-expert + @devops-expert | Segurança em arquivo versionável |
| Schema SQL | Colunas `id_origem`/`id_destino` | @dba-sql-expert | Nome real na `migration_state` |

---

## Especificação Final — `app/10_validar_api.py` (v2)

### Docstring/Header

```
Valida via API REST do Chatwoot se os dados migrados estão acessíveis.

Modo summary: compara contagens SOURCE DB vs DEST DB vs API por account.
Modo deep:    validação profunda por amostra de contatos — conversas,
              mensagens e links de anexos verificados via HTTP HEAD.

Saídas em .tmp/:
    validacao_api_{TS}.json   — dados brutos
    validacao_api_{TS}.csv    — tabela legível
    validacao_api_{TS}.log    — log completo (inclui DEBUG com dados completos)

Usage:
    python app/10_validar_api.py summary [--verbose]
    python app/10_validar_api.py deep [--sample-size N] [--check-urls] [--verbose]
    python app/10_validar_api.py deep --contact-phone "+5511..." [--check-urls]
```

### Checklist de Implementação (v2)

**Shared:**
- [ ] `_load_api_config()` — lê `.secrets/generate_erd.json["synchat"]`; nunca loga `api_key`
- [ ] `_probe_api()` — `GET /api/v1/profile`, `sys.exit(1)` se não 200
- [ ] `_api_get()` — header `api_access_token`, timeout configurável, `ApiError` tipado
- [ ] `_fetch_account_map()` — `migration_state WHERE tabela='accounts'`
- [ ] `_setup_logging()` — handler duplo stdout+`.log`, nível INFO/DEBUG por `--verbose`
- [ ] `_redact_url()` — redacta params `X-Amz-*`, `token=`, `signature=` antes de qualquer `log.*`

**Modo summary:**
- [ ] `_fetch_source_counts()` — GROUP BY account_id em SOURCE
- [ ] `_fetch_dest_db_counts()` — snapshot com sanidade embutida por dest_account_id
- [ ] `_fetch_api_counts()` — `/conversations/meta` + `/contacts page=1`
- [ ] `_build_summary_report()` — PURA, sem I/O
- [ ] `_write_summary_outputs()` — JSON + CSV em `.tmp/`

**Modo deep:**
- [ ] `_select_sample_contacts()` — query `richness_score`, N contatos por account
- [ ] `_deep_scan_db()` — SOURCE vs DEST DB por contato (já existe)
- [ ] `_deep_scan_api_contact()` — `GET /contacts/{dest_id}`, campos `name/email/phone`
- [ ] `_deep_scan_api_conversations()` — `GET /contacts/{id}/conversations`, aviso se len==20
- [ ] `_check_url()` — HEAD + `_redact_url()` + `verdict` semântico
- [ ] `_build_deep_report()` — PURA, sem I/O
- [ ] `_write_deep_outputs()` — JSON expandido + CSV por attachment

**Argparse:**
- [ ] Subcommands: `summary` e `deep`
- [ ] `deep --sample-size N` (default: 5)
- [ ] `deep --check-urls` (default: off)
- [ ] `deep --contact-phone` / `--contact-email` (alternativo ao sample)
- [ ] `--verbose`, `--timeout S`

### Escopo de Validação por Entidade (v2)

| Entidade | Modo summary — API | Modo summary — DB | Modo deep — API | Modo deep — DB | Sanidade |
|----------|-------------------|-------------------|-----------------|----------------|---------|
| conversations | ✅ `/meta all_count` | ✅ COUNT | ✅ por contato (lim. 20) | ✅ COUNT + orphans | `display_id`, `status`, `src_id` |
| contacts | ✅ `/contacts meta.count` | ✅ COUNT | ✅ GET /contacts/{id} | ✅ fields comparison | `phone`, `email`, `name` |
| messages | ❌ | ✅ COUNT | ✅ GET /messages por conversa | ✅ COUNT + `message_type` | `content`, `src_id` |
| attachments | ❌ | ✅ COUNT | ✅ HEAD `data_url` | ✅ `external_url` | verdict: ok/not_found/forbidden |

---

## Ações

- [ ] Implementar `app/10_validar_api.py` conforme checklist v2
- [ ] Adicionar targets `validate-api-counts` e `validate-api-deep` no `Makefile`
- [ ] Executar `python app/10_validar_api.py summary` primeiro para validar contagens macro
- [ ] Executar `python app/10_validar_api.py deep --sample-size 5` para validação profunda
- [ ] Executar `python app/10_validar_api.py deep --sample-size 5 --check-urls` para verificar links
- [ ] Se `delta_messages != 0`: investigar com `app/08_diagnostico_perda_dados.py`
- [ ] Se `attachments_not_found > 0`: registrar em `docs/decisions/` como perda de arquivo
- [ ] Registrar resultado final em `docs/SESSIONS/`

---

*Debate v2 conduzido por GitHub Copilot em 2026-04-20. Participantes: @system-engineer, @dba-sql-expert, @python-expert, @devops-expert, @chatwoot-expert.*
*Objetivos expandidos: validação profunda com verificação de links de anexos e logs máximos.*
