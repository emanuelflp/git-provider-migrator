import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict

import requests
from gitlab.exceptions import GitlabError

from migrator.clients.github import GitHubMigrator
from migrator.clients.gitlab import GitLabClient
from migrator.formatting.colors import _AnsiCodes, _setup_logging
from migrator.reporting.errors import ErrorsReporter, write_errors_report
from migrator.utils.lfs import _lfs_available
from migrator.utils.tokens import load_tokens_from_csv

logger = logging.getLogger("migrator")

# Providers currently supported as source or destination
_SOURCE_PROVIDERS = ["gitlab", "github", "bitbucket"]
_DEST_PROVIDERS   = ["github"]


def main():
    """Main entry point for the migration script"""
    parser = argparse.ArgumentParser(
        description="Migrate Git repositories between providers"
    )

    # ── Provider selection ───────────────────────────────────────────────
    parser.add_argument(
        "--source-provider",
        choices=_SOURCE_PROVIDERS,
        default="gitlab",
        metavar="PROVIDER",
        help=(
            f"Source Git provider. Choices: {', '.join(_SOURCE_PROVIDERS)} "
            "(default: gitlab). Affects API integrations and authentication hints."
        )
    )
    parser.add_argument(
        "--dest-provider",
        choices=_DEST_PROVIDERS,
        default="github",
        metavar="PROVIDER",
        help=(
            f"Destination Git provider. Choices: {', '.join(_DEST_PROVIDERS)} "
            "(default: github)."
        )
    )

    # ── Authentication ───────────────────────────────────────────────────
    parser.add_argument(
        "--github-token",
        required=False,
        help="GitHub Personal Access Token (or set GITHUB_TOKEN env var)"
    )
    parser.add_argument(
        "--gitlab-token",
        required=False,
        help="Source provider personal access token (or set GITLAB_TOKEN env var)"
    )
    parser.add_argument(
        "--tokens-csv",
        help="Path to CSV file with github_token and gitlab_token (default: tokens.csv)"
    )

    # ── Single-repo migration ────────────────────────────────────────────
    parser.add_argument(
        "--source-url",
        help="Source repository HTTPS URL (e.g., https://gitlab.com/org/repo.git)"
    )
    parser.add_argument(
        "--repo-name",
        help="Target repository name on the destination provider"
    )
    parser.add_argument(
        "--private",
        action="store_true",
        default=True,
        help="Make the destination repository private (default: True)"
    )
    parser.add_argument(
        "--public",
        action="store_true",
        help="Make the destination repository public"
    )
    parser.add_argument(
        "--description",
        help="Description for the new repository"
    )

    # ── Batch migration ──────────────────────────────────────────────────
    parser.add_argument(
        "--batch-file",
        help="Path to a JSON file containing multiple repositories to migrate"
    )
    parser.add_argument(
        "--from-gitlab",
        action="store_true",
        help=(
            "Fetch the repository list directly from the GitLab API "
            "(requires --source-provider gitlab)"
        )
    )
    parser.add_argument(
        "--gitlab-namespace",
        help=(
            "GitLab group path (e.g. 'mygroup/subgroup') or username to migrate. "
            "If omitted, migrates all repos of the authenticated user. "
            "Only used with --source-provider gitlab."
        )
    )
    parser.add_argument(
        "--gitlab-base-url",
        default="https://gitlab.com",
        help=(
            "Base URL of the GitLab instance (default: https://gitlab.com). "
            "Only used with --source-provider gitlab."
        )
    )

    # ── Destination options ──────────────────────────────────────────────
    parser.add_argument(
        "--github-org",
        help="GitHub organization name (optional, uses authenticated user if not provided)"
    )

    # ── Behaviour ────────────────────────────────────────────────────────
    parser.add_argument(
        "--archive-synced",
        action="store_true",
        help=(
            "Archive the source project after confirming all branches are fully "
            "synced on the destination. Currently supported only for GitLab sources."
        )
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        metavar="N",
        help="Number of parallel migration threads (default: 1 = sequential)."
    )
    parser.add_argument(
        "--commits-per-slice",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Split branch history into slices of N commits per push. "
            "Disabled by default — the full mirror is pushed in a single call. "
            "Enable this (e.g. --commits-per-slice 200) only if the push fails "
            "due to GitHub's 2 GB per-push limit. "
            "A warning is emitted automatically when the mirror exceeds 2 GB."
        )
    )
    parser.add_argument(
        "--skip-lfs",
        action="store_true",
        help=(
            "Disable Git LFS support. LFS pointer files will be migrated "
            "but binary LFS objects will NOT be transferred."
        )
    )
    parser.add_argument(
        "--errors-output",
        help="Path to the CSV file where failed migrations will be recorded."
    )
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="Ignored (clone+push is always synchronous); kept for backward compatibility"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable DEBUG level logging."
    )

    args = parser.parse_args()

    _setup_logging(debug=args.debug)
    if args.debug:
        logger.debug("DEBUG logging enabled")

    # ── LFS check ───────────────────────────────────────────────────────
    if not args.skip_lfs:
        if _lfs_available():
            logger.info("git-lfs detected — LFS support enabled")
        else:
            logger.warning(
                "git-lfs not found on PATH — LFS binary objects will NOT be migrated. "
                "Install git-lfs (https://git-lfs.com) or pass --skip-lfs to suppress this warning."
            )

    # ── Token resolution ─────────────────────────────────────────────────
    default_csv_path = Path.cwd() / "tokens.csv"
    tokens_csv_path = Path(args.tokens_csv) if args.tokens_csv else default_csv_path

    _validate_providers(args)
    github_token, gitlab_token = _resolve_tokens(args, tokens_csv_path)

    # ── Shared setup ─────────────────────────────────────────────────────
    migrator = GitHubMigrator(github_token=github_token, github_org=args.github_org)
    is_private = not args.public if args.public else args.private
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    default_errors_path = Path(__file__).resolve().parent.parent / f"migration_errors_{timestamp}.csv"
    errors_output = Path(args.errors_output) if args.errors_output else default_errors_path

    if args.from_gitlab:
        _run_from_gitlab_mode(args, migrator, is_private, errors_output, gitlab_token)
    elif args.batch_file:
        _run_batch_mode(args, migrator, errors_output, gitlab_token)
    else:
        _run_single_repo_mode(args, migrator, is_private, errors_output, gitlab_token)


