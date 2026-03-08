import logging
from typing import Dict, List, Optional

import gitlab
from gitlab.exceptions import GitlabError

logger = logging.getLogger("migrator")


class GitLabClient:
    """Fetches repository metadata from GitLab using the python-gitlab SDK."""

    def __init__(self, gitlab_token: str, base_url: str = "https://gitlab.com"):
        self._gl = gitlab.Gitlab(url=base_url, private_token=gitlab_token)
        logger.debug(f"GitLabClient initialised — url={base_url}")

    def list_user_repos(self, username: Optional[str] = None) -> List[Dict]:
        """
        List repositories for a user.
        If username is None, lists repos owned by the authenticated user.
        """
        try:
            if username:
                logger.debug(f"list_user_repos → user={username}")
                user = self._gl.users.list(username=username)[0]
                projects = user.projects.list(all=True, archived=False)
            else:
                logger.debug("list_user_repos → authenticated user")
                projects = self._gl.projects.list(
                    all=True, owned=True, membership=True, archived=False
                )
        except GitlabError as exc:
            logger.error(f"GitLab API error listing user repos: {exc}")
            raise

        logger.debug(f"list_user_repos ← {len(projects)} project(s)")
        return [p.asdict() for p in projects]

    def list_group_repos(self, group: str) -> List[Dict]:
        """List all repositories inside a GitLab group / subgroup (recursive)."""
        try:
            logger.debug(f"list_group_repos → group={group}")
            gl_group = self._gl.groups.get(group)
            projects = gl_group.projects.list(
                all=True, include_subgroups=True, archived=False
            )
        except GitlabError as exc:
            logger.error(f"GitLab API error listing group repos: {exc}")
            raise

        logger.debug(f"list_group_repos ← {len(projects)} project(s)")
        return [p.asdict() for p in projects]

    def list_branches(self, project_id: int) -> List[str]:
        """Return list of branch names for a GitLab project."""
        try:
            logger.debug(f"list_branches → project_id={project_id}")
            project = self._gl.projects.get(project_id)
            branches = project.branches.list(all=True)
        except GitlabError as exc:
            logger.error(f"GitLab API error listing branches for project {project_id}: {exc}")
            raise

        names = [b.name for b in branches]
        logger.debug(f"list_branches ← {len(names)} branch(es)")
        return names

    def archive_project(self, project_id: int) -> bool:
        """
        Archive a GitLab project.

        Returns:
            True on success, False otherwise.
        """
        try:
            logger.debug(f"archive_project → project_id={project_id}")
            project = self._gl.projects.get(project_id)
            project.archive()
            logger.debug(f"archive_project ← success")
            return True
        except GitlabError as exc:
            logger.error(f"Failed to archive GitLab project {project_id}: {exc}")
            return False

    def repos_to_migration_list(self, projects: List[Dict], private: bool = True) -> List[Dict]:
        """Convert GitLab project dicts into the migration config format."""
        return [
            {
                "source_url":        project["http_url_to_repo"],
                "repo_name":         project["path"],
                "description":       project.get("description") or "",
                "private":           private,
                "gitlab_project_id": project["id"],
            }
            for project in projects
        ]
