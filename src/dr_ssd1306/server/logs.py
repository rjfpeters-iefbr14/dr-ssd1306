"""Logging for the service: one format for the app and uvicorn, polls at DEBUG.

As the rti-demo's FSP does it (modules/fsp, bff_endpoint.py): LOG_LEVEL or
--log-level sets the root logger, uvicorn's records propagate to it, and the
access lines of requests that are polled all the time are demoted to DEBUG.
"""

import logging
import sys

LOG_FORMAT = "%(asctime)s - %(name)s - %(threadName)s - %(levelname)s - %(message)s"
# What uvicorn's --log-level takes; "trace" is uvicorn's own, DEBUG here.
LOG_CHOICES = ["critical", "error", "warning", "info", "debug", "trace"]


def resolve_log_level(value: str | None, default: int = logging.INFO) -> int:
    """A level name (any case), number or "trace" as a logging level.

    An unknown or empty value gives `default`, so a typo in LOG_LEVEL
    doesn't stop the service.
    """
    if value is None:
        return default
    name = str(value).strip().upper()
    if not name:
        return default
    if name.isdigit():
        return int(name)
    if name == "TRACE":
        return logging.DEBUG
    level = logging.getLevelName(name)  # an int for known names, else a str
    return level if isinstance(level, int) else default


def uvicorn_log_level(value: str | None, level: int) -> str:
    """The name uvicorn takes for `value`, resolved to `level`."""
    name = (value or "").strip().lower()
    return name if name in LOG_CHOICES else logging.getLevelName(level).lower()


def configure_logging(level: int) -> None:
    """The root logger at `level`, to stdout (for Docker)."""
    logging.basicConfig(level=level, format=LOG_FORMAT, handlers=[logging.StreamHandler(sys.stdout)], force=True)


class QuietPollFilter(logging.Filter):
    """Demote uvicorn access lines of polled requests to DEBUG.

    The browser page polls the state and the screen every second, the FSP
    asks /plugin/attached about every 2 s and Docker checks /health: at
    INFO they bury the requests that change something. Matched by method
    and path, so a POST of the settings stays at INFO. The demoted lines show
    when uvicorn.access is at DEBUG.
    """

    QUIET = {
        ("GET", "/health"),
        ("GET", "/api/state"),
        ("GET", "/api/screen.png"),
        ("GET", "/plugin/attached"),
        ("GET", "/plugin/status"),
    }

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        # uvicorn access records: (client_addr, method, path, http_version, status)
        if not isinstance(args, tuple) or len(args) < 3:
            return True
        path = str(args[2]).split("?", 1)[0]
        if (str(args[1]).upper(), path) not in self.QUIET:
            return True
        record.levelno = logging.DEBUG
        record.levelname = "DEBUG"
        return logging.getLogger("uvicorn.access").isEnabledFor(logging.DEBUG)


def quiet_polls() -> None:
    """Install QuietPollFilter on uvicorn.access, once."""
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, QuietPollFilter) for f in access.filters):
        access.addFilter(QuietPollFilter())
