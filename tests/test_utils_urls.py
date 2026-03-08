"""Unit tests for migrator/utils/urls.py"""
import pytest
from migrator.utils.urls import _redact_url


class TestRedactUrl:
    def test_url_with_token_in_password_field(self):
        url = "https://oauth2:glpat-secret@gitlab.com/org/repo.git"
        result = _redact_url(url)
        assert "glpat-secret" not in result
        assert "***" in result
        assert "gitlab.com/org/repo.git" in result
        assert "oauth2" in result

    def test_url_without_credentials_unchanged(self):
        url = "https://gitlab.com/org/repo.git"
        assert _redact_url(url) == url

    def test_url_with_port_preserved(self):
        url = "https://user:token@gitlab.mycompany.com:8080/org/repo.git"
        result = _redact_url(url)
        assert "token" not in result
        assert ":8080" in result
        assert "***" in result

    def test_url_with_username_only_unchanged(self):
        # No password → nothing to redact
        url = "https://gitlab.com/org/repo.git"
        assert _redact_url(url) == url

    def test_github_token_url(self):
        url = "https://x-access-token:ghp_supersecret@github.com/org/repo.git"
        result = _redact_url(url)
        assert "ghp_supersecret" not in result
        assert "x-access-token" in result
        assert "github.com/org/repo.git" in result
