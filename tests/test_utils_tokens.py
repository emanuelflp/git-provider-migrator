"""Unit tests for migrator/utils/tokens.py"""
import csv
import pytest
from pathlib import Path
from migrator.utils.tokens import load_tokens_from_csv


@pytest.fixture
def tmp_csv(tmp_path):
    """Helper factory: write a CSV file and return its Path."""
    def _make(content: str) -> Path:
        p = tmp_path / "tokens.csv"
        p.write_text(content, encoding="utf-8")
        return p
    return _make


class TestLoadTokensFromCsv:
    def test_key_value_format(self, tmp_csv):
        path = tmp_csv("key,value\ngithub_token,ghp_abc\ngitlab_token,glpat_xyz\n")
        tokens = load_tokens_from_csv(path)
        assert tokens["github_token"] == "ghp_abc"
        assert tokens["gitlab_token"] == "glpat_xyz"

    def test_header_row_format(self, tmp_csv):
        path = tmp_csv("github_token,gitlab_token\nghp_abc,glpat_xyz\n")
        tokens = load_tokens_from_csv(path)
        assert tokens["github_token"] == "ghp_abc"
        assert tokens["gitlab_token"] == "glpat_xyz"

    def test_missing_file_returns_empty(self, tmp_path):
        result = load_tokens_from_csv(tmp_path / "nonexistent.csv")
        assert result == {}

    def test_empty_file_returns_empty(self, tmp_csv):
        path = tmp_csv("")
        result = load_tokens_from_csv(path)
        assert result == {}

    def test_partial_tokens(self, tmp_csv):
        path = tmp_csv("key,value\ngithub_token,ghp_abc\n")
        tokens = load_tokens_from_csv(path)
        assert tokens["github_token"] == "ghp_abc"
        assert "gitlab_token" not in tokens

    def test_unknown_keys_ignored(self, tmp_csv):
        path = tmp_csv("key,value\nsome_other_key,value123\n")
        tokens = load_tokens_from_csv(path)
        assert tokens == {}

    def test_whitespace_trimmed(self, tmp_csv):
        path = tmp_csv("key,value\n github_token , ghp_abc \n")
        tokens = load_tokens_from_csv(path)
        assert tokens["github_token"] == "ghp_abc"
