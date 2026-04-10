"""Unit tests for FKValidator (T041)."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.utils.fk_validator import FKValidator, ValidationReport


def _make_engine(orphan_counts: dict[str, int] | None = None):
    """Build a mock engine that returns controlled orphan counts.

    The engine's execute will return 0 for all FK checks by default,
    or the values specified in orphan_counts (keyed by ``child.fk_col``).
    """
    orphan_counts = orphan_counts or {}
    engine = MagicMock()
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)

    def execute_side_effect(stmt):
        stmt_str = str(stmt)
        # Determine which relationship this is from the SQL
        for rel, count in orphan_counts.items():
            child, _, rest = rel.partition(".")
            fk_col, _, _ = rest.partition(" →")
            if child in stmt_str and fk_col in stmt_str:
                result = MagicMock()
                result.fetchone.return_value = (count,)
                return result
        # Default: 0 orphans
        result = MagicMock()
        result.fetchone.return_value = (0,)
        return result

    conn.execute.side_effect = execute_side_effect
    engine.connect.return_value = conn
    return engine


# ---------------------------------------------------------------------------
# T041-1 — FK check returns 0 orphans for clean destination
# ---------------------------------------------------------------------------


def test_fk_validator_clean_destination():
    """Validator returns is_clean=True when all FK checks return 0 orphans."""
    engine = _make_engine()
    validator = FKValidator()
    report = validator.validate(engine)

    assert report.is_clean
    assert report.total_orphans == 0
    # All 10 FK relationships should be checked
    assert len(report.orphan_counts) == 10


# ---------------------------------------------------------------------------
# T041-2 — FK check correctly detects injected orphan
# ---------------------------------------------------------------------------


def test_fk_validator_detects_orphan():
    """Validator detects injected orphan count in a specific relationship."""
    # Inject 3 orphans in inboxes.account_id
    _engine = _make_engine(orphan_counts={"inboxes.account_id → accounts.id": 3})
    _validator = FKValidator()

    # We need to patch the SQL execution more directly since the engine mock
    # uses SQL text matching which may differ from actual compiled output.
    # Let's use a simpler approach: patch the conn.execute to return
    # 3 for any inboxes-account_id query.
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    call_count = [0]

    def execute_side(stmt):
        call_count[0] += 1
        result = MagicMock()
        stmt_str = str(stmt)
        if "inboxes" in stmt_str and "account_id" in stmt_str and call_count[0] == 1:
            result.fetchone.return_value = (3,)
        else:
            result.fetchone.return_value = (0,)
        return result

    conn.execute.side_effect = execute_side
    engine2 = MagicMock()
    engine2.connect.return_value = conn

    report = FKValidator().validate(engine2)

    assert not report.is_clean
    assert report.total_orphans >= 3


# ---------------------------------------------------------------------------
# T041-3 — ValidationReport.is_clean property
# ---------------------------------------------------------------------------


def test_validation_report_is_clean_true():
    """is_clean returns True when all orphan counts are 0."""
    report = ValidationReport(
        orphan_counts={
            "inboxes.account_id → accounts.id": 0,
            "teams.account_id → accounts.id": 0,
        }
    )
    assert report.is_clean


def test_validation_report_is_clean_false():
    """is_clean returns False when any orphan count > 0."""
    report = ValidationReport(
        orphan_counts={
            "inboxes.account_id → accounts.id": 0,
            "teams.account_id → accounts.id": 5,
        }
    )
    assert not report.is_clean


# ---------------------------------------------------------------------------
# T041-4 — ValidationReport.total_orphans property
# ---------------------------------------------------------------------------


def test_validation_report_total_orphans():
    """total_orphans returns sum of all orphan counts."""
    report = ValidationReport(
        orphan_counts={
            "a → b": 3,
            "c → d": 7,
            "e → f": 0,
        }
    )
    assert report.total_orphans == 10
