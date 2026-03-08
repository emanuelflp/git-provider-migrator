# Git Provider Migrator

A CLI tool and Python library to migrate Git repositories between providers — preserving full commit history, branches, tags, and Git LFS objects.

> **Current support:** any Git host as **source** · GitHub as **destination**

## Features

- **Full history migration** via `git clone --mirror` + `git push`
- **Batch migration** from a JSON file or directly from the GitLab API
- **Incremental sync** — if the destination is behind the source, missing commits are pushed automatically
- **Git LFS support** — fetches and pushes LFS objects; auto-converts plain blobs > 100 MB to LFS
- **Large repo support** — push in configurable commit slices to stay under GitHub's 2 GB per-push limit
- **Parallel workers** — migrate multiple repositories concurrently
- **Organization support** — migrate to a personal account or a GitHub organization
- **Real-time error reporting** — failures written to a CSV file as they occur

## Compatibility Matrix

### As source (origin)

| Provider | Clone & push history | Token auth | LFS fetch | Batch via API | Branch listing via API | Archive after sync |
|---|---|---|---|---|---|---|
| **GitLab** | ✅ Full | ✅ `--gitlab-token` | ✅ | ✅ `--from-gitlab` | ✅ | ✅ `--archive-synced` |
| **GitHub** | ✅ Full | ✅ `--gitlab-token` | ✅ | ❌ | ❌ | ❌ |
| **Bitbucket** | ✅ Full | ⚠️ Embed in URL¹ | ✅ | ❌ | ❌ | ❌ |

¹ Bitbucket does not support token-as-password in the same way; credentials must be embedded directly in the HTTPS URL (`https://user:app_password@bitbucket.org/...`).

### As destination

| Provider | Repo creation | Push history | LFS push | Org support | Sync check |
|---|---|---|---|---|---|
| **GitHub** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **GitLab** | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Bitbucket** | ❌ | ❌ | ❌ | ❌ | ❌ |

### Legend

| Symbol | Meaning |
|---|---|
| ✅ | Fully supported |
| ⚠️ | Partially supported — works but requires manual steps or workarounds |
| ❌ | Not supported |

---

## Requirements

- Python 3.8+
- `git` on PATH
- `git-lfs` on PATH *(optional — required only for LFS object transfer)*

## Installation

```bash
pip install git-provider-migrator
```

Or install from source:

```bash
git clone https://github.com/emanuelflp/git-provider-migrator.git
cd git-provider-migrator
pip install -e .
```

---

## Authentication

### Source providers

The source can be any Git host that provides an HTTPS clone URL. For private repositories, an access token must be passed via `--source-token` (or `GITLAB_TOKEN` env var for GitLab).

#### GitLab

