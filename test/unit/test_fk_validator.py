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

    def execute_side_effect(stmt, params=None):
        """Mock execute that returns orphan counts based on SQL statement."""
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

    conn.execute = execute_side_effect
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
    # All FK relationships should be checked (12 as of this test)
    assert len(report.orphan_counts) == 12


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

    def execute_side(stmt, params=None):
        """Mock execute that returns 3 for first inboxes-account_id query."""
        call_count[0] += 1
        result = MagicMock()
        stmt_str = str(stmt)
        if "inboxes" in stmt_str and "account_id" in stmt_str and call_count[0] == 1:
            result.fetchone.return_value = (3,)
        else:
            result.fetchone.return_value = (0,)
        return result

    conn.execute = execute_side
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


# ---------------------------------------------------------------------------
# T041-5 — FK validator with account_id scoping
# ---------------------------------------------------------------------------


def test_fk_validator_validate_with_account_scoping():
    """Validator applies account_id scope when provided."""
    engine = MagicMock()
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    conn.execute.return_value.fetchone.return_value = (0,)
    engine.connect.return_value = conn

    validator = FKValidator()
    report = validator.validate(engine, account_id=42)

    assert report.is_clean
    # Verify at least one execute call included account_id in params
    execute_calls = conn.execute.call_args_list
    # Check if any call has account_id parameter
    found_account_param = False
    for call in execute_calls:
        if len(call[0]) > 1 and isinstance(call[0][1], dict):
            if "account_id" in call[0][1]:
                found_account_param = True
                break
    assert found_account_param


# ---------------------------------------------------------------------------
# T041-6 — FK validator exception handling (returns -1 for unknown)
# ---------------------------------------------------------------------------


def test_fk_validator_validate_exception_returns_unknown():
    """Validator returns -1 (unknown) when a FK check raises exception."""
    engine = MagicMock()
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)

    # Simulate exception on one relationship, success on others
    call_count = [0]

    def execute_side(stmt, params=None):
        call_count[0] += 1
        # Fail on second call
        if call_count[0] == 2:
            raise Exception("Database error")
        result = MagicMock()
        result.fetchone.return_value = (0,)
        return result

    conn.execute = execute_side
    engine.connect.return_value = conn

    validator = FKValidator()
    report = validator.validate(engine)

    # Should have one -1 (error) and rest 0
    assert -1 in report.orphan_counts.values()
