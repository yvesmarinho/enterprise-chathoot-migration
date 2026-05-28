#!/usr/bin/env python3
"""
Post-Migration FK Orphan Validator

Validates that all Foreign Key references in DEST database point to existing records.
Helps detect issues like the inbox_id orphan problem that caused ERROR 500.

Usage:
    MIGRATION_DEST_KEY=vya-chat-dev uv run python scripts/validate_fk_orphans.py [--account-id 69]
"""

import json
import logging
from datetime import datetime
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
log = logging.getLogger(__name__)

# Database connection
SECRETS_FILE = Path('.secrets/generate_erd.json')
import os
DEST_KEY = os.environ.get('MIGRATION_DEST_KEY', 'vya-chat-dev')

def load_db_config():
    """Load DB config from secrets file"""
    if not SECRETS_FILE.exists():
        raise FileNotFoundError(f"Secrets file not found: {SECRETS_FILE}")
    
    data = json.loads(SECRETS_FILE.read_text())
    if DEST_KEY not in data:
        raise KeyError(f"Key {DEST_KEY!r} not found in secrets")
    
    inst = data[DEST_KEY]
    return {
        'dbname': inst['database'],
        'user': inst['username'],
        'password': inst['password'],
        'host': inst['host'],
        'port': inst['port'],
    }

DB_CONFIG = load_db_config()

# Define FK validations: (source_table, fk_column, target_table, target_column)
FK_VALIDATIONS = [
    # Messages table
    ('messages', 'inbox_id', 'inboxes', 'id'),
    ('messages', 'account_id', 'accounts', 'id'),
    ('messages', 'conversation_id', 'conversations', 'id'),
    
    # Conversations table
    ('conversations', 'inbox_id', 'inboxes', 'id'),
    ('conversations', 'account_id', 'accounts', 'id'),
    
    # Contact Inboxes
    ('contact_inboxes', 'inbox_id', 'inboxes', 'id'),
    ('contact_inboxes', 'contact_id', 'contacts', 'id'),
    
    # Inbox Members
    ('inbox_members', 'inbox_id', 'inboxes', 'id'),
    ('inbox_members', 'user_id', 'users', 'id'),
    
    # Webhooks
    ('webhooks', 'inbox_id', 'inboxes', 'id'),
    ('webhooks', 'account_id', 'accounts', 'id'),
]


def validate_fk(conn, source_table, fk_column, target_table, target_column, account_id=None):
    """
    Validate that all non-NULL values in fk_column exist in target table.
    
    Returns: (orphan_count, orphan_samples)
    """
    where_clause = ""
    params = []
    
    if account_id and 'account_id' in [fk_column, 'account_id']:
        if fk_column == 'account_id':
            where_clause = "WHERE account_id = %s"
            params = [account_id]
        elif hasattr(conn.cursor(), 'description'):
            # Check if account_id column exists
            check_query = f"""
            SELECT 1 FROM information_schema.columns 
            WHERE table_name = '{source_table}' AND column_name = 'account_id'
            """
            with conn.cursor() as cur:
                cur.execute(check_query)
                if cur.fetchone():
                    where_clause = "WHERE account_id = %s"
                    params = [account_id]
    
    # Count orphans
    count_query = f"""
    SELECT COUNT(*) as orphan_count
    FROM {source_table} t1
    WHERE {fk_column} IS NOT NULL
      AND NOT EXISTS (
        SELECT 1 FROM {target_table} t2 
        WHERE t2.{target_column} = t1.{fk_column}
      )
      {f'AND t1.account_id = %s' if account_id and 'account_id' in ['account_id'] else ''}
    """
    
    # Simplified count query
    count_query = f"""
    SELECT COUNT(*) as orphan_count
    FROM {source_table} t1
    WHERE {fk_column} IS NOT NULL
      AND NOT EXISTS (
        SELECT 1 FROM {target_table} t2 
        WHERE t2.{target_column} = t1.{fk_column}
      )
    """
    
    if account_id:
        count_query += f" AND account_id = %s"
        params = [account_id]
    
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(count_query, params if params else ())
        result = cur.fetchone()
        orphan_count = result['orphan_count'] if result else 0
    
    # Get samples
    sample_query = f"""
    SELECT t1.id, t1.{fk_column}, COUNT(*) as count
    FROM {source_table} t1
    WHERE {fk_column} IS NOT NULL
      AND NOT EXISTS (
        SELECT 1 FROM {target_table} t2 
        WHERE t2.{target_column} = t1.{fk_column}
      )
    """
    
    if account_id:
        sample_query += f" AND account_id = %s"
        params = [account_id]
    
    sample_query += f" GROUP BY t1.id, t1.{fk_column} LIMIT 5"
    
    samples = []
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sample_query, params if params else ())
        samples = cur.fetchall()
    
    return orphan_count, samples


