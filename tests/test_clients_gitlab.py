"""Unit tests for migrator/clients/gitlab.py"""
from unittest.mock import MagicMock, patch, PropertyMock
import pytest
from gitlab.exceptions import GitlabError
from migrator.clients.gitlab import GitLabClient


@pytest.fixture
def mock_gl():
    """Return a patched Gitlab instance and the GitLabClient wrapping it."""
    with patch("migrator.clients.gitlab.gitlab.Gitlab") as MockGitlab:
        gl_instance = MagicMock()
        MockGitlab.return_value = gl_instance
        client = GitLabClient(gitlab_token="test-token", base_url="https://gitlab.com")
        yield client, gl_instance


class TestListUserRepos:
    def test_authenticated_user(self, mock_gl):
        client, gl = mock_gl
        proj = MagicMock()
        proj.asdict.return_value = {"id": 1, "path": "repo1", "http_url_to_repo": "https://gitlab.com/user/repo1.git"}
        gl.projects.list.return_value = [proj]

        result = client.list_user_repos()

        gl.projects.list.assert_called_once_with(all=True, owned=True, membership=True, archived=False)
        assert len(result) == 1
        assert result[0]["path"] == "repo1"

    def test_specific_username(self, mock_gl):
        client, gl = mock_gl
        user = MagicMock()
        proj = MagicMock()
        proj.asdict.return_value = {"id": 2, "path": "repo2", "http_url_to_repo": "https://gitlab.com/other/repo2.git"}
        user.projects.list.return_value = [proj]
        gl.users.list.return_value = [user]

        result = client.list_user_repos(username="otheruser")

        gl.users.list.assert_called_once_with(username="otheruser")
        assert result[0]["path"] == "repo2"

    def test_raises_on_gitlab_error(self, mock_gl):
        client, gl = mock_gl
        gl.projects.list.side_effect = GitlabError("unauthorized")
        with pytest.raises(GitlabError):
            client.list_user_repos()


class TestListGroupRepos:
    def test_lists_group_projects(self, mock_gl):
        client, gl = mock_gl
        group = MagicMock()
        proj = MagicMock()
        proj.asdict.return_value = {"id": 3, "path": "repo3", "http_url_to_repo": "https://gitlab.com/grp/repo3.git"}
        group.projects.list.return_value = [proj]
        gl.groups.get.return_value = group

        result = client.list_group_repos("mygroup")

        gl.groups.get.assert_called_once_with("mygroup")
        group.projects.list.assert_called_once_with(all=True, include_subgroups=True, archived=False)
        assert result[0]["path"] == "repo3"

    def test_raises_on_gitlab_error(self, mock_gl):
        client, gl = mock_gl
        gl.groups.get.side_effect = GitlabError("not found")
        with pytest.raises(GitlabError):
            client.list_group_repos("missing-group")


class TestListBranches:
    def test_returns_branch_names(self, mock_gl):
        client, gl = mock_gl
        project = MagicMock()
        b1, b2 = MagicMock(), MagicMock()
        b1.name, b2.name = "main", "develop"
        project.branches.list.return_value = [b1, b2]
        gl.projects.get.return_value = project

        result = client.list_branches(42)

        gl.projects.get.assert_called_once_with(42)
        assert result == ["main", "develop"]

    def test_raises_on_gitlab_error(self, mock_gl):
        client, gl = mock_gl
        gl.projects.get.side_effect = GitlabError("not found")
        with pytest.raises(GitlabError):
            client.list_branches(42)


class TestArchiveProject:
    def test_returns_true_on_success(self, mock_gl):
        client, gl = mock_gl
        project = MagicMock()
        gl.projects.get.return_value = project

        assert client.archive_project(99) is True
        project.archive.assert_called_once()

    def test_returns_false_on_gitlab_error(self, mock_gl):
        client, gl = mock_gl
        project = MagicMock()
        project.archive.side_effect = GitlabError("forbidden")
        gl.projects.get.return_value = project

        assert client.archive_project(99) is False


class TestReposToMigrationList:
    def test_converts_correctly(self, mock_gl):
        client, _ = mock_gl
        projects = [
            {
                "id": 10,
                "path": "my-repo",
                "http_url_to_repo": "https://gitlab.com/org/my-repo.git",
                "description": "A repo",
            }
        ]
        result = client.repos_to_migration_list(projects, private=True)
        assert len(result) == 1
        entry = result[0]
        assert entry["source_url"] == "https://gitlab.com/org/my-repo.git"
        assert entry["repo_name"] == "my-repo"
        assert entry["description"] == "A repo"
        assert entry["private"] is True
        assert entry["gitlab_project_id"] == 10

    def test_missing_description_defaults_to_empty_string(self, mock_gl):
        client, _ = mock_gl
        projects = [{"id": 1, "path": "r", "http_url_to_repo": "https://gitlab.com/o/r.git"}]
        result = client.repos_to_migration_list(projects)
        assert result[0]["description"] == ""
