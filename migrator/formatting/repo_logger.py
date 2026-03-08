import logging

logger = logging.getLogger("migrator")


class RepoLogger:
    """Thin wrapper that prefixes every log message with [repo_name]."""

    def __init__(self, repo_name: str):
        self._prefix = f"[{repo_name}]"

    def _fmt(self, msg: str) -> str:
        return f"{self._prefix} {msg}"

    def info(self, msg: str) -> None:
        logger.info(self._fmt(msg))

    def warning(self, msg: str) -> None:
        logger.warning(self._fmt(msg))

    def error(self, msg: str) -> None:
        logger.error(self._fmt(msg))

    def debug(self, msg: str) -> None:
        logger.debug(self._fmt(msg))
