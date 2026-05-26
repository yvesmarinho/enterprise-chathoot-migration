# CORREÇÕES P0 — Bug D21 (Idempotência Quebrada)

**Data**: 2026-05-26  
**Autor**: GitHub Copilot  
**Referência**: [D21-BUG-CRITICO-IDEMPOTENCIA-DEDUPLICACAO-GLOBAL-2026-05-26.md](./debates/D21-BUG-CRITICO-IDEMPOTENCIA-DEDUPLICACAO-GLOBAL-2026-05-26.md)

---

## 📦 Arquivos Modificados

1. **src/utils/account_resolver.py** — Novas funções de validação
2. **src/migrar.py** — Validação de account pré-existente + flag --force-overwrite
3. **src/migrators/active_storage_blobs_migrator.py** — Registro de mapeamentos em skips

---

## ✅ Correção #1: Validação de Account Pré-existente

### Problema
Pipeline não verificava se account já existe no DEST antes de migrar, resultando em:
- Account vazio criado (ou reutilizado)
- Dados skipados por deduplicação global
- Migração reporta sucesso (exit 0) mas 0 dados migrados

### Solução Implementada

**Arquivo**: `src/utils/account_resolver.py`

Adicionadas duas novas funções:

```python
def find_account_by_name_in_dest(
    dest_engine: Engine, account_name: str, fuzzy: bool = True
) -> Optional[dict]:
    """Busca account no DEST por nome (exato ou fuzzy).
    
    Returns:
        Dict com id, name, created_at se encontrado; None caso contrário
    
    Raises:
        ValueError: Se múltiplos accounts corresponderem (fuzzy=True)
    """
```

```python
def check_account_exists_with_data(
    dest_engine: Engine, account_name: str
) -> tuple[bool, Optional[dict]]:
    """Verifica se account existe no DEST e se tem dados.
    
    Returns:
        Tupla (has_data: bool, stats: dict|None)
        - has_data=True se account existe E tem conversations/messages/attachments
        - stats=dict com id, name, conversations, messages, attachments
        - stats=None se account não existe
    """
```

**Arquivo**: `src/migrar.py`

Adicionado após linha 300 (após resolução do account no SOURCE):

```python
# (2a.1) Verificar se account já existe no DEST (validação P0 — D21)
if not args.dry_run:
    has_data, dest_stats = check_account_exists_with_data(dest_engine, args.account)
    
    if has_data and dest_stats:
        # Account existe COM DADOS
        if not args.force_overwrite:
            logger.error("❌ Account '%s' já existe no DEST (ID=%d) com dados:", ...)
            logger.error("Opções:")
            logger.error("  1. Use --force-overwrite para sobrescrever")
            logger.error("  2. Limpe manualmente: cleanup_accounts.py --account-ids %d", ...)
            return 4  # Exit code: account já existe com dados
        else:
            # --force-overwrite ativo — cleanup automático
            delete_account_data(dest_engine, [dest_account_id], dry_run=False)
    
    elif dest_stats:
        # Account existe mas VAZIO — apenas warning
        logger.warning("⚠️  Account '%s' já existe mas está VAZIO", ...)
    
    else:
        # Account NÃO existe — OK
        logger.info("✅ Account '%s' não existe no DEST — será criado", ...)
```

### Novos Exit Codes

| Code | Significado |
|------|-------------|
| `4` | Account já existe no DEST com dados (sem --force-overwrite) |
| `5` | Erro no cleanup automático (com --force-overwrite) |

### Nova Flag CLI

```bash
uv run python -m src.migrar --env dev --account "Nome" --force-overwrite
```

**Descrição**: Sobrescreve account no DEST mesmo que já tenha dados. Executa cleanup automático antes da migração.

⚠️ **CUIDADO**: Causa PERDA DE DADOS permanente.

---

## ✅ Correção #2: Registro de Mapeamentos em Skips

### Problema
`ActiveStorageBlobsMigrator` fazia deduplicação por `key` (correto — UNIQUE constraint), mas:
- ❌ Quando key já existia → `return None` (skip INSERT)
- ❌ Mapeamento `id_origem → id_destino_existente` **NÃO era registrado** na migration_state
- ❌ Downstream migrators (active_storage_attachments) não conseguiam resolver FK → orphans → skip cascata

**Resultado**: 100% skip rate mesmo com account limpo.

### Solução Implementada

**Arquivo**: `src/migrators/active_storage_blobs_migrator.py`

**Antes** (ERRADO):
```python
# Buscar apenas keys
existing_keys = {row[0] for row in conn.execute(select(dest_table.c.key))}

def remap_fn(row: dict) -> dict | None:
    if key in existing_keys:
        return None  # ❌ Skip SEM registrar mapeamento
```

**Depois** (CORRETO):
```python
# Buscar key → id mapping
existing_key_to_id = {}
for row in conn.execute(select(dest_table.c.id, dest_table.c.key)):
    existing_key_to_id[row[1]] = row[0]  # key → id

# PRÉ-PROCESSAR duplicates e registrar mapeamentos (FIX D21)
duplicates_registered = 0
with self.dest_engine.begin() as conn:
    for row in rows:
        id_origin = int(row["id"])
        key = row["key"]
        
        if key in existing_key_to_id:
            id_destino_existente = existing_key_to_id[key]
            
            # ✅ Registrar mapeamento para downstream migrators
            self.state_repo.save_mapping(
                conn, "active_storage_blobs", id_origin, id_destino_existente
            )
            duplicates_registered += 1

logger.info("ActiveStorageBlobsMigrator: %d duplicate keys registered", duplicates_registered)

# remap_fn continua skipando INSERT (correto)
def remap_fn(row: dict) -> dict | None:
    if key in existing_key_to_id:
        return None  # Skip INSERT mas mapeamento já foi registrado
```

