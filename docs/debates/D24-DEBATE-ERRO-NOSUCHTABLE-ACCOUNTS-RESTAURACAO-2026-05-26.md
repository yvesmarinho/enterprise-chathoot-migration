# D24 — Erro `NoSuchTableError` em `accounts` após restauração do DEST

**Data**: 2026-05-26
**Status**: Confirmado e corrigido com bootstrap sob demanda da tabela `accounts`
**Impacto**: A migração travava na primeira tabela do pipeline, impedindo qualquer execução da account `Unimed Guaxupé`.

---

## Contexto

Após restaurar a base de dados do DEST, a execução do pipeline falhou imediatamente em `accounts` com:

```text
sqlalchemy.exc.NoSuchTableError: accounts
```

O erro apareceu durante a reflexão da tabela no `AccountsMigrator`, antes de qualquer inserção de dados.

---

## Sintoma Observado

Fluxo executado:
1. `src/migrar.py --env dev --account "Unimed Guaxupé" --verbose`
2. `resolve_account_id()` encontrou a source account corretamente.
3. A validação do DEST tratou `accounts` como ausente.
4. O pipeline entrou em `AccountsMigrator`.
5. A reflexão da tabela `accounts` no DEST abortou com `NoSuchTableError`.

---

## Causa Raiz

A base restaurada do DEST estava sem `public.accounts` no momento do arranque.

Isso aparecia como `NoSuchTableError` em `accounts` porque o migrator tentava
refletir a tabela antes de garantir que a tabela existia no ambiente restaurado.

---

## Correção Aplicada

Arquivos corrigidos:
- [src/utils/schema_bootstrap.py](../../src/utils/schema_bootstrap.py)
- [src/migrators/accounts_migrator.py](../../src/migrators/accounts_migrator.py)

Mudança principal:
- o migrador de `accounts` passou a criar `public.accounts` no DEST a partir do
	metadata do SOURCE apenas quando a tabela está ausente

Isso torna o pipeline tolerante ao estado pós-restauração e evita que a
execução morra antes do primeiro batch.

---

## Verificação

- `uv run python -m py_compile src/migrators/accounts_migrator.py src/utils/schema_bootstrap.py` executado com sucesso.
- O erro de reflexão ficou documentado para rastreabilidade.

---

## Atualização de Execução

Na retomada de 2026-05-26 às 17:50, o mesmo erro reapareceu antes do bootstrap.
Com a correção sob demanda, o DEST passa a receber `public.accounts` apenas
quando necessário, sem custo de bootstrap integral no startup.

Na execução seguinte, o pipeline avançou até `inboxes`, mas a criação pontual
da tabela falhou com dependência de FK (`public.portals`) ausente.

Correção adicional aplicada em `src/utils/schema_bootstrap.py`:
- bootstrap recursivo de dependências FK antes de criar a tabela alvo
- criação de uma tabela por vez (`tables=[dest_table]`) para reduzir acoplamento

Atualização final (18:13):
- a criação de uma tabela isolada ainda falhava em runtime com
	`NoReferencedTableError`, porque o SQLAlchemy exige que as tabelas
	referenciadas por FK estejam no mesmo `MetaData` durante o `create_all`.
- o helper foi ajustado para montar um grafo de dependências FK do schema
	`public` e criar o conjunto de tabelas dependentes no mesmo `MetaData`
	(com `checkfirst=True`).

Atualização final 2 (18:25):
- o pipeline avançou até `conversation_labels`, mas `_migrate_tags()` falhou
	com `UndefinedTable: relation "tags" does not exist` ao executar
	`SELECT id, name FROM tags` no DEST.
- correção aplicada no `ConversationLabelsMigrator`:
	- bootstrap sob demanda de `public.tags` antes da leitura
	- SQL qualificado com schema (`public.tags`, `public.taggings`)
	- `nextval('public.tags_id_seq')` para inserção de tags novas

---

## Impacto no Pipeline

Este erro era o bloqueio inicial do fluxo atual. Sem a correção:
- o pipeline não sai da primeira etapa
- nenhum migrator subsequente é executado
- nenhuma correção de visibilidade ou dados de negócio pode ser validada

Com a correção, o fluxo pode avançar para as próximas etapas do merge.