Create a [Personal Access Token](https://gitlab.com/-/profile/personal_access_tokens) with the `read_repository` scope.

```bash
export GITLAB_TOKEN="glpat-..."
```

For self-hosted instances, pass the base URL:

```bash
git-provider-migrator --gitlab-base-url https://gitlab.mycompany.com ...
```

#### GitHub (as source)

Create a [Personal Access Token](https://github.com/settings/tokens) with the `repo` scope (classic) or `Contents: read` (fine-grained).

```bash
# pass directly as the source token
git-provider-migrator --gitlab-token "ghp_..." --source-url https://github.com/org/repo.git ...
```

#### Bitbucket

Create an [App Password](https://bitbucket.org/account/settings/app-passwords/) with `Repositories: Read` permission. Embed it in the clone URL:

```bash
# https://username:app_password@bitbucket.org/workspace/repo.git
git-provider-migrator --source-url "https://user:apppassword@bitbucket.org/workspace/repo.git" ...
```

#### Azure DevOps

Create a [Personal Access Token](https://dev.azure.com) with `Code: Read` scope. Embed it in the clone URL:

```bash
# https://user:token@dev.azure.com/org/project/_git/repo
git-provider-migrator --source-url "https://user:token@dev.azure.com/org/project/_git/repo" ...
```

#### Gitea / Forgejo

Create an API token in **Settings → Applications → Access Tokens** with `repository: read` permission:

```bash
git-provider-migrator --gitlab-token "your-gitea-token" \
               --source-url   "https://gitea.mycompany.com/user/repo.git" ...
```

#### Any other provider

Any HTTPS git URL with embedded credentials works:

```bash
git-provider-migrator --source-url "https://user:token@git.mycompany.com/repo.git" ...
```

---

### Destination: GitHub

Create a [Personal Access Token](https://github.com/settings/tokens) with the following permissions:

| Token type | Required permissions |
|---|---|
| Classic | `repo` (full control) |
| Fine-grained | `Contents` (read/write) · `Metadata` (read) · `Administration` (read/write) |

```bash
export GITHUB_TOKEN="ghp_..."
```

Tokens are resolved in this order of priority:

1. CLI flags (`--github-token`, `--gitlab-token`)
2. `tokens.csv` file in the project directory
3. Environment variables (`GITHUB_TOKEN`, `GITLAB_TOKEN`)

---

## Usage

### Migrate a single repository

```bash
# From GitLab
git-provider-migrator \
  --source-url  https://gitlab.com/your-org/your-repo.git \
  --repo-name   your-repo \
  --private

# From GitHub
git-provider-migrator \
  --source-url   https://github.com/source-org/your-repo.git \
  --gitlab-token ghp_sourcetoken... \
  --repo-name    your-repo \
  --private

# From Bitbucket
git-provider-migrator \
  --source-url  "https://user:apppassword@bitbucket.org/workspace/your-repo.git" \
  --repo-name   your-repo \
  --private

# From Azure DevOps
git-provider-migrator \
  --source-url  "https://user:token@dev.azure.com/org/project/_git/your-repo" \
  --repo-name   your-repo \
  --private

# From a self-hosted Gitea instance
git-provider-migrator \
  --source-url   https://gitea.mycompany.com/user/your-repo.git \
  --gitlab-token your-gitea-token \
  --repo-name    your-repo \
  --private
```

### Migrate to a GitHub organization

```bash
git-provider-migrator \
  --github-org  your-github-org \
  --source-url  https://gitlab.com/old-org/project.git \
  --repo-name   project
```

### Batch migration from a JSON file

```json
[
  {
    "source_url":  "https://gitlab.com/your-org/frontend.git",
    "repo_name":   "frontend",
    "private":     true,
    "description": "Frontend application"
  },
  {
    "source_url":  "https://github.com/source-org/backend.git",
    "repo_name":   "backend",
    "private":     true
  },
  {
    "source_url":  "https://user:pass@bitbucket.org/workspace/mobile.git",
    "repo_name":   "mobile",
    "private":     true
  }
]
```

```bash
git-provider-migrator --batch-file repositories.json
```

### Batch migration from GitLab API

Automatically fetches the repository list via the GitLab API — no need to maintain a JSON file.

```bash
# All repos from a GitLab group
git-provider-migrator --from-gitlab --gitlab-namespace your-group

# All repos from a GitLab user
git-provider-migrator --from-gitlab --gitlab-namespace username

# All repos owned by the authenticated GitLab user
git-provider-migrator --from-gitlab

# From a self-hosted GitLab instance
git-provider-migrator --from-gitlab \
               --gitlab-base-url https://gitlab.mycompany.com \
               --gitlab-namespace your-group
```

---

## CLI Reference

| Flag | Default | Description |
|---|---|---|
| `--source-provider` | `gitlab` | Source Git provider (`gitlab`, `github`, `bitbucket`) |
| `--dest-provider` | `github` | Destination Git provider (`github`) |
| `--github-token` | `$GITHUB_TOKEN` | GitHub personal access token (destination) |
| `--gitlab-token` | `$GITLAB_TOKEN` | Source provider personal access token |
| `--github-org` | *(user account)* | Migrate into a GitHub organization |
| `--source-url` | — | Source repository HTTPS URL |
| `--repo-name` | — | Target repository name on GitHub |
| `--private` / `--public` | `--private` | Repository visibility |
| `--batch-file` | — | JSON file with list of repositories |
| `--from-gitlab` | — | Fetch repository list from GitLab API (requires `--source-provider gitlab`) |
| `--gitlab-namespace` | *(authenticated user)* | GitLab group or username (only with `--source-provider gitlab`) |
| `--gitlab-base-url` | `https://gitlab.com` | GitLab instance base URL (only with `--source-provider gitlab`) |
| `--workers` | `1` | Number of parallel migration threads |
| `--commits-per-slice` | `500` | Commits per push slice (reduce for very large repos) |
| `--archive-synced` | `false` | Archive the source project after successful sync (only with `--source-provider gitlab`) |
| `--skip-lfs` | `false` | Skip Git LFS object transfer |
| `--errors-output` | `migration_errors_<ts>.csv` | Path for the error report CSV |
| `--tokens-csv` | `tokens.csv` | Path to CSV file containing tokens |
| `--debug` | `false` | Enable verbose debug logging |

---

## Python API

```python
from migrator.clients.github import GitHubMigrator

migrator = GitHubMigrator(github_token="ghp_...", github_org="my-org")

# Single repository (any source)
success, reason = migrator.migrate_repository(
    source_url="https://gitlab.com/your-org/your-repo.git",  # any git URL
    repo_name="your-repo",
    gitlab_token="glpat-...",   # source token, if needed
    private=True,
)

# Multiple repositories (mixed sources)
results = migrator.migrate_repositories(
    repositories=[
        {"source_url": "https://gitlab.com/org/repo1.git",           "repo_name": "repo1", "private": True},
        {"source_url": "https://github.com/source-org/repo2.git",    "repo_name": "repo2", "private": True},
        {"source_url": "https://user:pass@bitbucket.org/ws/repo3.git","repo_name": "repo3", "private": True},
    ],
    gitlab_token="glpat-...",
    workers=4,
)

for repo, info in results.items():
    print(repo, "✓" if info["success"] else f"✗ {info['reason']}")
```

---

## How It Works

1. **Compare** — if the repository already exists on GitHub, all branches are compared against the source. If GitHub is up to date, the migration is skipped.
2. **Clone** — the source is cloned with `git clone --mirror` into a temporary directory.
3. **LFS** — existing LFS objects are fetched from the source; plain blobs larger than 100 MB are automatically converted to LFS via `git lfs migrate import`.
4. **Push** — all branches are pushed in chronological commit slices (configurable via `--commits-per-slice`) to stay within GitHub's 2 GB per-push limit.
5. **LFS push** — LFS objects are pushed to GitHub with `git lfs push --all`.
6. **Cleanup** — the temporary clone is removed.

---

## Contributing

Contributions are welcome. Please open an issue to discuss significant changes before submitting a pull request.

```bash
git clone https://github.com/emanuelflp/git-provider-migrator.git
cd git-provider-migrator
pip install -e .
```

## License

MIT — see [LICENSE](LICENSE).
