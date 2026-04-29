# Guia de Alterações Técnicas — Migração Chatwoot
**Data**: 2026-04-29  
**Objetivo**: Documentar alterações necessárias para otimizar processo de migração  

---

## 1. Alterações em Scripts de Migração

### 1.1 Adicionar Validação Automática Pós-Migração

**Arquivo**: `src/migrators/conversation_migrator.py` (exemplo)

**Adicionar método**:
```python
def validate_migration(
    self, 
    account_id_source: int, 
    account_id_dest: int,
    sample_size: int = 100
) -> dict:
    """Valida migração com amostragem aleatória.
    
    Args:
        account_id_source: ID do account no SOURCE
        account_id_dest: ID do account no DEST (pode ser diferente)
        sample_size: Número de registros para amostrar
        
    Returns:
        Dict com estatísticas de validação
    """
    from sqlalchemy import text
    import random
    
    # Coletar IDs do SOURCE
    query_src = text("""
        SELECT id, display_id 
        FROM conversations 
        WHERE account_id = :account_id
        ORDER BY RANDOM()
        LIMIT :limit
    """)
    
    with self.source_conn.execute(
        query_src, 
        {"account_id": account_id_source, "limit": sample_size}
    ) as result:
        source_samples = [(row[0], row[1]) for row in result.fetchall()]
    
    # Validar no DEST
    found = 0
    not_found = []
    
    query_dest = text("""
        SELECT id FROM conversations
        WHERE display_id = :display_id AND account_id = :account_id
    """)
    
    for src_id, display_id in source_samples:
        with self.dest_conn.execute(
            query_dest,
            {"display_id": display_id, "account_id": account_id_dest}
        ) as result:
            if result.fetchone():
                found += 1
            else:
                not_found.append(display_id)
    
    return {
        "total_sampled": len(source_samples),
        "found": found,
        "not_found_count": len(not_found),
        "success_rate": found / len(source_samples) * 100,
        "missing_display_ids": not_found[:10]  # Primeiros 10
    }
```

**Uso**:
```python
# Ao final da migração de conversations
validation_result = conversation_migrator.validate_migration(
    account_id_source=1,
    account_id_dest=1,
    sample_size=100
)

if validation_result["success_rate"] < 95:
    logger.warning(
        f"Taxa de sucesso abaixo do esperado: {validation_result['success_rate']:.1f}%"
    )
    logger.warning(f"Display IDs ausentes: {validation_result['missing_display_ids']}")
```

---

### 1.2 Implementar Modo MERGE vs. FULL Migration

**Arquivo**: `src/migrators/base_migrator.py`

**Adicionar enum**:
```python
from enum import Enum

class MigrationStrategy(Enum):
    """Estratégia de migração."""
    FULL = "full"           # Migrar tudo, assume DEST vazio
    MERGE = "merge"         # Mesclar com dados existentes
    INCREMENTAL = "incr"    # Apenas novos desde última migração
```

**Modificar método migrate**:
```python
def migrate(
    self,
    account_id_source: int,
    account_id_dest: int,
    strategy: MigrationStrategy = MigrationStrategy.FULL,
    **kwargs
) -> dict:
    """Executa migração com estratégia especificada.
    
    Args:
        account_id_source: ID no SOURCE
        account_id_dest: ID no DEST
        strategy: FULL, MERGE ou INCREMENTAL
        **kwargs: Parâmetros adicionais (ex: date_from para INCREMENTAL)
        
    Returns:
        Dict com estatísticas de migração
    """
    logger.info(f"Iniciando migração {strategy.value} para account {account_id_source}")
    
    if strategy == MigrationStrategy.MERGE:
        # Verificar registros existentes no DEST
        existing_ids = self._get_existing_display_ids(account_id_dest)
        logger.info(f"DEST já possui {len(existing_ids)} conversations")
        
    elif strategy == MigrationStrategy.INCREMENTAL:
        last_migration_date = kwargs.get("date_from")
        if not last_migration_date:
            raise ValueError("INCREMENTAL requires 'date_from' parameter")
        logger.info(f"Migrando apenas após {last_migration_date}")
    
    # ... resto da lógica de migração
```

**Helper method**:
```python
def _get_existing_display_ids(self, account_id: int) -> set[int]:
    """Retorna set de display_ids já presentes no DEST."""
    from sqlalchemy import text
    
    query = text("""
        SELECT DISTINCT display_id 
        FROM conversations 
        WHERE account_id = :account_id
    """)
    
    with self.dest_conn.execute(query, {"account_id": account_id}) as result:
        return {row[0] for row in result.fetchall()}
```

---

### 1.3 Logging Estruturado de Falhas

**Arquivo**: `src/utils/migration_logger.py` (novo)

