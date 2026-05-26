# D21 — BUG CRÍTICO: Idempotência Quebrada por Deduplicação Global

**Data**: 2026-05-26
**Severidade**: 🔴 **CRÍTICA** — Pipeline completamente não-funcional para merge
**Status**: 🐛 **CONFIRMADO** — Causa raiz identificada
**Impacto**: Migração de account resulta em account vazio (0 dados) mesmo com exit code 0

---

## 📋 Sumário Executivo

A migração da **Unimed Guaxupé** (source account_id=25 → dest account_id=69) completou com **exit code 0** e **0 orphans FK**, mas resultou em:

```
Account 69 (Unimed Guaxupé) no DEST:
  ✅ Account criado
  ❌ Conversations: 0  (esperado: 8202)
  ❌ Messages: 0       (esperado: 46046)
  ❌ Attachments: 0    (esperado: 1938)
  ❌ ActiveStorage: 0  (esperado: 1927, 99.43% coverage)
```

**Causa raiz**: Deduplicação GLOBAL em vez de scoped por account + ausência de validação de account name pré-existente.

---

## 🔍 Análise Técnica

### 1. Evidências do Log

```
2026-05-26T11:33:35 INFO migrar.attachments — Table attachments: total=1938 migrated=0 skipped=1938 failed=0
2026-05-26T11:33:46 INFO migrar.active_storage_blobs — Table active_storage_blobs: total=30511 migrated=0 skipped=30511 failed=0
2026-05-26T11:34:01 INFO migrar.active_storage_attachments — Table active_storage_attachments: total=30487 migrated=0 skipped=30487 failed=0
```

**100% skip rate** apesar de account 69 estar limpo (deletado e recriado durante a sessão).

### 2. Estado do DEST Antes da Migração

```sql
-- DEST tinha 19 accounts PRÉ-EXISTENTES (IDs 1, 17, 20, 28, 30-44)
-- Total de blobs: 134.230 (de OUTROS accounts)
-- Account 69 NÃO existia (foi deletado via cleanup_accounts.py)
```

### 3. Comportamento Observado

#### Fase 1: Account Migration
```
AccountsMigrator: migrated=1 skipped=0 ✅
→ Account 69 CRIADO com sucesso
→ migration_state registrou: tabela=accounts, id_origem=25, id_destino=69
```

#### Fase 2: Data Migration (Attachments, ActiveStorage)
```
ActiveStorageBlobsMigrator:
  1. Query GLOBAL: SELECT key FROM active_storage_blobs (retorna 134k keys)
  2. Para cada blob do SOURCE:
     - if key in existing_keys → SKIP
  3. Resultado: 30.511 blobs SKIPADOS (eram de outros accounts!)

AttachmentsMigrator:
  1. Verifica apenas migration_state (message_id, account_id)
  2. Como messages NÃO foram migrados → attachments SKIPADOS
  3. Resultado: 1.938 attachments SKIPADOS
```

---

## 🐛 Root Cause Analysis

### Bug #1: Deduplicação Global (ActiveStorageBlobsMigrator)

**Arquivo**: `src/migrators/active_storage_blobs_migrator.py`
**Linhas**: 60-68

```python
# CÓDIGO ATUAL (ERRADO):
with self.dest_engine.connect() as conn:
    existing_keys_query = select(dest_table.c.key)
    existing_keys = {row[0] for row in conn.execute(existing_keys_query)}
    # ↑ Retorna TODAS as keys do DEST, incluindo de OUTROS accounts

def remap_fn(row: dict) -> dict | None:
    key = row["key"]
    if key in existing_keys:  # ← SKIP mesmo que key seja de outro account!
        return None
```

**Problema**:
- A query `SELECT key FROM active_storage_blobs` retorna keys de **TODOS os accounts** no DEST
- Quando migrando account 69 (limpo), os blobs são skipados porque keys já existem (mas pertencem a accounts 1, 17, 20, etc.)
- **active_storage_blobs NÃO tem coluna account_id** → impossível fazer scope por account direto

**Solução Necessária**:
Deduplicação por `key` está **CORRETA** (UNIQUE constraint), mas a lógica de skip está **ERRADA**:
- Se `key` já existe no DEST:
  - ✅ **SKIP inserção** (correto — evita UniqueViolation)
  - ❌ **NÃO registrar mapeamento** (ERRADO — causa orphans downstream)
  - ✅ **DEVERIA**: Registrar mapeamento `id_origem → id_destino_existente` na migration_state

