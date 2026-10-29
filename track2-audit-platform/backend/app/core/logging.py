import contextvars
import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

# ContextVar to store request_id across async tasks and threads
request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")


class StructuredJSONFormatter(logging.Formatter):
    """Formats log records as structured single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        log_data: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Include request_id if available in context or record
        req_id = getattr(record, "request_id", None) or request_id_ctx.get()
        if req_id:
            log_data["request_id"] = req_id

        # Include custom extra attributes
        for key, value in record.__dict__.items():
            if key not in {
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "message",
                "request_id",
            }:
                try:
                    json.dumps(value)
                    log_data[key] = value
                except (TypeError, OverflowError):
                    log_data[key] = str(value)

        # Include exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data)


def setup_logging(log_level: str = "INFO") -> logging.Logger:
    """Configure root logger to emit structured JSON output."""
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Avoid duplicate handlers on re-configuration
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(StructuredJSONFormatter())
    root_logger.addHandler(stream_handler)

    # Silence overly verbose third-party loggers if needed
    logging.getLogger("uvicorn.access").handlers = [stream_handler]
    logging.getLogger("uvicorn.error").handlers = [stream_handler]

    return root_logger
