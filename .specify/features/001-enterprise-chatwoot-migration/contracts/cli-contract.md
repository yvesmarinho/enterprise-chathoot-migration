# CLI Contract: enterprise-chatwoot-migration

**Branch**: `001-enterprise-chatwoot-migration`
**Date**: 2026-04-09
**Interface Type**: CLI Script (Python)
**Entrypoint**: `python src/migrar.py`

---

## Command Schema

### Invocação básica

```bash
python src/migrar.py
```

Sem argumentos obrigatórios na fase inicial. A ferramenta carrega configuração
exclusivamente de `.secrets/generate_erd.json`.

### Argumentos opcionais (fase inicial)

| Flag | Tipo | Default | Descrição |
|------|------|---------|-----------|
| `--dry-run` | bool flag | False | Executa sem escrita no banco destino; imprime contagens de O que seria migrado |
| `--only-table` | str | None | Migra apenas a tabela especificada (ex: `contacts`). Respeita dependências de FK. |
| `--verbose` | bool flag | False | Log nível DEBUG no stdout (mascaramento ainda aplicado) |

---

## Exit Codes

| Código | Significado |
|--------|-------------|
| `0` | Migração concluída com sucesso (zero falhas ou apenas falhas registradas/esperadas) |
| `1` | Erro de configuração — credenciais ausentes ou inválidas |
| `2` | Erro de conexão — banco inacessível |
| `3` | Falha catastrófica — violação de FK em entidade raiz (`accounts`); rollback manual necessário |
| `4` | Erro interno inesperado |

---

## Output Schema (stdout)

Todas as linhas seguem o padrão: `[TIMESTAMP] [LEVEL] [TABELA] mensagem`

```
[2026-04-09 18:00:00] INFO  [SYSTEM]  Iniciando migração enterprise-chatwoot-migration
[2026-04-09 18:00:01] INFO  [SYSTEM]  Offsets calculados: accounts=20, contacts=225536, ...
[2026-04-09 18:00:02] INFO  [accounts] Iniciando migração: 5 registros
[2026-04-09 18:00:02] INFO  [accounts] Batch 1/1 (5 registros) — OK
[2026-04-09 18:00:03] INFO  [accounts] Concluído: 5 migrados, 0 falhas
[2026-04-09 18:01:30] INFO  [contacts] Iniciando migração: 38.868 registros
[2026-04-09 18:01:30] INFO  [contacts] Batch 1/78 (500 registros) — OK
...
[2026-04-09 18:01:59] WARN  [conversations] ID 12345 pulado — contact_id inválido
...
[2026-04-09 18:59:00] INFO  [SYSTEM]  Relatório de validação: .tmp/migration_20260409_180000_report.txt
[2026-04-09 18:59:00] INFO  [SYSTEM]  Migração concluída. Total migrado: 418.828. Falhas: 3.
```

**Dados nunca aparecem em output**: nenhum nome, email, telefone, conteúdo de mensagem.

---

## Relatório de Validação (arquivo)

Salvo em `.tmp/migration_YYYYMMDD_HHMMSS_report.txt`:

```
=== RELATÓRIO DE VALIDAÇÃO — enterprise-chatwoot-migration ===
Data/hora: 2026-04-09 18:59:00
Duração total: 59m 00s

TABELA           | ORIGEM | MIGRADO | DESTINO_TOTAL | FALHAS
-----------------+--------+---------+---------------+-------
accounts         |      5 |       5 |            25 |      0
inboxes          |     21 |      21 |           172 |      0
users            |    112 |     112 |           406 |      0
teams            |      3 |       3 |            25 |      0
labels           |     32 |      32 |           216 |      0
contacts         | 38.868 |  38.868 |       264.404 |      0
conversations    | 41.743 |  41.740 |       195.322 |      3
messages         |310.155 | 310.155 |     1.613.104 |      0
attachments      | 26.889 |  26.889 |       100.324 |      0
-----------------+--------+---------+---------------+-------
TOTAL            |418.828 | 418.825 |     2.174.998 |      3

FALHAS DETALHADAS (IDs apenas, sem conteúdo):
  conversations: IDs origem [12345, 23456, 34567] — contact_id inválido

STATUS: SUCESSO COM AVISOS
```

---

## Arquivo de Configuração (`.secrets/generate_erd.json`)

Schema esperado pelo script (nunca impresso ou logado):

```json
{
  "chatwoot_dev_db": {
    "host": "wfdb02.vya.digital",
    "port": 5432,
    "database": "chatwoot_dev_db",
    "user": "...",
    "password": "...",
    "SSL": false
  },
  "chatwoot004_dev_db": {
    "host": "wfdb02.vya.digital",
    "port": 5432,
    "database": "chatwoot004_dev_db",
    "user": "...",
    "password": "...",
    "SSL": false
  }
}
```

---

## Invariantes do Contrato

1. O script NUNCA modifica `chatwoot_dev_db`
2. O script NUNCA imprime credenciais, senhas ou tokens
3. O script NUNCA imprime conteúdo de mensagens, nomes ou emails de usuários/contatos
4. Re-execução sem novos dados origina exit code `0` com "0 novos registros"
5. Falha de conexão ANTES do primeiro insert origina exit code `2` sem dados no destino