def main():
    """Main validation flow"""
    start_time = datetime.now()
    log.info("=" * 80)
    log.info("Starting FK Orphan Validation")
    log.info("=" * 80)
    
    import sys
    account_id = None
    if len(sys.argv) > 1 and sys.argv[1] == '--account-id' and len(sys.argv) > 2:
        account_id = int(sys.argv[2])
        log.info(f"Validating Account {account_id} only")
    
    result = {
        'timestamp': start_time.isoformat(),
        'account_id': account_id,
        'status': 'running',
        'validations': []
    }
    
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        log.info(f"✅ Connected to {DB_CONFIG['dbname']}")
        
        total_orphans = 0
        issues_found = []
        
        for source_table, fk_column, target_table, target_column in FK_VALIDATIONS:
            log.info(f"\n▶ Validating {source_table}.{fk_column} → {target_table}.{target_column}")
            
            try:
                orphan_count, samples = validate_fk(
                    conn, source_table, fk_column, target_table, target_column, account_id
                )
                
                validation_result = {
                    'source_table': source_table,
                    'fk_column': fk_column,
                    'target_table': target_table,
                    'target_column': target_column,
                    'orphan_count': orphan_count,
                    'samples': [dict(s) for s in samples]
                }
                result['validations'].append(validation_result)
                
                if orphan_count == 0:
                    log.info(f"  ✅ OK: 0 orphans")
                else:
                    log.warning(f"  ❌ ISSUE: {orphan_count} orphaned records")
                    for sample in samples:
                        log.warning(f"     Sample: {source_table}.id={sample['id']}, {fk_column}={sample[fk_column]}")
                    issues_found.append({
                        'table': source_table,
                        'column': fk_column,
                        'count': orphan_count
                    })
                    total_orphans += orphan_count
                    
            except Exception as e:
                log.warning(f"  ⚠️  Could not validate (table may not exist): {e}")
                validation_result = {
                    'source_table': source_table,
                    'fk_column': fk_column,
                    'target_table': target_table,
                    'target_column': target_column,
                    'error': str(e)
                }
                result['validations'].append(validation_result)
        
        conn.close()
        
        # Summary
        log.info("\n" + "=" * 80)
        if total_orphans == 0:
            log.info("✅ VALIDATION PASSED: No FK orphans detected")
            result['status'] = 'success'
        else:
            log.error(f"❌ VALIDATION FAILED: {total_orphans} total orphaned records found")
            log.error(f"Issues: {issues_found}")
            result['status'] = 'failed'
            result['issues'] = issues_found
        
    except Exception as e:
        log.error(f"❌ Execution error: {e}", exc_info=True)
        result['status'] = 'error'
        result['error'] = str(e)
    
    finally:
        # Save result
        end_time = datetime.now()
        result['duration_seconds'] = (end_time - start_time).total_seconds()
        
        output_path = Path('.tmp') / f'validate_fk_orphans_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w') as f:
            json.dump(result, f, indent=2, default=str, ensure_ascii=False)
        
        log.info(f"\nResult saved to: {output_path}")
        log.info("=" * 80)
        
        return result


if __name__ == '__main__':
    main()