```python
"""Logger estruturado para migração."""
import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

@dataclass
class MigrationFailure:
    """Registro de falha de migração."""
    timestamp: str
    account_id_source: int
    account_id_dest: int
    entity_type: str  # "conversation", "message", "contact", etc.
    entity_id_source: int
    display_id: int | None
    error_type: str
    error_message: str
    context: dict[str, Any] | None = None

class MigrationLogger:
    """Logger com suporte a registro estruturado de falhas."""
    
    def __init__(self, log_dir: Path):
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.failures: list[MigrationFailure] = []
        self.logger = logging.getLogger(__name__)
    
    def log_failure(
        self,
        account_id_source: int,
        account_id_dest: int,
        entity_type: str,
        entity_id_source: int,
        error_type: str,
        error_message: str,
        display_id: int | None = None,
        context: dict | None = None
    ):
        """Registra falha de migração."""
        failure = MigrationFailure(
            timestamp=datetime.now().isoformat(),
            account_id_source=account_id_source,
            account_id_dest=account_id_dest,
            entity_type=entity_type,
            entity_id_source=entity_id_source,
            display_id=display_id,
            error_type=error_type,
            error_message=error_message,
            context=context
        )
        self.failures.append(failure)
        
        self.logger.warning(
            f"Migration failure: {entity_type} id={entity_id_source} "
            f"(display_id={display_id}) - {error_type}: {error_message}"
        )
    
    def save_failures(self, filename: str = None):
        """Salva falhas em JSON."""
        if not self.failures:
            self.logger.info("Nenhuma falha registrada")
            return
        
        if filename is None:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"migration_failures_{ts}.json"
        
        filepath = self.log_dir / filename
        
        data = {
            "total_failures": len(self.failures),
            "by_type": self._group_by_type(),
            "failures": [asdict(f) for f in self.failures]
        }
        
        filepath.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        
        self.logger.info(f"Falhas salvas em: {filepath}")
    
    def _group_by_type(self) -> dict[str, int]:
        """Agrupa falhas por tipo de erro."""
        result = {}
        for failure in self.failures:
            result[failure.error_type] = result.get(failure.error_type, 0) + 1
        return result
```

**Uso no migrator**:
```python
from src.utils.migration_logger import MigrationLogger

class ConversationMigrator:
    def __init__(self, ...):
        # ...
        self.mig_logger = MigrationLogger(Path("logs/migration"))
    
    def migrate_conversation(self, conv_id: int):
        try:
            # ... lógica de migração
            pass
        except IntegrityError as e:
            self.mig_logger.log_failure(
                account_id_source=self.account_id_source,
                account_id_dest=self.account_id_dest,
                entity_type="conversation",
                entity_id_source=conv_id,
                display_id=conv_data.get("display_id"),
                error_type="IntegrityError",
                error_message=str(e),
                context={"inbox_id": conv_data.get("inbox_id")}
            )
            raise
    
    def finalize(self):
        """Ao final da migração."""
        self.mig_logger.save_failures()
```

---

## 2. Alterações em Configuração

### 2.1 Arquivo de Configuração de Migração

**Arquivo**: `config/migration_config.yaml` (novo)

```yaml
# Configuração de migração por account
accounts:
  vya_digital:
    source_id: 1
    dest_id: 1
    strategy: merge  # merge | full | incremental
    validation:
      enabled: true
      sample_size: 100
      threshold: 80  # % mínimo de sucesso
    filters:
      # Filtros opcionais
      inboxes: [3, 7, 32, 34, 39, 53, 84, 85, 89, 103, 122, 123, 125]
      date_from: null  # "2024-01-01" para incremental
      status: null     # [0, 1, 2] para filtrar por status
    
  sol_copernico:
    source_id: 4
    dest_id: 44
    strategy: full
    validation:
      enabled: true
      sample_size: 100
      threshold: 95
    
  unimed_pocos_pj:
    source_id: 17
    dest_id: 17
    strategy: merge
    validation:
      enabled: true
      sample_size: 100
      threshold: 95
  
  unimed_pocos_pf:
    source_id: 18
    dest_id: 45
    strategy: full
    validation:
      enabled: true
      sample_size: 100
      threshold: 95
  
  unimed_guaxupe:
    source_id: 25
    dest_id: 46
    strategy: full
    validation:
      enabled: true
      sample_size: 100
      threshold: 95

# Configuração geral
general:
  batch_size: 1000
  rate_limit_ms: 0  # 0 = sem rate limit
  parallel_workers: 4
  dry_run: false
  
  # Retry logic
  max_retries: 3
  retry_delay_s: 5
  
  # Logs
  log_level: INFO
  log_dir: logs/migration
  save_failures: true
```

