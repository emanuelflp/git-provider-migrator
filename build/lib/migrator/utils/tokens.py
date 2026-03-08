import csv
from pathlib import Path
from typing import Dict


def _load_key_value_format(reader: csv.DictReader) -> Dict[str, str]:
    """Handle CSV with `key,value` column layout."""
    tokens: Dict[str, str] = {}
    for row in reader:
        key = (row.get("key") or row.get("KEY") or "").strip().lower()
        value = (row.get("value") or row.get("VALUE") or "").strip()
        if key in {"github_token", "gitlab_token"} and value:
            tokens[key] = value
    return tokens


def _load_header_format(reader: csv.DictReader) -> Dict[str, str]:
    """Handle CSV with `github_token,gitlab_token` header layout (single data row)."""
    tokens: Dict[str, str] = {}
    for row in reader:
        github_token = (row.get("github_token") or row.get("GITHUB_TOKEN") or "").strip()
        gitlab_token = (row.get("gitlab_token") or row.get("GITLAB_TOKEN") or "").strip()
        if github_token:
            tokens["github_token"] = github_token
        if gitlab_token:
            tokens["gitlab_token"] = gitlab_token
        break
    return tokens


def load_tokens_from_csv(csv_path: Path) -> Dict[str, str]:
    """Load tokens from a CSV file with columns `key,value` or token-named headers."""
    if not csv_path.exists():
        return {}

    with open(csv_path, "r", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        if not reader.fieldnames:
            return {}

        normalized_headers = [h.strip().lower() for h in reader.fieldnames if h]

        # Supported formats:
        # 1) key,value rows -> github_token,<token> / gitlab_token,<token>
        if "key" in normalized_headers and "value" in normalized_headers:
            return _load_key_value_format(reader)

        # 2) single-row headers: github_token,gitlab_token
        return _load_header_format(reader)
