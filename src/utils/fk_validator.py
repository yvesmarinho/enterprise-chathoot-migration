"""FK referential integrity validator for the destination database.

:description: Checks each FK relationship in the Chatwoot schema and reports
    orphan counts.  A zero orphan count on all relationships confirms that the
    migration preserved full referential integrity.

    Relationships checked (from data-model.md FK graph):

    +---------------------+--------+-----------+--------+
    | Child table         | FK col | Parent    | PK col |
    +=====================+========+===========+========+
    | inboxes             | account_id | accounts | id  |
    | teams               | account_id | accounts | id  |
    | labels              | account_id | accounts | id  |
    | contacts            | account_id | accounts | id  |
    | conversations       | account_id | accounts | id  |
    | conversations       | inbox_id   | inboxes  | id  |
    | messages            | account_id | accounts | id  |
    | messages            | conversation_id | conversations | id |
    | attachments         | message_id | messages | id  |
    +---------------------+--------+-----------+--------+

    ``contact_id``, ``assignee_id``, ``team_id``, ``sender_id`` are nullable
    and intentionally excluded (NULL-out strategy documented in tasks.md).

    Example::

        validator = FKValidator()
        report = validator.validate(dest_engine)
        print(report.orphan_counts)   # {'inboxes.account_id → accounts.id': 0, ...}
        assert report.is_clean
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

# Each tuple: (child_table, fk_column, parent_table, parent_pk, account_scope)
# account_scope: SQL expression appended as ``AND {account_scope}`` when an
#   account_id is provided.  Uses ``:account_id`` as the bind-parameter name.
#   ``None`` means no account-level scoping is applied (unscoped full-table scan).
_FK_RELATIONSHIPS: list[tuple[str, str, str, str, str | None]] = [
    ("inboxes", "account_id", "accounts", "id", "account_id = :account_id"),
    ("teams", "account_id", "accounts", "id", "account_id = :account_id"),
    ("labels", "account_id", "accounts", "id", "account_id = :account_id"),
    ("contacts", "account_id", "accounts", "id", "account_id = :account_id"),
    ("conversations", "account_id", "accounts", "id", "account_id = :account_id"),
    ("conversations", "inbox_id", "inboxes", "id", "account_id = :account_id"),
    (
        "contact_inboxes",
        "contact_id",
        "contacts",
        "id",
        "contact_id IN (SELECT id FROM contacts WHERE account_id = :account_id)",
    ),
    (
        "contact_inboxes",
        "inbox_id",
        "inboxes",
        "id",
        "contact_id IN (SELECT id FROM contacts WHERE account_id = :account_id)",
    ),
    ("messages", "account_id", "accounts", "id", "account_id = :account_id"),
    (
        "messages",
        "conversation_id",
        "conversations",
        "id",
        "account_id = :account_id",
    ),
    (
        "attachments",
        "message_id",
        "messages",
        "id",
        "account_id = :account_id",
    ),
    ("attachments", "account_id", "accounts", "id", "account_id = :account_id"),
]


@dataclass
class ValidationReport:
    """Result of FK validation across all checked relationships.

    :param orphan_counts: Mapping of relationship label → orphan count.
    :type orphan_counts: dict[str, int]
    """

    orphan_counts: dict[str, int] = field(default_factory=dict)

    @property
    def is_clean(self) -> bool:
        """Return True iff all FK relationships have zero orphans.

        :returns: True when no orphan rows exist.
        :rtype: bool
        """
        return all(v == 0 for v in self.orphan_counts.values())

    @property
    def total_orphans(self) -> int:
        """Total count of orphan rows across all relationships.

        :returns: Sum of all orphan counts.
        :rtype: int
        """
        return sum(self.orphan_counts.values())


class FKValidator:
    """Validates referential integrity in the destination database.

    Example::

        validator = FKValidator()
        report = validator.validate(dest_engine)
        if not report.is_clean:
            print(f"{report.total_orphans} orphan FK rows detected")
    """

    def validate(
        self,
        dest_engine: Engine,
        account_id: int | None = None,
    ) -> ValidationReport:
        """Run all FK checks and return a :class:`ValidationReport`.

        Each check runs ``COUNT(*) WHERE fk_col IS NOT NULL AND fk_col NOT IN
        (SELECT id FROM parent_table)``.

        When *account_id* is provided, an additional ``AND child_account_col =
        account_id`` clause is appended for every relationship that declares a
        ``child_account_col`` (5th element in :data:`_FK_RELATIONSHIPS`).  This
        scopes the validation to a single migrated account, avoiding false
        positives from pre-existing rows belonging to other accounts.

        :param dest_engine: Engine connected to the destination database.
        :type dest_engine: Engine
        :param account_id: Destination account ID to scope checks.  When
            ``None``, the entire table is scanned (unscoped).
        :type account_id: int | None
        :returns: Validation report with orphan counts per relationship.
        :rtype: ValidationReport
        """
        report = ValidationReport()

        with dest_engine.connect() as conn:
            for child, fk_col, parent, parent_pk, account_scope in _FK_RELATIONSHIPS:
                rel_label = f"{child}.{fk_col} → {parent}.{parent_pk}"
                try:
                    account_clause = ""
                    params: dict = {}
                    if account_id is not None and account_scope is not None:
                        account_clause = f" AND {account_scope}"
                        params = {"account_id": account_id}
                    row = conn.execute(
                        text(
                            f"SELECT COUNT(*) FROM {child} "  # noqa: S608
                            f"WHERE {fk_col} IS NOT NULL "
                            f"AND {fk_col} NOT IN (SELECT {parent_pk} FROM {parent})"
                            f"{account_clause}"
                        ),
                        params,
                    ).fetchone()
                    orphan_count = int(row[0]) if row else 0
                    report.orphan_counts[rel_label] = orphan_count
                    if orphan_count > 0:
                        logger.warning("FK violation: %s — %d orphan(s)", rel_label, orphan_count)
                    else:
                        logger.debug("FK OK: %s", rel_label)
                except Exception as exc:  # noqa: BLE001
                    logger.error("FK check failed for %s: %s", rel_label, exc)
                    report.orphan_counts[rel_label] = -1  # unknown

        logger.info(
            "FKValidator: %d relationships checked, %d total orphans",
            len(_FK_RELATIONSHIPS),
            report.total_orphans,
        )
        return report
