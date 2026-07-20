"""Centralised logging setup for the dapply project.

Convention (see AGENTS.md "Logging"):
    import logging
    logger = logging.getLogger(__name__)

    # at a CLI entrypoint:
    from logutils import setup_logging
    setup_logging()

``setup_logging`` configures the root logger to emit to stdout, so the
existing cron stdout capture (``/tmp/dapply-daily.log``) and
``python script.py 2>&1`` continue to work after migrating off ``print``.
"""

import logging
import sys

DEFAULT_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
DEFAULT_DATEFMT = "%Y-%m-%d %H:%M:%S"


def setup_logging(
    level: int = logging.INFO,
    fmt: str = DEFAULT_FORMAT,
    datefmt: str = DEFAULT_DATEFMT,
    stream=None,
) -> None:
    """Configure the root logger to stream to *stream* (default stdout).

    Idempotent: repeated calls will not attach duplicate handlers, but the
    root level is always updated to *level*.
    """
    if stream is None:
        stream = sys.stdout
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter(fmt, datefmt))
        root.addHandler(handler)
    root.setLevel(level)
