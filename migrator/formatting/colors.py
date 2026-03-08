import logging
import sys


class _AnsiCodes:
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    GREEN   = "\033[32m"
    YELLOW  = "\033[33m"
    RED     = "\033[31m"
    CYAN    = "\033[36m"
    MAGENTA = "\033[35m"
    DIM     = "\033[2m"


class ColorFormatter(logging.Formatter):
    """
    Applies ANSI colors to console log records based on level.
    Only attached to the StreamHandler — file handlers stay plain.
    """

    _LEVEL_COLORS = {
        logging.DEBUG:    _AnsiCodes.DIM,
        logging.INFO:     _AnsiCodes.CYAN,
        logging.WARNING:  _AnsiCodes.YELLOW,
        logging.ERROR:    _AnsiCodes.RED,
        logging.CRITICAL: _AnsiCodes.RED + _AnsiCodes.BOLD,
    }

    _FMT = "%(asctime)s - %(levelname)s - %(message)s"

    def format(self, record: logging.LogRecord) -> str:
        color = self._LEVEL_COLORS.get(record.levelno, "")
        msg = super().format(record)
        return f"{color}{msg}{_AnsiCodes.RESET}" if color else msg


def _setup_logging(debug: bool = False) -> None:
    """
    Configure root logger with a color-aware StreamHandler.
    Called once at startup (after args are parsed) so the level is correct.
    """
    root = logging.getLogger()
    # Remove any handlers added by a previous basicConfig call
    root.handlers.clear()

    level = logging.DEBUG if debug else logging.INFO
    root.setLevel(level)

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)

    fmt = "%(asctime)s - %(levelname)s - %(message)s"
    if sys.stderr.isatty():
        handler.setFormatter(ColorFormatter(fmt))
    else:
        handler.setFormatter(logging.Formatter(fmt))

    root.addHandler(handler)


# Bootstrap with INFO level; will be re-initialised in main() after arg parsing.
_setup_logging(debug=False)
logger = logging.getLogger("migrator")
