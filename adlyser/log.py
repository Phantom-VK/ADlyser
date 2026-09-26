"""Structured logging: ``log.info("event", extra={...})`` prints ``event key=value ...``."""

import logging
import sys

_STANDARD = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}
_configured = False


class _KeyValueFormatter(logging.Formatter):
    """Append any ``extra`` fields as ``key=value`` pairs."""

    def format(self, record: logging.LogRecord) -> str:
        """Format a record with its extra fields.

        :param record: the log record.
        :return: the formatted line.
        """
        base = super().format(record)
        extras = " ".join(f"{k}={v}" for k, v in record.__dict__.items() if k not in _STANDARD)
        return f"{base} {extras}".rstrip()


def get_logger(name: str) -> logging.Logger:
    """Return a logger, configuring the root handler on first use.

    :param name: usually ``__name__``.
    :return: a configured logger.
    """
    global _configured
    if not _configured:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(_KeyValueFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        root = logging.getLogger()
        root.addHandler(handler)
        root.setLevel(logging.INFO)
        logging.getLogger("httpx").setLevel(logging.WARNING)
        _configured = True
    return logging.getLogger(name)