**Loader**:
```python
import yaml
from pathlib import Path
from dataclasses import dataclass

@dataclass
class AccountConfig:
    source_id: int
    dest_id: int
    strategy: str
    validation_enabled: bool
    validation_sample_size: int
    validation_threshold: int
    filters: dict

class MigrationConfig:
    def __init__(self, config_file: Path):
        with open(config_file) as f:
            self.data = yaml.safe_load(f)
    
    def get_account_config(self, account_key: str) -> AccountConfig:
        """Retorna configuração de um account."""
        acc = self.data["accounts"][account_key]
        return AccountConfig(
            source_id=acc["source_id"],
            dest_id=acc["dest_id"],
            strategy=acc["strategy"],
            validation_enabled=acc["validation"]["enabled"],
            validation_sample_size=acc["validation"]["sample_size"],
            validation_threshold=acc["validation"]["threshold"],
            filters=acc.get("filters", {})
        )
```

---

## 3. Queries SQL de Diagnóstico

### 3.1 Identificar Conversations Ausentes

```sql
-- Encontrar display_ids do SOURCE que não estão no DEST
-- Para account_id=1 (ajustar para outros accounts)

WITH source_ids AS (
    SELECT display_id
    FROM chatwoot_dev1_db.conversations
    WHERE account_id = 1
),
dest_ids AS (
    SELECT display_id
    FROM chatwoot004_dev1_db.conversations
    WHERE account_id = 1
)
SELECT s.display_id
FROM source_ids s
LEFT JOIN dest_ids d ON s.display_id = d.display_id
WHERE d.display_id IS NULL
ORDER BY s.display_id
LIMIT 100;
```

### 3.2 Análise de Distribuição Temporal

```sql
-- Verificar se migração filtrou por data
SELECT 
    DATE_TRUNC('month', created_at) as mes,
    COUNT(*) as total
FROM conversations
WHERE account_id = 1
GROUP BY mes
ORDER BY mes DESC;

-- Comparar com DEST
SELECT 
    DATE_TRUNC('month', created_at) as mes,
    COUNT(*) as total
FROM chatwoot004_dev1_db.conversations
WHERE account_id = 1
GROUP BY mes
ORDER BY mes DESC;
```

### 3.3 Identificar Colisões de Display_ID

```sql
-- Display_ids duplicados no DEST (indicam merge com dados existentes)
SELECT 
    display_id,
    COUNT(*) as duplicatas,
    ARRAY_AGG(id) as conversation_ids,
    ARRAY_AGG(inbox_id) as inbox_ids
FROM conversations
WHERE account_id = 1
GROUP BY display_id
HAVING COUNT(*) > 1
ORDER BY duplicatas DESC;
```

### 3.4 Verificar Integridade Referencial

```sql
-- Conversations com inbox_id inválido
SELECT 
    c.id,
    c.display_id,
    c.inbox_id,
    i.id as inbox_exists
FROM conversations c
LEFT JOIN inboxes i ON i.id = c.inbox_id AND i.account_id = c.account_id
WHERE c.account_id = 1 AND i.id IS NULL;

-- Conversations com contact_id inválido
SELECT 
    c.id,
    c.display_id,
    c.contact_id,
    co.id as contact_exists
FROM conversations c
LEFT JOIN contacts co ON co.id = c.contact_id AND co.account_id = c.account_id
WHERE c.account_id = 1 AND c.contact_id IS NOT NULL AND co.id IS NULL;
```

---

## 4. Script de Correção de Dados

### 4.1 Re-migrar Conversations Faltantes

**Arquivo**: `scripts/remigrate_missing_conversations.py`

