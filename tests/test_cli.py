"""Unit tests for migrator/cli.py — argument parsing and provider validation."""
import sys
from unittest.mock import patch, MagicMock
import pytest


def _run_main(*argv):
    """Run main() with the given argv, capturing SystemExit."""
    with patch("sys.argv", ["migrate"] + list(argv)):
        from migrator.cli import main
        with pytest.raises(SystemExit) as exc_info:
            main()
    return exc_info.value.code


class TestProviderValidation:
    def test_invalid_dest_provider_rejected_by_argparse(self):
        """argparse choices rejects unknown dest provider before main() logic runs."""
        with patch("sys.argv", ["migrate", "--dest-provider", "bitbucket",
                                "--source-url", "https://example.com/r.git",
                                "--repo-name", "r"]):
            from migrator.cli import main
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 2  # argparse error exit code

    def test_from_gitlab_requires_source_provider_gitlab(self, caplog):
        with patch("sys.argv", ["migrate",
                                "--source-provider", "github",
                                "--from-gitlab",
                                "--github-token", "ghp_test"]):
            from migrator.cli import main
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 1

    def test_archive_synced_ignored_for_non_gitlab(self, caplog):
        """--archive-synced with a non-gitlab source should warn and continue (not exit 1)."""
        with patch("migrator.cli.GitHubMigrator") as MockMigrator:
            mock_instance = MagicMock()
            mock_instance.migrate_repository.return_value = (True, "ok")
            MockMigrator.return_value = mock_instance

            with patch("migrator.cli._lfs_available", return_value=True):
                with patch("migrator.cli.load_tokens_from_csv", return_value={}):
                    with patch("sys.argv", ["migrate",
                                            "--source-provider", "bitbucket",
                                            "--archive-synced",
                                            "--github-token", "ghp_test",
                                            "--source-url", "https://bitbucket.org/o/r.git",
                                            "--repo-name", "r",
                                            "--skip-lfs"]):
                        from migrator.cli import main
                        with pytest.raises(SystemExit) as exc_info:
                            main()

        # archive_synced warning issued but migration proceeds → exit 0
        assert exc_info.value.code == 0


class TestTokenResolution:
    """Token priority: CLI flag > CSV > env var."""

    def _build_argv_single_repo(self, extra=None):
        base = ["--source-url", "https://gitlab.com/o/r.git", "--repo-name", "r", "--skip-lfs"]
        return base + (extra or [])

    def test_github_token_from_env(self):
        with patch("migrator.cli.GitHubMigrator") as MockMigrator:
            instance = MagicMock()
            instance.migrate_repository.return_value = (True, "ok")
            MockMigrator.return_value = instance

            with patch("migrator.cli.load_tokens_from_csv", return_value={}):
                with patch("migrator.cli._lfs_available", return_value=True):
                    with patch.dict("os.environ", {"GITHUB_TOKEN": "ghp_env_token"}, clear=False):
                        with patch("sys.argv", ["migrate"] + self._build_argv_single_repo()):
                            from migrator.cli import main
                            with pytest.raises(SystemExit) as exc_info:
                                main()

        assert exc_info.value.code == 0
        MockMigrator.assert_called_once_with(github_token="ghp_env_token", github_org=None)

    def test_missing_github_token_exits_1(self):
        with patch("migrator.cli.load_tokens_from_csv", return_value={}):
            with patch("migrator.cli._lfs_available", return_value=True):
                with patch.dict("os.environ", {}, clear=True):
                    # Ensure GITHUB_TOKEN not in env
                    import os
                    os.environ.pop("GITHUB_TOKEN", None)
                    with patch("sys.argv", ["migrate"] + self._build_argv_single_repo()):
                        from migrator.cli import main
                        with pytest.raises(SystemExit) as exc_info:
                            main()
        assert exc_info.value.code == 1

    def test_cli_token_overrides_env(self):
        with patch("migrator.cli.GitHubMigrator") as MockMigrator:
            instance = MagicMock()
            instance.migrate_repository.return_value = (True, "ok")
            MockMigrator.return_value = instance

            with patch("migrator.cli.load_tokens_from_csv", return_value={}):
                with patch("migrator.cli._lfs_available", return_value=True):
                    with patch.dict("os.environ", {"GITHUB_TOKEN": "ghp_env_token"}, clear=False):
                        with patch("sys.argv", ["migrate"] + self._build_argv_single_repo(
                            ["--github-token", "ghp_cli_token"]
                        )):
                            from migrator.cli import main
                            with pytest.raises(SystemExit) as exc_info:
                                main()

        MockMigrator.assert_called_once_with(github_token="ghp_cli_token", github_org=None)