### Fluxo Corrigido

```
SOURCE: active_storage_blobs.id=12345, key="abc123xyz..."
DEST: key="abc123xyz..." já existe (id=67890, de outro account)

ANTES (ERRADO):
  1. ActiveStorageBlobsMigrator: key exists → skip
  2. ❌ migration_state NÃO registra (12345 → 67890)
  3. ActiveStorageAttachmentsMigrator: busca blob_id=12345 → NOT FOUND → orphan → skip
  4. Resultado: attachment não migrado

DEPOIS (CORRETO):
  1. ActiveStorageBlobsMigrator: key exists → pre-register (12345 → 67890)
  2. ✅ migration_state REGISTRA (active_storage_blobs, 12345, 67890)
  3. ActiveStorageAttachmentsMigrator: busca blob_id=12345 → FOUND (67890) → migrate
  4. Resultado: attachment migrado com sucesso
```

### Inspiração

Esta solução segue o padrão **JÁ IMPLEMENTADO** em `ContactsMigrator` (linhas 125-137):
```python
if dest_id is not None:
    self.id_remapper.register_alias("contacts", src_id, dest_id)
    dedup_records.append((src_id, dest_id))

self.state_repo.record_success_bulk(dest_conn, "contacts", batch)
```

---

## 🧪 Testes Necessários

### Teste 1: Account Não Existe no DEST
```bash
uv run python -m src.migrar --env dev --account "Novo Account"
```
**Esperado**: ✅ Migração completa (criar account + popular)

### Teste 2: Account Existe Vazio
```bash
# Preparação: criar account vazio no DEST
uv run python -m src.migrar --env dev --account "Account Vazio"
```
**Esperado**: ⚠️ Warning + continuar migração

### Teste 3: Account Existe Com Dados (Sem --force-overwrite)
```bash
uv run python -m src.migrar --env dev --account "Unimed Guaxupé"
```
**Esperado**: ❌ Exit code 4 + mensagem de erro + opções

### Teste 4: Account Existe Com Dados (Com --force-overwrite)
```bash
uv run python -m src.migrar --env dev --account "Unimed Guaxupé" --force-overwrite
```
**Esperado**: 
1. ⚠️ Warning "será sobrescrito"
2. 🗑️ Cleanup automático
3. ✅ Migração completa

### Teste 5: Deduplicação de Blobs (Nova Lógica)
```bash
# Preparação:
# 1. Migrar account A (cria blobs)
# 2. Deletar account A (blobs permanecem)
# 3. Migrar account B (usa mesmos blobs — ex: imagens genéricas)

uv run python -m src.migrar --env dev --account "Account B"
```
**Esperado**:
- ✅ Blobs skipados (duplicate keys)
- ✅ Mapeamentos registrados na migration_state
- ✅ Attachments migrados (resolvem FK via mapeamento)
- ✅ Coverage ~99% igual ao SOURCE

---

## 📊 Impacto das Correções

### Funcionalidade Restaurada
- ✅ Migração incremental (account-by-account)
- ✅ Re-migração de account (após cleanup)
- ✅ Merge de múltiplos SOURCE DBs em DEST único
- ✅ Deduplicação de recursos compartilhados (blobs, contacts)

### Segurança Adicionada
- ✅ Validação de account pré-existente
- ✅ Proteção contra sobrescrita acidental (exit code 4)
- ✅ Cleanup automático controlado (--force-overwrite)

### Compatibilidade Mantida
- ✅ Migração fresh (SOURCE → DEST vazio) não afetada
- ✅ Exit code 0 ainda significa sucesso total
- ✅ Logs compatíveis (apenas novos warnings/erros)

---

## 🔍 Checklist de Validação

Antes de considerar o bug RESOLVIDO:

- [x] Código compila sem erros
- [ ] Teste 1 passa (account novo)
- [ ] Teste 2 passa (account vazio)
- [ ] Teste 3 passa (account com dados, sem --force)
- [ ] Teste 4 passa (account com dados, com --force)
- [ ] Teste 5 passa (deduplicação de blobs)
- [ ] FK validation 0 orphans
- [ ] Coverage ActiveStorage ~99%
- [ ] Log mostra "migrated > 0" (não 100% skip)
- [ ] Documentação atualizada (README, RUNBOOK)

---

## 📝 Próximos Passos

1. **Executar bateria de testes** (Testes 1-5)
2. **Validar migração Unimed Guaxupé** com novo código
3. **Atualizar RUNBOOK** com --force-overwrite
4. **Adicionar testes de regressão** (pytest)
5. **Revisar outros migrators** (verificar se precisam de fix similar)

---

## 📚 Referências

- **Bug Report**: [D21-BUG-CRITICO-IDEMPOTENCIA-DEDUPLICACAO-GLOBAL-2026-05-26.md](./debates/D21-BUG-CRITICO-IDEMPOTENCIA-DEDUPLICACAO-GLOBAL-2026-05-26.md)
- **Inspiração**: `src/migrators/contacts_migrator.py` (linhas 125-137)
- **Padrão**: Pre-process duplicates → register mappings → skip INSERT
- **Exit Codes**: 0=success, 1=partial, 3=catastrophic, 4=account exists, 5=cleanup error

---

*Gerado automaticamente em 2026-05-26 — Correções P0 Bug D21*
