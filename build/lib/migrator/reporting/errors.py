import csv
import logging
import threading
from pathlib import Path
from typing import Dict

logger = logging.getLogger("migrator")


class ErrorsReporter:
    """
    Writes failed migrations to a CSV file in real time — one row per failure,
    flushed immediately so the file is always up-to-date during a long run.

    Usage (as context manager):
        with ErrorsReporter(path) as reporter:
            reporter.write(repo_name, source_url, reason)
    """

    FIELDS = ["repo_name", "source_url", "status", "reason"]

    def __init__(self, output_path: Path):
        self.output_path = output_path
        self._file = None
        self._writer = None
        self._count = 0
        self._lock = threading.Lock()

    def __enter__(self) -> "ErrorsReporter":
        self._file = open(self.output_path, "w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._file, fieldnames=self.FIELDS)
        self._writer.writeheader()
        self._file.flush()
        logger.info(f"Error report file opened: {self.output_path}")
        return self

    def __exit__(self, *_):
        if self._file:
            self._file.close()
        if self._count == 0:
            logger.info("No errors recorded — all migrations succeeded or are in sync.")
        else:
            logger.info(f"Error report closed: {self.output_path}  ({self._count} entries)")

    def write(self, repo_name: str, source_url: str, reason: str) -> None:
        """Append one error row and flush immediately (thread-safe)."""
        if self._writer is None:
            raise RuntimeError("ErrorsReporter must be used as a context manager")

        status_label = (
            "out_of_sync"
            if ("out of sync" in reason.lower())
            else "error"
        )
        with self._lock:
            self._writer.writerow({
                "repo_name": repo_name,
                "source_url": source_url,
                "status": status_label,
                "reason": reason,
            })
            self._file.flush()
            self._count += 1
        logger.warning(f"[{repo_name}] Error recorded in report: [{status_label}]")


def write_errors_report(results: Dict[str, Dict], output_path: Path) -> None:
    """Write a CSV report from a completed results dict (end-of-run fallback)."""
    with ErrorsReporter(output_path) as reporter:
        for repo_name, info in results.items():
            if not info["success"]:
                reporter.write(
                    repo_name=repo_name,
                    source_url=info.get("source_url", ""),
                    reason=info.get("reason", ""),
                )
