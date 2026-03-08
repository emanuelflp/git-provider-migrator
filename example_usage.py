#!/usr/bin/env python3
"""
Example script showing how to use the GitHubMigrator class programmatically
"""

import os
from migrator.clients.github import GitHubMigrator

# Example 1: Migrate a single repository
def example_single_repo():
    """Example of migrating a single repository"""

    # Get tokens from environment
    github_token = os.environ.get("GITHUB_TOKEN")
    gitlab_token = os.environ.get("GITLAB_TOKEN")

    if not github_token:
        print("Please set GITHUB_TOKEN environment variable")
        return

    # Initialize migrator
    migrator = GitHubMigrator(github_token=github_token)

    # Migrate a repository
    success, reason = migrator.migrate_repository(
        source_url="https://gitlab.com/username/my-project.git",
        repo_name="my-project",
        gitlab_token=gitlab_token,
        private=True,
        description="My project migrated from GitLab",
        wait=True
    )

    if success:
        print("✓ Migration completed successfully!")
    else:
        print(f"✗ Migration failed: {reason}")


# Example 2: Migrate multiple repositories
def example_batch_migration():
    """Example of migrating multiple repositories"""

    github_token = os.environ.get("GITHUB_TOKEN")
    gitlab_token = os.environ.get("GITLAB_TOKEN")

    if not github_token:
        print("Please set GITHUB_TOKEN environment variable")
        return

    # Initialize migrator
    migrator = GitHubMigrator(github_token=github_token)

    # Define repositories to migrate
    repositories = [
        {
            "source_url": "https://gitlab.com/username/frontend.git",
            "repo_name": "frontend",
            "private": True,
            "description": "Frontend application"
        },
        {
            "source_url": "https://gitlab.com/username/backend.git",
            "repo_name": "backend",
            "private": True,
            "description": "Backend API"
        },
        {
            "source_url": "https://gitlab.com/username/mobile.git",
            "repo_name": "mobile",
            "private": True,
            "description": "Mobile app"
        }
    ]

    # Migrate all repositories
    results = migrator.migrate_repositories(
        repositories=repositories,
        gitlab_token=gitlab_token,
        wait=True
    )

    # Print results
    print("\n" + "="*60)
    print("Migration Results:")
    print("="*60)

    for repo_name, info in results.items():
        status = "✓ SUCCESS" if info["success"] else "✗ FAILED"
        line = f"{status}: {repo_name}"
        if not info["success"] and info.get("reason"):
            line += f"  — {info['reason']}"
        print(line)

    successful = sum(1 for info in results.values() if info["success"])
    print(f"\nTotal: {successful}/{len(results)} successful")


# Example 3: Migrate to an organization
def example_org_migration():
    """Example of migrating to a GitHub organization"""

    github_token = os.environ.get("GITHUB_TOKEN")
    gitlab_token = os.environ.get("GITLAB_TOKEN")

    if not github_token:
        print("Please set GITHUB_TOKEN environment variable")
        return

    # Initialize migrator with organization
    migrator = GitHubMigrator(
        github_token=github_token,
        github_org="my-organization"
    )

    # Migrate repository to organization
    success, reason = migrator.migrate_repository(
        source_url="https://gitlab.com/old-org/project.git",
        repo_name="project",
        gitlab_token=gitlab_token,
        private=True,
        description="Project migrated from GitLab",
        wait=True
    )

    if success:
        print("✓ Migration to organization completed successfully!")
    else:
        print(f"✗ Migration failed: {reason}")


# Example 4: Check if repository exists before migration
def example_check_existence():
    """Example of checking if a repository exists"""

    github_token = os.environ.get("GITHUB_TOKEN")

    if not github_token:
        print("Please set GITHUB_TOKEN environment variable")
        return

    migrator = GitHubMigrator(github_token=github_token)

    repo_name = "my-project"

    if migrator.check_repo_exists(repo_name):
        print(f"✓ Repository '{repo_name}' already exists on GitHub")
    else:
        print(f"✗ Repository '{repo_name}' does not exist on GitHub")


if __name__ == "__main__":
    print("Git Provider Migrator - Usage Examples")
    print("="*60)
    print("\nChoose an example to run:")
    print("1. Migrate a single repository")
    print("2. Batch migrate multiple repositories")
    print("3. Migrate to an organization")
    print("4. Check if repository exists")
    print("\nUncomment the example you want to run in this file.")
    print("="*60)

    # Uncomment one of these to run:
    # example_single_repo()
    # example_batch_migration()
    # example_org_migration()
    # example_check_existence()