class TestModeSelection:
    def test_no_source_url_no_batch_file_exits_1(self):
        with patch("migrator.cli.load_tokens_from_csv", return_value={}):
            with patch("migrator.cli._lfs_available", return_value=True):
                with patch.dict("os.environ", {"GITHUB_TOKEN": "ghp_test"}, clear=False):
                    with patch("sys.argv", ["migrate", "--skip-lfs"]):
                        from migrator.cli import main
                        with pytest.raises(SystemExit) as exc_info:
                            main()
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# Mode-specific tests
# ---------------------------------------------------------------------------
import json
from pathlib import Path
from types import SimpleNamespace


def _make_args(**kwargs):
    """Build a SimpleNamespace simulating parsed argparse arguments."""
    defaults = dict(
        source_provider="gitlab",
        dest_provider="github",
        gitlab_base_url="https://gitlab.com",
        gitlab_namespace=None,
        archive_synced=False,
        workers=1,
        skip_lfs=True,
        commits_per_slice=500,
        batch_file=None,
        source_url=None,
        repo_name=None,
        description=None,
        public=False,
        private=True,
        errors_output=None,
        debug=False,
        from_gitlab=False,
        github_org=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestFromGitlabMode:
    """Tests for _run_from_gitlab_mode (cli.py lines 279-326)."""

    def test_no_gitlab_token_exits_1(self, tmp_path):
        from migrator.cli import _run_from_gitlab_mode
        args = _make_args()
        mock_migrator = MagicMock()
        with pytest.raises(SystemExit) as exc_info:
            _run_from_gitlab_mode(args, mock_migrator, True, tmp_path / "err.csv", None)
        assert exc_info.value.code == 1

    def test_namespace_calls_list_group_repos(self, tmp_path):
        from migrator.cli import _run_from_gitlab_mode
        args = _make_args(gitlab_namespace="mygroup")
        mock_migrator = MagicMock()
        mock_migrator.migrate_repositories.return_value = {
            "repo1": {"success": True, "reason": "", "source_url": "https://gitlab.com/g/r.git"}
        }

        with patch("migrator.cli.GitLabClient") as MockGLClient:
            mock_gl = MagicMock()
            mock_gl.list_group_repos.return_value = [
                {"id": 1, "path": "repo1", "http_url_to_repo": "https://gitlab.com/g/r.git", "description": ""}
            ]
            mock_gl.repos_to_migration_list.return_value = [
                {"source_url": "https://gitlab.com/g/r.git", "repo_name": "repo1", "private": True}
            ]
            MockGLClient.return_value = mock_gl

            with pytest.raises(SystemExit) as exc_info:
                _run_from_gitlab_mode(args, mock_migrator, True, tmp_path / "err.csv", "gl-token")

        mock_gl.list_group_repos.assert_called_once_with("mygroup")
        assert exc_info.value.code == 0

    def test_no_namespace_calls_list_user_repos(self, tmp_path):
        from migrator.cli import _run_from_gitlab_mode
        args = _make_args(gitlab_namespace=None)
        mock_migrator = MagicMock()
        mock_migrator.migrate_repositories.return_value = {
            "repo1": {"success": True, "reason": ""}
        }

        with patch("migrator.cli.GitLabClient") as MockGLClient:
            mock_gl = MagicMock()
            mock_gl.list_user_repos.return_value = [
                {"id": 1, "path": "repo1", "http_url_to_repo": "https://gitlab.com/u/r.git", "description": ""}
            ]
            mock_gl.repos_to_migration_list.return_value = [
                {"source_url": "https://gitlab.com/u/r.git", "repo_name": "repo1", "private": True}
            ]
            MockGLClient.return_value = mock_gl

            with pytest.raises(SystemExit) as exc_info:
                _run_from_gitlab_mode(args, mock_migrator, True, tmp_path / "err.csv", "gl-token")

        mock_gl.list_user_repos.assert_called_once_with()
        assert exc_info.value.code == 0

    def test_no_projects_exits_0_with_warning(self, tmp_path):
        from migrator.cli import _run_from_gitlab_mode
        args = _make_args(gitlab_namespace=None)
        mock_migrator = MagicMock()

        with patch("migrator.cli.GitLabClient") as MockGLClient:
            mock_gl = MagicMock()
            mock_gl.list_user_repos.return_value = []
            mock_gl.repos_to_migration_list.return_value = []
            MockGLClient.return_value = mock_gl

            with pytest.raises(SystemExit) as exc_info:
                _run_from_gitlab_mode(args, mock_migrator, True, tmp_path / "err.csv", "gl-token")

        assert exc_info.value.code == 0

    def test_all_failed_exits_1(self, tmp_path):
        from migrator.cli import _run_from_gitlab_mode
        args = _make_args(gitlab_namespace=None)
        mock_migrator = MagicMock()
        mock_migrator.migrate_repositories.return_value = {
            "repo1": {"success": False, "reason": "error", "source_url": "https://x.git"}
        }

        with patch("migrator.cli.GitLabClient") as MockGLClient:
            mock_gl = MagicMock()
            mock_gl.list_user_repos.return_value = [
                {"id": 1, "path": "repo1", "http_url_to_repo": "https://x.git", "description": ""}
            ]
            mock_gl.repos_to_migration_list.return_value = [
                {"source_url": "https://x.git", "repo_name": "repo1", "private": True}
            ]
            MockGLClient.return_value = mock_gl

            with pytest.raises(SystemExit) as exc_info:
                _run_from_gitlab_mode(args, mock_migrator, True, tmp_path / "err.csv", "gl-token")

        assert exc_info.value.code == 1

    def test_namespace_404_falls_back_to_user(self, tmp_path):
        """GitlabError 404 on group → retry as user."""
        from migrator.cli import _run_from_gitlab_mode
        from gitlab.exceptions import GitlabError
        args = _make_args(gitlab_namespace="maybe-user")
        mock_migrator = MagicMock()
        mock_migrator.migrate_repositories.return_value = {
            "repo1": {"success": True, "reason": ""}
        }

        with patch("migrator.cli.GitLabClient") as MockGLClient:
            mock_gl = MagicMock()
            # first call raises 404, second call succeeds
            err = GitlabError("Not Found")
            err.response_code = 404
            mock_gl.list_group_repos.side_effect = err
            mock_gl.list_user_repos.return_value = [
                {"id": 1, "path": "repo1", "http_url_to_repo": "https://x.git", "description": ""}
            ]
            mock_gl.repos_to_migration_list.return_value = [
                {"source_url": "https://x.git", "repo_name": "repo1", "private": True}
            ]
            MockGLClient.return_value = mock_gl

            with pytest.raises(SystemExit) as exc_info:
                _run_from_gitlab_mode(args, mock_migrator, True, tmp_path / "err.csv", "gl-token")

        mock_gl.list_user_repos.assert_called_once_with("maybe-user")
        assert exc_info.value.code == 0


class TestBatchMode:
    """Tests for _run_batch_mode (cli.py lines 331-348)."""

    def test_valid_batch_file_exits_0_on_success(self, tmp_path):
        from migrator.cli import _run_batch_mode
        batch_data = [
            {"source_url": "https://gitlab.com/o/r.git", "repo_name": "repo1"},
        ]
        batch_file = tmp_path / "batch.json"
        batch_file.write_text(json.dumps(batch_data))

        args = _make_args(
            batch_file=str(batch_file),
            archive_synced=False,
            workers=1,
            skip_lfs=True,
            commits_per_slice=500,
        )
        mock_migrator = MagicMock()
        mock_migrator.migrate_repositories.return_value = {
            "repo1": {"success": True, "reason": ""}
        }

        with pytest.raises(SystemExit) as exc_info:
            _run_batch_mode(args, mock_migrator, tmp_path / "err.csv", None)

        assert exc_info.value.code == 0
        mock_migrator.migrate_repositories.assert_called_once()

    def test_all_failed_exits_1(self, tmp_path):
        from migrator.cli import _run_batch_mode
        batch_data = [{"source_url": "https://x.git", "repo_name": "repo1"}]
        batch_file = tmp_path / "batch.json"
        batch_file.write_text(json.dumps(batch_data))

        args = _make_args(batch_file=str(batch_file))
        mock_migrator = MagicMock()
        mock_migrator.migrate_repositories.return_value = {
            "repo1": {"success": False, "reason": "error"}
        }

        with pytest.raises(SystemExit) as exc_info:
            _run_batch_mode(args, mock_migrator, tmp_path / "err.csv", None)

        assert exc_info.value.code == 1


class TestSingleRepoMode:
    """Tests for _run_single_repo_mode (cli.py lines 370, 380-403)."""

    def test_missing_source_url_exits_1(self, tmp_path):
        from migrator.cli import _run_single_repo_mode
        args = _make_args(source_url=None, repo_name="repo")
        mock_migrator = MagicMock()
        with pytest.raises(SystemExit) as exc_info:
            _run_single_repo_mode(args, mock_migrator, True, tmp_path / "err.csv", None)
        assert exc_info.value.code == 1

    def test_missing_repo_name_exits_1(self, tmp_path):
        from migrator.cli import _run_single_repo_mode
        args = _make_args(source_url="https://x.git", repo_name=None)
        mock_migrator = MagicMock()
        with pytest.raises(SystemExit) as exc_info:
            _run_single_repo_mode(args, mock_migrator, True, tmp_path / "err.csv", None)
        assert exc_info.value.code == 1

    def test_success_exits_0(self, tmp_path):
        from migrator.cli import _run_single_repo_mode
        args = _make_args(source_url="https://gitlab.com/o/r.git", repo_name="r")
        mock_migrator = MagicMock()
        mock_migrator.migrate_repository.return_value = (True, "")

        with pytest.raises(SystemExit) as exc_info:
            _run_single_repo_mode(args, mock_migrator, True, tmp_path / "err.csv", None)

        assert exc_info.value.code == 0

    def test_failure_exits_1(self, tmp_path):
        from migrator.cli import _run_single_repo_mode
        args = _make_args(source_url="https://gitlab.com/o/r.git", repo_name="r")
        mock_migrator = MagicMock()
        mock_migrator.migrate_repository.return_value = (False, "clone failed")

        with pytest.raises(SystemExit) as exc_info:
            _run_single_repo_mode(args, mock_migrator, True, tmp_path / "err.csv", None)

        assert exc_info.value.code == 1


class TestLfsWarning:
    """Tests for the LFS availability check (cli.py lines 222-226)."""

    def test_lfs_not_available_logs_warning(self, capfd):
        """When lfs is not available and --skip-lfs is absent, warning is logged to stderr."""
        with patch("migrator.cli.GitHubMigrator") as MockMigrator:
            instance = MagicMock()
            instance.migrate_repository.return_value = (True, "")
            MockMigrator.return_value = instance

            with patch("migrator.cli.load_tokens_from_csv", return_value={}):
                with patch("migrator.cli._lfs_available", return_value=False):
                    with patch.dict("os.environ", {"GITHUB_TOKEN": "ghp_test"}, clear=False):
                        with patch("sys.argv", [
                            "migrate",
                            "--source-url", "https://gitlab.com/o/r.git",
                            "--repo-name", "r",
                            # no --skip-lfs
                        ]):
                            from migrator.cli import main
                            with pytest.raises(SystemExit):
                                main()

        _, err = capfd.readouterr()
        assert "git-lfs" in err

    def test_lfs_available_logs_info(self, capfd):
        """When lfs is available and --skip-lfs is absent, info message is logged to stderr."""
        with patch("migrator.cli.GitHubMigrator") as MockMigrator:
            instance = MagicMock()
            instance.migrate_repository.return_value = (True, "")
            MockMigrator.return_value = instance

            with patch("migrator.cli.load_tokens_from_csv", return_value={}):
                with patch("migrator.cli._lfs_available", return_value=True):
                    with patch.dict("os.environ", {"GITHUB_TOKEN": "ghp_test"}, clear=False):
                        with patch("sys.argv", [
                            "migrate",
                            "--source-url", "https://gitlab.com/o/r.git",
                            "--repo-name", "r",
                        ]):
                            from migrator.cli import main
                            with pytest.raises(SystemExit):
                                main()

        _, err = capfd.readouterr()
        assert "LFS" in err


class TestPrintSummary:
    """Tests for _print_summary (cli.py lines 408-409 out-of-sync path)."""

    def test_out_of_sync_reason_logged_as_warning(self, caplog):
        import logging
        from migrator.cli import _print_summary
        results = {
            "repo1": {"success": False, "reason": "Out of sync — GitHub is missing commits"},
        }
        with caplog.at_level(logging.WARNING):
            _print_summary(results)
        assert any("out of sync" in rec.message.lower() for rec in caplog.records)

    def test_regular_failure_logged_as_error(self, caplog):
        import logging
        from migrator.cli import _print_summary
        results = {
            "repo1": {"success": False, "reason": "git clone failed"},
        }
        with caplog.at_level(logging.ERROR):
            _print_summary(results)
        assert any("FAILED" in rec.message for rec in caplog.records)

    def test_success_logged(self, caplog):
        import logging
        from migrator.cli import _print_summary
        results = {
            "repo1": {"success": True, "reason": ""},
        }
        with caplog.at_level(logging.INFO):
            _print_summary(results)
        assert any("SUCCESS" in rec.message for rec in caplog.records)