### Bug #2: Ausência de Validação de Account Name

**Arquivo**: `src/migrar.py`
**Linhas**: 280-300

```python
# CÓDIGO ATUAL (INCOMPLETO):
if args.account:
    account_id_filter = resolve_account_id(source_engine, args.account, fuzzy=True)
    # ↑ Resolve apenas no SOURCE
    # ❌ NÃO verifica se account com mesmo NAME já existe no DEST
```

**Problema**:
1. Usuário executa: `./scripts/start-migration-daemon.sh --env dev --account "Unimed Guaxupé"`
2. Pipeline resolve: `source_account_id=25`
3. Pipeline **NÃO verifica** se account "Unimed Guaxupé" já existe no DEST
4. AccountsMigrator tenta inserir → **já existe** → skip (idempotente) → retorna `dest_account_id=69`
5. Migrators subsequentes assumem que account 69 está **vazio**, mas na verdade tem dados pré-existentes (de migrações anteriores)

**Requisito Violado**:
Usuário havia solicitado explicitamente:
> "deve ser validado se existe o nome do account na base destino"

**Solução Necessária**:
```python
# ADICIONAR em src/migrar.py após resolver source account:
dest_account = check_account_exists_in_dest(dest_engine, args.account)
if dest_account:
    # Account com mesmo NAME já existe no DEST
    dest_account_id = dest_account["id"]

    # Verificar se tem dados
    stats = get_account_stats(dest_engine, dest_account_id)
    if stats["messages"] > 0 or stats["conversations"] > 0:
        logger.error(
            "Account '%s' já existe no DEST (ID=%d) com dados: "
            "%d conversations, %d messages. Aborting.",
            args.account, dest_account_id, stats["conversations"], stats["messages"]
        )
        logger.error("Use --force-overwrite para sobrescrever (CUIDADO: perda de dados)")
        return 4  # Exit code: account já existe com dados
    else:
        logger.warning(
            "Account '%s' já existe no DEST (ID=%d) mas está VAZIO. "
            "Continuando migração...",
            args.account, dest_account_id
        )
```

### Bug #3: Migration State Não Registra Skips de Deduplicação

**Arquivo**: `src/migrators/base_migrator.py` (inferido, não lido ainda)

**Problema**:
Quando `remap_fn()` retorna `None` (skip), o registro **NÃO é gravado** na `migration_state`. Isso causa:
- Downstream migrators não conseguem resolver FKs
- Orphan warnings em cascata
- Dados não migrados sem erro visível

**Exemplo**:
```python
# active_storage_blobs migrator
blob_id_origem = 12345, key = "abc123xyz..."
# Key já existe no DEST (id_destino = 67890, de outro account)
# remap_fn retorna None → SKIP
# ❌ migration_state NÃO registra: (active_storage_blobs, 12345, 67890)

# active_storage_attachments migrator (downstream)
# Tenta resolver: blob_id = 12345
# ❌ Não encontra mapeamento → orphan → SKIP attachment
```

**Solução Necessária**:
Quando skipando por deduplicação, **AINDA ASSIM** gravar mapeamento:
```python
if key in existing_keys:
    # Key já existe — descobrir id_destino_existente
    id_destino_existente = get_existing_id_by_key(conn, dest_table, key)

    # Registrar mapeamento para downstream migrators
    state_repo.save_mapping(
        conn, "active_storage_blobs", id_origem, id_destino_existente
    )

    return None  # Skip INSERT (correto)
```

---

## 📊 Impacto

### Funcionalidade Quebrada
- ❌ Migração incremental (account-by-account para DEST com dados existentes)
- ❌ Re-migração de account (mesmo após cleanup)
- ❌ Merge de múltiplos SOURCE DBs em DEST único

### Funcionalidade Preservada
- ✅ Migração fresh (SOURCE completo → DEST vazio)
- ✅ Migração de account único para DEST vazio

### Dados Afetados
- **Account 69 (Unimed Guaxupé)**: 0 dados migrados apesar de sucesso reportado
- **Outros accounts**: Não afetados (pré-existentes intactos)
- **S3 Blobs**: Não afetados (blobs não foram movidos/alterados)

