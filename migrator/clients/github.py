import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import requests
from urllib.parse import urlparse as _urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

from migrator.formatting.repo_logger import RepoLogger
from migrator.utils.urls import _redact_url
from migrator.utils.lfs import _lfs_available
from migrator.reporting.errors import ErrorsReporter

if TYPE_CHECKING:
    from migrator.clients.gitlab import GitLabClient

logger = logging.getLogger("migrator")

_REFS_HEADS = "refs/heads/"
_REPO_NAME_RE = re.compile(r'^[a-zA-Z0-9._\-]+$')


class GitHubMigrator:
    """Handles migration of repositories from GitLab to GitHub"""

    def __init__(self, github_token: str, github_org: Optional[str] = None):
        """
        Initialize the migrator

        Args:
            github_token: GitHub Personal Access Token with repo and import permissions
            github_org: GitHub organization name (optional, uses authenticated user if not provided)
        """
        self.github_token = github_token
        self.github_org = github_org
        self.github_api_base = "https://api.github.com"
        self.headers = {
            "Authorization": f"token {github_token}",
            "Accept": "application/vnd.github.v3+json"
        }

    def get_github_user(self) -> str:
        """Get the authenticated GitHub user"""
        response = requests.get(
            f"{self.github_api_base}/user",
            headers=self.headers
        )
        response.raise_for_status()
        return response.json()["login"]

    def _safe_repo_name(self, repo_name: str) -> str:
        """Validate repo_name contains only safe characters for URL path construction."""
        if not _REPO_NAME_RE.match(repo_name):
            raise ValueError(f"Invalid repository name: {repo_name!r}")
        return repo_name

    def check_repo_exists(self, repo_name: str) -> Optional[Dict]:
        """
        Check if a repository already exists on GitHub.

        Returns:
            The repo info dict if it exists, None otherwise.
        """
        repo_name = self._safe_repo_name(repo_name)
        owner = self.github_org if self.github_org else self.get_github_user()
        url = f"{self.github_api_base}/repos/{owner}/{repo_name}"
        logger.debug(f"check_repo_exists → GET {url}")

        response = requests.get(url, headers=self.headers)
        logger.debug(f"check_repo_exists ← {response.status_code}")

        if response.status_code == 200:
            return response.json()
        elif response.status_code == 404:
            return None
        else:
            response.raise_for_status()

    def get_github_latest_commit(self, repo_name: str, branch: str) -> Optional[str]:
        """Return the latest commit SHA on *branch* from the GitHub repo, or None."""
        repo_name = self._safe_repo_name(repo_name)
        owner = self.github_org if self.github_org else self.get_github_user()
        url = f"{self.github_api_base}/repos/{owner}/{repo_name}/commits/{branch}"
        logger.debug(f"get_github_latest_commit → GET {url}")
        response = requests.get(url, headers=self.headers)
        logger.debug(f"get_github_latest_commit ← {response.status_code}")
        if response.status_code == 200:
            sha = response.json().get("sha")
            logger.debug(f"get_github_latest_commit  sha={sha}")
            return sha
        return None

    def is_repo_empty(self, repo_name: str) -> bool:
        """
        Return True if the GitHub repo exists but has no commits/branches.

        GitHub returns 409 Conflict with "Git Repository is empty" when the repo
        was just created and has never received a push. It may also return an
        empty array on the /branches endpoint in some edge cases.
        """
        repo_name = self._safe_repo_name(repo_name)
        owner = self.github_org if self.github_org else self.get_github_user()

        # /git/refs returns 409 for a truly empty repo, 200 with [] if there are no refs,
        # and 200 with data when there are commits.
        url = f"{self.github_api_base}/repos/{owner}/{repo_name}/git/refs"
        logger.debug(f"is_repo_empty → GET {url}")
        response = requests.get(url, headers=self.headers)
        logger.debug(f"is_repo_empty ← {response.status_code}")

        if response.status_code == 409:
            # "Git Repository is empty" — confirmed empty
            logger.debug("is_repo_empty: 409 Conflict → repo is empty")
            return True
        if response.status_code == 200:
            empty = len(response.json()) == 0
            logger.debug(f"is_repo_empty: 200, refs={len(response.json())} → empty={empty}")
            return empty
        # Any other status (404, 4xx) — cannot determine, assume not empty
        logger.debug(f"is_repo_empty: unexpected status {response.status_code} → assume not empty")
        return False

    def get_github_branches(self, repo_name: str) -> List[str]:
        """Return the list of branch names present in the GitHub repo."""
        repo_name = self._safe_repo_name(repo_name)
        owner = self.github_org if self.github_org else self.get_github_user()
        branches = []
        page = 1
        while True:
            url = f"{self.github_api_base}/repos/{owner}/{repo_name}/branches"
            response = requests.get(url, headers=self.headers, params={"per_page": 100, "page": page})
            response.raise_for_status()
            data = response.json()
            if not data:
                break
            branches.extend(b["name"] for b in data)
            if len(data) < 100:
                break
            page += 1
        return branches

    def compare_all_branches(
        self,
        repo_name: str,
        source_url: str,
        gitlab_branches: List[str],
        gitlab_token: Optional[str] = None,
        log: Optional["RepoLogger"] = None,
    ) -> Tuple[bool, str]:
        """
        Verify that every GitLab branch exists on GitHub and is in sync
        (GitHub contains all commits from that branch — may be ahead).

        Returns:
            (all_synced: bool, detail_message: str)
        """
        log = log or RepoLogger(repo_name)
        github_branches = set(self.get_github_branches(repo_name))
        out_of_sync: List[str] = []
        missing: List[str] = []

        for branch in gitlab_branches:
            if branch not in github_branches:
                missing.append(branch)
                continue

            in_sync, msg = self.compare_repos(
                repo_name=repo_name,
                source_url=source_url,
                default_branch=branch,
                gitlab_token=gitlab_token,
                log=log,
            )
            if not in_sync:
                out_of_sync.append(f"{branch}: {msg}")

        issues: List[str] = []
        if missing:
            issues.append(f"branches missing on GitHub: {', '.join(missing)}")
        if out_of_sync:
            issues.append("branches out of sync: " + "; ".join(out_of_sync))

        if issues:
            return False, " | ".join(issues)

        return True, ""

    def get_gitlab_latest_commit(
        self, source_url: str, branch: str, gitlab_token: Optional[str] = None
    ) -> Optional[str]:
        """
        Return the latest commit SHA on *branch* from the GitLab repo via API.
        Derives the API endpoint from the clone URL.
        """
        from urllib.parse import urlparse
        import urllib.parse as _up

        parsed = urlparse(source_url)
        # strip .git suffix and leading /
        project_path = parsed.path.lstrip("/").removesuffix(".git")
        base = f"{parsed.scheme}://{parsed.netloc}"
        encoded = _up.quote(project_path, safe="")
        api_url = f"{base}/api/v4/projects/{encoded}/repository/commits/{branch}"
        logger.debug(f"get_gitlab_latest_commit → GET {api_url}")

        headers = {}
        if gitlab_token:
            headers["PRIVATE-TOKEN"] = gitlab_token

        response = requests.get(api_url, headers=headers)
        logger.debug(f"get_gitlab_latest_commit ← {response.status_code}")
        if response.status_code == 200:
            sha = response.json().get("id")
            logger.debug(f"get_gitlab_latest_commit  sha={sha}")
            return sha
        return None

    def compare_repos(
        self,
        repo_name: str,
        source_url: str,
        default_branch: str,
        gitlab_token: Optional[str] = None,
        log: Optional["RepoLogger"] = None,
    ) -> Tuple[bool, str]:
        """
        Compare the default branch between GitHub (destination) and GitLab (origin).

        Uses GitHub's compare API to check whether the GitLab HEAD commit is
        already reachable from the GitHub branch (i.e. GitHub is ahead or equal).

        Logic:
          - If SHAs are equal                    → in sync  ✓
          - If GitHub has GitLab HEAD in history  → GitHub is ahead, nothing missing → in sync  ✓
          - If GitLab has commits not in GitHub   → out of sync  ✗

        Returns:
            (in_sync: bool, message: str)
        """
        repo_name = self._safe_repo_name(repo_name)
        log = log or RepoLogger(repo_name)
        gh_sha = self.get_github_latest_commit(repo_name, default_branch)
        gl_sha = self.get_gitlab_latest_commit(source_url, default_branch, gitlab_token)

        if gh_sha is None or gl_sha is None:
            msg = (
                f"Could not retrieve commits for comparison "
                f"(github={gh_sha!r}, gitlab={gl_sha!r})"
            )
            log.warning(msg)
            return False, msg

        if gh_sha == gl_sha:
            log.info(f"✓ In sync on branch '{default_branch}' (SHA {gh_sha[:8]})")
            return True, ""

        # Use GitHub compare API: base=gitlab_sha...head=github_branch
        # "behind_by" tells how many commits the BASE (gitlab) is behind the HEAD (github).
        # If behind_by >= 0 and ahead_by == 0 → github contains all gitlab commits.
        owner = self.github_org if self.github_org else self.get_github_user()
        compare_url = (
            f"{self.github_api_base}/repos/{owner}/{repo_name}/compare/{gl_sha}...{default_branch}"
        )
        log.debug(f"compare_repos → GET {compare_url}")
        response = requests.get(compare_url, headers=self.headers)
        log.debug(f"compare_repos ← {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            status = data.get("status")          # "ahead", "behind", "diverged", "identical"
            ahead_by = data.get("ahead_by", 0)   # commits github has that gitlab doesn't
            behind_by = data.get("behind_by", 0) # commits gitlab has that github doesn't

            if behind_by == 0:
                # GitHub contains all commits from GitLab (may be ahead)
                log.info(
                    f"✓ GitHub is ahead by {ahead_by} commit(s) on branch '{default_branch}' — "
                    f"GitLab origin is fully included"
                )
                return True, ""
            else:
                msg = (
                    f"Out of sync — GitHub is missing {behind_by} commit(s) from GitLab "
                    f"(GitHub HEAD={gh_sha[:8]}, GitLab HEAD={gl_sha[:8]}, "
                    f"compare status={status!r}, branch={default_branch})"
                )
                log.warning(f"✗ {msg}")
                return False, msg

        elif response.status_code == 404:
            # gl_sha not found in github at all — definitely out of sync
            msg = (
                f"Out of sync — GitLab HEAD {gl_sha[:8]} not found in GitHub history "
                f"(branch: {default_branch})"
            )
            log.warning(f"✗ {msg}")
            return False, msg
        else:
            # Fallback: can't determine, treat as unknown
            msg = (
                f"Could not compare repositories "
                f"(GitHub compare API returned {response.status_code})"
            )
            log.warning(msg)
            return False, msg

    @staticmethod
    @staticmethod
    def _blob_line_to_pattern(line: str, threshold_bytes: int) -> Optional[str]:
        """Parse one cat-file output line; return an LFS pattern string or None."""
        parts = line.split(" ", 3)
        if len(parts) < 3 or parts[1] != "blob":
            return None
        try:
            if int(parts[2]) <= threshold_bytes:
                return None
        except ValueError:
            return None
        path = parts[3].strip() if len(parts) > 3 else ""
        if not path:
            return None
        ext = os.path.splitext(path)[1].lower()
        return f"*{ext}" if ext else path

    @staticmethod
    def _find_large_blob_extensions(mirror_path: str, threshold_bytes: int, log: "RepoLogger") -> set:
        """
        Return a set of file patterns (e.g. ``*.zip``) for blobs exceeding *threshold_bytes*.
        Returns an empty set when nothing exceeds the threshold.
        """
        log.debug(f"$ git rev-list --objects --all  (cwd={mirror_path})")
        rev_list = subprocess.run(
            ["git", "rev-list", "--objects", "--all"],
            capture_output=True, text=True, cwd=mirror_path,
        )
        if rev_list.returncode != 0 or not rev_list.stdout.strip():
            return set()

        log.debug(f"$ git cat-file --batch-check  (cwd={mirror_path})")
        cat_file = subprocess.run(
            ["git", "cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize) %(rest)"],
            input=rev_list.stdout,
            capture_output=True, text=True, cwd=mirror_path,
        )

        patterns = (
            GitHubMigrator._blob_line_to_pattern(line, threshold_bytes)
            for line in cat_file.stdout.splitlines()
        )
        return {p for p in patterns if p is not None}

    @staticmethod
    def _migrate_large_blobs_to_lfs(
        mirror_path: str,
        log: "RepoLogger",
        size_threshold_mb: int = 100,
    ) -> bool:
        """
        Convert any blob larger than *size_threshold_mb* MB into a Git LFS object
        in-place, rewriting the mirror's history via ``git lfs migrate import``.

        This is needed when the source repo (GitLab) stored large files as plain
        Git blobs — GitHub rejects pushes containing files > 100 MB.

        Returns True if any blobs were migrated (history was rewritten), False otherwise.
        """
        threshold_bytes = size_threshold_mb * 1024 * 1024
        large_extensions = GitHubMigrator._find_large_blob_extensions(mirror_path, threshold_bytes, log)

        if not large_extensions:
            log.debug("No blobs above size threshold — skipping lfs migrate import")
            return False

        exts_str = ",".join(sorted(large_extensions))
        log.info(
            f"  Found blobs > {size_threshold_mb} MB — converting to LFS "
            f"(patterns: {exts_str})..."
        )

        migrate_cmd = [
            "git", "lfs", "migrate", "import",
            "--everything",
            f"--include={exts_str}",
        ]
        log.debug(f"$ {' '.join(migrate_cmd)}  (cwd={mirror_path})")
        result = subprocess.run(
            migrate_cmd,
            capture_output=True, text=True, cwd=mirror_path,
        )
        log.debug(f"lfs migrate stdout: {result.stdout.strip()}")
        log.debug(f"lfs migrate stderr: {result.stderr.strip()}")

        if result.returncode != 0:
            raise RuntimeError(
                f"git lfs migrate import failed: {result.stderr.strip()}"
            )

        log.info(f"  ✓ Large blobs converted to LFS ({exts_str})")
        return True

    @staticmethod
    def _repo_uses_lfs(mirror_path: str) -> bool:
        """
        Return True if the mirrored repo contains any Git LFS tracked files.
        Checks for pointer files in blobs and for .gitattributes with filter=lfs.
        """
        try:
            logger.debug(f"$ git lfs ls-files  (cwd={mirror_path})")
            result = subprocess.run(
                ["git", "lfs", "ls-files"],
                capture_output=True, text=True, cwd=mirror_path,
            )
            logger.debug(f"git lfs ls-files rc={result.returncode} stdout={result.stdout.strip()!r}")
            if result.returncode == 0 and result.stdout.strip():
                return True
        except FileNotFoundError:
            logger.debug("git lfs ls-files: git-lfs not found on PATH")

        # Fallback: grep .gitattributes for filter=lfs
        try:
            logger.debug(f"$ git show HEAD:.gitattributes  (cwd={mirror_path})")
            result = subprocess.run(
                ["git", "show", "HEAD:.gitattributes"],
                capture_output=True, text=True, cwd=mirror_path,
            )
            logger.debug(f"git show HEAD:.gitattributes rc={result.returncode}")
            if result.returncode == 0 and "filter=lfs" in result.stdout:
                return True
        except FileNotFoundError:
            logger.debug("git show: git not found on PATH")

        return False

    @staticmethod
    def _get_mirror_refs(mirror_path: str) -> List[str]:
        """Return all refs (branches + tags) in a bare/mirror repo, sorted by ref name."""
        result = subprocess.run(
            ["git", "for-each-ref", "--format=%(refname)", "--sort=version:refname"],
            capture_output=True, text=True, cwd=mirror_path, check=True,
        )
        return [r.strip() for r in result.stdout.splitlines() if r.strip()]

    @staticmethod
    def _get_branch_commits(mirror_path: str, ref: str) -> List[str]:
        """
        Return all commit SHAs on *ref* in chronological order (oldest first).
        """
        result = subprocess.run(
            ["git", "rev-list", "--reverse", ref],
            capture_output=True, text=True, cwd=mirror_path, check=True,
        )
        return [c.strip() for c in result.stdout.splitlines() if c.strip()]

    def _push_branch_in_slices(
        self,
        mirror_path: str,
        remote_url: str,
        ref: str,
        log: "RepoLogger",
        commits_per_slice: int = 500,
    ) -> None:
        """
        Push a single branch to GitHub in chronological commit slices.

        Each slice pushes only the commits up to a checkpoint SHA, keeping each
        individual push well below GitHub's 2 GB hard limit.

        After all slices are pushed, the real branch ref is updated to its final SHA.
        """
        short = ref.replace(_REFS_HEADS, "")
        commits = self._get_branch_commits(mirror_path, ref)
        total = len(commits)

        if total == 0:
            log.warning(f"  branch {short} has no commits — skipping")
            return

        log.info(f"  branch '{short}' has {total} commit(s) — pushing in slices of {commits_per_slice}...")

        # Determine checkpoint SHAs (every N commits, plus the final one)
        checkpoints: List[str] = []
        for i in range(commits_per_slice - 1, total - 1, commits_per_slice):
            checkpoints.append(commits[i])
        checkpoints.append(commits[-1])  # always include the final commit

        # Deduplicate while preserving order
        seen: set = set()
        unique_checkpoints: List[str] = []
        for sha in checkpoints:
            if sha not in seen:
                seen.add(sha)
                unique_checkpoints.append(sha)

        for idx, sha in enumerate(unique_checkpoints, start=1):
            is_last = (idx == len(unique_checkpoints))
            push_ref = f"{sha}:{_REFS_HEADS}{short}"
            label = f"slice {idx}/{len(unique_checkpoints)} ({sha[:8]})"
            if is_last:
                label += " [final]"
            log.info(f"    {label}")
            log.debug(f"$ git push --force {_redact_url(remote_url)} {sha[:8]}:{_REFS_HEADS}{short}  (cwd={mirror_path})")

            result = subprocess.run(
                ["git", "push", "--force", remote_url, push_ref],
                capture_output=True, text=True, cwd=mirror_path,
            )
            log.debug(f"    stdout: {result.stdout.strip()}")
            log.debug(f"    stderr: {result.stderr.strip()}")

            if result.returncode != 0:
                stderr = result.stderr.strip()
                raise RuntimeError(
                    f"git push failed for branch '{short}' at {label}: {stderr}"
                )

        log.info(f"  ✓ branch '{short}' pushed successfully")

    def _push_in_batches(
        self,
        mirror_path: str,
        remote_url: str,
        log: "RepoLogger",
        commits_per_slice: int = 500,
    ) -> None:
        """
        Push all refs to GitHub, splitting large branches into commit slices
        to stay under GitHub's 2 GB per-push hard limit.

        Order:
          1. Branches (refs/heads/*) — each pushed in chronological slices.
          2. Tags (refs/tags/*) — pushed together in one call.
          3. Other refs (notes, etc.) — best-effort, failures are silently skipped.
        """
        refs = self._get_mirror_refs(mirror_path)
        branches = [r for r in refs if r.startswith(_REFS_HEADS)]
        tags     = [r for r in refs if r.startswith("refs/tags/")]
        other    = [r for r in refs if not r.startswith(_REFS_HEADS) and not r.startswith("refs/tags/")]

        log.info(f"Pushing {len(branches)} branch(es), {len(tags)} tag(s) (slice mode, {commits_per_slice} commits/slice)...")

        # ── branches ────────────────────────────────────────────────────────
        for ref in branches:
            self._push_branch_in_slices(
                mirror_path=mirror_path,
                remote_url=remote_url,
                ref=ref,
                log=log,
                commits_per_slice=commits_per_slice,
            )

        # ── tags ────────────────────────────────────────────────────────────
        if tags:
            log.info(f"  pushing {len(tags)} tag(s)...")
            log.debug(f"$ git push --force {_redact_url(remote_url)} --tags  (cwd={mirror_path})")
            result = subprocess.run(
                ["git", "push", "--force", remote_url, "--tags"],
                capture_output=True, text=True, cwd=mirror_path,
            )
            log.debug(f"  stdout: {result.stdout.strip()}")
            log.debug(f"  stderr: {result.stderr.strip()}")
            if result.returncode != 0:
                raise RuntimeError(f"git push --tags failed: {result.stderr.strip()}")
            log.info("  ✓ tags pushed successfully")

        # ── other refs ───────────────────────────────────────────────────────
        for ref in other:
            log.debug(f"  pushing ref: {ref}")
            result = subprocess.run(
                ["git", "push", "--force", remote_url, ref],
                capture_output=True, text=True, cwd=mirror_path,
            )
            if result.returncode != 0:
                log.debug(f"  ⚠ skipping ref {ref}: {result.stderr.strip()}")

    def _build_authenticated_url(self, url: str, token: str, username: str = "oauth2") -> str:
        """
        Embed token credentials into an HTTPS git URL.

        Resulting format: https://<username>:<token>@<host>[:<port>]/<path>

        - GitLab personal access tokens  → username="oauth2"
        - GitHub personal access tokens  → username="x-access-token"
        """
        from urllib.parse import urlparse
        parsed = urlparse(url)
        host = parsed.hostname or ""
        port_part = f":{parsed.port}" if parsed.port else ""
        path = parsed.path  # already starts with /
        return f"{parsed.scheme}://{username}:{token}@{host}{port_part}{path}"

    def _maybe_archive(
        self,
        archive_synced: bool,
        gitlab_client: Optional["GitLabClient"],
        gitlab_project_id: Optional[int],
        log: "RepoLogger",
    ) -> None:
        """Archive the GitLab project if archive_synced is True and client/id are available."""
        if archive_synced and gitlab_client and gitlab_project_id:
            log.info(f"archiving GitLab project {gitlab_project_id}...")
            if gitlab_client.archive_project(gitlab_project_id):
                log.info("✓ GitLab project archived successfully")
            else:
                log.warning("⚠ Failed to archive GitLab project")

    def _check_sync_status(
        self,
        repo_name: str,
        existing_repo: Dict,
        source_url: str,
        gitlab_client: Optional["GitLabClient"],
        gitlab_project_id: Optional[int],
        gitlab_token: Optional[str],
        archive_synced: bool,
        log: "RepoLogger",
    ) -> Tuple[bool, Optional[Dict]]:
        """
        Check whether an already-existing GitHub repo is fully in sync with GitLab.

        Returns:
            (True, result_dict)  if fully synced (repo should NOT be re-migrated)
            (False, None)        if empty or behind (migration should proceed)
        """
        owner = self.github_org if self.github_org else self.get_github_user()

        if self.is_repo_empty(repo_name):
            log.info(
                f"Repository {owner}/{repo_name} exists but is empty — "
                f"proceeding with migration..."
            )
            return False, None

        default_branch = existing_repo.get("default_branch") or "main"
        log.info(
            f"Repository {owner}/{repo_name} already exists — "
            f"validating all branches..."
        )

        if gitlab_client and gitlab_project_id:
            gitlab_branches = gitlab_client.list_branches(gitlab_project_id)
        else:
            gitlab_branches = [default_branch]

        log.info(
            f"found {len(gitlab_branches)} GitLab branch(es): "
            f"{', '.join(gitlab_branches)}"
        )

        all_synced, _ = self.compare_all_branches(
            repo_name=repo_name,
            source_url=source_url,
            gitlab_branches=gitlab_branches,
            gitlab_token=gitlab_token,
            log=log,
        )

        if all_synced:
            log.info("✓ All branches are in sync with GitHub")
            self._maybe_archive(archive_synced, gitlab_client, gitlab_project_id, log)
            return True, {"status": "synced", "reason": ""}

        log.info(
            "GitHub is behind GitLab — resuming migration to sync missing commits..."
        )
        return False, None

    def _create_github_repo(
        self,
        repo_name: str,
        private: bool,
        description: Optional[str],
        log: "RepoLogger",
    ) -> Optional[Dict]:
        """
        Create an empty GitHub repository.

        Returns:
            None on success, or a ``{"status": "synced", ...}`` dict on a 422 race condition.
        Raises:
            requests.HTTPError on unexpected API errors.
        """
        owner = self.github_org if self.github_org else self.get_github_user()
        url = (
            f"{self.github_api_base}/orgs/{self.github_org}/repos"
            if self.github_org
            else f"{self.github_api_base}/user/repos"
        )
        repo_data: Dict = {"name": repo_name, "private": private, "auto_init": False}
        if description:
            repo_data["description"] = description

        log.info(f"Creating repository {owner}/{repo_name}...")
        create_response = requests.post(url, headers=self.headers, json=repo_data)

        if create_response.status_code == 201:
            log.info(f"Repository {owner}/{repo_name} created successfully")
            return None
        if create_response.status_code == 422:
            log.warning(f"Repository {owner}/{repo_name} already exists (race condition)")
            return {"status": "synced", "reason": "Repository appeared during migration"}
        create_response.raise_for_status()
        return None

    def _clone_mirror_and_push(
        self,
        source_url: str,
        clone_url: str,
        github_push_url: str,
        repo_name: str,
        mirror_path: str,
        enable_lfs: bool,
        commits_per_slice: int,
        log: "RepoLogger",
    ) -> None:
        """
        Clone the source repo as a mirror and push all refs to GitHub.

        Handles Git LFS fetching, large-blob conversion, and sliced pushes.
        Raises RuntimeError on git command failures.
        """
        owner = self.github_org if self.github_org else self.get_github_user()

        parsed = _urlparse(clone_url)
        if parsed.scheme not in ("https", "http") or not parsed.hostname:
            raise ValueError(f"Unsafe clone URL scheme: {parsed.scheme!r}")

        _cmd = ["git", "clone", "--mirror", clone_url, mirror_path]  # NOSONAR — URL validated above
        log.debug(f"$ git clone --mirror {_redact_url(clone_url)} {mirror_path}")
        log.info(f"Cloning {source_url} ...")
        try:
            clone_result = subprocess.run(
                _cmd,
                check=True,
                capture_output=True,
                text=True,
            )
            log.debug(f"git clone stdout: {clone_result.stdout.strip()}")
            log.debug(f"git clone stderr: {clone_result.stderr.strip()}")

            if enable_lfs and _lfs_available() and self._repo_uses_lfs(mirror_path):
                log.info("LFS objects detected — fetching all LFS objects from GitLab...")
                _cmd = ["git", "lfs", "fetch", "--all"]
                log.debug(f"$ git lfs fetch --all  (cwd={mirror_path})")
                lfs_fetch_result = subprocess.run(
                    _cmd,
                    check=True,
                    capture_output=True,
                    text=True,
                    cwd=mirror_path,
                    env={**os.environ, "GIT_LFS_SKIP_SMUDGE": "0"},
                )
                log.debug(f"git lfs fetch stdout: {lfs_fetch_result.stdout.strip()}")
                log.debug(f"git lfs fetch stderr: {lfs_fetch_result.stderr.strip()}")
            elif enable_lfs and not _lfs_available() and self._repo_uses_lfs(mirror_path):
                log.warning(
                    "LFS objects detected but git-lfs is NOT installed — "
                    "LFS pointers will be migrated but binary objects will be MISSING. "
                    "Install git-lfs and re-run to migrate LFS objects."
                )

            if enable_lfs and _lfs_available():
                self._migrate_large_blobs_to_lfs(mirror_path, log)

            log.info(f"Pushing to {owner}/{repo_name} ...")
            self._push_in_batches(
                mirror_path=mirror_path,
                remote_url=github_push_url,
                log=log,
                commits_per_slice=commits_per_slice,
            )

            if enable_lfs and _lfs_available() and self._repo_uses_lfs(mirror_path):
                log.info("Pushing LFS objects to GitHub...")
                _cmd = ["git", "lfs", "push", "--all", github_push_url]
                log.debug(f"$ git lfs push --all {_redact_url(github_push_url)}  (cwd={mirror_path})")
                lfs_push_result = subprocess.run(
                    _cmd,
                    check=True,
                    capture_output=True,
                    text=True,
                    cwd=mirror_path,
                )
                log.debug(f"git lfs push stdout: {lfs_push_result.stdout.strip()}")
                log.debug(f"git lfs push stderr: {lfs_push_result.stderr.strip()}")
                log.info("✓ LFS objects pushed successfully")

        except subprocess.CalledProcessError as e:
            stdout = (e.stdout or "").strip()
            stderr = (e.stderr or "").strip()
            log.debug(f"git command failed — stdout: {stdout}")
            log.debug(f"git command failed — stderr: {stderr}")
            raise RuntimeError(f"git operation failed: {stderr}") from e

    def start_import(
        self,
        source_url: str,
        repo_name: str,
        gitlab_token: Optional[str] = None,
        private: bool = True,
        description: Optional[str] = None,
        gitlab_client: Optional["GitLabClient"] = None,
        gitlab_project_id: Optional[int] = None,
        archive_synced: bool = False,
        log: Optional["RepoLogger"] = None,
        enable_lfs: bool = True,
        commits_per_slice: int = 500,
    ) -> Dict:
        """
        Migrate a repository from GitLab to GitHub via git clone --mirror + push.

        When the repo already exists on GitHub, all GitLab branches are compared:
          - Every branch must be present on GitHub.
          - GitHub must contain all commits from each GitLab branch (can be ahead).
        If fully in sync, returns "synced" (and archives if archive_synced=True).
        If GitHub is behind GitLab on any branch, migration proceeds automatically
        to push the missing commits (force-push with full history from GitLab).

        Returns:
            Status dict with "status" key. Possible statuses:
              "complete"  – migrated successfully (and archived if archive_synced)
              "synced"    – all branches already in sync (and archived if archive_synced)
        """
        log = log or RepoLogger(repo_name)
        owner = self.github_org if self.github_org else self.get_github_user()

        existing_repo = self.check_repo_exists(repo_name)
        if existing_repo:
            should_skip, result = self._check_sync_status(
                repo_name=repo_name,
                existing_repo=existing_repo,
                source_url=source_url,
                gitlab_client=gitlab_client,
                gitlab_project_id=gitlab_project_id,
                gitlab_token=gitlab_token,
                archive_synced=archive_synced,
                log=log,
            )
            if should_skip:
                return result

        if not existing_repo:
            race_result = self._create_github_repo(repo_name, private, description, log)
            if race_result is not None:
                return race_result

        clone_url = (
            self._build_authenticated_url(source_url, gitlab_token, username="oauth2")
            if gitlab_token
            else source_url
        )
        github_push_url = self._build_authenticated_url(
            f"https://github.com/{owner}/{repo_name}.git",
            self.github_token,
            username="x-access-token",
        )

        tmpdir = tempfile.mkdtemp(prefix="gitlab_migrate_")
        mirror_path = os.path.join(tmpdir, repo_name + ".git")
        log.debug(f"tmpdir={tmpdir}")
        try:
            self._clone_mirror_and_push(
                source_url=source_url,
                clone_url=clone_url,
                github_push_url=github_push_url,
                repo_name=repo_name,
                mirror_path=mirror_path,
                enable_lfs=enable_lfs,
                commits_per_slice=commits_per_slice,
                log=log,
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

        log.info("✓ Migration complete")
        self._maybe_archive(archive_synced, gitlab_client, gitlab_project_id, log)
        return {"status": "complete"}

    def migrate_repository(
        self,
        source_url: str,
        repo_name: str,
        gitlab_token: Optional[str] = None,
        private: bool = True,
        description: Optional[str] = None,
        gitlab_client: Optional["GitLabClient"] = None,
        gitlab_project_id: Optional[int] = None,
        archive_synced: bool = False,
        enable_lfs: bool = True,
        commits_per_slice: int = 500,
    ) -> Tuple[bool, str]:
        """
        Migrate a single repository from GitLab to GitHub.

        Returns:
            Tuple of (success, error_reason). error_reason is empty on success/synced.
            If GitHub is behind GitLab, the missing commits are pushed automatically.
        """
        log = RepoLogger(repo_name)
        try:
            log.debug(f"migrate_repository called: source_url={source_url} private={private} archive_synced={archive_synced}")
            result = self.start_import(
                source_url=source_url,
                repo_name=repo_name,
                gitlab_token=gitlab_token,
                private=private,
                description=description,
                gitlab_client=gitlab_client,
                gitlab_project_id=gitlab_project_id,
                archive_synced=archive_synced,
                log=log,
                enable_lfs=enable_lfs,
                commits_per_slice=commits_per_slice,
            )

            status = result.get("status")
            log.debug(f"start_import result: {result}")

            if status in ("complete", "synced"):
                return True, ""

            return True, ""

        except Exception as e:
            reason = str(e)
            log.error(f"Failed to migrate: {reason}")
            return False, reason

    def migrate_repositories(
        self,
        repositories: List[Dict],
        gitlab_token: Optional[str] = None,
        gitlab_client: Optional["GitLabClient"] = None,
        archive_synced: bool = False,
        errors_reporter: Optional["ErrorsReporter"] = None,
        workers: int = 1,
        enable_lfs: bool = True,
        commits_per_slice: int = 500,
    ) -> Dict[str, Dict]:
        """
        Migrate multiple repositories from GitLab to GitHub.

        If *errors_reporter* is provided, each failure is written to the CSV
        immediately after it occurs (real-time), not just at the end.

        Args:
            workers: Number of parallel migration threads (default: 1 = sequential).

        Returns:
            Dict mapping repo_name -> {"success": bool, "reason": str, "source_url": str}
        """
        results: Dict[str, Dict] = {}
        results_lock = threading.Lock()

        def _migrate_one(repo_config: Dict) -> None:
            source_url = repo_config["source_url"]
            repo_name = repo_config["repo_name"]
            private = repo_config.get("private", True)
            description = repo_config.get("description")
            gitlab_project_id = repo_config.get("gitlab_project_id")

            log = RepoLogger(repo_name)
            log.info(f"Starting migration from {source_url}")

            success, reason = self.migrate_repository(
                source_url=source_url,
                repo_name=repo_name,
                gitlab_token=gitlab_token,
                private=private,
                description=description,
                gitlab_client=gitlab_client,
                gitlab_project_id=gitlab_project_id,
                archive_synced=archive_synced,
                enable_lfs=enable_lfs,
                commits_per_slice=commits_per_slice,
            )

            with results_lock:
                results[repo_name] = {
                    "success": success,
                    "reason": reason,
                    "source_url": source_url,
                }

            if not success and errors_reporter is not None:
                errors_reporter.write(
                    repo_name=repo_name,
                    source_url=source_url,
                    reason=reason,
                )

        def _handle_future_error(repo_name: str, exc: Exception) -> None:
            logger.error(f"Unexpected error migrating {repo_name}: {exc}")
            source_url = next(r["source_url"] for r in repositories if r["repo_name"] == repo_name)
            with results_lock:
                results[repo_name] = {"success": False, "reason": str(exc), "source_url": source_url}
            if errors_reporter is not None:
                errors_reporter.write(repo_name=repo_name, source_url=source_url, reason=str(exc))

        if workers > 1:
            logger.info(f"Running migrations in parallel with {workers} workers...")
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {executor.submit(_migrate_one, repo): repo["repo_name"] for repo in repositories}
                for future in as_completed(futures):
                    repo_name = futures[future]
                    try:
                        future.result()
                    except Exception as exc:
                        _handle_future_error(repo_name, exc)
        else:
            for repo_config in repositories:
                _migrate_one(repo_config)
                time.sleep(2)

        return results