```python
#!/usr/bin/env python3
"""Re-migra conversations que falharam na migração inicial."""
import json
import logging
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.factory.connection_factory import ConnectionFactory
from src.migrators.conversation_migrator import ConversationMigrator
from sqlalchemy import text

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

def get_missing_display_ids(
    source_conn,
    dest_conn,
    account_id_source: int,
    account_id_dest: int
) -> list[int]:
    """Retorna display_ids do SOURCE ausentes no DEST."""
    
    # SOURCE
    query_src = text("""
        SELECT DISTINCT display_id 
        FROM conversations 
        WHERE account_id = :account_id
    """)
    source_ids = {
        row[0] for row in 
        source_conn.execute(query_src, {"account_id": account_id_source})
    }
    
    # DEST
    query_dest = text("""
        SELECT DISTINCT display_id 
        FROM conversations 
        WHERE account_id = :account_id
    """)
    dest_ids = {
        row[0] for row in 
        dest_conn.execute(query_dest, {"account_id": account_id_dest})
    }
    
    missing = source_ids - dest_ids
    return sorted(missing)

def main():
    account_id_source = 1
    account_id_dest = 1
    
    factory = ConnectionFactory()
    source_engine = factory.create_source_engine()
    dest_engine = factory.create_dest_engine()
    
    with source_engine.connect() as src, dest_engine.connect() as dst:
        missing = get_missing_display_ids(src, dst, account_id_source, account_id_dest)
        
        log.info(f"Encontrados {len(missing)} display_ids ausentes")
        
        if not missing:
            log.info("Nenhuma conversation faltando. Migração completa!")
            return 0
        
        # Re-migrar
        migrator = ConversationMigrator(src, dst)
        
        for display_id in missing:
            try:
                # Buscar conversation original
                query = text("""
                    SELECT id FROM conversations
                    WHERE account_id = :account_id AND display_id = :display_id
                """)
                result = src.execute(query, {
                    "account_id": account_id_source,
                    "display_id": display_id
                })
                row = result.fetchone()
                
                if row:
                    conv_id = row[0]
                    migrator.migrate_single_conversation(
                        conv_id,
                        account_id_dest
                    )
                    log.info(f"✓ Re-migrado: display_id={display_id}")
                else:
                    log.warning(f"✗ Não encontrado no SOURCE: display_id={display_id}")
                    
            except Exception as e:
                log.error(f"✗ Erro ao migrar display_id={display_id}: {e}")
        
        dst.commit()
        log.info(f"Re-migração concluída. Tentou migrar {len(missing)} conversations")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

---

## 5. Melhorias em Testes

### 5.1 Teste de Validação Automatizado

**Arquivo**: `test/integration/test_validation.py`

```python
"""Testes de validação de migração."""
import pytest
from src.validation.migration_validator import MigrationValidator

def test_validation_vya_digital(source_conn, dest_conn, api_config):
    """Testa validação do account Vya Digital."""
    validator = MigrationValidator(source_conn, dest_conn, api_config)
    
    result = validator.validate_account(
        account_id_source=1,
        account_id_dest=1,
        sample_size=100
    )
    
    # Para MERGE, aceitar threshold menor
    assert result["success_rate"] >= 80, \
        f"Taxa de sucesso abaixo do esperado: {result['success_rate']}%"
    
    assert result["api_success_rate"] >= 80, \
        f"API success rate abaixo do esperado: {result['api_success_rate']}%"

def test_validation_full_migration(source_conn, dest_conn, api_config):
    """Testa validação de migração completa (Sol Copernico)."""
    validator = MigrationValidator(source_conn, dest_conn, api_config)
    
    result = validator.validate_account(
        account_id_source=4,
        account_id_dest=44,
        sample_size=100
    )
    
    # Para FULL migration, exigir threshold alto
    assert result["success_rate"] >= 95, \
        f"Taxa de sucesso abaixo do esperado: {result['success_rate']}%"
```

---

## 6. Checklist de Deploy

### Pré-Migração
- [ ] Backup completo do DEST
- [ ] Verificar espaço em disco (DEST precisa ~2x o tamanho do SOURCE)
- [ ] Gerar token de API válido
- [ ] Atualizar `.secrets/generate_erd.json` com credenciais corretas
- [ ] Validar conectividade: SOURCE, DEST, API
- [ ] Revisar `config/migration_config.yaml`

### Durante Migração
- [ ] Monitorar logs em tempo real: `tail -f logs/migration/*.log`
- [ ] Verificar uso de CPU/memória
- [ ] Validar primeiros 100 registros antes de continuar
- [ ] Salvar snapshots de progresso a cada 10k registros

### Pós-Migração
- [ ] Executar validação automática (100 registros por account)
- [ ] Verificar taxa de sucesso ≥ threshold configurado
- [ ] Analisar arquivo de falhas: `logs/migration_failures_*.json`
- [ ] Validar manualmente amostra via interface web
- [ ] Testar APIs críticas (envio de mensagem, criação de conversation)
- [ ] Documentar qualquer desvio do esperado

### Rollback (se necessário)
- [ ] Restaurar backup do DEST
- [ ] Revisar logs de erro
- [ ] Ajustar configuração/código
- [ ] Re-testar em ambiente de staging

---

## 7. Resumo de Arquivos Criados/Modificados

### Novos Arquivos
```
config/
  migration_config.yaml          # Configuração centralizada

src/utils/
  migration_logger.py            # Logger estruturado

scripts/
  remigrate_missing_conversations.py  # Re-migração de falhas

test/integration/
  test_validation.py             # Testes automatizados

.tmp/
  18_validacao_multi_account.py  # Validação multi-account
  gerar_novo_token.py            # Gerador de tokens API
  testar_autenticacao_api.py     # Teste seguro de autenticação
```

### Arquivos Modificados
```
src/migrators/
  base_migrator.py              # Adicionar estratégias MERGE/FULL
  conversation_migrator.py      # Adicionar validate_migration()

README.md                       # Documentar novos scripts
```

---

**Documento gerado**: 2026-04-29  
**Próxima revisão**: Após implementação das alterações  
**Responsável**: Equipe de engenharia + DevOps