---

## 🔧 Correções Necessárias

### 1. Validação de Account Name (src/migrar.py)

**Prioridade**: 🔴 **P0 — BLOCKER**

```python
# Adicionar após linha 300 em src/migrar.py:

# (2c) Verificar se account já existe no DEST
if args.account and not args.dry_run:
    dest_account_name = resolve_account_name(dest_engine, account_id_filter, source_engine)
    existing_dest_account = find_account_by_name(dest_engine, dest_account_name)

    if existing_dest_account:
        dest_account_id = existing_dest_account["id"]
        stats = get_account_stats(dest_engine, dest_account_id)

        has_data = (
            stats["conversations"] > 0
            or stats["messages"] > 0
            or stats["attachments"] > 0
        )

        if has_data and not args.force_overwrite:
            logger.error(
                "❌ Account '%s' já existe no DEST (ID=%d) com dados:",
                dest_account_name, dest_account_id
            )
            logger.error("   Conversations: %d", stats["conversations"])
            logger.error("   Messages: %d", stats["messages"])
            logger.error("   Attachments: %d", stats["attachments"])
            logger.error("")
            logger.error("Opções:")
            logger.error("  1. Use --force-overwrite para sobrescrever (PERDA DE DADOS)")
            logger.error("  2. Limpe o account manualmente: python scripts/cleanup_accounts.py --account-ids %d", dest_account_id)
            logger.error("  3. Escolha outro account no SOURCE")
            return 4

        elif has_data and args.force_overwrite:
            logger.warning(
                "⚠️  Account '%s' (ID=%d) será SOBRESCRITO (--force-overwrite ativo)",
                dest_account_name, dest_account_id
            )
            # Executar cleanup automático
            from scripts.cleanup_accounts import delete_account_data
            logger.info("Limpando dados pré-existentes...")
            delete_account_data(dest_engine, [dest_account_id], dry_run=False)
            logger.info("✅ Cleanup concluído")

        else:
            logger.warning(
                "⚠️  Account '%s' já existe no DEST (ID=%d) mas está VAZIO",
                dest_account_name, dest_account_id
            )
            logger.info("Continuando migração...")
```

### 2. Deduplicação com Registro de Mapeamento (active_storage_blobs_migrator.py)

**Prioridade**: 🔴 **P0 — BLOCKER**

```python
# Substituir método migrate() em ActiveStorageBlobsMigrator:

def migrate(self) -> MigrationResult:
    self.logger.info("ActiveStorageBlobsMigrator: starting")
    src_table = Table("active_storage_blobs", MetaData(), autoload_with=self.source_engine)
    dest_table = Table("active_storage_blobs", MetaData(), autoload_with=self.dest_engine)

    rows = self._select_source_rows(src_table)
    self.logger.info("ActiveStorageBlobsMigrator: %d source rows fetched", len(rows))

    # Pre-load existing keys → id mapping
    with self.dest_engine.connect() as conn:
        from sqlalchemy import select
        existing_keys_query = select(dest_table.c.id, dest_table.c.key)
        existing_map = {row[1]: row[0] for row in conn.execute(existing_keys_query)}
        # existing_map = {"abc123xyz": 67890, ...}

    self.logger.info("ActiveStorageBlobsMigrator: %d existing keys in DEST", len(existing_map))

    def remap_fn(row: dict) -> dict | None:
        id_origin = int(row["id"])
        key = row["key"]

        if key in existing_map:
            # Key já existe — SKIP insert mas REGISTRAR mapeamento
            id_destino_existente = existing_map[key]

            # ✅ CRÍTICO: Registrar mapeamento para downstream migrators
            with self.dest_engine.connect() as conn:
                self.state_repo.save_mapping(
                    conn, "active_storage_blobs", id_origin, id_destino_existente
                )

            self.logger.debug(
                "ActiveStorageBlobsMigrator: id=%d → id=%d (key '%s' exists, reusing)",
                id_origin, id_destino_existente, key
            )
            return None  # Skip INSERT

        # Key nova — migrar normalmente
        return {
            **row,
            "id": self.id_remapper.remap(id_origin, "active_storage_blobs"),
        }

    # Continue com _run_batches...
```

