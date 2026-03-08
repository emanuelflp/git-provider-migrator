import logging
import subprocess
from typing import Optional

logger = logging.getLogger("migrator")

_LFS_AVAILABLE: Optional[bool] = None  # cached lazily


def _check_lfs_installed() -> bool:
    """Return True if git-lfs is available on PATH."""
    try:
        logger.debug("$ git lfs version")
        result = subprocess.run(
            ["git", "lfs", "version"],
            capture_output=True, text=True,
        )
        logger.debug(f"git lfs version rc={result.returncode} stdout={result.stdout.strip()!r}")
        return result.returncode == 0
    except FileNotFoundError:
        logger.debug("git lfs version: git-lfs not found on PATH")
        return False


def _lfs_available() -> bool:
    global _LFS_AVAILABLE
    if _LFS_AVAILABLE is None:
        _LFS_AVAILABLE = _check_lfs_installed()
    return _LFS_AVAILABLE