def _validate_providers(args) -> None:
    """Validate provider-related arguments and log the chosen provider pair."""
    if args.dest_provider != "github":
        logger.error(
            f"Destination provider '{args.dest_provider}' is not yet supported. "
            f"Supported destinations: {', '.join(_DEST_PROVIDERS)}"
        )
        sys.exit(1)

    if args.from_gitlab and args.source_provider != "gitlab":
        logger.error(
            "--from-gitlab requires --source-provider gitlab "
            f"(got '{args.source_provider}')"
        )
        sys.exit(1)

    if args.archive_synced and args.source_provider != "gitlab":
        logger.warning(
            f"--archive-synced is only supported for GitLab sources "
            f"(source provider is '{args.source_provider}') — flag will be ignored."
        )
        args.archive_synced = False

    if args.gitlab_namespace and args.source_provider != "gitlab":
        logger.warning(
            f"--gitlab-namespace is only used with --source-provider gitlab "
            f"(got '{args.source_provider}') — flag will be ignored."
        )

    logger.info(f"Provider: {args.source_provider} → {args.dest_provider}")


def _resolve_tokens(args, tokens_csv_path) -> tuple:
    """Resolve GitHub and GitLab tokens from CLI args, CSV file, or environment variables."""
    csv_tokens = load_tokens_from_csv(tokens_csv_path)

    github_token = (
        args.github_token
        or csv_tokens.get("github_token")
        or os.environ.get("GITHUB_TOKEN")
    )
    gitlab_token = (
        args.gitlab_token
        or csv_tokens.get("gitlab_token")
        or os.environ.get("GITLAB_TOKEN")
    )

    if not github_token:
        logger.error(
            "GitHub token not found. Provide --github-token, set GITHUB_TOKEN, "
            "or add github_token to %s",
            tokens_csv_path
        )
        sys.exit(1)

    return (github_token, gitlab_token)