### 3. Adicionar Flag --force-overwrite (argparse)

**Prioridade**: 🟡 **P1 — HIGH**

```python
# Em src/migrar.py, função build_parser():

parser.add_argument(
    "--force-overwrite",
    action="store_true",
    help=(
        "Sobrescrever account no DEST mesmo que já tenha dados. "
        "⚠️ CUIDADO: Causa PERDA DE DADOS permanente. "
        "Executa cleanup automático antes da migração."
    ),
)
```

---

## 🧪 Casos de Teste

### Caso 1: Account Não Existe no DEST
```bash
uv run python -m src.migrar --env dev --account "Novo Account"
# Esperado: Migração completa (criar + popular)
# Status: ✅ FUNCIONA (não afetado pelo bug)
```

### Caso 2: Account Existe no DEST (Vazio)
```bash
# Preparação: criar account vazio no DEST
uv run python -m src.migrar --env dev --account "Account Vazio"
# Esperado: ⚠️ Warning + continuar migração
# Status: ❌ FALHA (skip de dados por deduplicação global)
```

### Caso 3: Account Existe no DEST (Com Dados)
```bash
# Preparação: account já migrado previamente
uv run python -m src.migrar --env dev --account "Unimed Guaxupé"
# Esperado: ❌ Erro + abort (sem --force-overwrite)
# Status: ❌ FALHA (não valida existência, cria duplicado)
```

### Caso 4: Re-migração com --force-overwrite
```bash
uv run python -m src.migrar --env dev --account "Unimed Guaxupé" --force-overwrite
# Esperado: Cleanup automático + migração completa
# Status: ⚠️ NÃO IMPLEMENTADO (flag não existe)
```

---

## 📝 Lições Aprendidas

### L6: Deduplicação Deve Preservar Mapeamentos
- **Problema**: `remap_fn() → None` não registra mapeamento
- **Solução**: Sempre gravar `id_origem → id_destino` na migration_state, mesmo em skips
- **Aplicação**: Todos os migrators com deduplicação (contacts, blobs, etc.)

### L7: Validar Pré-condições no Início da Pipeline
- **Problema**: Descobrir account duplicado após migrar metade dos dados
- **Solução**: Validar account name existente ANTES de iniciar migração
- **Aplicação**: Check no início de `main()`, não no meio

### L8: Exit Code 0 ≠ Sucesso Real
- **Problema**: Pipeline reportou sucesso (exit 0) mas 100% skip
- **Solução**: Validar RESULTADO esperado vs. obtido (migrated > 0)
- **Aplicação**: Adicionar assertion no final: `if migrated_count == 0 and expected > 0: exit(5)`

### L9: Logs Devem Alertar Para Anomalias
- **Problema**: 100% skip não gerou WARNING
- **Solução**: Se skip_rate > 80% → log.warning() + investigação sugerida
- **Aplicação**: Base migrator `_run_batches()` post-processing

---

## 🚦 Status das Correções

| # | Correção | Prioridade | Status | Responsável |
|---|----------|-----------|--------|-------------|
| 1 | Validação de account name | P0 🔴 | 🔄 EM ANÁLISE | Copilot |
| 2 | Deduplicação com mapeamento | P0 🔴 | 🔄 EM ANÁLISE | Copilot |
| 3 | Flag --force-overwrite | P1 🟡 | 📋 PLANEJADO | Copilot |
| 4 | Testes de regressão | P1 🟡 | 📋 PLANEJADO | - |
| 5 | Documentação de uso | P2 🔵 | 📋 PLANEJADO | - |

---

## 📚 Referências

- **D18**: Investigação inicial (ActiveStorage missing)
- **D19**: UniqueViolation error (primeira tentativa de fix)
- **Logs**: `.tmp/migration_daemon_20260526_113110.log`
- **Código**: `src/migrar.py`, `src/migrators/active_storage_blobs_migrator.py`
- **Data Atual**: 2026-05-26

---

**Próximos Passos**:
1. ✅ Documentar bug (este arquivo)
2. 🔄 Implementar correção #1 (validação account name)
3. 🔄 Implementar correção #2 (deduplicação com mapeamento)
4. 📋 Adicionar testes de regressão
5. 📋 Atualizar documentação de uso

---

*Fim do Debate D21*
