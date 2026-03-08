"""Unit tests for migrator/clients/github.py — GitHubMigrator"""
from unittest.mock import MagicMock, patch, call
import pytest
import requests
from migrator.clients.github import GitHubMigrator


@pytest.fixture
def migrator():
    return GitHubMigrator(github_token="test-token", github_org=None)


@pytest.fixture
def org_migrator():
    return GitHubMigrator(github_token="test-token", github_org="my-org")


def _mock_response(status_code: int, json_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(response=resp)
    return resp


class TestGetGithubUser:
    def test_returns_login(self, migrator):
        mock_user = MagicMock()
        mock_user.login = "jdoe"
        migrator._gh.get_user = MagicMock(return_value=mock_user)
        assert migrator.get_github_user() == "jdoe"

    def test_caches_user(self, migrator):
        mock_user = MagicMock()
        mock_user.login = "jdoe"
        migrator._gh.get_user = MagicMock(return_value=mock_user)
        migrator.get_github_user()
        migrator.get_github_user()
        migrator._gh.get_user.assert_called_once()


class TestCheckRepoExists:
    def test_returns_dict_when_exists(self, migrator):
        mock_repo = MagicMock()
        mock_repo.name = "my-repo"
        mock_repo.full_name = "jdoe/my-repo"
        mock_repo.private = False
        mock_repo.default_branch = "main"
        migrator._gh.get_repo = MagicMock(return_value=mock_repo)
        migrator._cached_user = "jdoe"
        result = migrator.check_repo_exists("my-repo")
        assert result == {"name": "my-repo", "full_name": "jdoe/my-repo", "private": False, "default_branch": "main"}

    def test_returns_none_when_404(self, migrator):
        from github import UnknownObjectException
        migrator._gh.get_repo = MagicMock(side_effect=UnknownObjectException(404, "Not Found"))
        migrator._cached_user = "jdoe"
        result = migrator.check_repo_exists("missing-repo")
        assert result is None

    def test_uses_org_when_set(self, org_migrator):
        mock_repo = MagicMock()
        mock_repo.name = "r"
        mock_repo.full_name = "my-org/r"
        mock_repo.private = False
        mock_repo.default_branch = "main"
        org_migrator._gh.get_repo = MagicMock(return_value=mock_repo)
        org_migrator.check_repo_exists("r")
        org_migrator._gh.get_repo.assert_called_once_with("my-org/r")


class TestIsRepoEmpty:
    def test_true_on_409(self, migrator):
        from github import GithubException
        mock_repo = MagicMock()
        exc = GithubException(409, "Git Repository is empty", {})
        mock_repo.get_git_refs = MagicMock(side_effect=exc)
        migrator._gh.get_repo = MagicMock(return_value=mock_repo)
        migrator._cached_user = "jdoe"
        assert migrator.is_repo_empty("repo") is True

    def test_true_on_empty_refs(self, migrator):
        mock_repo = MagicMock()
        mock_repo.get_git_refs = MagicMock(return_value=[])
        migrator._gh.get_repo = MagicMock(return_value=mock_repo)
        migrator._cached_user = "jdoe"
        assert migrator.is_repo_empty("repo") is True

    def test_false_when_refs_exist(self, migrator):
        mock_ref = MagicMock()
        mock_repo = MagicMock()
        mock_repo.get_git_refs = MagicMock(return_value=[mock_ref])
        migrator._gh.get_repo = MagicMock(return_value=mock_repo)
        migrator._cached_user = "jdoe"
        assert migrator.is_repo_empty("repo") is False


class TestGetGithubLatestCommit:
    def test_returns_sha(self, migrator):
        mock_commit = MagicMock()
        mock_commit.sha = "abc123"
        mock_branch = MagicMock()
        mock_branch.commit = mock_commit
        mock_repo = MagicMock()
        mock_repo.get_branch = MagicMock(return_value=mock_branch)
        migrator._gh.get_repo = MagicMock(return_value=mock_repo)
        migrator._cached_user = "jdoe"
        result = migrator.get_github_latest_commit("repo", "main")
        assert result == "abc123"

    def test_returns_none_on_404(self, migrator):
        from github import UnknownObjectException
        mock_repo = MagicMock()
        mock_repo.get_branch = MagicMock(side_effect=UnknownObjectException(404, "Not Found"))
        migrator._gh.get_repo = MagicMock(return_value=mock_repo)
        migrator._cached_user = "jdoe"
        result = migrator.get_github_latest_commit("repo", "missing-branch")
        assert result is None


class TestBuildAuthenticatedUrl:
    def test_inserts_credentials(self, migrator):
        url = "https://gitlab.com/org/repo.git"
        result = migrator._build_authenticated_url(url, "mytoken", username="oauth2")
        assert result == "https://oauth2:mytoken@gitlab.com/org/repo.git"

    def test_replaces_existing_credentials(self, migrator):
        url = "https://old:oldtoken@gitlab.com/org/repo.git"
        result = migrator._build_authenticated_url(url, "newtoken", username="oauth2")
        assert "oldtoken" not in result
        assert "newtoken" in result


class TestPushBranchInSlices:
    """Tests for _push_branch_in_slices checkpoint logic."""

    def _make_commits(self, n: int):
        return [f"sha{i:04d}" for i in range(n)]

    def test_single_slice_when_few_commits(self, migrator):
        """10 commits with slice=500 → one push (the final SHA)."""
        commits = self._make_commits(10)
        mock_log = MagicMock()
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with patch.object(migrator, "_get_branch_commits", return_value=commits):
            with patch("subprocess.run", return_value=mock_result) as mock_run:
                migrator._push_branch_in_slices(
                    mirror_path="/tmp/fake",
                    remote_url="https://x-access-token:tok@github.com/org/repo.git",
                    ref="refs/heads/main",
                    log=mock_log,
                    commits_per_slice=500,
                )
        # One push for 10 commits (all fit in one slice)
        push_calls = [c for c in mock_run.call_args_list if "push" in c[0][0]]
        assert len(push_calls) == 1
        assert commits[-1] in push_calls[0][0][0][-1]

    def test_multiple_slices(self, migrator):
        """105 commits with slice=50 → 3 slices (50, 100, 104)."""
        commits = self._make_commits(105)
        mock_log = MagicMock()
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with patch.object(migrator, "_get_branch_commits", return_value=commits):
            with patch("subprocess.run", return_value=mock_result) as mock_run:
                migrator._push_branch_in_slices(
                    mirror_path="/tmp/fake",
                    remote_url="https://x-access-token:tok@github.com/org/repo.git",
                    ref="refs/heads/main",
                    log=mock_log,
                    commits_per_slice=50,
                )
        push_calls = [c for c in mock_run.call_args_list if "push" in c[0][0]]
        # ceil(105 / 50) = 3 slices
        assert len(push_calls) == 3

    def test_raises_on_push_failure(self, migrator):
        commits = self._make_commits(5)
        mock_log = MagicMock()
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "remote: rejected"

        with patch.object(migrator, "_get_branch_commits", return_value=commits):
            with patch("subprocess.run", return_value=mock_result):
                with pytest.raises(RuntimeError, match="git push failed"):
                    migrator._push_branch_in_slices(
                        mirror_path="/tmp/fake",
                        remote_url="https://x-access-token:tok@github.com/org/repo.git",
                        ref="refs/heads/main",
                        log=mock_log,
                        commits_per_slice=500,
                    )

    def test_skips_empty_branch(self, migrator):
        mock_log = MagicMock()
        with patch.object(migrator, "_get_branch_commits", return_value=[]):
            with patch("subprocess.run") as mock_run:
                migrator._push_branch_in_slices(
                    mirror_path="/tmp/fake",
                    remote_url="https://x-access-token:tok@github.com/org/repo.git",
                    ref="refs/heads/empty",
                    log=mock_log,
                )
        mock_run.assert_not_called()


class TestSafeRepoName:
    def test_valid_simple_name(self, migrator):
        assert migrator._safe_repo_name("my-repo") == "my-repo"

    def test_valid_name_with_dots_and_underscore(self, migrator):
        assert migrator._safe_repo_name("my.repo_1") == "my.repo_1"

    def test_slash_raises_value_error(self, migrator):
        with pytest.raises(ValueError):
            migrator._safe_repo_name("org/repo")

    def test_path_traversal_raises_value_error(self, migrator):
        with pytest.raises(ValueError):
            migrator._safe_repo_name("../etc/passwd")

    def test_space_raises_value_error(self, migrator):
        with pytest.raises(ValueError):
            migrator._safe_repo_name("my repo")


class TestGetGithubBranches:
    def test_empty_response_returns_empty_list(self, migrator):
        mock_repo = MagicMock()
        mock_repo.get_branches = MagicMock(return_value=[])
        migrator._gh.get_repo = MagicMock(return_value=mock_repo)
        migrator._cached_user = "jdoe"
        result = migrator.get_github_branches("repo")
        assert result == []

    def test_single_page_returns_all_branches(self, migrator):
        mock_branches = [MagicMock() for i in range(5)]
        for i, b in enumerate(mock_branches):
            b.name = f"branch-{i}"
        mock_repo = MagicMock()
        mock_repo.get_branches = MagicMock(return_value=mock_branches)
        migrator._gh.get_repo = MagicMock(return_value=mock_repo)
        migrator._cached_user = "jdoe"
        result = migrator.get_github_branches("repo")
        assert result == [f"branch-{i}" for i in range(5)]

    def test_paginated_returns_all_branches(self, migrator):
        """PyGitHub handles pagination automatically."""
        mock_branches = [MagicMock() for _ in range(150)]
        for i, b in enumerate(mock_branches):
            b.name = f"branch-{i}"
        mock_repo = MagicMock()
        mock_repo.get_branches = MagicMock(return_value=mock_branches)
        migrator._gh.get_repo = MagicMock(return_value=mock_repo)
        migrator._cached_user = "jdoe"
        result = migrator.get_github_branches("repo")
        assert len(result) == 150

    def test_uses_org_when_set(self, org_migrator):
        mock_repo = MagicMock()
        mock_repo.get_branches = MagicMock(return_value=[])
        org_migrator._gh.get_repo = MagicMock(return_value=mock_repo)
        org_migrator.get_github_branches("repo")
        org_migrator._gh.get_repo.assert_called_once_with("my-org/repo")


class TestGetGitlabLatestCommit:
    def test_returns_sha_on_200(self, migrator):
        with patch("requests.get", return_value=_mock_response(200, {"id": "abcdef123"})):
            result = migrator.get_gitlab_latest_commit(
                "https://gitlab.com/org/repo.git", "main", "token"
            )
        assert result == "abcdef123"

    def test_returns_none_on_404(self, migrator):
        with patch("requests.get", return_value=_mock_response(404)):
            result = migrator.get_gitlab_latest_commit(
                "https://gitlab.com/org/repo.git", "main"
            )
        assert result is None

    def test_uses_private_token_header_when_given(self, migrator):
        with patch("requests.get", return_value=_mock_response(200, {"id": "abc"})) as mock_get:
            migrator.get_gitlab_latest_commit(
                "https://gitlab.com/org/repo.git", "main", "my-gitlab-token"
            )
        headers = mock_get.call_args[1]["headers"]
        assert headers.get("PRIVATE-TOKEN") == "my-gitlab-token"

    def test_no_token_sends_no_auth_header(self, migrator):
        with patch("requests.get", return_value=_mock_response(200, {"id": "abc"})) as mock_get:
            migrator.get_gitlab_latest_commit("https://gitlab.com/org/repo.git", "main")
        headers = mock_get.call_args[1]["headers"]
        assert "PRIVATE-TOKEN" not in headers


class TestCompareRepos:
    def test_same_sha_returns_true(self, migrator):
        with patch.object(migrator, "get_github_latest_commit", return_value="abc123"):
            with patch.object(migrator, "get_gitlab_latest_commit", return_value="abc123"):
                success, msg = migrator.compare_repos(
                    repo_name="repo",
                    source_url="https://gitlab.com/o/r.git",
                    default_branch="main",
                )
        assert success is True
        assert msg == ""

    def test_github_behind_returns_false(self, migrator):
        mock_comparison = MagicMock()
        mock_comparison.ahead_by = 0
        mock_comparison.behind_by = 3
        mock_comparison.status = "behind"
        mock_repo = MagicMock()
        mock_repo.compare = MagicMock(return_value=mock_comparison)
        migrator._gh.get_repo = MagicMock(return_value=mock_repo)
        migrator._cached_user = "jdoe"
        with patch.object(migrator, "get_github_latest_commit", return_value="aaaa1111"):
            with patch.object(migrator, "get_gitlab_latest_commit", return_value="bbbb2222"):
                success, msg = migrator.compare_repos(
                    repo_name="repo",
                    source_url="https://gitlab.com/o/r.git",
                    default_branch="main",
                )
        assert success is False
        assert "missing" in msg.lower() or "out of sync" in msg.lower()

    def test_github_ahead_returns_true(self, migrator):
        mock_comparison = MagicMock()
        mock_comparison.ahead_by = 5
        mock_comparison.behind_by = 0
        mock_comparison.status = "ahead"
        mock_repo = MagicMock()
        mock_repo.compare = MagicMock(return_value=mock_comparison)
        migrator._gh.get_repo = MagicMock(return_value=mock_repo)
        migrator._cached_user = "jdoe"
        with patch.object(migrator, "get_github_latest_commit", return_value="aaaa1111"):
            with patch.object(migrator, "get_gitlab_latest_commit", return_value="bbbb2222"):
                success, msg = migrator.compare_repos(
                    repo_name="repo",
                    source_url="https://gitlab.com/o/r.git",
                    default_branch="main",
                )
        assert success is True
        assert msg == ""

    def test_none_shas_returns_false(self, migrator):
        with patch.object(migrator, "get_github_latest_commit", return_value=None):
            with patch.object(migrator, "get_gitlab_latest_commit", return_value=None):
                success, msg = migrator.compare_repos(
                    repo_name="repo",
                    source_url="https://gitlab.com/o/r.git",
                    default_branch="main",
                )
        assert success is False
        assert "Could not retrieve" in msg

    def test_compare_404_returns_false(self, migrator):
        """GitLab SHA not found in GitHub history."""
        from github import GithubException
        exc = GithubException(404, "Not Found", {})
        mock_repo = MagicMock()
        mock_repo.compare = MagicMock(side_effect=exc)
        migrator._gh.get_repo = MagicMock(return_value=mock_repo)
        migrator._cached_user = "jdoe"
        with patch.object(migrator, "get_github_latest_commit", return_value="aaaa1111"):
            with patch.object(migrator, "get_gitlab_latest_commit", return_value="bbbb2222"):
                success, msg = migrator.compare_repos(
                    repo_name="repo",
                    source_url="https://gitlab.com/o/r.git",
                    default_branch="main",
                )
        assert success is False
        assert "not found" in msg.lower() or "out of sync" in msg.lower() or "error" in msg.lower()

    def test_compare_unexpected_status_returns_false(self, migrator):
        """Unexpected HTTP status from compare API returns False."""
        from github import GithubException
        exc = GithubException(500, "Server Error", {})
        mock_repo = MagicMock()
        mock_repo.compare = MagicMock(side_effect=exc)
        migrator._gh.get_repo = MagicMock(return_value=mock_repo)
        migrator._cached_user = "jdoe"
        with patch.object(migrator, "get_github_latest_commit", return_value="aaaa1111"):
            with patch.object(migrator, "get_gitlab_latest_commit", return_value="bbbb2222"):
                success, msg = migrator.compare_repos(
                    repo_name="repo",
                    source_url="https://gitlab.com/o/r.git",
                    default_branch="main",
                )
        assert success is False


class TestBlobLineToPattern:
    def test_blob_above_threshold_returns_ext(self):
        line = "sha123 blob 1000 path/to/file.zip"
        result = GitHubMigrator._blob_line_to_pattern(line, threshold_bytes=500)
        assert result == "*.zip"

    def test_blob_at_threshold_returns_none(self):
        line = "sha123 blob 500 file.zip"
        result = GitHubMigrator._blob_line_to_pattern(line, threshold_bytes=500)
        assert result is None

    def test_blob_below_threshold_returns_none(self):
        line = "sha123 blob 100 file.zip"
        result = GitHubMigrator._blob_line_to_pattern(line, threshold_bytes=500)
        assert result is None

    def test_non_blob_type_returns_none(self):
        line = "sha123 tree 1000 some-dir"
        result = GitHubMigrator._blob_line_to_pattern(line, threshold_bytes=100)
        assert result is None

    def test_too_few_parts_returns_none(self):
        line = "sha123 blob"
        result = GitHubMigrator._blob_line_to_pattern(line, threshold_bytes=100)
        assert result is None

    def test_file_with_no_extension_returns_path(self):
        line = "sha123 blob 1000 Makefile"
        result = GitHubMigrator._blob_line_to_pattern(line, threshold_bytes=500)
        assert result == "Makefile"

    def test_invalid_size_returns_none(self):
        line = "sha123 blob notanumber file.zip"
        result = GitHubMigrator._blob_line_to_pattern(line, threshold_bytes=100)
        assert result is None

    def test_file_extension_is_lowercased(self):
        line = "sha123 blob 1000 archive.ZIP"
        result = GitHubMigrator._blob_line_to_pattern(line, threshold_bytes=500)
        assert result == "*.zip"


class TestCreateGithubRepo:
    def test_201_returns_none(self, migrator):
        log = MagicMock()
        mock_user = MagicMock()
        mock_user.create_repo = MagicMock(return_value=MagicMock())
        migrator._gh.get_user = MagicMock(return_value=mock_user)
        migrator._cached_user = "jdoe"
        result = migrator._create_github_repo("repo", True, None, log)
        assert result is None

    def test_422_returns_synced_dict(self, migrator):
        from github import GithubException
        log = MagicMock()
        mock_user = MagicMock()
        mock_user.create_repo = MagicMock(side_effect=GithubException(422, "already exists", {}))
        migrator._gh.get_user = MagicMock(return_value=mock_user)
        migrator._cached_user = "jdoe"
        result = migrator._create_github_repo("repo", True, None, log)
        assert result is not None
        assert result["status"] == "synced"

    def test_201_with_description(self, migrator):
        log = MagicMock()
        mock_user = MagicMock()
        mock_user.create_repo = MagicMock(return_value=MagicMock())
        migrator._gh.get_user = MagicMock(return_value=mock_user)
        migrator._cached_user = "jdoe"
        migrator._create_github_repo("repo", False, "My description", log)
        mock_user.create_repo.assert_called_once_with(
            name="repo",
            private=False,
            auto_init=False,
            description="My description",
        )

    def test_org_repo_uses_org_url(self, org_migrator):
        log = MagicMock()
        mock_org = MagicMock()
        mock_org.create_repo = MagicMock(return_value=MagicMock())
        org_migrator._gh.get_organization = MagicMock(return_value=mock_org)
        org_migrator._create_github_repo("repo", True, None, log)
        org_migrator._gh.get_organization.assert_called_once_with("my-org")
        mock_org.create_repo.assert_called_once()


class TestMaybeArchive:
    """Tests for _maybe_archive helper."""

    def test_archives_when_all_conditions_met(self, migrator):
        log = MagicMock()
        gitlab_client = MagicMock()
        gitlab_client.archive_project.return_value = True
        migrator._maybe_archive(True, gitlab_client, 42, log)
        gitlab_client.archive_project.assert_called_once_with(42)

    def test_skips_when_archive_synced_false(self, migrator):
        log = MagicMock()
        gitlab_client = MagicMock()
        migrator._maybe_archive(False, gitlab_client, 42, log)
        gitlab_client.archive_project.assert_not_called()

    def test_skips_when_no_gitlab_client(self, migrator):
        log = MagicMock()
        migrator._maybe_archive(True, None, 42, log)  # no error

    def test_logs_warning_when_archive_fails(self, migrator):
        log = MagicMock()
        gitlab_client = MagicMock()
        gitlab_client.archive_project.return_value = False
        migrator._maybe_archive(True, gitlab_client, 42, log)
        log.warning.assert_called()


class TestMigrateRepository:
    def test_complete_status_returns_true(self, migrator):
        with patch.object(migrator, "start_import", return_value={"status": "complete"}):
            success, reason = migrator.migrate_repository(
                source_url="https://gitlab.com/o/r.git",
                repo_name="my-repo",
            )
        assert success is True
        assert reason == ""

    def test_synced_status_returns_true(self, migrator):
        with patch.object(migrator, "start_import", return_value={"status": "synced"}):
            success, reason = migrator.migrate_repository(
                source_url="https://gitlab.com/o/r.git",
                repo_name="my-repo",
            )
        assert success is True
        assert reason == ""

    def test_exception_returns_false_with_message(self, migrator):
        with patch.object(migrator, "start_import", side_effect=Exception("clone failed")):
            success, reason = migrator.migrate_repository(
                source_url="https://gitlab.com/o/r.git",
                repo_name="my-repo",
            )
        assert success is False
        assert "clone failed" in reason

    def test_runtime_error_returns_false(self, migrator):
        with patch.object(migrator, "start_import", side_effect=RuntimeError("git push failed")):
            success, reason = migrator.migrate_repository(
                source_url="https://gitlab.com/o/r.git",
                repo_name="my-repo",
            )
        assert success is False
        assert "git push failed" in reason


class TestMigrateRepositories:
    def _repo(self, name, url=None):
        return {
            "repo_name": name,
            "source_url": url or f"https://gitlab.com/o/{name}.git",
            "private": True,
        }

    def test_single_success_sequential(self, migrator):
        with patch.object(migrator, "migrate_repository", return_value=(True, "")):
            with patch("migrator.clients.github.time.sleep"):
                results = migrator.migrate_repositories([self._repo("repo1")])
        assert results["repo1"]["success"] is True
        assert results["repo1"]["reason"] == ""

    def test_single_failure_calls_reporter(self, migrator):
        reporter = MagicMock()
        with patch.object(migrator, "migrate_repository", return_value=(False, "clone error")):
            with patch("migrator.clients.github.time.sleep"):
                results = migrator.migrate_repositories(
                    [self._repo("repo1")],
                    errors_reporter=reporter,
                )
        assert results["repo1"]["success"] is False
        reporter.write.assert_called_once_with(
            repo_name="repo1",
            source_url="https://gitlab.com/o/repo1.git",
            reason="clone error",
        )

    def test_two_repos_sequential(self, migrator):
        with patch.object(migrator, "migrate_repository", return_value=(True, "")):
            with patch("migrator.clients.github.time.sleep"):
                results = migrator.migrate_repositories(
                    [self._repo("repo1"), self._repo("repo2")]
                )
        assert len(results) == 2
        assert results["repo1"]["success"] is True
        assert results["repo2"]["success"] is True

    def test_two_repos_parallel(self, migrator):
        with patch.object(migrator, "migrate_repository", return_value=(True, "")):
            results = migrator.migrate_repositories(
                [self._repo("repo1"), self._repo("repo2")],
                workers=2,
            )
        assert len(results) == 2
        assert results["repo1"]["success"] is True
        assert results["repo2"]["success"] is True

    def test_success_without_reporter(self, migrator):
        """No errors_reporter provided should not cause errors."""
        with patch.object(migrator, "migrate_repository", return_value=(True, "")):
            with patch("migrator.clients.github.time.sleep"):
                results = migrator.migrate_repositories([self._repo("repo1")])
        assert results["repo1"]["success"] is True

    def test_source_url_stored_in_results(self, migrator):
        with patch.object(migrator, "migrate_repository", return_value=(True, "")):
            with patch("migrator.clients.github.time.sleep"):
                results = migrator.migrate_repositories(
                    [self._repo("repo1", "https://example.com/repo1.git")]
                )
        assert results["repo1"]["source_url"] == "https://example.com/repo1.git"


class TestCompareAllBranches:
    def test_all_in_sync_returns_true(self, migrator):
        with patch.object(migrator, "get_github_branches", return_value=["main"]):
            with patch.object(migrator, "compare_repos", return_value=(True, "")):
                success, msg = migrator.compare_all_branches(
                    repo_name="repo",
                    source_url="https://gitlab.com/o/r.git",
                    gitlab_branches=["main"],
                )
        assert success is True
        assert msg == ""

    def test_missing_branch_returns_false(self, migrator):
        with patch.object(migrator, "get_github_branches", return_value=[]):
            success, msg = migrator.compare_all_branches(
                repo_name="repo",
                source_url="https://gitlab.com/o/r.git",
                gitlab_branches=["main", "develop"],
            )
        assert success is False
        assert "missing" in msg.lower()

    def test_out_of_sync_branch_returns_false(self, migrator):
        with patch.object(migrator, "get_github_branches", return_value=["main"]):
            with patch.object(migrator, "compare_repos", return_value=(False, "behind by 3")):
                success, msg = migrator.compare_all_branches(
                    repo_name="repo",
                    source_url="https://gitlab.com/o/r.git",
                    gitlab_branches=["main"],
                )
        assert success is False
        assert "out of sync" in msg.lower()
