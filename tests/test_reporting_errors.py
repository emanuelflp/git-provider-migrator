"""Unit tests for migrator/reporting/errors.py"""
import csv
import threading
from pathlib import Path
import pytest
from migrator.reporting.errors import ErrorsReporter, write_errors_report


class TestErrorsReporter:
    def test_creates_csv_with_header(self, tmp_path):
        path = tmp_path / "errors.csv"
        with ErrorsReporter(path) as reporter:
            pass
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            assert reader.fieldnames == ["repo_name", "source_url", "status", "reason"]

    def test_writes_error_row(self, tmp_path):
        path = tmp_path / "errors.csv"
        with ErrorsReporter(path) as reporter:
            reporter.write("my-repo", "https://gitlab.com/org/my-repo.git", "push failed")
        with open(path, newline="") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1
        assert rows[0]["repo_name"] == "my-repo"
        assert rows[0]["source_url"] == "https://gitlab.com/org/my-repo.git"
        assert rows[0]["status"] == "error"
        assert rows[0]["reason"] == "push failed"

    def test_status_out_of_sync(self, tmp_path):
        path = tmp_path / "errors.csv"
        with ErrorsReporter(path) as reporter:
            reporter.write("repo", "https://example.com/repo.git", "branch is out of sync with remote")
        with open(path, newline="") as f:
            rows = list(csv.DictReader(f))
        assert rows[0]["status"] == "out_of_sync"

    def test_multiple_rows(self, tmp_path):
        path = tmp_path / "errors.csv"
        with ErrorsReporter(path) as reporter:
            reporter.write("repo-a", "https://example.com/a.git", "error A")
            reporter.write("repo-b", "https://example.com/b.git", "error B")
        with open(path, newline="") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 2

    def test_count_tracks_writes(self, tmp_path):
        path = tmp_path / "errors.csv"
        with ErrorsReporter(path) as reporter:
            reporter.write("r1", "u1", "e1")
            reporter.write("r2", "u2", "e2")
            assert reporter._count == 2

    def test_raises_outside_context_manager(self, tmp_path):
        reporter = ErrorsReporter(tmp_path / "errors.csv")
        with pytest.raises(RuntimeError, match="context manager"):
            reporter.write("r", "u", "e")

    def test_thread_safe_writes(self, tmp_path):
        path = tmp_path / "errors.csv"
        errors = [("repo" + str(i), f"https://example.com/{i}.git", f"err {i}") for i in range(50)]
        with ErrorsReporter(path) as reporter:
            threads = [
                threading.Thread(target=reporter.write, args=row)
                for row in errors
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        with open(path, newline="") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 50


class TestWriteErrorsReport:
    def test_only_failures_written(self, tmp_path):
        path = tmp_path / "report.csv"
        results = {
            "ok-repo":  {"success": True, "source_url": "https://example.com/ok.git", "reason": ""},
            "bad-repo": {"success": False, "source_url": "https://example.com/bad.git", "reason": "clone failed"},
        }
        write_errors_report(results, path)
        with open(path, newline="") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1
        assert rows[0]["repo_name"] == "bad-repo"

    def test_empty_results(self, tmp_path):
        path = tmp_path / "report.csv"
        write_errors_report({}, path)
        with open(path, newline="") as f:
            rows = list(csv.DictReader(f))
        assert rows == []
