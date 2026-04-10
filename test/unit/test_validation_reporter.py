"""Unit tests for ValidationReporter (T039)."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.migrators.base_migrator import MigrationResult
from src.reports.validation_reporter import ValidationReporter


def _make_results() -> list[MigrationResult]:
    """Return a complete set of 9 MigrationResult objects."""
    return [
        MigrationResult("accounts", 5, 5, 0, []),
        MigrationResult("inboxes", 21, 21, 0, []),
        MigrationResult("users", 112, 112, 0, []),
        MigrationResult("teams", 3, 3, 0, []),
        MigrationResult("labels", 32, 32, 0, []),
        MigrationResult("contacts", 38868, 38868, 0, []),
        MigrationResult("conversations", 41743, 41743, 0, []),
        MigrationResult("messages", 310155, 310155, 0, []),
        MigrationResult("attachments", 26889, 26889, 0, []),
    ]


def _make_dest_engine():
    """Return a mock engine that returns sensible row counts."""
    engine = MagicMock()
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    conn.execute.return_value.fetchone.return_value = (12345,)
    engine.connect.return_value = conn
    return engine


# ---------------------------------------------------------------------------
# T039-1 — Report contains all 9 table rows
# ---------------------------------------------------------------------------


def test_report_contains_all_9_tables(tmp_path):
    """Generated report contains a row for each of the 9 migration tables."""
    reporter = ValidationReporter()
    results = _make_results()
    engine = _make_dest_engine()

    with patch("src.reports.validation_reporter.Path") as mock_path_cls:
        # Allow .tmp/ creation via real path but redirect report file
        real_path = Path

        def path_side_effect(arg):
            if arg == ".tmp":
                return tmp_path
            return real_path(arg)

        mock_path_cls.side_effect = path_side_effect

        # Let the real code run but write to tmp_path
        _ = reporter.generate(results, engine, duration_seconds=1.5)

    # (report_path may point at a real file if Path wasn't fully mocked)
    # Use a simpler approach: patch just the write_text / mkdir
    reporter2 = ValidationReporter()
    written_content = []

    with patch("src.reports.validation_reporter.Path") as MockPath:
        mock_file = MagicMock()
        mock_file.resolve.return_value = tmp_path / "report.txt"

        def write_text(content, encoding="utf-8"):
            written_content.append(content)

        mock_file.write_text = write_text
        mock_dir = MagicMock()
        mock_dir.__truediv__ = MagicMock(return_value=mock_file)
        mock_dir.mkdir = MagicMock()
        MockPath.return_value = mock_dir

        reporter2.generate(results, engine, duration_seconds=1.5)

    assert written_content, "write_text was never called"
    content = written_content[0]
    for table in [
        "accounts",
        "inboxes",
        "users",
        "teams",
        "labels",
        "contacts",
        "conversations",
        "messages",
        "attachments",
    ]:
        assert table in content


# ---------------------------------------------------------------------------
# T039-2 — Failed IDs appear as integers (no content)
# ---------------------------------------------------------------------------


def test_report_failed_ids_as_integers():
    """Failed IDs section contains integer IDs, not record content."""
    results = [
        MigrationResult("contacts", 10, 8, 1, [12345, 67890]),
    ]
    engine = _make_dest_engine()
    reporter = ValidationReporter()
    written_content = []

    with patch("src.reports.validation_reporter.Path") as MockPath:
        mock_file = MagicMock()
        mock_file.resolve.return_value = Path("/tmp/report.txt")
        mock_file.write_text = lambda c, encoding="utf-8": written_content.append(c)
        mock_dir = MagicMock()
        mock_dir.__truediv__ = MagicMock(return_value=mock_file)
        mock_dir.mkdir = MagicMock()
        MockPath.return_value = mock_dir

        reporter.generate(results, engine, duration_seconds=0.5)

    content = written_content[0]
    assert "12345" in content
    assert "67890" in content
    # No actual message content should appear
    assert "Hello" not in content


# ---------------------------------------------------------------------------
# T039-3 — File path format matches migration_YYYYMMDD_HHMMSS_report.txt
# ---------------------------------------------------------------------------


def test_report_file_path_format():
    """Report file is named migration_YYYYMMDD_HHMMSS_report.txt."""
    import re

    results = [MigrationResult("accounts", 5, 5, 0, [])]
    engine = _make_dest_engine()
    reporter = ValidationReporter()
    filenames_written = []

    with patch("src.reports.validation_reporter.Path") as MockPath:
        mock_file = MagicMock()
        mock_file.resolve.return_value = Path("/tmp/report.txt")
        mock_file.write_text = lambda c, encoding="utf-8": None

        mock_dir = MagicMock()

        def truediv(name):
            filenames_written.append(name)
            return mock_file

        mock_dir.__truediv__ = MagicMock(side_effect=truediv)
        mock_dir.mkdir = MagicMock()
        MockPath.return_value = mock_dir

        reporter.generate(results, engine, duration_seconds=2.0)

    assert any(
        re.match(r"migration_\d{8}_\d{6}_report\.txt", name)
        for name in filenames_written
    ), f"No matching filename found in: {filenames_written}"


# ---------------------------------------------------------------------------
# T039-4 — generate() with mocked inputs completes quickly (< 5 seconds)
# ---------------------------------------------------------------------------


def test_report_generation_under_5_seconds():
    """reporter.generate() with mocked engine completes in < 5 seconds (SC-007 proxy)."""
    results = _make_results()
    engine = _make_dest_engine()
    reporter = ValidationReporter()

    with patch("src.reports.validation_reporter.Path") as MockPath:
        mock_file = MagicMock()
        mock_file.resolve.return_value = Path("/tmp/report.txt")
        mock_file.write_text = lambda c, encoding="utf-8": None
        mock_dir = MagicMock()
        mock_dir.__truediv__ = MagicMock(return_value=mock_file)
        mock_dir.mkdir = MagicMock()
        MockPath.return_value = mock_dir

        start = time.time()
        reporter.generate(results, engine, duration_seconds=42.0)
        elapsed = time.time() - start

    assert elapsed < 5.0, f"generate() took {elapsed:.2f}s — must be < 5s"
