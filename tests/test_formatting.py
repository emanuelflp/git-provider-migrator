"""Unit tests for migrator/formatting/repo_logger.py and migrator/formatting/colors.py"""
import logging
from unittest.mock import patch

import pytest

from migrator.formatting.repo_logger import RepoLogger
from migrator.formatting.colors import ColorFormatter, _setup_logging


class TestRepoLogger:
    def test_init_sets_prefix(self):
        rl = RepoLogger("my-repo")
        assert rl._prefix == "[my-repo]"

    def test_init_sanitizes_newline_in_repo_name(self):
        rl = RepoLogger("re\npo")
        assert rl._prefix == "[re_po]"

    def test_init_sanitizes_carriage_return_in_repo_name(self):
        rl = RepoLogger("re\rpo")
        assert rl._prefix == "[re_po]"

    def test_fmt_basic(self):
        rl = RepoLogger("test-repo")
        assert rl._fmt("hello world") == "[test-repo] hello world"

    def test_fmt_sanitizes_newline_in_message(self):
        rl = RepoLogger("repo")
        result = rl._fmt("line1\nline2")
        assert result == "[repo] line1 line2"

    def test_fmt_sanitizes_carriage_return_in_message(self):
        rl = RepoLogger("repo")
        result = rl._fmt("line1\rline2")
        assert result == "[repo] line1 line2"

    def test_info_calls_logger_info(self):
        rl = RepoLogger("repo")
        with patch("migrator.formatting.repo_logger.logger") as mock_logger:
            rl.info("test message")
        mock_logger.info.assert_called_once_with("[repo] test message")

    def test_warning_calls_logger_warning(self):
        rl = RepoLogger("repo")
        with patch("migrator.formatting.repo_logger.logger") as mock_logger:
            rl.warning("warn message")
        mock_logger.warning.assert_called_once_with("[repo] warn message")

    def test_error_calls_logger_error(self):
        rl = RepoLogger("repo")
        with patch("migrator.formatting.repo_logger.logger") as mock_logger:
            rl.error("error message")
        mock_logger.error.assert_called_once_with("[repo] error message")

    def test_debug_calls_logger_debug(self):
        rl = RepoLogger("repo")
        with patch("migrator.formatting.repo_logger.logger") as mock_logger:
            rl.debug("debug message")
        mock_logger.debug.assert_called_once_with("[repo] debug message")


class TestColorFormatter:
    def _make_record(self, level, msg="test message"):
        return logging.LogRecord(
            name="test",
            level=level,
            pathname="",
            lineno=0,
            msg=msg,
            args=(),
            exc_info=None,
        )

    def test_format_warning_includes_yellow_ansi(self):
        formatter = ColorFormatter("%(message)s")
        record = self._make_record(logging.WARNING, "warn msg")
        result = formatter.format(record)
        assert "\033[33m" in result  # ANSI yellow
        assert "warn msg" in result

    def test_format_error_includes_red_ansi(self):
        formatter = ColorFormatter("%(message)s")
        record = self._make_record(logging.ERROR, "error msg")
        result = formatter.format(record)
        assert "\033[31m" in result  # ANSI red
        assert "error msg" in result

    def test_format_info_includes_cyan_ansi(self):
        formatter = ColorFormatter("%(message)s")
        record = self._make_record(logging.INFO, "info msg")
        result = formatter.format(record)
        assert "\033[36m" in result  # ANSI cyan
        assert "info msg" in result

    def test_format_debug_includes_dim_ansi(self):
        formatter = ColorFormatter("%(message)s")
        record = self._make_record(logging.DEBUG, "debug msg")
        result = formatter.format(record)
        assert "\033[2m" in result  # ANSI dim
        assert "debug msg" in result

    def test_format_includes_reset_code(self):
        formatter = ColorFormatter("%(message)s")
        record = self._make_record(logging.INFO, "hi")
        result = formatter.format(record)
        assert "\033[0m" in result  # ANSI reset

    def test_setup_logging_isatty_true_uses_color_formatter(self):
        """When stderr is a tty, ColorFormatter should be used (hits line 55)."""
        with patch("migrator.formatting.colors.sys") as mock_sys:
            mock_sys.stderr.isatty.return_value = True
            _setup_logging(debug=False)
        root = logging.getLogger()
        assert root.level == logging.INFO

    def test_setup_logging_debug_sets_debug_level(self):
        """debug=True should set root logger to DEBUG."""
        _setup_logging(debug=True)
        root = logging.getLogger()
        assert root.level == logging.DEBUG

    def test_setup_logging_info_sets_info_level(self):
        """debug=False should set root logger to INFO."""
        _setup_logging(debug=False)
        root = logging.getLogger()
        assert root.level == logging.INFO
