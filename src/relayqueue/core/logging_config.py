import contextvars
import json
import logging
from datetime import UTC, datetime

request_id_context = contextvars.ContextVar(
    "request_id",
    default="-",
)


class JSONFormatter(logging.Formatter):
    """Format application logs as structured JSON."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_context.get(),
        }

        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        if record.stack_info:
            log_entry["stack"] = self.formatStack(record.stack_info)

        return json.dumps(log_entry, default=str)


def configure_logging() -> None:
    """Configure application-wide JSON logging."""

    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
