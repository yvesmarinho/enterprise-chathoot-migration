"""Unit tests for POCReporter (TPOC005).

Tests cover:
- All 5 Outcome values are represented in generated report.
- add_record() caps at MAX_SAMPLES per outcome.
- surviving_ids populated only for WOULD_MIGRATE / WOULD_MIGRATE_MODIFIED.
- POCReporter.generate() creates a file matching poc_YYYYMMDD_HHMMSS_report.txt.
- Report file contains expected summary table columns.
- Empty results list produces a valid (non-crashing) report.
- masked_preview values appear verbatim in the report.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.reports.poc_reporter import (
    MAX_SAMPLES,
    Outcome,
    POCResult,
    POCReporter,
    RecordSample,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sample(id_origem: int, outcome: Outcome, reason: str = "test") -> RecordSample:
    return RecordSample(
        id_origem=id_origem,
        outcome=outcome,
        reason=reason,
        masked_preview={"id": id_origem, "created_at": "2024-01-01"},
    )


def _full_result(table: str = "contacts", n: int = 1) -> POCResult:
    """Return a POCResult with one record per Outcome value."""
    result = POCResult(table=table, total_source=n * len(Outcome))
    for i, outcome in enumerate(Outcome):
        result.add_record(_sample(i + 1, outcome))
    return result


# ---------------------------------------------------------------------------
# POCResult.add_record — counter
# ---------------------------------------------------------------------------


def test_add_record_increments_counter():
    result = POCResult(table="accounts", total_source=3)
    for i in range(3):
        result.add_record(_sample(i + 1, Outcome.WOULD_MIGRATE))
    assert result.outcome_counts[Outcome.WOULD_MIGRATE.value] == 3


def test_add_record_multiple_outcomes():
    result = POCResult(table="users", total_source=2)
    result.add_record(_sample(1, Outcome.WOULD_MIGRATE))
    result.add_record(_sample(2, Outcome.WOULD_MIGRATE_MODIFIED))
    assert result.outcome_counts[Outcome.WOULD_MIGRATE.value] == 1
    assert result.outcome_counts[Outcome.WOULD_MIGRATE_MODIFIED.value] == 1


# ---------------------------------------------------------------------------
# POCResult.add_record — sample cap
# ---------------------------------------------------------------------------


def test_add_record_caps_at_max_samples():
    result = POCResult(table="messages", total_source=MAX_SAMPLES + 5)
    for i in range(MAX_SAMPLES + 5):
        result.add_record(_sample(i + 1, Outcome.WOULD_MIGRATE))

    samples = result.samples[Outcome.WOULD_MIGRATE.value]
    assert len(samples) == MAX_SAMPLES
    assert result.outcome_counts[Outcome.WOULD_MIGRATE.value] == MAX_SAMPLES + 5


def test_add_record_samples_independent_per_outcome():
    result = POCResult(table="contacts", total_source=30)
    for i in range(15):
        result.add_record(_sample(i + 1, Outcome.WOULD_MIGRATE))
    for i in range(15):
        result.add_record(_sample(100 + i, Outcome.ORPHAN_FK_SKIP))

    assert len(result.samples[Outcome.WOULD_MIGRATE.value]) == MAX_SAMPLES
    assert len(result.samples[Outcome.ORPHAN_FK_SKIP.value]) == MAX_SAMPLES


# ---------------------------------------------------------------------------
# POCResult.surviving_ids
# ---------------------------------------------------------------------------


def test_surviving_ids_populated_for_would_migrate():
    result = POCResult(table="accounts", total_source=5)
    for i in range(1, 6):
        result.add_record(_sample(i, Outcome.WOULD_MIGRATE))
    assert result.surviving_ids == {1, 2, 3, 4, 5}


def test_surviving_ids_populated_for_modified():
    result = POCResult(table="users", total_source=3)
    for i in range(1, 4):
        result.add_record(_sample(i, Outcome.WOULD_MIGRATE_MODIFIED))
    assert result.surviving_ids == {1, 2, 3}


def test_surviving_ids_not_populated_for_skip_outcomes():
    result = POCResult(table="contacts", total_source=3)
    result.add_record(_sample(1, Outcome.ORPHAN_FK_SKIP))
    result.add_record(_sample(2, Outcome.ALREADY_MIGRATED))
    result.add_record(_sample(3, Outcome.COLLISION))
    assert result.surviving_ids == set()


def test_surviving_ids_exceeds_max_samples():
    """surviving_ids must hold ALL IDs, not just the sampled 10."""
    result = POCResult(table="contacts", total_source=MAX_SAMPLES + 5)
    for i in range(1, MAX_SAMPLES + 6):
        result.add_record(_sample(i, Outcome.WOULD_MIGRATE))

    assert len(result.surviving_ids) == MAX_SAMPLES + 5
    assert len(result.samples[Outcome.WOULD_MIGRATE.value]) == MAX_SAMPLES


# ---------------------------------------------------------------------------
# POCReporter.generate — file creation
# ---------------------------------------------------------------------------


def test_generate_creates_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    reporter = POCReporter()
    result = _full_result()
    path = reporter.generate([result], duration_seconds=1.23)

    assert path.exists()
    assert re.match(r"poc_\d{8}_\d{6}_report\.txt", path.name)


def test_generate_returns_path_object(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    reporter = POCReporter()
    path = reporter.generate([_full_result()], duration_seconds=0.5)
    assert isinstance(path, Path)


def test_generate_empty_results_does_not_crash(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    reporter = POCReporter()
    path = reporter.generate([], duration_seconds=0.0)
    assert path.exists()


# ---------------------------------------------------------------------------
# POCReporter.generate — report content
# ---------------------------------------------------------------------------


def test_report_contains_all_outcome_columns(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    reporter = POCReporter()
    path = reporter.generate([_full_result("accounts")], duration_seconds=2.0)
    content = path.read_text(encoding="utf-8")

    assert "MIGRATE" in content
    assert "MODIFIED" in content
    assert "ORPHAN" in content
    assert "DEDUP" in content
    assert "COLLISION" in content


def test_report_contains_table_name(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    reporter = POCReporter()
    path = reporter.generate([_full_result("conversations")], duration_seconds=1.0)
    content = path.read_text(encoding="utf-8")
    assert "conversations" in content


def test_report_contains_duration(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    reporter = POCReporter()
    path = reporter.generate([_full_result()], duration_seconds=48.39)
    content = path.read_text(encoding="utf-8")
    assert "48.39s" in content


def test_report_contains_masked_preview(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = POCResult(table="inboxes", total_source=1)
    result.add_record(
        RecordSample(
            id_origem=42,
            outcome=Outcome.WOULD_MIGRATE,
            reason="clean",
            masked_preview={"id": 42, "created_at": "2024-06-01"},
        )
    )
    reporter = POCReporter()
    path = reporter.generate([result], duration_seconds=0.1)
    content = path.read_text(encoding="utf-8")
    assert '"id": 42' in content
    assert "clean" in content


def test_report_multiple_tables(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tables = ["accounts", "inboxes", "contacts"]
    results = [_full_result(t) for t in tables]
    reporter = POCReporter()
    path = reporter.generate(results, duration_seconds=5.0)
    content = path.read_text(encoding="utf-8")
    for t in tables:
        assert t in content


# ---------------------------------------------------------------------------
# Outcome enum — completeness
# ---------------------------------------------------------------------------


def test_all_five_outcomes_exist():
    values = {o.value for o in Outcome}
    assert values == {
        "WOULD_MIGRATE",
        "WOULD_MIGRATE_MODIFIED",
        "ORPHAN_FK_SKIP",
        "ALREADY_MIGRATED",
        "COLLISION",
    }
