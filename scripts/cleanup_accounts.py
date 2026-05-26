#!/usr/bin/env python3
"""Rollback/Cleanup de accounts específicos do DEST."""

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, text

SECRETS_FILE = Path(__file__).parent.parent / ".secrets" / "generate_erd.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_config(key: str) -> dict:
    """Carrega configuração do secrets."""
    if not SECRETS_FILE.exists():
        raise FileNotFoundError(f"Secrets file not found: {SECRETS_FILE}")

    with open(SECRETS_FILE, "r", encoding="utf-8") as f:
        secrets = json.load(f)

    if key not in secrets:
        available = [k for k in secrets if not k.startswith("_")]
        raise KeyError(f"Key '{key}' not found. Available: {available}")

    config = secrets[key]
    return {
        "host": config["host"],
        "port": config["port"],
        "database": config["database"],
        "user": config["username"],
        "password": config["password"],
        "sslmode": config.get("sslmode", "disable"),
    }


def delete_account_data(engine, account_ids: list[int], dry_run: bool = False) -> dict:
    """Deleta todos os dados relacionados aos account_ids.

    Args:
        engine: SQLAlchemy engine
        account_ids: Lista de account IDs para deletar
        dry_run: Se True, apenas conta sem deletar

    Returns:
        Dict com contadores de registros deletados por tabela
    """
    stats = {}

    with engine.begin() as conn:
        logger.info("=== Iniciando cleanup de accounts %s ===", account_ids)
        logger.info("Modo: %s", "DRY-RUN (apenas contagem)" if dry_run else "REAL (deletando)")

        # 1. conversation_labels (taggings)
        query = text("""
            SELECT COUNT(*) FROM taggings t
            JOIN conversations c ON c.id = t.taggable_id AND t.taggable_type = 'Conversation'
            WHERE c.account_id = ANY(:account_ids)
        """)
        count = conn.execute(query, {"account_ids": account_ids}).scalar()
        stats["conversation_labels"] = count
        logger.info("conversation_labels (taggings): %d registros", count)

        if not dry_run and count > 0:
            delete_query = text("""
                DELETE FROM taggings
                WHERE id IN (
                    SELECT t.id FROM taggings t
                    JOIN conversations c ON c.id = t.taggable_id AND t.taggable_type = 'Conversation'
                    WHERE c.account_id = ANY(:account_ids)
                )
            """)
            conn.execute(delete_query, {"account_ids": account_ids})
            logger.info("✅ conversation_labels deletados")

        # 2. active_storage_variant_records
        query = text("""
            SELECT COUNT(*) FROM active_storage_variant_records asvr
            JOIN active_storage_blobs asb ON asb.id = asvr.blob_id
            JOIN active_storage_attachments asa ON asa.blob_id = asb.id
            JOIN attachments att ON att.id = asa.record_id AND asa.record_type = 'Attachment'
            JOIN messages m ON m.id = att.message_id
            JOIN conversations c ON c.id = m.conversation_id
            WHERE c.account_id = ANY(:account_ids)
        """)
        count = conn.execute(query, {"account_ids": account_ids}).scalar()
        stats["active_storage_variant_records"] = count
        logger.info("active_storage_variant_records: %d registros", count)

        if not dry_run and count > 0:
            delete_query = text("""
                DELETE FROM active_storage_variant_records
                WHERE blob_id IN (
                    SELECT DISTINCT asb.id FROM active_storage_blobs asb
                    JOIN active_storage_attachments asa ON asa.blob_id = asb.id
                    JOIN attachments att ON att.id = asa.record_id AND asa.record_type = 'Attachment'
                    JOIN messages m ON m.id = att.message_id
                    JOIN conversations c ON c.id = m.conversation_id
                    WHERE c.account_id = ANY(:account_ids)
                )
            """)
            conn.execute(delete_query, {"account_ids": account_ids})
            logger.info("✅ active_storage_variant_records deletados")

        # 3. active_storage_attachments
        query = text("""
            SELECT COUNT(*) FROM active_storage_attachments asa
            JOIN attachments att ON att.id = asa.record_id AND asa.record_type = 'Attachment'
            JOIN messages m ON m.id = att.message_id
            JOIN conversations c ON c.id = m.conversation_id
            WHERE c.account_id = ANY(:account_ids)
        """)
        count = conn.execute(query, {"account_ids": account_ids}).scalar()
        stats["active_storage_attachments"] = count
        logger.info("active_storage_attachments: %d registros", count)

        if not dry_run and count > 0:
            delete_query = text("""
                DELETE FROM active_storage_attachments
                WHERE id IN (
                    SELECT asa.id FROM active_storage_attachments asa
                    JOIN attachments att ON att.id = asa.record_id AND asa.record_type = 'Attachment'
                    JOIN messages m ON m.id = att.message_id
                    JOIN conversations c ON c.id = m.conversation_id
                    WHERE c.account_id = ANY(:account_ids)
                )
            """)
            conn.execute(delete_query, {"account_ids": account_ids})
            logger.info("✅ active_storage_attachments deletados")

        # 4. active_storage_blobs (órfãos após deletar attachments)
        # Vamos marcar os blobs para deleção depois de deletar attachments

        # 5. attachments
        query = text("""
            SELECT COUNT(*) FROM attachments att
            JOIN messages m ON m.id = att.message_id
            JOIN conversations c ON c.id = m.conversation_id
            WHERE c.account_id = ANY(:account_ids)
        """)
        count = conn.execute(query, {"account_ids": account_ids}).scalar()
        stats["attachments"] = count
        logger.info("attachments: %d registros", count)

        if not dry_run and count > 0:
            delete_query = text("""
                DELETE FROM attachments
                WHERE message_id IN (
                    SELECT m.id FROM messages m
                    JOIN conversations c ON c.id = m.conversation_id
                    WHERE c.account_id = ANY(:account_ids)
                )
            """)
            conn.execute(delete_query, {"account_ids": account_ids})
            logger.info("✅ attachments deletados")

        # 6. messages
        query = text("""
            SELECT COUNT(*) FROM messages m
            JOIN conversations c ON c.id = m.conversation_id
            WHERE c.account_id = ANY(:account_ids)
        """)
        count = conn.execute(query, {"account_ids": account_ids}).scalar()
        stats["messages"] = count
        logger.info("messages: %d registros", count)

        if not dry_run and count > 0:
            delete_query = text("""
                DELETE FROM messages
                WHERE conversation_id IN (
                    SELECT id FROM conversations
                    WHERE account_id = ANY(:account_ids)
                )
            """)
            conn.execute(delete_query, {"account_ids": account_ids})
            logger.info("✅ messages deletados")

        # 7. conversations
        query = text("""
            SELECT COUNT(*) FROM conversations
            WHERE account_id = ANY(:account_ids)
        """)
        count = conn.execute(query, {"account_ids": account_ids}).scalar()
        stats["conversations"] = count
        logger.info("conversations: %d registros", count)

        if not dry_run and count > 0:
            delete_query = text("DELETE FROM conversations WHERE account_id = ANY(:account_ids)")
            conn.execute(delete_query, {"account_ids": account_ids})
            logger.info("✅ conversations deletados")

        # 8. contact_inboxes
        query = text("""
            SELECT COUNT(*) FROM contact_inboxes ci
            JOIN inboxes i ON i.id = ci.inbox_id
            WHERE i.account_id = ANY(:account_ids)
        """)
        count = conn.execute(query, {"account_ids": account_ids}).scalar()
        stats["contact_inboxes"] = count
        logger.info("contact_inboxes: %d registros", count)

        if not dry_run and count > 0:
            delete_query = text("""
                DELETE FROM contact_inboxes
                WHERE inbox_id IN (
                    SELECT id FROM inboxes WHERE account_id = ANY(:account_ids)
                )
            """)
            conn.execute(delete_query, {"account_ids": account_ids})
            logger.info("✅ contact_inboxes deletados")

        # 9. contacts (CUIDADO: não deletar se compartilhados)
        query = text("""
            SELECT COUNT(*) FROM contacts
            WHERE account_id = ANY(:account_ids)
        """)
        count = conn.execute(query, {"account_ids": account_ids}).scalar()
        stats["contacts"] = count
        logger.info("contacts: %d registros", count)

        if not dry_run and count > 0:
            delete_query = text("DELETE FROM contacts WHERE account_id = ANY(:account_ids)")
            conn.execute(delete_query, {"account_ids": account_ids})
            logger.info("✅ contacts deletados")

        # 10. labels
        query = text("SELECT COUNT(*) FROM labels WHERE account_id = ANY(:account_ids)")
        count = conn.execute(query, {"account_ids": account_ids}).scalar()
        stats["labels"] = count
        logger.info("labels: %d registros", count)

        if not dry_run and count > 0:
            delete_query = text("DELETE FROM labels WHERE account_id = ANY(:account_ids)")
            conn.execute(delete_query, {"account_ids": account_ids})
            logger.info("✅ labels deletados")

        # 11. team_members
        query = text("""
            SELECT COUNT(*) FROM team_members tm
            JOIN teams t ON t.id = tm.team_id
            WHERE t.account_id = ANY(:account_ids)
        """)
        count = conn.execute(query, {"account_ids": account_ids}).scalar()
        stats["team_members"] = count
        logger.info("team_members: %d registros", count)

        if not dry_run and count > 0:
            delete_query = text("""
                DELETE FROM team_members
                WHERE team_id IN (
                    SELECT id FROM teams WHERE account_id = ANY(:account_ids)
                )
            """)
            conn.execute(delete_query, {"account_ids": account_ids})
            logger.info("✅ team_members deletados")

        # 12. teams
        query = text("SELECT COUNT(*) FROM teams WHERE account_id = ANY(:account_ids)")
        count = conn.execute(query, {"account_ids": account_ids}).scalar()
        stats["teams"] = count
        logger.info("teams: %d registros", count)

        if not dry_run and count > 0:
            delete_query = text("DELETE FROM teams WHERE account_id = ANY(:account_ids)")
            conn.execute(delete_query, {"account_ids": account_ids})
            logger.info("✅ teams deletados")

        # 13. account_users (NÃO deletar users, apenas a relação)
        query = text("""
            SELECT COUNT(*) FROM account_users
            WHERE account_id = ANY(:account_ids)
        """)
        count = conn.execute(query, {"account_ids": account_ids}).scalar()
        stats["account_users"] = count
        logger.info("account_users: %d registros", count)

        if not dry_run and count > 0:
            delete_query = text("DELETE FROM account_users WHERE account_id = ANY(:account_ids)")
            conn.execute(delete_query, {"account_ids": account_ids})
            logger.info("✅ account_users deletados")

        # 14. webhooks
        query = text("SELECT COUNT(*) FROM webhooks WHERE account_id = ANY(:account_ids)")
        count = conn.execute(query, {"account_ids": account_ids}).scalar()
        stats["webhooks"] = count
        logger.info("webhooks: %d registros", count)

        if not dry_run and count > 0:
            delete_query = text("DELETE FROM webhooks WHERE account_id = ANY(:account_ids)")
            conn.execute(delete_query, {"account_ids": account_ids})
            logger.info("✅ webhooks deletados")

        # 15. inboxes
        query = text("SELECT COUNT(*) FROM inboxes WHERE account_id = ANY(:account_ids)")
        count = conn.execute(query, {"account_ids": account_ids}).scalar()
        stats["inboxes"] = count
        logger.info("inboxes: %d registros", count)

        if not dry_run and count > 0:
            delete_query = text("DELETE FROM inboxes WHERE account_id = ANY(:account_ids)")
            conn.execute(delete_query, {"account_ids": account_ids})
            logger.info("✅ inboxes deletados")

        # 16. canned_responses
        query = text("SELECT COUNT(*) FROM canned_responses WHERE account_id = ANY(:account_ids)")
        count = conn.execute(query, {"account_ids": account_ids}).scalar()
        stats["canned_responses"] = count
        logger.info("canned_responses: %d registros", count)

        if not dry_run and count > 0:
            delete_query = text("DELETE FROM canned_responses WHERE account_id = ANY(:account_ids)")
            conn.execute(delete_query, {"account_ids": account_ids})
            logger.info("✅ canned_responses deletados")

        # 17. custom_attribute_definitions
        query = text("""
            SELECT COUNT(*) FROM custom_attribute_definitions
            WHERE account_id = ANY(:account_ids)
        """)
        count = conn.execute(query, {"account_ids": account_ids}).scalar()
        stats["custom_attribute_definitions"] = count
        logger.info("custom_attribute_definitions: %d registros", count)

        if not dry_run and count > 0:
            delete_query = text("""
                DELETE FROM custom_attribute_definitions
                WHERE account_id = ANY(:account_ids)
            """)
            conn.execute(delete_query, {"account_ids": account_ids})
            logger.info("✅ custom_attribute_definitions deletados")

        # 18. migration_state — SKIP (estrutura varia, não crítico)
        stats["migration_state"] = 0
        logger.info("migration_state: SKIP")

        # 19. accounts (FINAL)
        query = text("SELECT COUNT(*) FROM accounts WHERE id = ANY(:account_ids)")
        count = conn.execute(query, {"account_ids": account_ids}).scalar()
        stats["accounts"] = count
        logger.info("accounts: %d registros", count)

        if not dry_run and count > 0:
            delete_query = text("DELETE FROM accounts WHERE id = ANY(:account_ids)")
            conn.execute(delete_query, {"account_ids": account_ids})
            logger.info("✅ accounts deletados")

        # 20. Orphan blobs cleanup — DESABILITADO (pode deletar blobs de outros accounts)
        stats["orphan_blobs_deleted"] = 0
        logger.info("Orphan blobs cleanup: SKIP (não seguro)")

    return stats


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Rollback/Cleanup de accounts")
    parser.add_argument(
        "--account-ids", nargs="+", type=int, required=True, help="IDs dos accounts para deletar"
    )
    parser.add_argument("--dry-run", action="store_true", help="Apenas conta, não deleta")
    parser.add_argument(
        "--dest-key",
        default="vya-chat-dev",
        help="Chave do DEST no secrets (default: vya-chat-dev)",
    )

    args = parser.parse_args()

    logger.info("Carregando configuração: %s", args.dest_key)
    config = load_config(args.dest_key)

    uri = (
        f"postgresql://{config['user']}:{config['password']}"
        f"@{config['host']}:{config['port']}/{config['database']}"
        f"?sslmode={config['sslmode']}"
    )
    engine = create_engine(uri, echo=False)

    logger.info("Conectado a: %s", config["database"])

    stats = delete_account_data(engine, args.account_ids, dry_run=args.dry_run)

    logger.info("\n=== SUMÁRIO ===")
    total = sum(v for k, v in stats.items() if k != "orphan_blobs_deleted")
    for table, count in stats.items():
        logger.info("  %-35s: %d", table, count)
    logger.info("  %-35s: %d", "TOTAL", total)

    if args.dry_run:
        logger.warning("\n⚠️ DRY-RUN concluído — nenhum dado foi deletado")
    else:
        logger.info("\n✅ Cleanup concluído com sucesso")

    engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