def _run_from_gitlab_mode(args, migrator, is_private, errors_output, gitlab_token) -> None:
    """Mode 1: fetch repository list from the GitLab API and migrate all repos."""
    if not gitlab_token:
        logger.error(
            "A source token is required when using --from-gitlab. "
            "Provide --gitlab-token, set GITLAB_TOKEN, or add gitlab_token to %s",
            args.gitlab_base_url
        )
        sys.exit(1)

    gl_client = GitLabClient(gitlab_token=gitlab_token, base_url=args.gitlab_base_url)

    logger.info(f"Fetching repositories from GitLab ({args.gitlab_base_url})...")

    if args.gitlab_namespace:
        try:
            projects = gl_client.list_group_repos(args.gitlab_namespace)
            logger.info(f"Found {len(projects)} repos in group '{args.gitlab_namespace}'")
        except GitlabError as e:
            if getattr(e, 'response_code', None) in (404, 403):
                logger.info(f"Not a group, trying as user '{args.gitlab_namespace}'...")
                projects = gl_client.list_user_repos(args.gitlab_namespace)
                logger.info(f"Found {len(projects)} repos for user '{args.gitlab_namespace}'")
            else:
                raise
    else:
        projects = gl_client.list_user_repos()
        logger.info(f"Found {len(projects)} repos for the authenticated GitLab user")

    if not projects:
        logger.warning("No repositories found. Nothing to migrate.")
        sys.exit(0)

    repositories = gl_client.repos_to_migration_list(projects, private=is_private)

    with ErrorsReporter(errors_output) as reporter:
        results = migrator.migrate_repositories(
            repositories=repositories,
            gitlab_token=gitlab_token,
            gitlab_client=gl_client,
            archive_synced=args.archive_synced,
            errors_reporter=reporter,
            workers=args.workers,
            enable_lfs=not args.skip_lfs,
            commits_per_slice=args.commits_per_slice,
        )

    _print_summary(results)
    successful = sum(1 for info in results.values() if info["success"])
    sys.exit(0 if successful == len(results) else 1)


def _run_batch_mode(args, migrator, errors_output, gitlab_token) -> None:
    """Mode 2: load repository list from a JSON batch file and migrate all repos."""
    logger.info(f"Loading repositories from {args.batch_file}")
    with open(args.batch_file, 'r') as f:
        repositories = json.load(f)

    with ErrorsReporter(errors_output) as reporter:
        results = migrator.migrate_repositories(
            repositories=repositories,
            gitlab_token=gitlab_token,
            archive_synced=args.archive_synced,
            errors_reporter=reporter,
            workers=args.workers,
            enable_lfs=not args.skip_lfs,
            commits_per_slice=args.commits_per_slice,
        )

    _print_summary(results)
    successful = sum(1 for info in results.values() if info["success"])
    sys.exit(0 if successful == len(results) else 1)


def _run_single_repo_mode(args, migrator, is_private, errors_output, gitlab_token) -> None:
    """Mode 3: migrate a single repository specified via --source-url and --repo-name."""
    if not args.source_url or not args.repo_name:
        logger.error("For single repository migration, both --source-url and --repo-name are required")
        logger.info("Or use --batch-file / --from-gitlab for migrating multiple repositories")
        sys.exit(1)

    success, reason = migrator.migrate_repository(
        source_url=args.source_url,
        repo_name=args.repo_name,
        gitlab_token=gitlab_token,
        private=is_private,
        description=args.description,
        archive_synced=args.archive_synced,
        enable_lfs=not args.skip_lfs,
        commits_per_slice=args.commits_per_slice,
    )

    if not success:
        write_errors_report(
            {args.repo_name: {"success": False, "reason": reason, "source_url": args.source_url}},
            errors_output
        )

    sys.exit(0 if success else 1)


def _print_summary(results: Dict[str, Dict]) -> None:
    """Print the final migration summary to the log."""
    use_color = sys.stdout.isatty()

    def _c(code: str, text: str) -> str:
        return f"{code}{text}{_AnsiCodes.RESET}" if use_color else text

    logger.info("=" * 60)
    logger.info("Migration Summary:")
    logger.info("=" * 60)

    successful = sum(1 for info in results.values() if info["success"])
    total = len(results)

    for repo_name, info in results.items():
        if info["success"]:
            logger.info(_c(_AnsiCodes.GREEN, f"✓ SUCCESS:      {repo_name}"))
        else:
            reason = info.get("reason", "")
            if "out of sync" in reason.lower():
                logger.warning(_c(_AnsiCodes.YELLOW, f"⚠ OUT OF SYNC:  {repo_name}  —  {reason}"))
            else:
                logger.error(_c(_AnsiCodes.RED, f"✗ FAILED:       {repo_name}  —  {reason}"))

    summary_color = _AnsiCodes.GREEN if successful == total else _AnsiCodes.YELLOW
    logger.info(_c(summary_color + _AnsiCodes.BOLD, f"Total: {successful}/{total} successful"))


def _print_summary_and_errors(results: Dict[str, Dict], errors_output: Path) -> None:
    """Legacy helper: print summary and write the error CSV at end-of-run."""
    _print_summary(results)
    write_errors_report(results, errors_output)
